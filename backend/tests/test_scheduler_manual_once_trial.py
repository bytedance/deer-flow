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
from deerflow.persistence.scheduled_tasks import ScheduledTaskRepository
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
