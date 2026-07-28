"""Contract suite for the schedule repository ports.

Every case here runs **twice**: once against the in-memory doubles and once
against the SQL adapters on a real file-backed sqlite database. That is the
point -- a rule stated in a port docstring has to hold for both, and a
divergence becomes a failure rather than a surprise in production.

What the contract owns is single-threaded semantics: which rows `claim_due`
selects, that `add` refuses a second active record, what `protect_terminal`
preserves. What it deliberately does **not** own is atomicity -- the doubles
provide none, and a green run here says nothing about two dispatchers racing.
That is covered against a real database in
``test_scheduled_task_dispatch_race.py``. Do not read a passing contract suite
as licence to run more than one scheduler.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from schedule_fakes import (
    FakeRunLauncher,
    FakeThreadLookup,
    InMemoryScheduledRunRepository,
    InMemoryScheduledTaskRepository,
)

from app.adapters.schedule.scheduled_run_repository import SqlScheduledRunRepository
from app.adapters.schedule.scheduled_task_repository import SqlScheduledTaskRepository
from deerflow.config.database_config import DatabaseConfig
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
from deerflow.persistence.engine import close_engine, get_session_factory, init_engine_from_config

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)
CRON = ScheduleSpec.cron_schedule("0 9 * * *", "UTC")
ONCE = ScheduleSpec.once_at(datetime(2026, 8, 1, 9, 0, tzinfo=UTC), "UTC")


@pytest_asyncio.fixture(params=["memory", "sql"])
async def repos(request, tmp_path) -> AsyncIterator[tuple[ScheduledTaskRepository, ScheduledRunRepository]]:
    """One parametrized fixture, two implementations of the same ports."""
    if request.param == "memory":
        yield InMemoryScheduledTaskRepository(), InMemoryScheduledRunRepository()
        return
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    try:
        sf = get_session_factory()
        assert sf is not None
        yield SqlScheduledTaskRepository(sf), SqlScheduledRunRepository(sf)
    finally:
        await close_engine()


@pytest_asyncio.fixture
async def tasks(repos) -> ScheduledTaskRepository:
    return repos[0]


@pytest_asyncio.fixture
async def runs(repos) -> ScheduledRunRepository:
    return repos[1]


async def seed(
    repo: ScheduledTaskRepository,
    task: ScheduledTask,
    *,
    claimed_until: datetime | None = None,
) -> ScheduledTask:
    """Install a task, optionally already carrying a claim.

    A claim cannot be installed through the port -- `claim_due` only stamps
    tasks that are actually due, and these cases need shapes that claiming
    would never produce (running with an *expired* claim, running with a live
    one). So each implementation is set up directly: the fake exposes a seed
    helper, and the SQL side writes the row. That is the one place this suite
    reaches past the port, and it is why the assertions that follow go back
    through it.
    """
    stored = await repo.add(task)
    if claimed_until is None:
        return stored

    if isinstance(repo, InMemoryScheduledTaskRepository):
        repo.seed(task, lease_owner="prior-worker", lease_expires_at=claimed_until)
        return task

    from deerflow.persistence.scheduled_tasks.model import ScheduledTaskRow

    factory = get_session_factory()
    assert factory is not None
    async with factory() as session:
        row = await session.get(ScheduledTaskRow, task.task_id)
        row.lease_owner = "prior-worker"
        row.lease_expires_at = claimed_until
        await session.commit()
    return task


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
    signatures -- enough to catch a rename that updates one side only."""

    async def test_repositories_satisfy_their_ports(self, tasks, runs):
        assert isinstance(tasks, ScheduledTaskRepository)
        assert isinstance(runs, ScheduledRunRepository)


