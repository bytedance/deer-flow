"""Semantics of the in-memory schedule doubles.

These are the rules ``docs`` calls the port contract: what `claim_due` selects,
when `add` refuses, what `protect_terminal` preserves. They are asserted here
against the fakes so the doubles cannot drift from the ports they stand in for
while the service tests lean on them.

This file is the seed of the contract suite: when the SQL adapters land, the
same cases run against both implementations and any divergence between them
becomes a failure rather than a surprise in production. Concurrency stays out
of scope in both tiers -- see the note in ``schedule_fakes``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from schedule_fakes import (
    FakeRunLauncher,
    FakeThreadLookup,
    InMemoryScheduledRunRepository,
    InMemoryScheduledTaskRepository,
)

from deerflow.domain.schedule.model import (
    ActiveRunConflictError,
    ContextMode,
    RunStatus,
    ScheduledRun,
    ScheduledTask,
    ScheduleSpec,
    TaskStatus,
    TriggerKind,
)
from deerflow.domain.schedule.ports import ScheduledRunRepository, ScheduledTaskRepository

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)
CRON = ScheduleSpec.cron_schedule("0 9 * * *", "UTC")
ONCE = ScheduleSpec.once_at(datetime(2026, 8, 1, 9, 0, tzinfo=UTC), "UTC")


def make_task(
    task_id: str = "task-1",
    *,
    user_id: str = "user-1",
    status: TaskStatus = TaskStatus.ENABLED,
    next_run_at: datetime | None = None,
    schedule: ScheduleSpec = CRON,
    thread_id: str | None = None,
    context_mode: ContextMode = ContextMode.FRESH_THREAD_PER_RUN,
) -> ScheduledTask:
    return ScheduledTask(
        task_id=task_id,
        user_id=user_id,
        title=task_id,
        prompt="do the thing",
        schedule=schedule,
        status=status,
        next_run_at=next_run_at,
        thread_id=thread_id,
        context_mode=context_mode,
    )


class TestProtocolConformance:
    """`runtime_checkable` only checks that the methods exist, not their
    signatures -- enough to catch a rename that updates one side only.

    Declared async purely to match this module's asyncio mark; there is
    nothing to await.
    """

    async def test_task_repository_satisfies_the_port(self):
        assert isinstance(InMemoryScheduledTaskRepository(), ScheduledTaskRepository)

    async def test_run_repository_satisfies_the_port(self):
        assert isinstance(InMemoryScheduledRunRepository(), ScheduledRunRepository)


class TestTaskOwnershipIsolation:
    """Another user's task must read as absent, never as forbidden."""

    async def test_get_hides_another_users_task(self):
        repo = InMemoryScheduledTaskRepository()
        await repo.add(make_task(user_id="owner"))
        assert await repo.get("task-1", user_id="owner") is not None
        assert await repo.get("task-1", user_id="intruder") is None

    async def test_save_refuses_another_users_task(self):
        repo = InMemoryScheduledTaskRepository()
        await repo.add(make_task(user_id="owner"))
        assert await repo.save(make_task(user_id="intruder")) is None
        assert (await repo.get("task-1", user_id="owner")).user_id == "owner"

    async def test_delete_refuses_another_users_task(self):
        repo = InMemoryScheduledTaskRepository()
        await repo.add(make_task(user_id="owner"))
        assert await repo.delete("task-1", user_id="intruder") is False
        assert await repo.get("task-1", user_id="owner") is not None

    async def test_list_by_thread_only_matches_bound_tasks(self):
        repo = InMemoryScheduledTaskRepository()
        await repo.add(make_task("bound", context_mode=ContextMode.REUSE_THREAD, thread_id="thread-1"))
        await repo.add(make_task("unbound"))
        listed = await repo.list_by_user_and_thread("user-1", "thread-1")
        assert [task.task_id for task in listed] == ["bound"]


