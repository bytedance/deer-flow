"""Regression test for issue #4452: Scheduler can launch a second run after bookkeeping failure.

When `_launch_run` succeeds but the subsequent `update_status(..., status="running")`
fails (e.g., transient database failure), the exception handler must NOT release
the active slot. The launched run_id is already live in the external scheduler,
so the task must remain ineligible for another launch until that run terminates.

This test verifies:
1. When launch succeeds but bookkeeping fails, the slot remains occupied
2. The launched run_id is preserved (not set to None)
3. A second dispatch is rejected because has_active_runs returns True
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from app.scheduler.service import ScheduledTaskService
from deerflow.config.database_config import DatabaseConfig
from deerflow.persistence.engine import close_engine, get_session_factory, init_engine_from_config
from deerflow.persistence.scheduled_task_runs import ScheduledTaskRunRepository
from deerflow.persistence.scheduled_tasks import ScheduledTaskRepository

pytestmark = pytest.mark.asyncio


class _FailingUpdateStatusRunRepo(ScheduledTaskRunRepository):
    """Repository that fails the first update_status call but succeeds on retry.

    This simulates a transient database failure after _launch_run succeeds.
    """

    def __init__(self, session_factory, fail_first_update: bool = True) -> None:
        super().__init__(session_factory)
        self._fail_first_update = fail_first_update
        self._update_count = 0
        self._launched = []

    async def update_status(self, run_record_id, **kwargs):
        self._update_count += 1
        # Fail the FIRST update_status call (the launch-path update to "running")
        # but succeed on the second call (the bookkeeping-failure recovery path)
        if self._fail_first_update and self._update_count == 1:
            # Simulate transient DB failure
            raise RuntimeError("Simulated transient database failure")
        await super().update_status(run_record_id, **kwargs)


def _make_service(task_repo, run_repo, launched: list) -> ScheduledTaskService:
    async def fake_launch(**kwargs):
        # Yield to allow interleaving if needed
        await asyncio.sleep(0)
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


async def _seed_task(task_repo: ScheduledTaskRepository, task_id: str) -> dict:
    await task_repo.create(
        task_id=task_id,
        user_id="user-1",
        thread_id=None,
        context_mode="fresh_thread_per_run",
        assistant_id="lead_agent",
        title=task_id,
        prompt="do the thing",
        schedule_type="cron",
        schedule_spec={"cron": "*/5 * * * *"},
        timezone="UTC",
        next_run_at=None,
    )
    task = await task_repo.get(task_id, user_id="user-1")
    assert task is not None
    return task


async def _seed_once_task(task_repo: ScheduledTaskRepository, task_id: str) -> dict:
    """Seed a once task for testing bookkeeping-failure recovery."""
    run_at = datetime.now(UTC).replace(microsecond=0)
    await task_repo.create(
        task_id=task_id,
        user_id="user-1",
        thread_id=None,
        context_mode="fresh_thread_per_run",
        assistant_id="lead_agent",
        title=task_id,
        prompt="do the thing",
        schedule_type="once",
        schedule_spec={"run_at": run_at.isoformat()},
        timezone="UTC",
        next_run_at=run_at,
    )
    task = await task_repo.get(task_id, user_id="user-1")
    assert task is not None
    return task


async def test_launch_succeeds_but_bookkeeping_fails_keeps_slot_occupied(tmp_path):
    """Verify that when _launch_run succeeds but update_status fails, the slot is NOT released."""
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    try:
        sf = get_session_factory()
        assert sf is not None
        task_repo = ScheduledTaskRepository(sf)
        run_repo = _FailingUpdateStatusRunRepo(sf, fail_first_update=True)
        launched: list = []
        service = _make_service(task_repo, run_repo, launched)
        task = await _seed_task(task_repo, "task-bookkeeping-fail")
        now = datetime.now(UTC)

        # First dispatch: launch succeeds, but update_status fails
        result = await service.dispatch_task(dict(task), now=now, trigger="scheduled")

        # The launch was called (external run is live)
        assert len(launched) == 1, "Launch should have been called"
        assert launched[0]["metadata"]["scheduled_task_id"] == "task-bookkeeping-fail"

        # Result shows failed but with run_id preserved
        assert result["outcome"] == "failed", f"Expected 'failed', got {result['outcome']}"
        assert result["run_id"] is not None, "run_id should be preserved (not None)"
        assert result["run_id"] == "run-1", f"Expected 'run-1', got {result['run_id']}"

        # The slot is still occupied - check via has_active_runs
        # After the fix, the task should still have an active run
        # (status is 'running' in the DB, not 'failed')
        assert await run_repo.has_active_runs("task-bookkeeping-fail") is True, "Slot should still be occupied after bookkeeping failure"

        # Second dispatch should be rejected because slot is occupied
        launched.clear()
        result2 = await service.dispatch_task(dict(task), now=now, trigger="scheduled")

        # The second dispatch should not launch (conflict or skipped)
        assert result2["outcome"] in ("conflict", "skipped"), f"Second dispatch should be rejected, got {result2['outcome']}"
        assert len(launched) == 0, "Second launch should NOT have been called"

        # Verify DB state: there should be at least one task run with 'running' or 'skipped' status
        # The key invariant is: no second launch occurred
        runs = await run_repo.list_by_task("task-bookkeeping-fail", limit=10)
        assert len(runs) >= 1, "Should have at least one task run"

        # The first (original) run should have status 'running' (bookkeeping failure recovery kept it active)
        # or if it was skipped by the second dispatch, that's also acceptable
        # What matters is: the second dispatch did NOT launch a new run
        # (it was rejected because slot was still occupied)
    finally:
        await close_engine()


async def test_launch_fails_before_launch_does_release_slot(tmp_path):
    """Verify that when _launch_run itself fails, the slot IS released (original behavior)."""
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    try:
        sf = get_session_factory()
        assert sf is not None
        task_repo = ScheduledTaskRepository(sf)
        run_repo = ScheduledTaskRunRepository(sf)
        launched: list = []

        async def failing_launch(**kwargs):
            launched.append(kwargs)
            raise RuntimeError("Launch failed")

        service = ScheduledTaskService(
            task_repo=task_repo,
            task_run_repo=run_repo,
            launch_run=failing_launch,
            poll_interval_seconds=5,
            lease_seconds=120,
            max_concurrent_runs=10,
        )
        task = await _seed_task(task_repo, "task-launch-fail")
        now = datetime.now(UTC)

        result = await service.dispatch_task(dict(task), now=now, trigger="scheduled")

        # Launch was attempted
        assert len(launched) == 1

        # Result shows failed with run_id=None (no run was launched)
        assert result["outcome"] == "failed"
        assert result["run_id"] is None

        # The slot should be released - has_active_runs should return False
        assert await run_repo.has_active_runs("task-launch-fail") is False, "Slot should be released when launch itself fails"

        # A second dispatch should be able to proceed (though launch will also fail)
        launched.clear()
        await service.dispatch_task(dict(task), now=now, trigger="scheduled")

        # Second dispatch attempted launch (will also fail, but it tried)
        assert len(launched) == 1, "Second dispatch should also attempt launch"
    finally:
        await close_engine()


async def test_once_task_bookkeeping_failure_keeps_status_running(tmp_path):
    """Verify once task stays 'running' (not 'enabled') after bookkeeping-failure recovery.

    For 'once' tasks the success path deliberately parks the parent task in
    'running' so cancel_stuck_once_tasks can reconcile it on restart.
    The recovery branch must match this, otherwise the task is orphaned
    on restart-after-crash: mark_stale_active_runs releases the run row
    but cancel_stuck_once_tasks never touches the parent (it only sweeps
    tasks with status == 'running').
    """
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    try:
        sf = get_session_factory()
        assert sf is not None
        task_repo = ScheduledTaskRepository(sf)
        run_repo = _FailingUpdateStatusRunRepo(sf, fail_first_update=True)
        launched: list = []
        service = _make_service(task_repo, run_repo, launched)
        task = await _seed_once_task(task_repo, "task-once-bookkeeping-fail")
        now = datetime.now(UTC)

        # Dispatch: launch succeeds, but first update_status fails
        result = await service.dispatch_task(dict(task), now=now, trigger="scheduled")

        # Launch was called
        assert len(launched) == 1
        assert result["outcome"] == "failed"
        assert result["run_id"] is not None, "run_id should be preserved"

        # Slot is still occupied (run row is 'running')
        assert await run_repo.has_active_runs("task-once-bookkeeping-fail") is True

        # The parent task's status must be 'running' (not 'enabled') so
        # cancel_stuck_once_tasks can reconcile it on restart.
        updated_task = await task_repo.get("task-once-bookkeeping-fail", user_id="user-1")
        assert updated_task is not None
        assert updated_task["status"] == "running", (
            f"Once task should have status 'running' after recovery, got '{updated_task['status']}'. "
            "Without this, cancel_stuck_once_tasks cannot reconcile the task on restart."
        )
    finally:
        await close_engine()