class TestTaskOwnershipIsolation:
    """Another user's task must read as absent, never as forbidden."""

    async def test_get_hides_another_users_task(self, tasks):
        await tasks.add(make_task(user_id="owner"))
        assert await tasks.get("task-1", user_id="owner") is not None
        assert await tasks.get("task-1", user_id="intruder") is None

    async def test_save_refuses_another_users_task(self, tasks):
        await tasks.add(make_task(user_id="owner"))
        assert await tasks.save(make_task(user_id="intruder")) is None
        stored = await tasks.get("task-1", user_id="owner")
        assert stored.user_id == "owner"

    async def test_delete_refuses_another_users_task(self, tasks):
        await tasks.add(make_task(user_id="owner"))
        assert await tasks.delete("task-1", user_id="intruder") is False
        assert await tasks.get("task-1", user_id="owner") is not None

    async def test_list_by_user_excludes_other_owners(self, tasks):
        await tasks.add(make_task("mine", user_id="owner"))
        await tasks.add(make_task("theirs", user_id="someone-else"))
        assert [t.task_id for t in await tasks.list_by_user("owner")] == ["mine"]

    async def test_list_by_thread_only_matches_bound_tasks(self, tasks):
        await tasks.add(make_task("bound", context_mode=ContextMode.REUSE_THREAD, thread_id="thread-1"))
        await tasks.add(make_task("unbound"))
        listed = await tasks.list_by_user_and_thread("user-1", "thread-1")
        assert [task.task_id for task in listed] == ["bound"]


class TestRoundTrip:
    """What goes in comes back out -- including the value object, which the
    SQL side has to rebuild from three separate columns."""

    async def test_a_cron_task_round_trips(self, tasks):
        original = await tasks.add(make_task(schedule=ScheduleSpec.cron_schedule("*/5 * * * *", "Asia/Shanghai")))
        stored = await tasks.get(original.task_id, user_id="user-1")
        assert stored.schedule == original.schedule
        assert stored.schedule.cron == "*/5 * * * *"
        assert stored.schedule.timezone == "Asia/Shanghai"

    async def test_a_once_task_round_trips_to_the_same_instant(self, tasks):
        original = await tasks.add(make_task(schedule=ONCE))
        stored = await tasks.get(original.task_id, user_id="user-1")
        assert stored.schedule == original.schedule

    async def test_timestamps_come_back_timezone_aware(self, tasks):
        """SQLite drops tzinfo on read; a naive datetime downstream would
        compare wrong against an aware `now`."""
        await tasks.add(make_task(next_run_at=NOW))
        stored = await tasks.get("task-1", user_id="user-1")
        assert stored.next_run_at.tzinfo is not None
        assert stored.created_at.tzinfo is not None

    async def test_save_replaces_the_whole_aggregate(self, tasks):
        from dataclasses import replace

        await tasks.add(make_task())
        stored = await tasks.get("task-1", user_id="user-1")

        await tasks.save(replace(stored, title="renamed", status=TaskStatus.PAUSED, run_count=7))

        reloaded = await tasks.get("task-1", user_id="user-1")
        assert reloaded.title == "renamed"
        assert reloaded.status is TaskStatus.PAUSED
        assert reloaded.run_count == 7


