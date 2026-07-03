from datetime import UTC, datetime

import pytest

from deerflow.config.database_config import DatabaseConfig
from deerflow.persistence.engine import close_engine, get_session_factory, init_engine_from_config
from deerflow.persistence.scheduled_task_runs import ScheduledTaskRunRepository
from deerflow.persistence.scheduled_tasks import ScheduledTaskRepository


@pytest.mark.asyncio
async def test_scheduled_task_repository_create_and_list(tmp_path):
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    sf = get_session_factory()
    assert sf is not None

    repo = ScheduledTaskRepository(sf)
    created = await repo.create(
        task_id="task-1",
        user_id="user-1",
        thread_id="thread-1",
        context_mode="reuse_thread",
        assistant_id="lead_agent",
        title="Daily summary",
        prompt="Summarize this thread",
        schedule_type="cron",
        schedule_spec={"cron": "0 9 * * *"},
        timezone="Asia/Shanghai",
        next_run_at=datetime(2026, 7, 2, 1, 0, tzinfo=UTC),
    )

    assert created["id"] == "task-1"
    listed = await repo.list_by_user("user-1")
    assert [task["id"] for task in listed] == ["task-1"]

    await close_engine()


@pytest.mark.asyncio
async def test_scheduled_task_run_repository_records_history(tmp_path):
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    sf = get_session_factory()
    assert sf is not None

    repo = ScheduledTaskRunRepository(sf)
    row = await repo.create(
        run_record_id="task-run-1",
        task_id="task-1",
        thread_id="thread-1",
        scheduled_for=datetime(2026, 7, 2, 1, 0, tzinfo=UTC),
        trigger="manual",
        status="queued",
    )

    assert row["id"] == "task-run-1"
    history = await repo.list_by_task("task-1")
    assert [entry["id"] for entry in history] == ["task-run-1"]

    await close_engine()


@pytest.mark.asyncio
async def test_mark_stale_active_runs_fails_orphaned_runs(tmp_path):
    """Runs stuck in queued/running after a process crash are swept to failed."""
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    sf = get_session_factory()
    assert sf is not None

    repo = ScheduledTaskRunRepository(sf)
    await repo.create(
        run_record_id="task-run-queued",
        task_id="task-1",
        thread_id="thread-1",
        scheduled_for=datetime(2026, 7, 2, 1, 0, tzinfo=UTC),
        trigger="scheduled",
        status="queued",
    )
    await repo.create(
        run_record_id="task-run-running",
        task_id="task-1",
        thread_id="thread-1",
        scheduled_for=datetime(2026, 7, 2, 1, 0, tzinfo=UTC),
        trigger="scheduled",
        status="running",
    )
    await repo.create(
        run_record_id="task-run-success",
        task_id="task-1",
        thread_id="thread-1",
        scheduled_for=datetime(2026, 7, 2, 1, 0, tzinfo=UTC),
        trigger="scheduled",
        status="success",
    )

    swept = await repo.mark_stale_active_runs(error="interrupted: gateway restarted")
    assert swept == 2

    history = await repo.list_by_task("task-1")
    by_id = {entry["id"]: entry for entry in history}
    assert by_id["task-run-queued"]["status"] == "failed"
    assert by_id["task-run-running"]["status"] == "failed"
    assert by_id["task-run-success"]["status"] == "success"

    await close_engine()
