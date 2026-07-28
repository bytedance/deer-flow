"""Use-case tests for ScheduleService, run entirely on in-memory doubles.

This file is the acceptance criterion of the hexagonal migration: the complete
scheduled-task lifecycle runs here with no HTTP, no database, and no run
runtime -- if any of that were still reachable from the domain, these tests
could not exist.

The dispatch cases mirror the pre-migration behaviour deliberately. Where a
comment says two paths must be indistinguishable, that is a regression the
tests are here to catch, not a description of the implementation.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from schedule_fakes import (
    FakeRunLauncher,
    FakeThreadLookup,
    InMemoryScheduledRunRepository,
    InMemoryScheduledTaskRepository,
)

from deerflow.domain.schedule.model import (
    ContextMode,
    InvalidScheduleError,
    LaunchFailedError,
    RunStatus,
    SchedulePolicy,
    ScheduleSpec,
    TaskNotFoundError,
    TaskNotMutableError,
    TaskStatus,
    ThreadBusyError,
    ThreadNotFoundError,
    TriggerKind,
)
from deerflow.domain.schedule.ports import RunOutcome
from deerflow.domain.schedule.service import ScheduleService

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)
CRON = ScheduleSpec.cron_schedule("0 9 * * *", "UTC")
POLICY = SchedulePolicy(min_once_delay_seconds=60, max_concurrent_runs=3, lease_seconds=120)


def once_spec(*, after_seconds: int = 3600) -> ScheduleSpec:
    return ScheduleSpec.once_at(NOW + timedelta(seconds=after_seconds), "UTC")


class _BlindRunRepo(InMemoryScheduledRunRepository):
    """`has_active` always misses.

    Reproduces the TOCTOU window the fast path cannot close: a concurrent
    dispatch inserted its record after this one looked. The active-slot
    rejection on `add` is then the only thing standing in the way.
    """

    async def has_active(self, task_id: str) -> bool:
        return False


def make_service(
    *,
    tasks: InMemoryScheduledTaskRepository | None = None,
    runs: InMemoryScheduledRunRepository | None = None,
    launcher: FakeRunLauncher | None = None,
    threads: FakeThreadLookup | None = None,
    policy: SchedulePolicy = POLICY,
) -> ScheduleService:
    return ScheduleService(
        tasks=tasks if tasks is not None else InMemoryScheduledTaskRepository(),
        runs=runs if runs is not None else InMemoryScheduledRunRepository(),
        launcher=launcher if launcher is not None else FakeRunLauncher(),
        threads=threads if threads is not None else FakeThreadLookup(),
        policy=policy,
        lease_owner="test-worker",
    )


async def create_cron_task(service: ScheduleService, *, schedule: ScheduleSpec = CRON):
    return await service.create_task(
        user_id="user-1",
        title="Daily summary",
        prompt="summarize",
        schedule=schedule,
        context_mode=ContextMode.FRESH_THREAD_PER_RUN,
        thread_id=None,
        now=NOW,
    )


# ==================================================================== lifecycle


class TestFullLifecycle:
    async def test_create_claim_dispatch_overlap_complete_pause_delete(self):
        """The acceptance criterion: the whole feature, zero IO.

        Every step below is a real use case going through real domain rules --
        only the four ports are doubles.
        """
        tasks = InMemoryScheduledTaskRepository()
        runs = InMemoryScheduledRunRepository()
        launcher = FakeRunLauncher()
        service = make_service(tasks=tasks, runs=runs, launcher=launcher)

        # -- create ---------------------------------------------------------
        task = await create_cron_task(service)
        assert task.status is TaskStatus.ENABLED
        assert task.next_run_at == datetime(2026, 7, 28, 9, 0, tzinfo=UTC)

        # -- become due, get claimed and dispatched --------------------------
        due_at = task.next_run_at + timedelta(seconds=1)
        results = await service.run_once(now=due_at)
        assert [r.outcome for r in results] == ["launched"]
        assert len(launcher.calls) == 1
        launch = launcher.calls[0]
        assert launch["prompt"] == "summarize"
        assert launch["owner_user_id"] == "user-1"
        assert launch["metadata"]["scheduled_task_id"] == task.task_id
        assert launch["metadata"]["scheduled_trigger"] == "scheduled"

        after_launch = await service.get_task(task.task_id, user_id="user-1")
        assert after_launch.status is TaskStatus.ENABLED, "a cron task stays claimable"
        assert after_launch.run_count == 1
        assert after_launch.last_run_id == "run-1"
        assert after_launch.next_run_at > due_at

        # -- next occurrence overlaps the still-running one ------------------
        overlap_at = after_launch.next_run_at + timedelta(seconds=1)
        overlapped = await service.run_once(now=overlap_at)
        assert [r.outcome for r in overlapped] == ["skipped"]
        assert len(launcher.calls) == 1, "the overlapping occurrence must not launch"

        after_skip = await service.get_task(task.task_id, user_id="user-1")
        assert after_skip.run_count == 1, "a skip is not an execution"
        assert after_skip.last_run_id == after_launch.last_run_id, "bookkeeping carried over"
        assert after_skip.status is TaskStatus.ENABLED

        # -- the first run finally finishes ----------------------------------
        record = next(r for r in runs.all_runs() if r.status is RunStatus.RUNNING)
        await service.handle_run_completion(
            RunOutcome(
                task_id=task.task_id,
                record_id=record.record_id,
                run_id="run-1",
                user_id="user-1",
                status=RunStatus.SUCCESS,
                error=None,
            ),
            now=overlap_at,
        )
        assert await runs.count_active() == 0, "the active slot is free again"

        # -- pause / resume ---------------------------------------------------
        paused = await service.pause_task(task.task_id, user_id="user-1")
        assert paused.status is TaskStatus.PAUSED
        assert await service.run_once(now=overlap_at + timedelta(days=2)) == [], "a paused task is not claimed"

        resumed = await service.resume_task(task.task_id, user_id="user-1")
        assert resumed.status is TaskStatus.ENABLED

        # -- history and delete ----------------------------------------------
        history = await service.list_task_runs(task.task_id, user_id="user-1")
        assert sorted(run.status for run in history) == [RunStatus.SKIPPED, RunStatus.SUCCESS]

        await service.delete_task(task.task_id, user_id="user-1")
        with pytest.raises(TaskNotFoundError):
            await service.get_task(task.task_id, user_id="user-1")


# ==================================================================== dispatch


class TestDispatchOutcomes:
    async def test_launch_records_the_run_and_the_bookkeeping(self):
        runs = InMemoryScheduledRunRepository()
        service = make_service(runs=runs)
        task = await create_cron_task(service)

        result = await service.dispatch_task(task, now=NOW, trigger=TriggerKind.SCHEDULED)

        assert result.outcome == "launched"
        assert result.run_id == "run-1"
        assert result.error is None
        stored = runs.all_runs()[0]
        assert stored.status is RunStatus.RUNNING
        assert stored.run_id == "run-1"
        assert stored.started_at == NOW

    async def test_manual_trigger_against_an_active_run_is_a_conflict_with_no_record(self):
        """Nothing was scheduled to happen, so there is no occurrence to
        account for -- the caller gets a conflict and the history stays clean."""
        runs = InMemoryScheduledRunRepository()
        service = make_service(runs=runs)
        task = await create_cron_task(service)
        await service.dispatch_task(task, now=NOW, trigger=TriggerKind.SCHEDULED)
        before = len(runs.all_runs())

        result = await service.trigger_task(task.task_id, user_id="user-1", now=NOW)

        assert result.outcome == "conflict"
        assert result.record_id is None
        assert result.error == "task already has an active run"
        assert len(runs.all_runs()) == before, "no history row for a rejected manual trigger"

    async def test_scheduled_overlap_records_a_terminal_tombstone(self):
        runs = InMemoryScheduledRunRepository()
        service = make_service(runs=runs)
        task = await create_cron_task(service)
        await service.dispatch_task(task, now=NOW, trigger=TriggerKind.SCHEDULED)

        result = await service.dispatch_task(task, now=NOW, trigger=TriggerKind.SCHEDULED)

        assert result.outcome == "skipped"
        assert result.error == "skipped: a previous run of this task is still active"
        tombstone = next(r for r in runs.all_runs() if r.status is RunStatus.SKIPPED)
        assert tombstone.is_active is False, "a queued tombstone would collide with the live run"
        assert tombstone.started_at == tombstone.finished_at == NOW

    async def test_launch_failure_is_recorded_as_failed(self):
        runs = InMemoryScheduledRunRepository()
        launcher = FakeRunLauncher(fail_with=LaunchFailedError("provider exploded"))
        service = make_service(runs=runs, launcher=launcher)
        task = await create_cron_task(service)

        result = await service.dispatch_task(task, now=NOW, trigger=TriggerKind.SCHEDULED)

        assert result.outcome == "failed"
        assert result.run_id is None
        assert "provider exploded" in result.error
        assert runs.all_runs()[0].status is RunStatus.FAILED

    async def test_busy_thread_on_the_scheduled_path_degrades_to_a_skip(self):
        launcher = FakeRunLauncher(fail_with=ThreadBusyError("thread busy"))
        service = make_service(launcher=launcher)
        task = await create_cron_task(service)

        result = await service.dispatch_task(task, now=NOW, trigger=TriggerKind.SCHEDULED)

        assert result.outcome == "skipped"

    async def test_busy_thread_on_a_manual_trigger_stays_a_conflict(self):
        """Not a skip: the user asked for this one, so it is reported rather
        than quietly accounted for. The router maps it to 409, not 502."""
        launcher = FakeRunLauncher(fail_with=ThreadBusyError("thread busy"))
        service = make_service(launcher=launcher)
        task = await create_cron_task(service)

        result = await service.dispatch_task(task, now=NOW, trigger=TriggerKind.MANUAL)

        assert result.outcome == "conflict"
        assert result.record_id is not None, "the attempt itself is still recorded"


class TestConflictCollapse:
    """The fast path and the active-slot rejection must be indistinguishable.

    Two concurrent dispatches can both pass `has_active`; whichever loses is
    rejected by the repository instead. A caller must not be able to tell which
    of the two mechanisms stopped it, or retry behaviour diverges.
    """

    async def _dispatch_second(self, run_repo, trigger: TriggerKind):
        # reuse_thread so the execution thread is fixed: a fresh-thread task
        # mints a new uuid per dispatch, which would make the two runs differ
        # for a reason that has nothing to do with the collapse.
        service = make_service(runs=run_repo, threads=FakeThreadLookup({"thread-1": "user-1"}))
        task = await service.create_task(
            user_id="user-1",
            title="t",
            prompt="p",
            schedule=CRON,
            context_mode=ContextMode.REUSE_THREAD,
            thread_id="thread-1",
            now=NOW,
        )
        await service.dispatch_task(task, now=NOW, trigger=TriggerKind.SCHEDULED)
        return await service.dispatch_task(task, now=NOW, trigger=trigger)

    @pytest.mark.parametrize("trigger", [TriggerKind.SCHEDULED, TriggerKind.MANUAL])
    async def test_both_paths_produce_the_same_result(self, trigger):
        via_fast_path = await self._dispatch_second(InMemoryScheduledRunRepository(), trigger)
        via_slot_rejection = await self._dispatch_second(_BlindRunRepo(), trigger)

        # record_id is freshly generated; every other field must match exactly.
        assert replace(via_fast_path, record_id=None) == replace(via_slot_rejection, record_id=None)

    async def test_the_losing_scheduled_dispatch_still_leaves_a_tombstone(self):
        runs = _BlindRunRepo()
        result = await self._dispatch_second(runs, TriggerKind.SCHEDULED)
        assert result.outcome == "skipped"
        assert any(r.status is RunStatus.SKIPPED for r in runs.all_runs())

    async def test_the_losing_manual_dispatch_leaves_nothing(self):
        runs = _BlindRunRepo()
        result = await self._dispatch_second(runs, TriggerKind.MANUAL)
        assert result.outcome == "conflict"
        assert not any(r.status is RunStatus.SKIPPED for r in runs.all_runs())


class TestOnceTaskDispatch:
    async def test_a_once_task_waits_in_running_for_its_completion(self):
        """Declaring it complete at launch would stick if the run failed or the
        process died before the hook could correct it."""
        service = make_service()
        task = await service.create_task(
            user_id="user-1",
            title="one shot",
            prompt="go",
            schedule=once_spec(),
            context_mode=ContextMode.FRESH_THREAD_PER_RUN,
            thread_id=None,
            now=NOW,
        )

        await service.dispatch_task(task, now=NOW, trigger=TriggerKind.SCHEDULED)

        after = await service.get_task(task.task_id, user_id="user-1")
        assert after.status is TaskStatus.RUNNING

    async def test_a_skipped_once_task_is_failed_not_completed(self):
        """The single occurrence was lost; `completed` would claim an execution
        that never happened."""
        runs = InMemoryScheduledRunRepository()
        service = make_service(runs=runs)
        task = await service.create_task(
            user_id="user-1",
            title="one shot",
            prompt="go",
            schedule=once_spec(),
            context_mode=ContextMode.FRESH_THREAD_PER_RUN,
            thread_id=None,
            now=NOW,
        )
        await service.dispatch_task(task, now=NOW, trigger=TriggerKind.SCHEDULED)
        reloaded = await service.get_task(task.task_id, user_id="user-1")

        await service.dispatch_task(reloaded, now=NOW, trigger=TriggerKind.SCHEDULED)

        after = await service.get_task(task.task_id, user_id="user-1")
        assert after.status is TaskStatus.FAILED
        assert after.last_error == "skipped: a previous run of this task is still active"


# ==================================================================== run_once


class TestRunOnceBudget:
    async def test_claims_nothing_when_the_global_budget_is_exhausted(self):
        """The cap is on active runs across all tasks, not on one poll's batch:
        long runs accumulate across cycles."""
        runs = InMemoryScheduledRunRepository()
        service = make_service(runs=runs, policy=replace(POLICY, max_concurrent_runs=1))
        first = await create_cron_task(service)
        await service.dispatch_task(first, now=NOW, trigger=TriggerKind.SCHEDULED)

        second = await create_cron_task(service)
        results = await service.run_once(now=second.next_run_at + timedelta(seconds=1))

        assert results == []

    async def test_claims_only_into_the_remaining_budget(self):
        tasks = InMemoryScheduledTaskRepository()
        service = make_service(tasks=tasks, policy=replace(POLICY, max_concurrent_runs=2))
        for _ in range(3):
            await create_cron_task(service)

        due_at = datetime(2026, 7, 28, 9, 0, 1, tzinfo=UTC)
        results = await service.run_once(now=due_at)

        assert len(results) == 2
        assert all(r.outcome == "launched" for r in results)

    async def test_a_claimed_task_is_marked_running_before_dispatch(self):
        """Claiming is what makes the task uneditable while it is being
        dispatched, so the claim must land before the launch."""
        tasks = InMemoryScheduledTaskRepository()
        service = make_service(tasks=tasks)
        task = await create_cron_task(service)

        await service.run_once(now=task.next_run_at + timedelta(seconds=1))

        assert tasks.lease_of(task.task_id) == (None, None), "the claim is released after dispatch"


# ==================================================================== completion


class TestRunCompletion:
    async def _launched_once_task(self):
        runs = InMemoryScheduledRunRepository()
        service = make_service(runs=runs)
        task = await service.create_task(
            user_id="user-1",
            title="one shot",
            prompt="go",
            schedule=once_spec(),
            context_mode=ContextMode.FRESH_THREAD_PER_RUN,
            thread_id=None,
            now=NOW,
        )
        await service.dispatch_task(task, now=NOW, trigger=TriggerKind.SCHEDULED)
        record = runs.all_runs()[0]
        return service, task, record

    @pytest.mark.parametrize(
        ("outcome_status", "expected"),
        [
            (RunStatus.SUCCESS, TaskStatus.COMPLETED),
            (RunStatus.FAILED, TaskStatus.FAILED),
            (RunStatus.INTERRUPTED, TaskStatus.CANCELLED),
        ],
    )
    async def test_once_task_terminal_mapping(self, outcome_status, expected):
        service, task, record = await self._launched_once_task()

        await service.handle_run_completion(
            RunOutcome(
                task_id=task.task_id,
                record_id=record.record_id,
                run_id="run-1",
                user_id="user-1",
                status=outcome_status,
                error=None if outcome_status is RunStatus.SUCCESS else "boom",
            ),
            now=NOW,
        )

        after = await service.get_task(task.task_id, user_id="user-1")
        assert after.status is expected

    async def test_a_cron_task_keeps_its_status_but_records_the_error(self):
        runs = InMemoryScheduledRunRepository()
        service = make_service(runs=runs)
        task = await create_cron_task(service)
        await service.dispatch_task(task, now=NOW, trigger=TriggerKind.SCHEDULED)
        record = runs.all_runs()[0]

        await service.handle_run_completion(
            RunOutcome(
                task_id=task.task_id,
                record_id=record.record_id,
                run_id="run-1",
                user_id="user-1",
                status=RunStatus.FAILED,
                error="boom",
            ),
            now=NOW,
        )

        after = await service.get_task(task.task_id, user_id="user-1")
        assert after.status is TaskStatus.ENABLED, "the schedule outlives any single run"
        assert after.last_error == "boom"

    async def test_a_task_deleted_mid_flight_is_not_an_error(self):
        service, task, record = await self._launched_once_task()
        await service.delete_task(task.task_id, user_id="user-1")

        await service.handle_run_completion(
            RunOutcome(
                task_id=task.task_id,
                record_id=record.record_id,
                run_id="run-1",
                user_id="user-1",
                status=RunStatus.SUCCESS,
                error=None,
            ),
            now=NOW,
        )


class TestReconcileOnStartup:
    async def test_sweeps_orphaned_runs_and_stuck_once_tasks(self):
        runs = InMemoryScheduledRunRepository()
        tasks = InMemoryScheduledTaskRepository()
        service = make_service(tasks=tasks, runs=runs)
        task = await service.create_task(
            user_id="user-1",
            title="one shot",
            prompt="go",
            schedule=once_spec(),
            context_mode=ContextMode.FRESH_THREAD_PER_RUN,
            thread_id=None,
            now=NOW,
        )
        await service.dispatch_task(task, now=NOW, trigger=TriggerKind.SCHEDULED)
        # The process dies here: the run is active and the once task is parked
        # in running with its claim already released.

        stale_runs, stuck_tasks = await service.reconcile_on_startup(error="gateway restarted")

        assert (stale_runs, stuck_tasks) == (1, 1)
        assert runs.all_runs()[0].status is RunStatus.INTERRUPTED
        after = await service.get_task(task.task_id, user_id="user-1")
        assert after.status is TaskStatus.CANCELLED


# ==================================================================== CRUD


class TestTaskManagement:
    async def test_reuse_thread_requires_an_accessible_thread(self):
        service = make_service(threads=FakeThreadLookup({"thread-1": "user-1"}))

        created = await service.create_task(
            user_id="user-1",
            title="t",
            prompt="p",
            schedule=CRON,
            context_mode=ContextMode.REUSE_THREAD,
            thread_id="thread-1",
            now=NOW,
        )
        assert created.thread_id == "thread-1"

        with pytest.raises(ThreadNotFoundError):
            await service.create_task(
                user_id="user-2",
                title="t",
                prompt="p",
                schedule=CRON,
                context_mode=ContextMode.REUSE_THREAD,
                thread_id="thread-1",
                now=NOW,
            )

    async def test_an_invalid_schedule_is_rejected_before_any_write(self):
        tasks = InMemoryScheduledTaskRepository()
        service = make_service(tasks=tasks)

        with pytest.raises(InvalidScheduleError):
            await service.create_task(
                user_id="user-1",
                title="t",
                prompt="p",
                schedule=once_spec(after_seconds=10),  # inside min_once_delay
                context_mode=ContextMode.FRESH_THREAD_PER_RUN,
                thread_id=None,
                now=NOW,
            )
        assert await service.list_tasks("user-1") == []

    async def test_update_leaves_omitted_fields_alone(self):
        service = make_service()
        task = await create_cron_task(service)

        updated = await service.update_task(task.task_id, user_id="user-1", now=NOW, title="renamed")

        assert updated.title == "renamed"
        assert updated.prompt == task.prompt
        assert updated.schedule == task.schedule

    async def test_rescheduling_a_terminal_task_re_arms_it(self):
        tasks = InMemoryScheduledTaskRepository()
        service = make_service(tasks=tasks)
        task = await create_cron_task(service)
        tasks.seed(replace(task, status=TaskStatus.FAILED))

        updated = await service.update_task(
            task.task_id,
            user_id="user-1",
            now=NOW,
            schedule=ScheduleSpec.cron_schedule("0 10 * * *", "UTC"),
        )

        assert updated.status is TaskStatus.ENABLED, "otherwise it would never be claimed again"

    async def test_a_running_task_cannot_be_edited(self):
        tasks = InMemoryScheduledTaskRepository()
        service = make_service(tasks=tasks)
        task = await create_cron_task(service)
        tasks.seed(replace(task, status=TaskStatus.RUNNING))

        with pytest.raises(TaskNotMutableError):
            await service.update_task(task.task_id, user_id="user-1", now=NOW, title="nope")
        with pytest.raises(TaskNotMutableError):
            await service.pause_task(task.task_id, user_id="user-1")

    async def test_a_running_task_can_still_be_deleted(self):
        """The pre-migration router gated update/pause/resume on this, but not
        delete -- that asymmetry is preserved."""
        tasks = InMemoryScheduledTaskRepository()
        service = make_service(tasks=tasks)
        task = await create_cron_task(service)
        tasks.seed(replace(task, status=TaskStatus.RUNNING))

        await service.delete_task(task.task_id, user_id="user-1")

    @pytest.mark.parametrize("call", ["get", "update", "pause", "resume", "delete", "runs"])
    async def test_another_users_task_is_reported_as_missing(self, call):
        service = make_service()
        task = await create_cron_task(service)
        kwargs = {"user_id": "intruder"}

        with pytest.raises(TaskNotFoundError):
            if call == "get":
                await service.get_task(task.task_id, **kwargs)
            elif call == "update":
                await service.update_task(task.task_id, now=NOW, title="x", **kwargs)
            elif call == "pause":
                await service.pause_task(task.task_id, **kwargs)
            elif call == "resume":
                await service.resume_task(task.task_id, **kwargs)
            elif call == "delete":
                await service.delete_task(task.task_id, **kwargs)
            else:
                await service.list_task_runs(task.task_id, **kwargs)

    async def test_tasks_are_listed_per_user_and_per_thread(self):
        service = make_service(threads=FakeThreadLookup({"thread-1": "user-1"}))
        bound = await service.create_task(
            user_id="user-1",
            title="bound",
            prompt="p",
            schedule=CRON,
            context_mode=ContextMode.REUSE_THREAD,
            thread_id="thread-1",
            now=NOW,
        )
        await create_cron_task(service)

        assert len(await service.list_tasks("user-1")) == 2
        assert await service.list_tasks("someone-else") == []
        by_thread = await service.list_tasks_by_thread("user-1", "thread-1")
        assert [t.task_id for t in by_thread] == [bound.task_id]