class TestClaimDue:
    async def test_claims_an_enabled_due_task(self, tasks):
        await tasks.add(make_task(next_run_at=NOW - timedelta(minutes=1)))

        claimed = await tasks.claim_due(now=NOW, lease_seconds=120, limit=10)

        assert [task.task_id for task in claimed] == ["task-1"]
        assert claimed[0].status is TaskStatus.RUNNING

    async def test_a_claimed_task_is_not_claimed_again(self, tasks):
        """The lease is not readable through the port, so the rule is asserted
        the way it actually matters: a second claimer comes back empty."""
        await tasks.add(make_task(next_run_at=NOW - timedelta(minutes=1)))
        assert len(await tasks.claim_due(now=NOW, lease_seconds=120, limit=10)) == 1

        assert await tasks.claim_due(now=NOW, lease_seconds=120, limit=10) == []

    async def test_the_claim_expires(self, tasks):
        await tasks.add(make_task(next_run_at=NOW - timedelta(minutes=1)))
        await tasks.claim_due(now=NOW, lease_seconds=60, limit=10)

        later = NOW + timedelta(seconds=61)
        reclaimed = await tasks.claim_due(now=later, lease_seconds=60, limit=10)

        assert [task.task_id for task in reclaimed] == ["task-1"]

    @pytest.mark.parametrize(
        ("label", "task_kwargs"),
        [
            ("not yet due", {"next_run_at": NOW + timedelta(minutes=1)}),
            ("never scheduled", {"next_run_at": None}),
            ("paused", {"status": TaskStatus.PAUSED, "next_run_at": NOW - timedelta(minutes=1)}),
            ("completed", {"status": TaskStatus.COMPLETED, "next_run_at": NOW - timedelta(minutes=1)}),
        ],
    )
    async def test_does_not_claim(self, tasks, label, task_kwargs):
        await tasks.add(make_task(**task_kwargs))
        assert await tasks.claim_due(now=NOW, lease_seconds=120, limit=10) == [], label

    async def test_reclaims_a_task_stuck_mid_dispatch(self, tasks):
        """The claimer died between claiming and launching: status is running,
        the claim has expired, and the task must not stay unreachable."""
        await seed(
            tasks,
            make_task(status=TaskStatus.RUNNING, next_run_at=NOW - timedelta(minutes=1)),
            claimed_until=NOW - timedelta(seconds=1),
        )

        claimed = await tasks.claim_due(now=NOW, lease_seconds=120, limit=10)

        assert [task.task_id for task in claimed] == ["task-1"]

    async def test_claims_the_most_overdue_first_and_honours_the_limit(self, tasks):
        await tasks.add(make_task("late", next_run_at=NOW - timedelta(hours=2)))
        await tasks.add(make_task("later", next_run_at=NOW - timedelta(hours=1)))

        claimed = await tasks.claim_due(now=NOW, lease_seconds=120, limit=1)

        assert [task.task_id for task in claimed] == ["late"]