class TestClaimDue:
    async def test_claims_an_enabled_due_task_and_stamps_the_lease(self):
        repo = InMemoryScheduledTaskRepository()
        await repo.add(make_task(next_run_at=NOW - timedelta(minutes=1)))

        claimed = await repo.claim_due(now=NOW, lease_owner="worker-1", lease_seconds=120, limit=10)

        assert [task.task_id for task in claimed] == ["task-1"]
        assert claimed[0].status is TaskStatus.RUNNING
        owner, expires = repo.lease_of("task-1")
        assert owner == "worker-1"
        assert expires == NOW + timedelta(seconds=120)

    @pytest.mark.parametrize(
        ("label", "task_kwargs"),
        [
            ("not yet due", {"next_run_at": NOW + timedelta(minutes=1)}),
            ("never scheduled", {"next_run_at": None}),
            ("paused", {"status": TaskStatus.PAUSED, "next_run_at": NOW - timedelta(minutes=1)}),
            ("completed", {"status": TaskStatus.COMPLETED, "next_run_at": NOW - timedelta(minutes=1)}),
        ],
    )
    async def test_does_not_claim(self, label, task_kwargs):
        repo = InMemoryScheduledTaskRepository()
        await repo.add(make_task(**task_kwargs))
        assert await repo.claim_due(now=NOW, lease_owner="w", lease_seconds=120, limit=10) == [], label

    async def test_does_not_steal_a_live_claim(self):
        repo = InMemoryScheduledTaskRepository()
        repo.seed(
            make_task(next_run_at=NOW - timedelta(minutes=1)),
            lease_owner="worker-1",
            lease_expires_at=NOW + timedelta(seconds=60),
        )
        assert await repo.claim_due(now=NOW, lease_owner="worker-2", lease_seconds=120, limit=10) == []

    async def test_reclaims_a_task_stuck_mid_dispatch(self):
        """The claimer died between claiming and launching: status is running,
        the lease has expired, and the task must not stay unreachable."""
        repo = InMemoryScheduledTaskRepository()
        repo.seed(
            make_task(status=TaskStatus.RUNNING, next_run_at=NOW - timedelta(minutes=1)),
            lease_owner="dead-worker",
            lease_expires_at=NOW - timedelta(seconds=1),
        )

        claimed = await repo.claim_due(now=NOW, lease_owner="worker-2", lease_seconds=120, limit=10)

        assert [task.task_id for task in claimed] == ["task-1"]
        assert repo.lease_of("task-1")[0] == "worker-2"

    async def test_claims_the_most_overdue_first_and_honours_the_limit(self):
        repo = InMemoryScheduledTaskRepository()
        await repo.add(make_task("late", next_run_at=NOW - timedelta(hours=2)))
        await repo.add(make_task("later", next_run_at=NOW - timedelta(hours=1)))

        claimed = await repo.claim_due(now=NOW, lease_owner="w", lease_seconds=120, limit=1)

        assert [task.task_id for task in claimed] == ["late"]


