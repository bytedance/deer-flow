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
    """Runs stuck in queued/running after a process crash are swept to interrupted."""
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
    assert by_id["task-run-queued"]["status"] == "interrupted"
    assert by_id["task-run-running"]["status"] == "interrupted"
    assert by_id["task-run-success"]["status"] == "success"

    await close_engine()


@pytest.mark.asyncio
async def test_update_status_protect_terminal_keeps_completion_result(tmp_path):
    """The launch-path "running" write must not clobber a terminal status
    already committed by the completion hook (launch/completion race)."""
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    sf = get_session_factory()
    assert sf is not None

    repo = ScheduledTaskRunRepository(sf)
    await repo.create(
        run_record_id="task-run-race",
        task_id="task-1",
        thread_id="thread-1",
        scheduled_for=datetime(2026, 7, 2, 1, 0, tzinfo=UTC),
        trigger="scheduled",
        status="queued",
    )
    # Completion hook wins the race and commits the terminal state first.
    await repo.update_status("task-run-race", status="failed", run_id="run-1", error="boom", finished_at=datetime(2026, 7, 2, 1, 1, tzinfo=UTC))
    # Late launch-path write: keeps terminal status/error, backfills started_at.
    await repo.update_status("task-run-race", status="running", run_id="run-1", started_at=datetime(2026, 7, 2, 1, 0, tzinfo=UTC), protect_terminal=True)

    entry = (await repo.list_by_task("task-1"))[0]
    assert entry["status"] == "failed"
    assert entry["error"] == "boom"
    assert entry["started_at"] is not None

    await close_engine()


@pytest.mark.asyncio
async def test_has_active_runs_sees_only_queued_and_running(tmp_path):
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    sf = get_session_factory()
    assert sf is not None

    repo = ScheduledTaskRunRepository(sf)
    assert await repo.has_active_runs("task-1") is False
    await repo.create(
        run_record_id="task-run-active",
        task_id="task-1",
        thread_id="thread-1",
        scheduled_for=datetime(2026, 7, 2, 1, 0, tzinfo=UTC),
        trigger="scheduled",
        status="running",
    )
    assert await repo.has_active_runs("task-1") is True
    await repo.update_status("task-run-active", status="success", run_id="run-1")
    assert await repo.has_active_runs("task-1") is False

    await close_engine()


@pytest.mark.asyncio
async def test_cancel_stuck_once_tasks_reconciles_orphaned_running(tmp_path):
    """Launched (lease cleared) once tasks stuck in running are cancelled at
    startup; leased ones are left for expired-lease reclaim."""
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    sf = get_session_factory()
    assert sf is not None

    repo = ScheduledTaskRepository(sf)
    for task_id, schedule_type, status in (
        ("task-once-stuck", "once", "running"),
        ("task-once-done", "once", "completed"),
        ("task-cron-running", "cron", "running"),
    ):
        await repo.create(
            task_id=task_id,
            user_id="user-1",
            thread_id=None,
            context_mode="fresh_thread_per_run",
            assistant_id="lead_agent",
            title=task_id,
            prompt="p",
            schedule_type=schedule_type,
            schedule_spec={"run_at": "2026-07-02T01:00:00+00:00"} if schedule_type == "once" else {"cron": "0 9 * * *"},
            timezone="UTC",
            next_run_at=None,
        )
        await repo.update(task_id, user_id="user-1", updates={"status": status})
    # A claimed-but-not-launched once task still holds its lease: keep it.
    await repo.create(
        task_id="task-once-leased",
        user_id="user-1",
        thread_id=None,
        context_mode="fresh_thread_per_run",
        assistant_id="lead_agent",
        title="task-once-leased",
        prompt="p",
        schedule_type="once",
        schedule_spec={"run_at": "2026-07-02T01:00:00+00:00"},
        timezone="UTC",
        next_run_at=datetime(2026, 7, 2, 1, 0, tzinfo=UTC),
    )
    await repo.update("task-once-leased", user_id="user-1", updates={"status": "running", "lease_expires_at": datetime(2026, 7, 2, 1, 2, tzinfo=UTC)})

    cancelled = await repo.cancel_stuck_once_tasks(error="interrupted: gateway restarted")
    assert cancelled == 1

    by_id = {t["id"]: t for t in await repo.list_by_user("user-1")}
    assert by_id["task-once-stuck"]["status"] == "cancelled"
    assert by_id["task-once-stuck"]["last_error"] == "interrupted: gateway restarted"
    assert by_id["task-once-done"]["status"] == "completed"
    assert by_id["task-cron-running"]["status"] == "running"
    assert by_id["task-once-leased"]["status"] == "running"

    await close_engine()
