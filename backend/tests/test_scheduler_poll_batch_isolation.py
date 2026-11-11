"""One unusable record must not abort the scheduler's claimed-task batch.

``stored_next_run_at`` tolerates a zone the installed tz database dropped and a
cron a newer croniter rejects, but a stored ``schedule_spec`` that is JSON
null, a list or a string raises ``AttributeError`` from ``.get``. Because the
launch-failure handler recomputes the schedule again, that escape aborted the
rest of ``run_once``'s claimed batch every poll. The loop also relied on every
dispatch path staying raise-free; it now isolates a single task's failure.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.scheduler.service import ScheduledTaskService
from deerflow.config.database_config import DatabaseConfig
from deerflow.persistence.engine import close_engine, get_session_factory, init_engine_from_config
from deerflow.persistence.scheduled_task_runs import ScheduledTaskRunRepository
from deerflow.persistence.scheduled_tasks import ScheduledTaskRepository
from deerflow.scheduler.schedules import UNSCHEDULABLE_ERROR_PREFIX, next_run_at, stored_next_run_at

pytestmark = pytest.mark.asyncio

DUE = datetime(2026, 1, 1, tzinfo=UTC)


def _make_service(task_repo, run_repo, launched: list) -> ScheduledTaskService:
    async def fake_launch(**kwargs):
        launched.append(kwargs)
        return {"run_id": f"run-{len(launched)}", "thread_id": kwargs["thread_id"]}

    return ScheduledTaskService(
        task_repo=task_repo,
        task_run_repo=run_repo,
        launch_run=fake_launch,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_runs=10,
    )


async def _seed_task(task_repo, task_id: str, *, schedule_spec) -> None:
    await task_repo.create(
        task_id=task_id,
        user_id="user-1",
        thread_id=None,
        context_mode="fresh_thread_per_run",
        assistant_id="lead_agent",
        title=task_id,
        prompt="do the thing",
        schedule_type="cron",
        schedule_spec=schedule_spec,
        timezone="UTC",
        next_run_at=DUE,
    )


@pytest.mark.parametrize("spec", [None, [], "*/5 * * * *", 5])
async def test_stored_next_run_at_rejects_a_non_object_spec_without_raising(spec):
    # The raw helper still raises: only runtime bookkeeping tolerates it.
    with pytest.raises(AttributeError):
        next_run_at("cron", spec, "UTC", now=datetime.now(UTC))

    next_at, reason = stored_next_run_at("cron", spec, "UTC", now=datetime.now(UTC))

    assert next_at is None
    assert reason is not None
    assert reason.startswith(UNSCHEDULABLE_ERROR_PREFIX)


async def test_non_object_stored_spec_is_paused_instead_of_aborting_the_batch(tmp_path):
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    try:
        sf = get_session_factory()
        task_repo = ScheduledTaskRepository(sf)
        run_repo = ScheduledTaskRunRepository(sf)
        launched: list = []
        service = _make_service(task_repo, run_repo, launched)

        await _seed_task(task_repo, "poisoned-spec", schedule_spec=[])
        await _seed_task(task_repo, "healthy-cron", schedule_spec={"cron": "*/5 * * * *"})

        # Before the fix the AttributeError escaped the claimed-task loop.
        await service.run_once(now=datetime.now(UTC))

        # The run itself still launches; only the schedule bookkeeping fails.
        assert len(launched) == 2
        poisoned = await task_repo.get("poisoned-spec", user_id="user-1")
        assert poisoned is not None
        assert poisoned["next_run_at"] is None
        assert poisoned["status"] == "paused"
        assert UNSCHEDULABLE_ERROR_PREFIX in (poisoned["last_error"] or "")
        healthy = await task_repo.get("healthy-cron", user_id="user-1")
        assert healthy is not None
        assert healthy["next_run_at"] is not None
    finally:
        await close_engine()


async def test_one_raising_dispatch_does_not_stop_the_rest_of_the_batch(tmp_path, monkeypatch):
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    try:
        sf = get_session_factory()
        task_repo = ScheduledTaskRepository(sf)
        run_repo = ScheduledTaskRunRepository(sf)
        launched: list = []
        service = _make_service(task_repo, run_repo, launched)

        await _seed_task(task_repo, "raising-task", schedule_spec={"cron": "*/5 * * * *"})
        await _seed_task(task_repo, "healthy-cron", schedule_spec={"cron": "*/5 * * * *"})

        original_dispatch = service.dispatch_task

        async def flaky_dispatch(task, *, now, trigger):
            if task["id"] == "raising-task":
                raise RuntimeError("per-record failure")
            return await original_dispatch(task, now=now, trigger=trigger)

        monkeypatch.setattr(service, "dispatch_task", flaky_dispatch)

        # The loop-level guard keeps the batch going and logs the failing task.
        await service.run_once(now=datetime.now(UTC))

        assert len(launched) == 1
    finally:
        await close_engine()