class TestRecordLaunch:
    async def test_writes_bookkeeping_and_releases_the_claim(self):
        repo = InMemoryScheduledTaskRepository()
        repo.seed(make_task(next_run_at=NOW), lease_owner="w", lease_expires_at=NOW + timedelta(seconds=60))

        await repo.record_launch(
            "task-1",
            status=TaskStatus.ENABLED,
            next_run_at=NOW + timedelta(days=1),
            last_run_at=NOW,
            last_run_id="run-1",
            last_thread_id="thread-1",
            last_error=None,
            increment_run_count=True,
        )

        task = await repo.get("task-1", user_id="user-1")
        assert task.status is TaskStatus.ENABLED
        assert task.last_run_id == "run-1"
        assert task.run_count == 1
        assert repo.lease_of("task-1") == (None, None)

    async def test_protect_terminal_keeps_a_concurrently_finalized_verdict(self):
        """A fast-failing run's completion hook lands before the launch path's
        own write; the completion is authoritative."""
        repo = InMemoryScheduledTaskRepository()
        await repo.add(make_task(status=TaskStatus.COMPLETED, schedule=ONCE))

        await repo.record_launch(
            "task-1",
            status=TaskStatus.RUNNING,
            next_run_at=None,
            last_run_at=NOW,
            last_run_id="run-1",
            last_thread_id="thread-1",
            last_error="stale",
            increment_run_count=True,
            protect_terminal=True,
        )

        task = await repo.get("task-1", user_id="user-1")
        assert task.status is TaskStatus.COMPLETED, "the terminal status must survive"
        assert task.last_error is None, "the terminal error must survive"
        assert task.last_run_id == "run-1", "bookkeeping is still recorded"
        assert task.run_count == 1

    async def test_without_protect_terminal_the_write_wins(self):
        repo = InMemoryScheduledTaskRepository()
        await repo.add(make_task(status=TaskStatus.COMPLETED, schedule=ONCE))

        await repo.record_launch(
            "task-1",
            status=TaskStatus.FAILED,
            next_run_at=None,
            last_run_at=NOW,
            last_run_id=None,
            last_thread_id=None,
            last_error="boom",
            increment_run_count=False,
        )

        task = await repo.get("task-1", user_id="user-1")
        assert task.status is TaskStatus.FAILED
        assert task.last_error == "boom"

    async def test_unknown_task_is_ignored(self):
        repo = InMemoryScheduledTaskRepository()
        await repo.record_launch(
            "nope",
            status=TaskStatus.ENABLED,
            next_run_at=None,
            last_run_at=None,
            last_run_id=None,
            last_thread_id=None,
            last_error=None,
            increment_run_count=False,
        )


class TestCancelStuckOnceTasks:
    async def test_cancels_a_launched_once_task_with_no_claim(self):
        repo = InMemoryScheduledTaskRepository()
        repo.seed(make_task(status=TaskStatus.RUNNING, schedule=ONCE))

        assert await repo.cancel_stuck_once_tasks(error="restarted") == 1
        task = await repo.get("task-1", user_id="user-1")
        assert task.status is TaskStatus.CANCELLED
        assert task.last_error == "restarted"

    async def test_leaves_a_claimed_task_to_lease_expiry(self):
        """Claimed but not launched -- expired-claim reclaim recovers it, and
        cancelling here would throw away a dispatch that never happened."""
        repo = InMemoryScheduledTaskRepository()
        repo.seed(
            make_task(status=TaskStatus.RUNNING, schedule=ONCE),
            lease_owner="w",
            lease_expires_at=NOW + timedelta(seconds=60),
        )
        assert await repo.cancel_stuck_once_tasks(error="restarted") == 0

    async def test_leaves_cron_tasks_alone(self):
        repo = InMemoryScheduledTaskRepository()
        repo.seed(make_task(status=TaskStatus.RUNNING, schedule=CRON))
        assert await repo.cancel_stuck_once_tasks(error="restarted") == 0


class TestActiveSlot:
    def _queued(self, task_id: str = "task-1") -> ScheduledRun:
        return ScheduledRun.queued(task_id=task_id, thread_id="thread-1", scheduled_for=NOW, trigger=TriggerKind.SCHEDULED)

    def _tombstone(self, task_id: str = "task-1") -> ScheduledRun:
        return ScheduledRun.skipped_tombstone(task_id=task_id, thread_id="thread-1", scheduled_for=NOW, trigger=TriggerKind.SCHEDULED)

    async def test_second_active_record_is_refused(self):
        repo = InMemoryScheduledRunRepository()
        await repo.add(self._queued())
        with pytest.raises(ActiveRunConflictError):
            await repo.add(self._queued())

    async def test_a_tombstone_never_conflicts(self):
        """Terminal from birth, so it sits outside the active-slot rule -- this
        is why the skip path cannot reuse the queued factory."""
        repo = InMemoryScheduledRunRepository()
        await repo.add(self._queued())
        await repo.add(self._tombstone())
        assert await repo.count_active() == 1

    async def test_another_task_is_unaffected(self):
        repo = InMemoryScheduledRunRepository()
        await repo.add(self._queued("task-1"))
        await repo.add(self._queued("task-2"))
        assert await repo.count_active() == 2

    async def test_slot_frees_up_once_the_record_terminalizes(self):
        repo = InMemoryScheduledRunRepository()
        first = await repo.add(self._queued())
        await repo.update_status(first.record_id, status=RunStatus.SUCCESS, finished_at=NOW)
        await repo.add(self._queued())
        assert await repo.count_active() == 1

    async def test_has_active_is_scoped_to_one_task_while_count_is_global(self):
        repo = InMemoryScheduledRunRepository()
        await repo.add(self._queued("task-1"))
        await repo.add(self._queued("task-2"))
        assert await repo.has_active("task-1") is True
        assert await repo.has_active("task-3") is False
        assert await repo.count_active() == 2


