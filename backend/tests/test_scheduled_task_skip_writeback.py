"""Regression test for the write-back on an overlap-skipped dispatch.

``ScheduledTaskService._finalize_skip`` preserves a task's launch bookkeeping
by reading the current values off the task dict and passing them straight back
into ``update_after_launch``. But repository dicts carry ISO *strings* for
timestamps (``ScheduledTaskRepository._row_to_dict`` runs every datetime column
through ``coerce_iso``), while ``scheduled_tasks.last_run_at`` is a
``DateTime`` column -- so the round trip fed a string into a datetime bind
parameter and the write raised.

It only reproduces once the task has actually launched at least once: before
that ``last_run_at`` is NULL, and NULL is accepted by the column. That is why
the existing dispatch tests, which all seed a fresh task, never hit it.

Uses the REAL repositories against a file-backed ``sqlite+aiosqlite`` DB,
because an in-memory fake stores whatever object it is handed and cannot
reject the type.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.scheduler.service import ScheduledTaskService
from deerflow.config.database_config import DatabaseConfig
from deerflow.persistence.engine import close_engine, get_session_factory, init_engine_from_config
from deerflow.persistence.scheduled_task_runs import ScheduledTaskRunRepository
from deerflow.persistence.scheduled_tasks import ScheduledTaskRepository

pytestmark = pytest.mark.asyncio


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


async def _seed_task(task_repo: ScheduledTaskRepository, task_id: str, *, schedule_type: str = "cron") -> dict:
    spec = {"cron": "*/5 * * * *"} if schedule_type == "cron" else {"run_at": "2099-01-01T00:00:00+00:00"}
    await task_repo.create(
        task_id=task_id,
        user_id="user-1",
        thread_id=None,
        context_mode="fresh_thread_per_run",
        assistant_id="lead_agent",
        title=task_id,
        prompt="do the thing",
        schedule_type=schedule_type,
        schedule_spec=spec,
        timezone="UTC",
        next_run_at=None,
    )
    task = await task_repo.get(task_id, user_id="user-1")
    assert task is not None
    return task


async def test_scheduled_skip_preserves_bookkeeping_of_a_previously_launched_task(tmp_path):
    """A cron task that already ran once, then overlaps, must record the skip
    without disturbing (or failing to write) its launch bookkeeping."""
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    try:
        sf = get_session_factory()
        assert sf is not None
        task_repo = ScheduledTaskRepository(sf)
        run_repo = ScheduledTaskRunRepository(sf)
        launched: list = []
        service = _make_service(task_repo, run_repo, launched)
        task = await _seed_task(task_repo, "task-skip-cron")

        first_at = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)
        first = await service.dispatch_task(dict(task), now=first_at, trigger="scheduled")
        assert first["outcome"] == "launched"

        after_launch = await task_repo.get("task-skip-cron", user_id="user-1")
        assert after_launch is not None
        # The precondition the old dispatch tests never established.
        assert after_launch["last_run_at"] is not None

        # The fake launcher never terminates the run, so its row is still
        # active and this second dispatch overlaps. `after_launch` is passed
        # verbatim, exactly as the poller passes what claim_due_tasks returned.
        second = await service.dispatch_task(after_launch, now=first_at + timedelta(minutes=5), trigger="scheduled")

        assert second["outcome"] == "skipped"
        assert len(launched) == 1, "the overlapping dispatch must not launch"

        after_skip = await task_repo.get("task-skip-cron", user_id="user-1")
        assert after_skip is not None
        # A skip is not an execution: the launch bookkeeping is carried over
        # untouched and the counter does not move.
        assert after_skip["last_run_at"] == after_launch["last_run_at"]
        assert after_skip["last_run_id"] == after_launch["last_run_id"]
        assert after_skip["last_thread_id"] == after_launch["last_thread_id"]
        assert after_skip["run_count"] == after_launch["run_count"] == 1
        # A cron task stays claimable; only `once` burns its occurrence.
        assert after_skip["status"] == "enabled"
        assert after_skip["last_error"] is None
        # The skip itself is recorded as a terminal tombstone.
        rows = await run_repo.list_by_task("task-skip-cron", limit=10)
        assert sorted(row["status"] for row in rows) == ["running", "skipped"]
    finally:
        await close_engine()


async def test_scheduled_skip_of_a_previously_launched_once_task_records_the_lost_occurrence(tmp_path):
    """Same write-back path, `once` branch: the single occurrence is lost, so
    the task ends `failed` and carries the skip reason."""
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    try:
        sf = get_session_factory()
        assert sf is not None
        task_repo = ScheduledTaskRepository(sf)
        run_repo = ScheduledTaskRunRepository(sf)
        launched: list = []
        service = _make_service(task_repo, run_repo, launched)
        task = await _seed_task(task_repo, "task-skip-once", schedule_type="once")

        first_at = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)
        first = await service.dispatch_task(dict(task), now=first_at, trigger="scheduled")
        assert first["outcome"] == "launched"

        after_launch = await task_repo.get("task-skip-once", user_id="user-1")
        assert after_launch is not None
        assert after_launch["last_run_at"] is not None

        second = await service.dispatch_task(after_launch, now=first_at + timedelta(minutes=5), trigger="scheduled")

        assert second["outcome"] == "skipped"
        after_skip = await task_repo.get("task-skip-once", user_id="user-1")
        assert after_skip is not None
        assert after_skip["last_run_at"] == after_launch["last_run_at"]
        assert after_skip["status"] == "failed"
        assert after_skip["last_error"] == "skipped: a previous run of this task is still active"
    finally:
        await close_engine()
