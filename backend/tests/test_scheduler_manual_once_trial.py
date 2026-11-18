"""A trial run ("Run once now") must not consume a one-time task's own run.

The UI offers the trial on every task and says trial runs don't count. For a
``once`` task launched before its run time, the trial's outcome belongs to
the trial's run row only: the task keeps its status and its ``next_run_at``,
and the poller still claims it at the run time. A trial after the run time
has passed is the task's run, so it finalizes the task as before.
"""

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio

from app.scheduler.service import ScheduledTaskService
from deerflow.config.database_config import DatabaseConfig
from deerflow.persistence.engine import close_engine, get_session_factory, init_engine_from_config
from deerflow.persistence.run.model import RunRow
from deerflow.persistence.scheduled_task_runs import ScheduledTaskRunRepository
from deerflow.persistence.scheduled_task_runs.model import ScheduledTaskRunRow
from deerflow.persistence.scheduled_task_runs.projection import once_run_still_scheduled
from deerflow.persistence.scheduled_tasks import ScheduledTaskRepository
from deerflow.persistence.scheduled_tasks.model import ScheduledTaskRow
from deerflow.runtime import RunStatus
from deerflow.runtime.runs.manager import RunRecord
from deerflow.runtime.runs.schemas import DisconnectMode
from deerflow.utils.time import coerce_iso

OWNER = "user-1"
TASK_ID = "task-once"


@pytest_asyncio.fixture
async def repos(tmp_path):
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    sf = get_session_factory()
    try:
        yield ScheduledTaskRepository(sf), ScheduledTaskRunRepository(sf)
    finally:
        await close_engine()


def _service(tasks, runs, launch_run):
    return ScheduledTaskService(
        task_repo=tasks,
        task_run_repo=runs,
        launch_run=launch_run,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_runs=3,
    )


async def _create_once_task(tasks, *, run_at: datetime, status: str = "enabled") -> dict:
    await tasks.create(
        task_id=TASK_ID,
        user_id=OWNER,
        thread_id=None,
        context_mode="fresh_thread_per_run",
        assistant_id=None,
        title="Release check",
        prompt="Check the release checklist.",
        schedule_type="once",
        schedule_spec={"run_at": run_at.isoformat()},
        timezone="UTC",
        next_run_at=run_at,
    )
    if status != "enabled":
        await tasks.update(TASK_ID, user_id=OWNER, updates={"status": status})
    return await tasks.get(TASK_ID, user_id=OWNER)


async def _create_recurring_task(tasks, *, task_id: str, schedule_type: str, schedule_spec: dict, next_run_at: datetime) -> dict:
    await tasks.create(
        task_id=task_id,
        user_id=OWNER,
        thread_id=None,
        context_mode="fresh_thread_per_run",
        assistant_id=None,
        title="Release check",
        prompt="Check the release checklist.",
        schedule_type=schedule_type,
        schedule_spec=schedule_spec,
        timezone="UTC",
        next_run_at=next_run_at,
    )
    return await tasks.get(task_id, user_id=OWNER)


def _record(launch: dict, run_id: str, status: RunStatus, error: str | None = None) -> RunRecord:
    return RunRecord(
        run_id=run_id,
        thread_id=launch["thread_id"],
        assistant_id=None,
        status=status,
        on_disconnect=DisconnectMode.continue_,
        metadata=launch["metadata"],
        user_id=OWNER,
        error=error,
    )


