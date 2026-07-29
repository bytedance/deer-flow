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

from deerflow.domain.schedule.commands import (
    UNSET,
    ContextChange,
    CreateScheduledTask,
    DeleteTask,
    PauseTask,
    ResumeTask,
    TriggerTask,
    UnsetType,
    UpdateScheduledTask,
)
from deerflow.domain.schedule.exceptions import (
    InvalidScheduleError,
    LaunchFailedError,
    TaskNotFoundError,
    TaskNotMutableError,
    ThreadBusyError,
    ThreadNotFoundError,
)
from deerflow.domain.schedule.model import (
    ContextMode,
    DispatchOutcome,
    RunStatus,
    SchedulePolicy,
    ScheduleSpec,
    TaskStatus,
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

    async def has_active(self, _task_id: str) -> bool:
        return False


class _LaunchWritesMidReadTaskRepo(InMemoryScheduledTaskRepository):
    """`record_launch` commits between the completion hook's read and its write.

    That ordering is not exotic -- `dispatch_task` performs its two bookkeeping
    writes after the launch returns, and a run that fails fast reaches the hook
    in between. Modelling it here rather than with real concurrency keeps the
    window deterministic.
    """

    def __init__(self, *, launch_next_run_at: datetime) -> None:
        super().__init__()
        self._launch_next_run_at = launch_next_run_at
        self._armed = False

    def arm(self) -> None:
        """Fire the interleaving on the next read, once."""
        self._armed = True

    async def get(self, task_id: str, *, user_id: str):
        task = await super().get(task_id, user_id=user_id)
        if self._armed:
            self._armed = False
            await self.record_launch(
                task_id,
                status=TaskStatus.ENABLED,
                next_run_at=self._launch_next_run_at,
                last_run_at=NOW,
                last_run_id="run-1",
                last_thread_id="thread-1",
                last_error=None,
                increment_run_count=True,
                protect_terminal=True,
            )
        return task


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
    )


