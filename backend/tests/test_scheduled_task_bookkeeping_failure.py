"""Regression tests for scheduler bookkeeping-failure recovery (issue #4452).

When ``_launch_run`` succeeds but a subsequent ``update_status`` or
``update_after_launch`` write fails (e.g. transient database error), the
exception handler must not release the active slot. The launched run_id is
already live in the external scheduler, so the task must remain ineligible
for another launch until that run reaches a terminal state.

These tests verify:
1. After a bookkeeping failure the slot stays occupied (cron)
2. When launch itself fails the slot is released (existing behaviour)
3. Recovery-branch task_status matches the success path for once tasks
4. Recovery-branch task_status matches the success path for cron tasks
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.scheduler.service import ScheduledTaskService


class _FailingUpdateRunRepo:
    """A run repository whose first ``update_status`` raises.

    This simulates a transient database failure after ``_launch_run``
    succeeds, at the point where the success path writes ``status="running"``
    to the run row.  Subsequent calls succeed so the recovery branch can
    complete its own ``update_status`` + ``update_after_launch`` writes.
    """

    def __init__(self, *, active: bool = False, fail_first_update: bool = True) -> None:
        self._update_count = 0
        self._active = active
        self._fail_first_update = fail_first_update
        self.created: dict | None = None
        self.updated: list = []

    async def create(self, **kwargs):
        self.created = kwargs
        return {"id": kwargs["run_record_id"]}

    async def update_status(self, run_record_id, **kwargs):
        self._update_count += 1
        if self._fail_first_update and self._update_count == 1:
            raise RuntimeError("Simulated transient database failure")
        self.updated.append((run_record_id, kwargs))

    async def has_active_runs(self, task_id: str) -> bool:
        return self._active

    async def count_active_runs(self) -> int:
        return 1 if self._active else 0

    async def mark_stale_active_runs(self, *, error: str) -> int:
        return 0


class _TaskRepo:
    """Minimal task repository for bookkeeping-failure tests."""

    def __init__(self, tasks: list[dict]) -> None:
        self._tasks = {t["id"]: dict(t) for t in tasks}
        self.updated: list = []

    async def claim_due_tasks(self, **_kwargs):
        return []

    async def get(self, task_id: str, *, user_id: str):
        t = self._tasks.get(task_id)
        return dict(t) if t is not None else None

    async def update(self, task_id: str, *, user_id: str, updates):
        t = self._tasks.get(task_id)
        if t is None:
            return None
        t.update(updates)
        return dict(t)

    async def update_after_launch(self, task_id: str, **kwargs):
        self.updated.append((task_id, kwargs))
        t = self._tasks.get(task_id)
        if t is not None:
            t["status"] = kwargs.get("status", t.get("status"))

    async def cancel_stuck_once_tasks(self, *, error: str) -> int:
        return 0


def _make_task(*, task_id: str, schedule_type: str = "cron", status: str = "enabled", user_id: str = "user-1", **overrides) -> dict:
    base = {
        "id": task_id,
        "user_id": user_id,
        "thread_id": None,
        "context_mode": "fresh_thread_per_run",
        "assistant_id": "lead_agent",
        "title": task_id,
        "prompt": "do the thing",
        "schedule_type": schedule_type,
        "schedule_spec": {"cron": "*/5 * * * *"} if schedule_type == "cron" else {"run_at": "2026-01-01T00:00:00+00:00"},
        "timezone": "UTC",
        "next_run_at": None,
        "status": status,
        "overlap_policy": "skip",
    }
    base.update(overrides)
    return base


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


@pytest.mark.asyncio
async def test_launch_succeeds_but_bookkeeping_fails_keeps_slot_occupied():
    """Cron task: when launch succeeds but update_status fails, the slot
    must remain occupied so a second dispatch cannot launch another run."""
    task = _make_task(task_id="task-bf-cron")
    task_repo = _TaskRepo([task])
    run_repo = _FailingUpdateRunRepo(active=False)
    launched: list = []
    service = _make_service(task_repo, run_repo, launched)

    # First dispatch: launch succeeds, update_status raises.
    result = await service.dispatch_task(dict(task), now=datetime.now(UTC), trigger="scheduled")

    assert len(launched) == 1
    assert launched[0]["metadata"]["scheduled_task_id"] == "task-bf-cron"
    assert result["outcome"] == "launched_bookkeeping_failed"
    assert result["run_id"] is not None
    assert result["run_id"] == "run-1"

    # The recovery branch re-wrote the run row as "running" with the live run_id.
    last_update = run_repo.updated[-1][1]
    assert last_update["status"] == "running"
    assert last_update["run_id"] == "run-1"

    # After recovery the run row is "running", so has_active_runs returns True.
    run_repo._active = True
    assert await run_repo.has_active_runs("task-bf-cron") is True

    # Second dispatch must be rejected because the slot is still occupied.
    launched.clear()
    result2 = await service.dispatch_task(dict(task), now=datetime.now(UTC), trigger="scheduled")

    assert result2["outcome"] in ("conflict", "skipped"), f"Second dispatch should be rejected, got {result2['outcome']}"
    assert len(launched) == 0


@pytest.mark.asyncio
async def test_launch_fails_before_launch_does_release_slot():
    """When ``_launch_run`` itself raises, the slot IS released (existing
    behaviour must be preserved)."""
    task = _make_task(task_id="task-launch-fail")
    task_repo = _TaskRepo([task])
    run_repo = _FailingUpdateRunRepo(active=False, fail_first_update=False)
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

    result = await service.dispatch_task(dict(task), now=datetime.now(UTC), trigger="scheduled")

    assert len(launched) == 1
    assert result["outcome"] == "failed"
    assert result["run_id"] is None

    # Slot is released — has_active_runs returns False.
    assert await run_repo.has_active_runs("task-launch-fail") is False

    # A second dispatch can proceed (launch will also fail, but it tries).
    launched.clear()
    await service.dispatch_task(dict(task), now=datetime.now(UTC), trigger="scheduled")
    assert len(launched) == 1


@pytest.mark.asyncio
async def test_once_task_bookkeeping_failure_keeps_status_running():
    """Once task: recovery branch must set parent status to "running" so
    ``cancel_stuck_once_tasks`` can reconcile the task on restart.

    The success path deliberately parks once tasks in "running" until
    ``handle_run_completion`` observes the real terminal outcome.  The
    recovery branch must match this — otherwise the task is orphaned: the
    run row is released by ``mark_stale_active_runs`` on restart, but the
    parent task (left as "enabled") is invisible to the sweeper.
    """
    run_at = datetime.now(UTC).replace(microsecond=0)
    task = _make_task(
        task_id="task-bf-once",
        schedule_type="once",
        schedule_spec={"run_at": run_at.isoformat()},
        next_run_at=run_at,
    )
    task_repo = _TaskRepo([task])
    run_repo = _FailingUpdateRunRepo(active=False)
    launched: list = []
    service = _make_service(task_repo, run_repo, launched)

    result = await service.dispatch_task(dict(task), now=run_at, trigger="scheduled")

    assert len(launched) == 1
    assert result["outcome"] == "launched_bookkeeping_failed"
    assert result["run_id"] is not None

    # The recovery branch re-wrote the run row as "running" with the live run_id.
    last_update = run_repo.updated[-1][1]
    assert last_update["status"] == "running"
    assert last_update["run_id"] == "run-1"

    # Slot is still occupied.
    run_repo._active = True
    assert await run_repo.has_active_runs("task-bf-once") is True

    # Parent task status must be "running", not "enabled".
    updated = await task_repo.get("task-bf-once", user_id="user-1")
    assert updated is not None
    assert updated["status"] == "running", f"Once task should have status 'running' after recovery, got '{updated['status']}'.  Without this, cancel_stuck_once_tasks cannot reconcile the task on restart."


@pytest.mark.asyncio
async def test_cron_task_bookkeeping_failure_keeps_status_enabled():
    """Cron task: recovery branch must keep parent status "enabled" so
    ``claim_due_tasks`` can reclaim it on the next poll cycle.

    The success path writes "enabled" for cron tasks.  If the recovery
    branch hardcodes "running" instead, the cron task is permanently stuck:
    ``handle_run_completion`` only updates status for once tasks,
    ``claim_due_tasks`` requires a non-NULL ``lease_expires_at`` (cleared
    by ``update_after_launch``), and ``cancel_stuck_once_tasks`` only
    sweeps once rows.  The task silently stops firing forever.
    """
    now = datetime.now(UTC)
    task = _make_task(task_id="task-bf-cron-status", schedule_type="cron", next_run_at=now)
    task_repo = _TaskRepo([task])
    run_repo = _FailingUpdateRunRepo(active=False)
    launched: list = []
    service = _make_service(task_repo, run_repo, launched)

    result = await service.dispatch_task(dict(task), now=now, trigger="scheduled")

    assert len(launched) == 1
    assert result["outcome"] == "launched_bookkeeping_failed"
    assert result["run_id"] is not None

    # Parent task status must be "enabled" so claim_due_tasks can reclaim it.
    updated = await task_repo.get("task-bf-cron-status", user_id="user-1")
    assert updated is not None
    assert updated["status"] == "enabled", f"Cron task should have status 'enabled' after recovery, got '{updated['status']}'.  Without this, the task is permanently stuck in 'running' and silently stops firing."