class TestRecordLaunch:
    async def test_writes_bookkeeping_and_frees_the_task_for_the_next_round(self, tasks):
        await tasks.add(make_task(next_run_at=NOW - timedelta(minutes=1)))
        await tasks.claim_due(now=NOW, lease_seconds=120, limit=10)

        await tasks.record_launch(
            "task-1",
            status=TaskStatus.ENABLED,
            next_run_at=NOW - timedelta(seconds=1),
            last_run_at=NOW,
            last_run_id="run-1",
            last_thread_id="thread-1",
            last_error=None,
            increment_run_count=True,
        )

        task = await tasks.get("task-1", user_id="user-1")
        assert task.status is TaskStatus.ENABLED
        assert task.last_run_id == "run-1"
        assert task.run_count == 1
        # The claim was released, so the next round can take it again.
        assert len(await tasks.claim_due(now=NOW, lease_seconds=120, limit=10)) == 1

    async def test_protect_terminal_keeps_a_concurrently_finalized_verdict(self, tasks):
        """A fast-failing run's completion hook lands before the launch path's
        own write; the completion is authoritative."""
        await tasks.add(make_task(status=TaskStatus.COMPLETED, schedule=ONCE))

        await tasks.record_launch(
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

        task = await tasks.get("task-1", user_id="user-1")
        assert task.status is TaskStatus.COMPLETED, "the terminal status must survive"
        assert task.last_error is None, "the terminal error must survive"
        assert task.last_run_id == "run-1", "bookkeeping is still recorded"
        assert task.run_count == 1

    async def test_without_protect_terminal_the_write_wins(self, tasks):
        await tasks.add(make_task(status=TaskStatus.COMPLETED, schedule=ONCE))

        await tasks.record_launch(
            "task-1",
            status=TaskStatus.FAILED,
            next_run_at=None,
            last_run_at=NOW,
            last_run_id=None,
            last_thread_id=None,
            last_error="boom",
            increment_run_count=False,
        )

        task = await tasks.get("task-1", user_id="user-1")
        assert task.status is TaskStatus.FAILED
        assert task.last_error == "boom"

    async def test_unknown_task_is_ignored(self, tasks):
        await tasks.record_launch(
            "nope",
            status=TaskStatus.ENABLED,
            next_run_at=None,
            last_run_at=None,
            last_run_id=None,
            last_thread_id=None,
            last_error=None,
            increment_run_count=False,
        )


class TestRecordCompletion:
    """The completion hook's write.

    Deliberately as narrow as `record_launch` is, and for the same reason: the
    two race, so neither may write through the whole aggregate. This one owns
    the terminal verdict and nothing else -- every scheduling field belongs to
    the launch path, which may commit at any point around it.
    """

    async def test_records_the_terminal_status_and_error(self, tasks):
        await tasks.add(make_task(status=TaskStatus.RUNNING, schedule=ONCE))

        await tasks.record_completion("task-1", user_id="user-1", status=TaskStatus.FAILED, error="boom")

        task = await tasks.get("task-1", user_id="user-1")
        assert task.status is TaskStatus.FAILED
        assert task.last_error == "boom"

    async def test_a_none_status_records_the_error_and_leaves_the_status(self, tasks):
        """A cron task's schedule outlives any single run, so only what went
        wrong is recorded."""
        await tasks.add(make_task(status=TaskStatus.ENABLED, schedule=CRON))

        await tasks.record_completion("task-1", user_id="user-1", status=None, error="boom")

        task = await tasks.get("task-1", user_id="user-1")
        assert task.status is TaskStatus.ENABLED
        assert task.last_error == "boom"

    async def test_never_rolls_back_a_concurrent_launch_write(self, tasks):
        """The regression this method exists to prevent.

        A fast-failing run reaches the completion hook while the dispatch path
        is still writing its bookkeeping. Whichever lands second must not undo
        the other: the launch owns the schedule, the completion owns the
        verdict.
        """
        await tasks.add(make_task(next_run_at=NOW - timedelta(minutes=1)))
        await tasks.claim_due(now=NOW, lease_seconds=120, limit=10)

        next_at = NOW + timedelta(days=1)
        await tasks.record_launch(
            "task-1",
            status=TaskStatus.ENABLED,
            next_run_at=next_at,
            last_run_at=NOW,
            last_run_id="run-1",
            last_thread_id="thread-1",
            last_error=None,
            increment_run_count=True,
            protect_terminal=True,
        )

        await tasks.record_completion("task-1", user_id="user-1", status=None, error="boom")

        task = await tasks.get("task-1", user_id="user-1")
        assert task.next_run_at == next_at, "the launch path's next fire time must survive"
        assert task.run_count == 1, "the launch path's run count must survive"
        assert task.last_run_id == "run-1"
        assert task.last_thread_id == "thread-1"
        assert task.last_error == "boom", "the completion still records its verdict"
        # The whole point: the task is still reachable by the next poll.
        claimed = await tasks.claim_due(now=NOW + timedelta(days=2), lease_seconds=120, limit=10)
        assert [t.task_id for t in claimed] == ["task-1"]

    async def test_another_users_task_is_untouched(self, tasks):
        await tasks.add(make_task(status=TaskStatus.ENABLED))

        await tasks.record_completion("task-1", user_id="someone-else", status=TaskStatus.FAILED, error="boom")

        task = await tasks.get("task-1", user_id="user-1")
        assert task.status is TaskStatus.ENABLED
        assert task.last_error is None

    async def test_unknown_task_is_ignored(self, tasks):
        await tasks.record_completion("nope", user_id="user-1", status=TaskStatus.FAILED, error="boom")


class TestCancelStuckOnceTasks:
    async def test_cancels_a_launched_once_task_with_no_claim(self, tasks):
        """Launched, so the claim was released; the completion hook then died
        with the process. Expired-claim reclaim can never see this one."""
        await tasks.add(make_task(status=TaskStatus.RUNNING, schedule=ONCE))

        assert await tasks.cancel_stuck_once_tasks(error="restarted") == 1
        task = await tasks.get("task-1", user_id="user-1")
        assert task.status is TaskStatus.CANCELLED
        assert task.last_error == "restarted"

    async def test_leaves_a_claimed_task_to_claim_expiry(self, tasks):
        """Claimed but not launched -- expired-claim reclaim recovers it, and
        cancelling here would throw away a dispatch that never happened."""
        await seed(
            tasks,
            make_task(status=TaskStatus.RUNNING, schedule=ONCE, next_run_at=NOW - timedelta(minutes=1)),
            claimed_until=NOW + timedelta(seconds=60),
        )
        assert await tasks.cancel_stuck_once_tasks(error="restarted") == 0

    async def test_leaves_cron_tasks_alone(self, tasks):
        await tasks.add(make_task(status=TaskStatus.RUNNING, schedule=CRON))
        assert await tasks.cancel_stuck_once_tasks(error="restarted") == 0


class TestActiveSlot:
    def _queued(self, task_id: str = "task-1") -> ScheduledRun:
        return ScheduledRun.queued(task_id=task_id, thread_id="thread-1", scheduled_for=NOW, trigger=TriggerKind.SCHEDULED)

    def _tombstone(self, task_id: str = "task-1") -> ScheduledRun:
        return ScheduledRun.skipped_tombstone(task_id=task_id, thread_id="thread-1", scheduled_for=NOW, trigger=TriggerKind.SCHEDULED)

    async def test_second_active_record_is_refused(self, runs):
        await runs.add(self._queued())
        with pytest.raises(ActiveRunConflictError):
            await runs.add(self._queued())

    async def test_a_tombstone_never_conflicts(self, runs):
        """Terminal from birth, so it sits outside the active-slot rule -- this
        is why the skip path cannot reuse the queued factory."""
        await runs.add(self._queued())
        await runs.add(self._tombstone())
        assert await runs.count_active() == 1

    async def test_another_task_is_unaffected(self, runs):
        await runs.add(self._queued("task-1"))
        await runs.add(self._queued("task-2"))
        assert await runs.count_active() == 2

    async def test_slot_frees_up_once_the_record_terminalizes(self, runs):
        first = await runs.add(self._queued())
        await runs.update_status(first.record_id, status=RunStatus.SUCCESS, finished_at=NOW)
        await runs.add(self._queued())
        assert await runs.count_active() == 1

    async def test_has_active_is_scoped_to_one_task_while_count_is_global(self, runs):
        await runs.add(self._queued("task-1"))
        await runs.add(self._queued("task-2"))
        assert await runs.has_active("task-1") is True
        assert await runs.has_active("task-3") is False
        assert await runs.count_active() == 2

    async def test_a_run_round_trips(self, runs):
        stored = await runs.add(self._queued())
        listed = await runs.list_by_task("task-1", limit=10, offset=0)
        assert [r.record_id for r in listed] == [stored.record_id]
        assert listed[0].trigger is TriggerKind.SCHEDULED
        assert listed[0].scheduled_for.tzinfo is not None


class TestRunStatusWrites:
    async def _one_queued(self, runs) -> ScheduledRun:
        return await runs.add(ScheduledRun.queued(task_id="t", thread_id="th", scheduled_for=NOW, trigger=TriggerKind.SCHEDULED))

    async def test_protect_terminal_backfills_without_overwriting(self, runs):
        run = await self._one_queued(runs)
        await runs.update_status(run.record_id, status=RunStatus.FAILED, error="boom", finished_at=NOW)

        # The launch path's write arrives late.
        await runs.update_status(run.record_id, status=RunStatus.RUNNING, run_id="run-1", started_at=NOW, protect_terminal=True)

        stored = (await runs.list_by_task("t", limit=10, offset=0))[0]
        assert stored.status is RunStatus.FAILED
        assert stored.error == "boom"
        assert stored.run_id == "run-1", "the id the completion could not know is backfilled"
        assert stored.started_at == NOW

    async def test_unknown_record_is_ignored(self, runs):
        await runs.update_status("nope", status=RunStatus.SUCCESS)

    async def test_mark_stale_active_terminalizes_orphans(self, runs):
        active = await self._one_queued(runs)
        done = await runs.add(ScheduledRun.skipped_tombstone(task_id="t", thread_id="th", scheduled_for=NOW, trigger=TriggerKind.SCHEDULED))

        assert await runs.mark_stale_active(error="gateway restarted") == 1

        by_id = {run.record_id: run for run in await runs.list_by_task("t", limit=10, offset=0)}
        assert by_id[active.record_id].status is RunStatus.INTERRUPTED
        assert by_id[active.record_id].error == "gateway restarted"
        assert by_id[done.record_id].status is RunStatus.SKIPPED


class TestLauncherAndThreadLookup:
    """Fake-only: these two ports have no SQL implementation -- one starts a
    run and the other asks the thread store, so both land in later adapters."""

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