class TestRunStatusWrites:
    async def test_protect_terminal_backfills_without_overwriting(self):
        repo = InMemoryScheduledRunRepository()
        run = await repo.add(ScheduledRun.queued(task_id="t", thread_id="th", scheduled_for=NOW, trigger=TriggerKind.SCHEDULED))
        await repo.update_status(run.record_id, status=RunStatus.FAILED, error="boom", finished_at=NOW)

        # The launch path's write arrives late.
        await repo.update_status(run.record_id, status=RunStatus.RUNNING, run_id="run-1", started_at=NOW, protect_terminal=True)

        stored = repo.all_runs()[0]
        assert stored.status is RunStatus.FAILED
        assert stored.error == "boom"
        assert stored.run_id == "run-1", "the id the completion could not know is backfilled"
        assert stored.started_at == NOW

    async def test_unknown_record_is_ignored(self):
        repo = InMemoryScheduledRunRepository()
        await repo.update_status("nope", status=RunStatus.SUCCESS)

    async def test_mark_stale_active_terminalizes_orphans(self):
        repo = InMemoryScheduledRunRepository()
        active = await repo.add(ScheduledRun.queued(task_id="t", thread_id="th", scheduled_for=NOW, trigger=TriggerKind.SCHEDULED))
        done = await repo.add(ScheduledRun.skipped_tombstone(task_id="t", thread_id="th", scheduled_for=NOW, trigger=TriggerKind.SCHEDULED))

        assert await repo.mark_stale_active(error="gateway restarted") == 1

        by_id = {run.record_id: run for run in repo.all_runs()}
        assert by_id[active.record_id].status is RunStatus.INTERRUPTED
        assert by_id[active.record_id].error == "gateway restarted"
        assert by_id[done.record_id].status is RunStatus.SKIPPED


class TestLauncherAndThreadLookup:
    async def test_launcher_records_the_call_and_echoes_the_thread(self):
        launcher = FakeRunLauncher()
        launched = await launcher.launch(
            thread_id="thread-1",
            assistant_id="lead_agent",
            prompt="go",
            owner_user_id="user-1",
            metadata={"scheduled_task_id": "task-1"},
        )
        assert launched.thread_id == "thread-1"
        assert launcher.calls[0]["metadata"] == {"scheduled_task_id": "task-1"}

    async def test_launcher_can_be_driven_into_either_failure_branch(self):
        boom = RuntimeError("nope")
        launcher = FakeRunLauncher(fail_with=boom)
        with pytest.raises(RuntimeError):
            await launcher.launch(thread_id="t", assistant_id=None, prompt="p", owner_user_id=None, metadata={})
        assert len(launcher.calls) == 1, "the attempt is still recorded"

    async def test_thread_lookup_requires_both_existence_and_ownership(self):
        lookup = FakeThreadLookup({"thread-1": "user-1"})
        assert await lookup.exists_for_user("thread-1", "user-1") is True
        assert await lookup.exists_for_user("thread-1", "user-2") is False
        assert await lookup.exists_for_user("missing", "user-1") is False