async def _claimed_ids(tasks, *, now: datetime) -> list[str]:
    claimed = await tasks.claim_due_tasks(now=now, lease_owner="poller", lease_seconds=30, limit=10)
    return [task["id"] for task in claimed]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("run_status", "error", "trial_status"),
    [
        (RunStatus.success, None, "success"),
        (RunStatus.error, "boom", "failed"),
        (RunStatus.interrupted, "cancelled by user", "interrupted"),
    ],
)
async def test_trial_before_run_time_keeps_the_once_run_scheduled(repos, run_status, error, trial_status):
    tasks, runs = repos
    now = datetime.now(UTC).replace(microsecond=0)
    run_at = now + timedelta(days=1)
    launches = []

    async def launch_run(**kwargs):
        launches.append(kwargs)
        return {"run_id": "run-trial", "thread_id": kwargs["thread_id"]}

    service = _service(tasks, runs, launch_run)
    task = await _create_once_task(tasks, run_at=run_at)

    result = await service.dispatch_task(task, now=now, trigger="manual")
    assert result["outcome"] == "launched"
    during = await tasks.get(TASK_ID, user_id=OWNER)
    assert (during["status"], during["next_run_at"]) == ("enabled", coerce_iso(run_at))

    await service.handle_run_completion(_record(launches[0], "run-trial", run_status, error))

    after = await tasks.get(TASK_ID, user_id=OWNER)
    assert (after["status"], after["next_run_at"]) == ("enabled", coerce_iso(run_at))
    # The trial's own outcome is still recorded on its run row.
    (occurrence,) = await runs.list_by_task(TASK_ID)
    assert (occurrence["trigger"], occurrence["status"]) == ("manual", trial_status)
    assert await _claimed_ids(tasks, now=now + timedelta(minutes=1)) == []
    assert await _claimed_ids(tasks, now=run_at + timedelta(minutes=1)) == [TASK_ID]


@pytest.mark.asyncio
async def test_trial_on_a_paused_once_task_keeps_it_paused_and_scheduled(repos):
    tasks, runs = repos
    now = datetime.now(UTC).replace(microsecond=0)
    run_at = now + timedelta(days=1)
    launches = []

    async def launch_run(**kwargs):
        launches.append(kwargs)
        return {"run_id": "run-trial", "thread_id": kwargs["thread_id"]}

    service = _service(tasks, runs, launch_run)
    task = await _create_once_task(tasks, run_at=run_at, status="paused")

    await service.dispatch_task(task, now=now, trigger="manual")
    assert (await tasks.get(TASK_ID, user_id=OWNER))["status"] == "paused"
    await service.handle_run_completion(_record(launches[0], "run-trial", RunStatus.success))

    after = await tasks.get(TASK_ID, user_id=OWNER)
    assert (after["status"], after["next_run_at"]) == ("paused", coerce_iso(run_at))


@pytest.mark.asyncio
async def test_completion_before_launch_bookkeeping_keeps_the_once_run_scheduled(repos):
    """A fast trial can finish before the launch path writes the parent."""
    tasks, runs = repos
    now = datetime.now(UTC).replace(microsecond=0)
    run_at = now + timedelta(days=1)
    service = None

    async def launch_run(**kwargs):
        await service.handle_run_completion(_record(kwargs, "run-trial", RunStatus.success))
        return {"run_id": "run-trial", "thread_id": kwargs["thread_id"]}

    service = _service(tasks, runs, launch_run)
    task = await _create_once_task(tasks, run_at=run_at)

    assert (await service.dispatch_task(task, now=now, trigger="manual"))["outcome"] == "launched"

    after = await tasks.get(TASK_ID, user_id=OWNER)
    assert (after["status"], after["next_run_at"]) == ("enabled", coerce_iso(run_at))
    assert await _claimed_ids(tasks, now=run_at + timedelta(minutes=1)) == [TASK_ID]


