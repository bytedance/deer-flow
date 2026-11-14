"""A task whose stored schedule no longer computes must not stop the scheduler.

Admission validates every schedule, but a stored one can stop computing later:
a zone the installed tz database no longer has, or a cron expression a newer
croniter rejects. The scheduler recomputes the next run inside the shared poll
(launch bookkeeping, lease recovery, queue expiry, launch failure and
finalization), so a raise there used to abort ``run_once`` on every poll and no
other task was admitted again. The task is now paused with the reason instead.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import update

from app.gateway.scheduled_task_validation import prepare_resume_updates, validate_scheduled_task_update
from app.scheduler.service import ScheduledTaskService
from deerflow.config.database_config import DatabaseConfig
from deerflow.config.scheduler_config import SchedulerConfig
from deerflow.persistence.engine import close_engine, get_session_factory, init_engine_from_config
from deerflow.persistence.run import RunRepository
from deerflow.persistence.scheduled_task_runs import ScheduledTaskRunRepository
from deerflow.persistence.scheduled_tasks import ScheduledTaskRepository
from deerflow.persistence.scheduled_tasks.model import ScheduledTaskRow
from deerflow.scheduler.schedules import UNSCHEDULABLE_ERROR_PREFIX

pytestmark = pytest.mark.asyncio

UNKNOWN_ZONE = "Mars/Olympus_Mons"
UNSCHEDULABLE_ERROR = f"{UNSCHEDULABLE_ERROR_PREFIX}Unknown timezone: {UNKNOWN_ZONE}"


@pytest_asyncio.fixture
async def repos(tmp_path):
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    try:
        factory = get_session_factory()
        assert factory is not None
        yield ScheduledTaskRepository(factory), ScheduledTaskRunRepository(factory), RunRepository(factory), factory
    finally:
        await close_engine()


async def _create_task(tasks, task_id, *, next_run_at, context_mode="reuse_thread", schedule_type="interval", schedule_spec=None):
    await tasks.create(
        task_id=task_id,
        user_id="user-1",
        thread_id=f"thread-{task_id}" if context_mode == "reuse_thread" else None,
        context_mode=context_mode,
        assistant_id="lead_agent",
        title=task_id,
        prompt="Work",
        schedule_type=schedule_type,
        schedule_spec=schedule_spec or {"every_seconds": 600},
        timezone="UTC",
        next_run_at=next_run_at,
    )


async def _break_timezone(factory, task_id):
    """Simulate a zone the tz database dropped after the task was admitted."""
    async with factory() as session:
        await session.execute(update(ScheduledTaskRow).where(ScheduledTaskRow.id == task_id).values(timezone=UNKNOWN_ZONE))
        await session.commit()


def _service(tasks, runs, launch_run):
    return ScheduledTaskService(task_repo=tasks, task_run_repo=runs, launch_run=launch_run, poll_interval_seconds=5, lease_seconds=120, max_concurrent_runs=10, queue_timeout_seconds=3600)


def _gateway_launcher(run_store, launched):
    """Record a durable run per occurrence, as Gateway admission does."""
    run_ids: dict[str, str] = {}

    async def launch_run(**kwargs):
        occurrence = kwargs["metadata"]["scheduled_task_run_id"]
        launched.append(kwargs["metadata"]["scheduled_task_id"])
        if occurrence not in run_ids:
            run_ids[occurrence] = f"run-{len(run_ids) + 1}"
            await run_store.put(run_ids[occurrence], thread_id=kwargs["thread_id"], user_id="user-1", status="running", metadata=dict(kwargs["metadata"]))
        return {"run_id": run_ids[occurrence], "thread_id": kwargs["thread_id"]}

    return launch_run


async def _assert_paused(tasks, task_id):
    task = await tasks.get(task_id, user_id="user-1")
    assert task["status"] == "paused"
    assert task["next_run_at"] is None
    assert task["last_error"] == UNSCHEDULABLE_ERROR


@pytest.mark.parametrize("context_mode", ["reuse_thread", "fresh_thread_per_run"])
async def test_unschedulable_task_is_paused_and_every_other_task_keeps_running(repos, context_mode):
    tasks, runs, run_store, factory = repos
    now = datetime.now(UTC)
    await _create_task(tasks, "broken", next_run_at=now - timedelta(seconds=30), context_mode=context_mode)
    await _create_task(tasks, "healthy", next_run_at=now - timedelta(seconds=10), context_mode=context_mode)
    await _create_task(tasks, "later", next_run_at=now + timedelta(seconds=300), context_mode=context_mode)
    await _break_timezone(factory, "broken")
    launched: list[str] = []
    service = _service(tasks, runs, _gateway_launcher(run_store, launched))

    # Past the 120 s launch lease, so lease recovery sees every claim.
    for poll in range(8):
        await service.run_once(now=now + timedelta(seconds=70 * poll))

    assert launched.count("broken") == (1 if context_mode == "reuse_thread" else 0)
    assert launched.count("healthy") == 1
    assert launched.count("later") == 1
    await _assert_paused(tasks, "broken")
    assert (await tasks.get("healthy", user_id="user-1"))["status"] == "enabled"


async def _launching_occurrence(tasks, runs, factory, *, now, run_status=None, run_store=None):
    await _create_task(tasks, "broken", next_run_at=None)
    await runs.create(run_record_id="occurrence-1", task_id="broken", thread_id="thread-broken", scheduled_for=now, trigger="scheduled", status="queued")
    assert await runs.claim_queued_run("occurrence-1", lease_owner="worker", now=now, lease_seconds=5, global_max_concurrent_runs=1)
    if run_status is not None:
        await run_store.put("run-1", thread_id="thread-broken", user_id="user-1", status=run_status, metadata={"scheduled_task_id": "broken", "scheduled_task_run_id": "occurrence-1", "scheduled_trigger": "scheduled"})
    await _break_timezone(factory, "broken")


@pytest.mark.parametrize("run_status", ["running", "success"])
async def test_lease_recovery_pauses_an_unschedulable_task_instead_of_raising(repos, run_status):
    """``running`` repairs the launch; ``success`` finalizes the occurrence."""
    tasks, runs, run_store, factory = repos
    now = datetime.now(UTC)
    await _launching_occurrence(tasks, runs, factory, now=now, run_status=run_status, run_store=run_store)

    assert await runs.recover_expired_launch_claims(error="expired", now=now + timedelta(seconds=6)) == 1

    await _assert_paused(tasks, "broken")
    [occurrence] = await runs.list_by_task("broken")
    assert occurrence["status"] == run_status
    assert occurrence["run_id"] == "run-1"


async def test_failed_launch_pauses_an_unschedulable_task(repos):
    tasks, runs, _run_store, factory = repos
    now = datetime.now(UTC)
    await _launching_occurrence(tasks, runs, factory, now=now)

    assert await runs.fail_launching_run("occurrence-1", task_id="broken", lease_owner="worker", error="launch failed", now=now)

    await _assert_paused(tasks, "broken")
    assert [row["status"] for row in await runs.list_by_task("broken")] == ["failed"]


async def test_queue_expiry_pauses_an_unschedulable_task(repos):
    tasks, runs, _run_store, factory = repos
    now = datetime.now(UTC)
    await _create_task(tasks, "broken", next_run_at=None)
    await runs.create(run_record_id="occurrence-1", task_id="broken", thread_id="thread-broken", scheduled_for=now, trigger="scheduled", status="queued")
    await _break_timezone(factory, "broken")

    expired = await runs.expire_queued_runs(created_before=now + timedelta(seconds=1), error="queue timeout", now=now)

    assert [row["id"] for row in expired] == ["occurrence-1"]
    await _assert_paused(tasks, "broken")


async def test_queue_expiry_continues_after_one_storage_error(repos, monkeypatch, caplog):
    tasks, runs, _run_store, factory = repos
    now = datetime.now(UTC)
    await _create_task(tasks, "a-poison", next_run_at=None)
    await _create_task(tasks, "z-healthy", next_run_at=None)
    await runs.create(
        run_record_id="poison-occurrence",
        task_id="a-poison",
        thread_id="thread-a-poison",
        scheduled_for=now,
        trigger="scheduled",
        status="queued",
    )
    await runs.create(
        run_record_id="healthy-occurrence",
        task_id="z-healthy",
        thread_id="thread-z-healthy",
        scheduled_for=now,
        trigger="scheduled",
        status="queued",
    )
    original_lock_task = ScheduledTaskRunRepository._lock_task

    async def flaky_lock_task(session, task_id):
        if task_id == "a-poison":
            raise RuntimeError("parent row lock failed")
        return await original_lock_task(session, task_id)

    monkeypatch.setattr(ScheduledTaskRunRepository, "_lock_task", staticmethod(flaky_lock_task))
    expired = await runs.expire_queued_runs(
        created_before=now + timedelta(seconds=1),
        error="queue timeout",
        now=now,
    )

    assert [row["id"] for row in expired] == ["healthy-occurrence"]
    assert [row["status"] for row in await runs.list_by_task("a-poison")] == ["queued"]
    assert [row["status"] for row in await runs.list_by_task("z-healthy")] == ["failed"]
    assert "Failed to expire queued scheduled occurrence poison-occurrence" in caplog.text


async def test_failed_recovery_pass_does_not_block_admission(repos, monkeypatch):
    tasks, runs, run_store, _factory = repos
    now = datetime.now(UTC)
    await _create_task(tasks, "healthy", next_run_at=now - timedelta(seconds=10))
    launched: list[str] = []
    service = _service(tasks, runs, _gateway_launcher(run_store, launched))

    async def broken_recovery(**_kwargs):
        raise RuntimeError("recovery pass failed")

    monkeypatch.setattr(runs, "recover_expired_launch_claims", broken_recovery)
    await service.run_once(now=now)

    assert launched == ["healthy"]


@pytest.mark.parametrize("invalid_spec", [None, 42, [42]])
async def test_paused_interval_can_replace_a_malformed_stored_spec(repos, invalid_spec):
    tasks, _, _, factory = repos
    now = datetime.now(UTC)
    await _create_task(tasks, "broken", next_run_at=now + timedelta(minutes=10), context_mode="fresh_thread_per_run")
    async with factory() as session:
        await session.execute(update(ScheduledTaskRow).where(ScheduledTaskRow.id == "broken").values(status="paused", schedule_spec=invalid_spec, next_run_at=None, origin_thread_id="thread-broken", max_runs=None, end_at=None))
        await session.commit()
    existing = await tasks.get("broken", user_id="user-1")
    assert existing is not None

    with pytest.raises(HTTPException) as resume_error:
        prepare_resume_updates(existing, {}, used=0, now=now)
    assert resume_error.value.status_code == 422
    assert resume_error.value.detail["code"] == "invalid_schedule"

    for fields in ({"timezone": "America/New_York"}, {"title": "Renamed"}):
        with pytest.raises(HTTPException) as update_error:
            await validate_scheduled_task_update(existing, fields, user_id="user-1", thread_store=None, scheduler_config=SchedulerConfig(), assistant_resolver=None, used=0, now=now)
        assert update_error.value.status_code == 422
        assert update_error.value.detail["code"] == "invalid_schedule"

    updates = await validate_scheduled_task_update(
        existing,
        {"schedule_spec": {"every_seconds": 900}, "max_runs": 5},
        user_id="user-1",
        thread_store=None,
        scheduler_config=SchedulerConfig(),
        assistant_resolver=None,
        used=0,
        now=now,
    )
    repaired = await tasks.update("broken", user_id="user-1", updates=updates, require_mutable=True)
    assert repaired is not None
    assert repaired["status"] == "paused"
    assert repaired["schedule_spec"] == {"every_seconds": 900}
    resume = prepare_resume_updates(repaired, {}, used=0, now=now)
    assert resume["status"] == "enabled"
    assert resume["next_run_at"] == now + timedelta(seconds=900)


async def test_resuming_reports_the_schedule_until_it_is_fixed(repos):
    """The pause is not a dead end: resume re-validates and names the problem."""
    tasks, runs, run_store, factory = repos
    now = datetime.now(UTC)
    await _create_task(tasks, "broken", next_run_at=now - timedelta(seconds=30))
    await _break_timezone(factory, "broken")
    await _service(tasks, runs, _gateway_launcher(run_store, [])).run_once(now=now)
    paused = await tasks.get("broken", user_id="user-1")

    with pytest.raises(HTTPException) as exc_info:
        prepare_resume_updates(paused, {}, used=0, now=now)

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == {"code": "invalid_schedule", "message": f"Unknown timezone: {UNKNOWN_ZONE}"}


async def test_once_task_without_a_computable_schedule_keeps_its_once_outcome(repos):
    tasks, runs, run_store, factory = repos
    now = datetime.now(UTC)
    await _create_task(tasks, "once", next_run_at=now - timedelta(seconds=30), schedule_type="once", schedule_spec={"run_at": (now - timedelta(seconds=30)).isoformat()})
    await _break_timezone(factory, "once")
    launched: list[str] = []

    await _service(tasks, runs, _gateway_launcher(run_store, launched)).run_once(now=now)

    task = await tasks.get("once", user_id="user-1")
    assert launched == ["once"]
    assert task["status"] == "running"
    assert task["next_run_at"] is None
    assert task["last_error"] is None