async def create_cron_task(service: ScheduleService, *, schedule: ScheduleSpec = CRON):
    return await service.create_scheduled_task(
        CreateScheduledTask(
            user_id="user-1",
            title="Daily summary",
            prompt="summarize",
            schedule=schedule,
            context_mode=ContextMode.FRESH_THREAD_PER_RUN,
            thread_id=None,
        ),
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
        assert [r.outcome for r in results] == [DispatchOutcome.LAUNCHED]
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
        assert [r.outcome for r in overlapped] == [DispatchOutcome.SKIPPED]
        assert len(launcher.calls) == 1, "the overlapping occurrence must not launch"

        after_skip = await service.get_task(task.task_id, user_id="user-1")
        assert after_skip.run_count == 1, "a skip is not an execution"
        assert after_skip.last_run_id == after_launch.last_run_id, "bookkeeping carried over"
        assert after_skip.status is TaskStatus.ENABLED
        # Only a lost one-shot occurrence is worth surfacing; a cron task simply
        # waits for its next turn, so the skip must not leave a user-visible
        # error behind (service.py:455). The `once` half is covered by
        # TestOnceTaskDispatch.test_a_skipped_once_task_is_failed_not_completed.
        assert after_skip.last_error is None, "a routine cron overlap is not an error to report"

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
        paused = await service.pause_task(PauseTask(task_id=task.task_id, user_id="user-1"))
        assert paused.status is TaskStatus.PAUSED
        assert await service.run_once(now=overlap_at + timedelta(days=2)) == [], "a paused task is not claimed"

        resumed = await service.resume_task(ResumeTask(task_id=task.task_id, user_id="user-1"))
        assert resumed.status is TaskStatus.ENABLED

        # -- history and delete ----------------------------------------------
        history = await service.list_task_runs(task.task_id, user_id="user-1")
        assert sorted(run.status for run in history) == [RunStatus.SKIPPED, RunStatus.SUCCESS]

        await service.delete_task(DeleteTask(task_id=task.task_id, user_id="user-1"))
        with pytest.raises(TaskNotFoundError):
            await service.get_task(task.task_id, user_id="user-1")


# ==================================================================== dispatch


class TestDispatchOutcomes:
    async def test_launch_records_the_run_and_the_bookkeeping(self):
        runs = InMemoryScheduledRunRepository()
        service = make_service(runs=runs)
        task = await create_cron_task(service)

        result = await service.dispatch_task(task, now=NOW, trigger=TriggerKind.SCHEDULED)

        assert result.outcome is DispatchOutcome.LAUNCHED
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

        result = await service.trigger_task(TriggerTask(task_id=task.task_id, user_id="user-1"), now=NOW)

        assert result.outcome is DispatchOutcome.CONFLICT
        assert result.record_id is None
        assert result.error == "task already has an active run"
        assert len(runs.all_runs()) == before, "no history row for a rejected manual trigger"

    async def test_scheduled_overlap_records_a_terminal_tombstone(self):
        runs = InMemoryScheduledRunRepository()
        service = make_service(runs=runs)
        task = await create_cron_task(service)
        await service.dispatch_task(task, now=NOW, trigger=TriggerKind.SCHEDULED)

        result = await service.dispatch_task(task, now=NOW, trigger=TriggerKind.SCHEDULED)

        assert result.outcome is DispatchOutcome.SKIPPED
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

        assert result.outcome is DispatchOutcome.FAILED
        assert result.run_id is None
        assert "provider exploded" in result.error
        assert runs.all_runs()[0].status is RunStatus.FAILED

    async def test_a_failed_launch_replaces_the_previous_run_bookkeeping(self):
        """A failed launch is still an execution *attempt*, so it overwrites the
        launch bookkeeping rather than carrying it over the way a skip does
        (contrast `_finalize_skip`, which passes the current values back).

        `record_launch` assigns every field unconditionally, so this is what
        `last_run_id=None` in `_fail` actually means for a task that had already
        run successfully: the id of the previous, unrelated run must not be left
        pointing at a launch that never happened.
        """
        launcher = FakeRunLauncher()
        runs = InMemoryScheduledRunRepository()
        service = make_service(runs=runs, launcher=launcher)
        task = await create_cron_task(service)
        await service.dispatch_task(task, now=NOW, trigger=TriggerKind.SCHEDULED)
        succeeded = await service.get_task(task.task_id, user_id="user-1")
        assert succeeded.last_run_id == "run-1", "precondition: a successful launch was recorded"

        # The slot has to be free, or the next dispatch is an overlap instead.
        await service.handle_run_completion(
            RunOutcome(
                task_id=task.task_id,
                record_id=runs.all_runs()[0].record_id,
                run_id="run-1",
                user_id="user-1",
                status=RunStatus.SUCCESS,
                error=None,
            ),
            now=NOW,
        )
        launcher.fail_with = LaunchFailedError("provider exploded")
        reloaded = await service.get_task(task.task_id, user_id="user-1")

        await service.dispatch_task(reloaded, now=NOW, trigger=TriggerKind.SCHEDULED)

        after = await service.get_task(task.task_id, user_id="user-1")
        assert after.last_run_id is None, "no run started, so no run id to point at"
        assert after.last_error == "provider exploded"
        assert after.last_run_at == NOW, "the attempt itself is timestamped"
        assert after.run_count == 1, "a failed launch is not a completed execution"

    async def test_busy_thread_on_the_scheduled_path_degrades_to_a_skip(self):
        launcher = FakeRunLauncher(fail_with=ThreadBusyError("thread busy"))
        service = make_service(launcher=launcher)
        task = await create_cron_task(service)

        result = await service.dispatch_task(task, now=NOW, trigger=TriggerKind.SCHEDULED)

        assert result.outcome is DispatchOutcome.SKIPPED

    async def test_busy_thread_on_a_manual_trigger_stays_a_conflict(self):
        """Not a skip: the user asked for this one, so it is reported rather
        than quietly accounted for. The router maps it to 409, not 502."""
        launcher = FakeRunLauncher(fail_with=ThreadBusyError("thread busy"))
        service = make_service(launcher=launcher)
        task = await create_cron_task(service)

        result = await service.dispatch_task(task, now=NOW, trigger=TriggerKind.MANUAL)

        assert result.outcome is DispatchOutcome.CONFLICT
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
        task = await service.create_scheduled_task(
            CreateScheduledTask(
                user_id="user-1",
                title="t",
                prompt="p",
                schedule=CRON,
                context_mode=ContextMode.REUSE_THREAD,
                thread_id="thread-1",
            ),
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
        assert result.outcome is DispatchOutcome.SKIPPED
        assert any(r.status is RunStatus.SKIPPED for r in runs.all_runs())

    async def test_the_losing_manual_dispatch_leaves_nothing(self):
        runs = _BlindRunRepo()
        result = await self._dispatch_second(runs, TriggerKind.MANUAL)
        assert result.outcome is DispatchOutcome.CONFLICT
        assert not any(r.status is RunStatus.SKIPPED for r in runs.all_runs())


class TestOnceTaskDispatch:
    async def test_a_once_task_waits_in_running_for_its_completion(self):
        """Declaring it complete at launch would stick if the run failed or the
        process died before the hook could correct it."""
        service = make_service()
        task = await service.create_scheduled_task(
            CreateScheduledTask(
                user_id="user-1",
                title="one shot",
                prompt="go",
                schedule=once_spec(),
                context_mode=ContextMode.FRESH_THREAD_PER_RUN,
                thread_id=None,
            ),
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
        task = await service.create_scheduled_task(
            CreateScheduledTask(
                user_id="user-1",
                title="one shot",
                prompt="go",
                schedule=once_spec(),
                context_mode=ContextMode.FRESH_THREAD_PER_RUN,
                thread_id=None,
            ),
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
        assert all(r.outcome is DispatchOutcome.LAUNCHED for r in results)

    async def test_the_claim_is_held_across_the_launch_and_released_after(self):
        """Claiming is what makes the task uneditable while it is being
        dispatched, so the claim has to be live *at the moment of the launch* --
        not merely taken at some point and released by the end.

        The launch is the only place that ordering is observable, so the
        launcher double reads the repository from inside `launch`. Asserting
        only on the end state would pass even if the claim were taken after the
        run had already started.
        """
        tasks = InMemoryScheduledTaskRepository()
        observed: dict = {}

        class _ObservingLauncher(FakeRunLauncher):
            async def launch(self, **kwargs):
                task_id = kwargs["metadata"]["scheduled_task_id"]
                observed["lease"] = tasks.lease_of(task_id)
                observed["status"] = (await tasks.get(task_id, user_id="user-1")).status
                return await super().launch(**kwargs)

        service = make_service(tasks=tasks, launcher=_ObservingLauncher())
        task = await create_cron_task(service)

        await service.run_once(now=task.next_run_at + timedelta(seconds=1))

        assert observed["status"] is TaskStatus.RUNNING, "the claim marks the task running before the launch"
        assert observed["lease"][1] is not None, "and the lease is still held while the run starts"
        assert tasks.lease_of(task.task_id) == (None, None), "released only once the dispatch is done"


# ==================================================================== completion


class TestRunCompletion:
    async def _launched_once_task(self):
        runs = InMemoryScheduledRunRepository()
        service = make_service(runs=runs)
        task = await service.create_scheduled_task(
            CreateScheduledTask(
                user_id="user-1",
                title="one shot",
                prompt="go",
                schedule=once_spec(),
                context_mode=ContextMode.FRESH_THREAD_PER_RUN,
                thread_id=None,
            ),
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

    async def test_a_task_deleted_mid_flight_still_finalizes_its_run(self):
        """A task deleted while its run was in flight has nothing to write back,
        and that is not an error -- but the *run* record must still be closed.

        The hook writes the record first and only then reads the task, so
        asserting on the record is what keeps that ordering honest; a test that
        only checked "no exception" would stay green if the record write were
        dropped entirely.
        """
        runs = InMemoryScheduledRunRepository()
        service = make_service(runs=runs)
        task = await service.create_scheduled_task(
            CreateScheduledTask(
                user_id="user-1",
                title="one shot",
                prompt="go",
                schedule=once_spec(),
                context_mode=ContextMode.FRESH_THREAD_PER_RUN,
                thread_id=None,
            ),
            now=NOW,
        )
        await service.dispatch_task(task, now=NOW, trigger=TriggerKind.SCHEDULED)
        record = runs.all_runs()[0]
        await service.delete_task(DeleteTask(task_id=task.task_id, user_id="user-1"))

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

        stored = runs.all_runs()[0]
        assert stored.status is RunStatus.SUCCESS, "the execution record is finalized regardless"
        assert stored.finished_at == NOW
        assert await runs.count_active() == 0, "the active slot is freed"

    async def test_a_cron_task_survives_a_launch_write_landing_mid_completion(self):
        """The interleaving `dispatch_task` already admits is possible.

        A run that fails fast reaches this hook while the dispatch path has not
        yet written its bookkeeping, so the hook reads a task still carrying the
        elapsed `next_run_at`. If the write-back replays that whole snapshot,
        the launch path's fresh fire time is rolled back and the task lands in
        `running` with no live claim -- a shape neither `claim_due` branch nor
        `cancel_stuck_once_tasks` can reach, i.e. permanently unschedulable.
        """
        tasks = _LaunchWritesMidReadTaskRepo(launch_next_run_at=NOW + timedelta(days=1))
        runs = InMemoryScheduledRunRepository()
        service = make_service(tasks=tasks, runs=runs)
        task = await create_cron_task(service)
        await service.dispatch_task(task, now=NOW, trigger=TriggerKind.SCHEDULED)
        record = runs.all_runs()[0]
        tasks.arm()

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
        assert after.last_error == "boom", "the completion still records its verdict"
        assert after.next_run_at == NOW + timedelta(days=1), "the launch path's fire time must survive"
        claimed = await tasks.claim_due(now=NOW + timedelta(days=2), lease_seconds=120, limit=10)
        assert [t.task_id for t in claimed] == [task.task_id], "the task must remain schedulable"


class TestReconcileOnStartup:
    async def test_sweeps_orphaned_runs_and_stuck_once_tasks(self):
        runs = InMemoryScheduledRunRepository()
        tasks = InMemoryScheduledTaskRepository()
        service = make_service(tasks=tasks, runs=runs)
        task = await service.create_scheduled_task(
            CreateScheduledTask(
                user_id="user-1",
                title="one shot",
                prompt="go",
                schedule=once_spec(),
                context_mode=ContextMode.FRESH_THREAD_PER_RUN,
                thread_id=None,
            ),
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

        created = await service.create_scheduled_task(
            CreateScheduledTask(
                user_id="user-1",
                title="t",
                prompt="p",
                schedule=CRON,
                context_mode=ContextMode.REUSE_THREAD,
                thread_id="thread-1",
            ),
            now=NOW,
        )
        assert created.thread_id == "thread-1"

        with pytest.raises(ThreadNotFoundError):
            await service.create_scheduled_task(
                CreateScheduledTask(
                    user_id="user-2",
                    title="t",
                    prompt="p",
                    schedule=CRON,
                    context_mode=ContextMode.REUSE_THREAD,
                    thread_id="thread-1",
                ),
                now=NOW,
            )

    async def test_an_invalid_schedule_is_rejected_before_any_write(self):
        tasks = InMemoryScheduledTaskRepository()
        service = make_service(tasks=tasks)

        with pytest.raises(InvalidScheduleError):
            await service.create_scheduled_task(
                CreateScheduledTask(
                    user_id="user-1",
                    title="t",
                    prompt="p",
                    schedule=once_spec(after_seconds=10),  # inside min_once_delay
                    context_mode=ContextMode.FRESH_THREAD_PER_RUN,
                    thread_id=None,
                ),
                now=NOW,
            )
        assert await service.list_tasks("user-1") == []

    def test_commands_are_dumb_data(self):
        # A command carries intent without validating it: business rules stay
        # on the aggregate, so error attribution (a malformed schedule before
        # an unknown thread) is owned by the handler's construction order,
        # not by the command's own constructor.
        cmd = CreateScheduledTask(user_id="u", title="", prompt="", schedule=CRON, context_mode="not-a-mode", thread_id=None)
        assert cmd.context_mode == "not-a-mode"

    def test_unset_is_a_singleton_distinct_from_none(self):
        # Three states, not two: an update field is UNSET (leave it alone),
        # None can stay a meaningful value elsewhere, and UNSET is falsy so
        # it cannot masquerade as a supplied value.
        assert UnsetType() is UNSET
        cmd = UpdateScheduledTask(task_id="t", user_id="u")
        assert cmd.title is UNSET
        assert cmd.title is not None
        assert not UNSET

    async def test_update_leaves_omitted_fields_alone(self):
        service = make_service()
        task = await create_cron_task(service)

        updated = await service.update_scheduled_task(UpdateScheduledTask(task_id=task.task_id, user_id="user-1", title="renamed"), now=NOW)

        assert updated.title == "renamed"
        assert updated.prompt == task.prompt
        assert updated.schedule == task.schedule

    async def test_update_with_everything_unset_changes_nothing(self):
        service = make_service()
        task = await create_cron_task(service)

        updated = await service.update_scheduled_task(UpdateScheduledTask(task_id=task.task_id, user_id="user-1"), now=NOW)

        assert updated == task

    async def test_update_can_change_the_prompt(self):
        service = make_service()
        task = await create_cron_task(service)

        updated = await service.update_scheduled_task(UpdateScheduledTask(task_id=task.task_id, user_id="user-1", prompt="new instructions"), now=NOW)

        assert updated.prompt == "new instructions"
        assert updated.title == task.title

    async def test_a_task_deleted_mid_update_reports_as_missing(self):
        """get_task saw it, save no longer does -- a concurrent delete landed
        in between. The caller gets the same not-found it would have got a
        moment earlier, rather than a None leaking out."""

        class _VanishingRepo(InMemoryScheduledTaskRepository):
            async def save(self, _task):
                return None

        tasks = _VanishingRepo()
        service = make_service(tasks=tasks)
        task = await create_cron_task(service)

        with pytest.raises(TaskNotFoundError):
            await service.update_scheduled_task(UpdateScheduledTask(task_id=task.task_id, user_id="user-1", title="x"), now=NOW)
        with pytest.raises(TaskNotFoundError):
            await service.pause_task(PauseTask(task_id=task.task_id, user_id="user-1"))

    async def test_context_is_changed_through_the_packaged_value(self):
        """context_mode and thread_id move together, so they are supplied
        together -- which is what lets every other update field use plain
        `None` for "not supplied"."""
        service = make_service(threads=FakeThreadLookup({"thread-1": "user-1"}))
        task = await create_cron_task(service)

        bound = await service.update_scheduled_task(
            UpdateScheduledTask(task_id=task.task_id, user_id="user-1", context=ContextChange(ContextMode.REUSE_THREAD, "thread-1")),
            now=NOW,
        )
        assert bound.context_mode is ContextMode.REUSE_THREAD
        assert bound.thread_id == "thread-1"

        unbound = await service.update_scheduled_task(
            UpdateScheduledTask(task_id=task.task_id, user_id="user-1", context=ContextChange(ContextMode.FRESH_THREAD_PER_RUN)),
            now=NOW,
        )
        assert unbound.thread_id is None, "switching to a fresh thread clears the binding"

    async def test_changing_context_to_an_inaccessible_thread_is_rejected(self):
        service = make_service(threads=FakeThreadLookup({"thread-1": "someone-else"}))
        task = await create_cron_task(service)

        with pytest.raises(ThreadNotFoundError):
            await service.update_scheduled_task(
                UpdateScheduledTask(task_id=task.task_id, user_id="user-1", context=ContextChange(ContextMode.REUSE_THREAD, "thread-1")),
                now=NOW,
            )

    async def test_rescheduling_a_terminal_task_re_arms_it(self):
        tasks = InMemoryScheduledTaskRepository()
        service = make_service(tasks=tasks)
        task = await create_cron_task(service)
        tasks.seed(replace(task, status=TaskStatus.FAILED))

        updated = await service.update_scheduled_task(
            UpdateScheduledTask(task_id=task.task_id, user_id="user-1", schedule=ScheduleSpec.cron_schedule("0 10 * * *", "UTC")),
            now=NOW,
        )

        assert updated.status is TaskStatus.ENABLED, "otherwise it would never be claimed again"

    async def test_a_running_task_cannot_be_edited(self):
        tasks = InMemoryScheduledTaskRepository()
        service = make_service(tasks=tasks)
        task = await create_cron_task(service)
        tasks.seed(replace(task, status=TaskStatus.RUNNING))

        with pytest.raises(TaskNotMutableError):
            await service.update_scheduled_task(UpdateScheduledTask(task_id=task.task_id, user_id="user-1", title="nope"), now=NOW)
        with pytest.raises(TaskNotMutableError):
            await service.pause_task(PauseTask(task_id=task.task_id, user_id="user-1"))

    async def test_a_running_task_can_still_be_deleted(self):
        """The pre-migration router gated update/pause/resume on this, but not
        delete -- that asymmetry is preserved."""
        tasks = InMemoryScheduledTaskRepository()
        service = make_service(tasks=tasks)
        task = await create_cron_task(service)
        tasks.seed(replace(task, status=TaskStatus.RUNNING))

        await service.delete_task(DeleteTask(task_id=task.task_id, user_id="user-1"))

    @pytest.mark.parametrize("call", ["get", "update", "pause", "resume", "delete", "runs"])
    async def test_another_users_task_is_reported_as_missing(self, call):
        service = make_service()
        task = await create_cron_task(service)
        with pytest.raises(TaskNotFoundError):
            if call == "get":
                await service.get_task(task.task_id, user_id="intruder")
            elif call == "update":
                await service.update_scheduled_task(UpdateScheduledTask(task_id=task.task_id, user_id="intruder", title="x"), now=NOW)
            elif call == "pause":
                await service.pause_task(PauseTask(task_id=task.task_id, user_id="intruder"))
            elif call == "resume":
                await service.resume_task(ResumeTask(task_id=task.task_id, user_id="intruder"))
            elif call == "delete":
                await service.delete_task(DeleteTask(task_id=task.task_id, user_id="intruder"))
            else:
                await service.list_task_runs(task.task_id, user_id="intruder")

    async def test_tasks_are_listed_per_user_and_per_thread(self):
        service = make_service(threads=FakeThreadLookup({"thread-1": "user-1"}))
        bound = await service.create_scheduled_task(
            CreateScheduledTask(
                user_id="user-1",
                title="bound",
                prompt="p",
                schedule=CRON,
                context_mode=ContextMode.REUSE_THREAD,
                thread_id="thread-1",
            ),
            now=NOW,
        )
        await create_cron_task(service)

        assert len(await service.list_tasks("user-1")) == 2
        assert await service.list_tasks("someone-else") == []
        by_thread = await service.list_tasks_by_thread("user-1", "thread-1")
        assert [t.task_id for t in by_thread] == [bound.task_id]