@pytest.mark.asyncio
async def test_late_trial_bookkeeping_keeps_a_newer_due_task_claim(repos):
    """The trial finishes, the poller claims the now-due task, then the trial's launch write lands.

    The poller's claim holds the parent's dispatch lease until its admission
    inserts the scheduled occurrence. The late trial write passes
    ``can_project`` (no new occurrence sequence yet), and used to clear that
    lease: admission then rejected the poller as stale, leaving the task
    ``running`` with no lease and no occurrence, which only stuck-once
    recovery would later finalize from the trial's outcome.
    """
    tasks, runs = repos
    now = datetime.now(UTC).replace(microsecond=0)
    run_at = now + timedelta(days=1)
    poll_at = run_at + timedelta(minutes=1)
    service = None
    claimed = []
    scheduled_launches = []

    async def launch_run(**kwargs):
        if kwargs["metadata"]["scheduled_trigger"] == "scheduled":
            scheduled_launches.append(kwargs)
            return {"run_id": "run-scheduled", "thread_id": kwargs["thread_id"]}
        await service.handle_run_completion(_record(kwargs, "run-trial", RunStatus.success))
        claimed.extend(await tasks.claim_due_tasks(now=poll_at, lease_owner=service._lease_owner, lease_seconds=30, limit=10))
        return {"run_id": "run-trial", "thread_id": kwargs["thread_id"]}

    service = _service(tasks, runs, launch_run)
    task = await _create_once_task(tasks, run_at=run_at)

    assert (await service.dispatch_task(task, now=now, trigger="manual"))["outcome"] == "launched"
    assert [row["id"] for row in claimed] == [TASK_ID]
    parent = await tasks.get(TASK_ID, user_id=OWNER)
    assert (parent["status"], parent["lease_owner"]) == ("running", service._lease_owner)

    result = await service.dispatch_task(claimed[0], now=poll_at, trigger="scheduled")

    assert (result["outcome"], result["run_id"]) == ("launched", "run-scheduled")
    assert len(scheduled_launches) == 1
    assert (await tasks.get(TASK_ID, user_id=OWNER))["status"] == "running"  # the scheduled run, not a stuck claim


@pytest.mark.asyncio
async def test_failure_before_admission_still_releases_the_pollers_own_claim(repos):
    """The other half of the lease rule: a write with no occurrence row is the claimer's own.

    A legacy thread id that fails validation is recorded before any occurrence
    exists, by the poller that holds the claim; that write must release it.
    """
    tasks, runs = repos
    now = datetime.now(UTC).replace(microsecond=0)

    async def launch_run(**_kwargs):
        raise AssertionError("an invalid thread id must not launch")

    service = _service(tasks, runs, launch_run)
    await tasks.create(
        task_id=TASK_ID,
        user_id=OWNER,
        thread_id="thread.with.dot",
        context_mode="reuse_thread",
        assistant_id=None,
        title="Release check",
        prompt="Check the release checklist.",
        schedule_type="once",
        schedule_spec={"run_at": (now - timedelta(minutes=1)).isoformat()},
        timezone="UTC",
        next_run_at=now - timedelta(minutes=1),
    )
    (claimed,) = await tasks.claim_due_tasks(now=now, lease_owner=service._lease_owner, lease_seconds=30, limit=10)

    assert (await service.dispatch_task(claimed, now=now, trigger="scheduled"))["outcome"] == "failed"

    after = await tasks.get(TASK_ID, user_id=OWNER)
    assert (after["status"], after["lease_owner"], after["lease_expires_at"]) == ("failed", None, None)


@pytest.mark.asyncio
async def test_recovered_trial_launch_keeps_the_once_task_enabled(repos):
    """Launch-claim recovery that finds the trial's live run must not mark the task running."""
    tasks, runs = repos
    now = datetime.now(UTC).replace(microsecond=0)
    run_at = now + timedelta(days=1)
    await _create_once_task(tasks, run_at=run_at)
    await runs.create(
        run_record_id="occurrence-trial",
        task_id=TASK_ID,
        thread_id="thread-trial",
        scheduled_for=now,
        trigger="manual",
        status="queued",
        coordinate_with_task=True,
        expected_task_user_id=OWNER,
        expected_task_status="enabled",
    )
    assert await runs.claim_queued_run("occurrence-trial", lease_owner="crashed", now=now, lease_seconds=120, global_max_concurrent_runs=3) is not None
    # The launcher committed the durable run, then died before its bookkeeping.
    async with get_session_factory()() as session:
        session.add(
            RunRow(
                run_id="run-trial",
                thread_id="thread-trial",
                user_id=OWNER,
                status="running",
                metadata_json={"scheduled_task_id": TASK_ID, "scheduled_task_run_id": "occurrence-trial"},
                created_at=now,
            )
        )
        await session.commit()

    assert await runs.recover_expired_launch_claims(error="recovered", now=now + timedelta(minutes=5)) == 1

    after = await tasks.get(TASK_ID, user_id=OWNER)
    assert (after["status"], after["last_run_id"], after["next_run_at"]) == ("enabled", "run-trial", coerce_iso(run_at))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("schedule_type", "schedule_spec"),
    [("interval", {"every_seconds": 3600}), ("cron", {"cron": "0 10 * * *"})],
)
async def test_manual_trial_does_not_push_recurring_next_run(repos, schedule_type, schedule_spec):
    """A trial before the next occurrence leaves the recurring cadence claimable."""
    tasks, runs = repos
    scheduled_at = datetime(2030, 1, 1, 10, tzinfo=UTC)
    trial_at = scheduled_at - timedelta(minutes=1)
    task_id = f"task-{schedule_type}"
    launches = []

    async def launch_run(**kwargs):
        launches.append(kwargs)
        return {"run_id": f"run-{schedule_type}-trial", "thread_id": kwargs["thread_id"]}

    service = _service(tasks, runs, launch_run)
    task = await _create_recurring_task(
        tasks,
        task_id=task_id,
        schedule_type=schedule_type,
        schedule_spec=schedule_spec,
        next_run_at=scheduled_at,
    )

    result = await service.dispatch_task(task, now=trial_at, trigger="manual")
    assert result["outcome"] == "launched"
    assert (await tasks.get(task_id, user_id=OWNER))["next_run_at"] == coerce_iso(scheduled_at)

    await service.handle_run_completion(_record(launches[0], result["run_id"], RunStatus.success))
    after = await tasks.get(task_id, user_id=OWNER)
    assert (after["status"], after["next_run_at"]) == ("enabled", coerce_iso(scheduled_at))

    claimed = await tasks.claim_due_tasks(now=scheduled_at, lease_owner="poller", lease_seconds=30, limit=10)
    assert [claimed_task["id"] for claimed_task in claimed] == [task_id]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("schedule_type", "schedule_spec", "expected_next_run_at"),
    [
        ("interval", {"every_seconds": 3600}, datetime(2030, 1, 1, 11, 6, tzinfo=UTC)),
        ("cron", {"cron": "0 10 * * *"}, datetime(2030, 1, 2, 10, tzinfo=UTC)),
    ],
)
async def test_trial_after_missed_recurring_slot_allows_one_catch_up(repos, schedule_type, schedule_spec, expected_next_run_at):
    """An overdue cursor survives the trial and advances only at catch-up dispatch."""
    tasks, runs = repos
    scheduled_at = datetime(2030, 1, 1, 10, tzinfo=UTC)
    trial_at = scheduled_at + timedelta(minutes=5)
    catch_up_at = scheduled_at + timedelta(minutes=6)
    task_id = f"overdue-{schedule_type}"
    launches = []

    async def launch_run(**kwargs):
        launches.append(kwargs)
        return {"run_id": f"run-{len(launches)}", "thread_id": kwargs["thread_id"]}

    service = _service(tasks, runs, launch_run)
    task = await _create_recurring_task(
        tasks,
        task_id=task_id,
        schedule_type=schedule_type,
        schedule_spec=schedule_spec,
        next_run_at=scheduled_at,
    )
    assert (await service.dispatch_task(task, now=trial_at, trigger="manual"))["outcome"] == "launched"
    assert (await tasks.get(task_id, user_id=OWNER))["next_run_at"] == coerce_iso(scheduled_at)

    # The due cursor must not bypass the trial's single active-occurrence slot.
    await service.run_once(now=trial_at + timedelta(seconds=30))
    assert len(launches) == 1
    assert len(await runs.list_by_task(task_id)) == 1

    await service.handle_run_completion(_record(launches[0], "run-1", RunStatus.success))
    assert (await tasks.get(task_id, user_id=OWNER))["next_run_at"] == coerce_iso(scheduled_at)
    await service.run_once(now=catch_up_at)

    assert [launch["metadata"]["scheduled_trigger"] for launch in launches] == ["manual", "scheduled"]
    assert (await tasks.get(task_id, user_id=OWNER))["next_run_at"] == coerce_iso(expected_next_run_at)
    # Neither another poll while active nor one after completion repeats the
    # overdue occurrence; the catch-up dispatch has moved the cursor forward.
    await service.run_once(now=catch_up_at + timedelta(seconds=1))
    await service.handle_run_completion(_record(launches[1], "run-2", RunStatus.success))
    await service.run_once(now=catch_up_at + timedelta(minutes=1))
    assert len(launches) == 2
    occurrences = await runs.list_by_task(task_id)
    assert sorted((row["trigger"], row["status"]) for row in occurrences) == [("manual", "success"), ("scheduled", "success")]
    assert (await tasks.get(task_id, user_id=OWNER))["next_run_at"] == coerce_iso(expected_next_run_at)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("schedule_type", "schedule_spec"),
    [("interval", {"every_seconds": 3600}), ("cron", {"cron": "0 10 * * *"})],
)
async def test_recovered_recurring_trial_keeps_next_run(repos, schedule_type, schedule_spec):
    """Crash recovery must preserve cadence for a manual recurring trial too."""
    tasks, runs = repos
    scheduled_at = datetime(2030, 1, 1, 10, tzinfo=UTC)
    trial_at = scheduled_at - timedelta(minutes=1)
    task_id = f"recovered-{schedule_type}"
    await _create_recurring_task(
        tasks,
        task_id=task_id,
        schedule_type=schedule_type,
        schedule_spec=schedule_spec,
        next_run_at=scheduled_at,
    )
    await runs.create(
        run_record_id=f"occurrence-{schedule_type}",
        task_id=task_id,
        thread_id=f"thread-{schedule_type}",
        scheduled_for=trial_at,
        trigger="manual",
        status="queued",
        coordinate_with_task=True,
        expected_task_user_id=OWNER,
        expected_task_status="enabled",
    )
    assert (
        await runs.claim_queued_run(
            f"occurrence-{schedule_type}",
            lease_owner="crashed",
            now=trial_at,
            lease_seconds=120,
            global_max_concurrent_runs=3,
        )
        is not None
    )
    async with get_session_factory()() as session:
        session.add(
            RunRow(
                run_id=f"run-{schedule_type}-trial",
                thread_id=f"thread-{schedule_type}",
                user_id=OWNER,
                status="running",
                metadata_json={"scheduled_task_id": task_id, "scheduled_task_run_id": f"occurrence-{schedule_type}"},
                created_at=trial_at,
            )
        )
        await session.commit()

    assert await runs.recover_expired_launch_claims(error="recovered", now=trial_at + timedelta(minutes=5)) == 1
    after = await tasks.get(task_id, user_id=OWNER)
    assert (after["status"], after["last_run_id"], after["next_run_at"]) == ("enabled", f"run-{schedule_type}-trial", coerce_iso(scheduled_at))


@pytest.mark.asyncio
async def test_trial_after_run_time_still_finalizes_the_once_task(repos):
    """Once the run time has passed, the trial is the task's run (scheduler off or not yet polled)."""
    tasks, runs = repos
    now = datetime.now(UTC).replace(microsecond=0)
    run_at = now - timedelta(minutes=5)
    launches = []

    async def launch_run(**kwargs):
        launches.append(kwargs)
        return {"run_id": "run-trial", "thread_id": kwargs["thread_id"]}

    service = _service(tasks, runs, launch_run)
    task = await _create_once_task(tasks, run_at=run_at)

    await service.dispatch_task(task, now=now, trigger="manual")
    assert (await tasks.get(TASK_ID, user_id=OWNER))["status"] == "running"
    await service.handle_run_completion(_record(launches[0], "run-trial", RunStatus.success))

    after = await tasks.get(TASK_ID, user_id=OWNER)
    assert (after["status"], after["next_run_at"]) == ("completed", None)


@pytest.mark.parametrize(
    ("schedule_type", "trigger", "expected"),
    [("once", "manual", True), ("once", "scheduled", False), ("cron", "manual", False), ("interval", "manual", False)],
)
def test_once_run_still_scheduled_applies_only_to_once_trials(schedule_type, trigger, expected):
    """A recurring task always has a next run, so the rule must not read that as a pending once run."""
    task = ScheduledTaskRow(schedule_type=schedule_type, next_run_at=datetime.now(UTC) + timedelta(days=1))
    occurrence = ScheduledTaskRunRow(trigger=trigger)
    assert once_run_still_scheduled(task, occurrence) is expected
