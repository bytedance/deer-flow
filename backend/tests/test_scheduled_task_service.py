from datetime import UTC, datetime, timedelta

import pytest

from app.scheduler.service import ScheduledTaskService
from deerflow.runtime import ConflictError, RunStatus
from deerflow.runtime.runs.manager import RunRecord
from deerflow.runtime.runs.schemas import DisconnectMode


class DummyTaskRepo:
    def __init__(self, rows):
        self.rows = rows
        self.claimed = False
        self.updated = None
        self.cancelled_stuck_once = None

    async def cancel_stuck_once_tasks(self, *, error):
        self.cancelled_stuck_once = error
        return 0

    async def claim_due_tasks(self, **_kwargs):
        if self.claimed:
            return []
        self.claimed = True
        return self.rows

    async def update_after_launch(self, *args, **kwargs):
        self.updated = (args, kwargs)

    async def get(self, task_id: str, *, user_id: str):
        row = next((item for item in self.rows if item["id"] == task_id and item["user_id"] == user_id), None)
        return dict(row) if row is not None else None

    async def update(self, task_id: str, *, user_id: str, updates):
        row = next((item for item in self.rows if item["id"] == task_id and item["user_id"] == user_id), None)
        if row is None:
            return None
        row.update(updates)
        return dict(row)


class DummyRunRepo:
    def __init__(self, *, active=False, active_count=0):
        self.created = None
        self.updated = []
        self.active = active
        self.active_count = active_count
        self.stale_marked = None

    async def count_active_runs(self):
        return self.active_count

    async def create(self, **kwargs):
        self.created = kwargs
        return {"id": kwargs["run_record_id"]}

    async def update_status(self, run_record_id, **kwargs):
        self.updated.append((run_record_id, kwargs))

    async def has_active_runs(self, task_id):
        return self.active

    async def mark_stale_active_runs(self, *, error):
        self.stale_marked = error
        return 0


@pytest.mark.asyncio
async def test_service_claims_and_dispatches_due_task():
    async def fake_launch(**kwargs):
        assert kwargs["owner_user_id"] == "user-1"
        assert kwargs["metadata"]["scheduled_task_id"] == "task-1"
        assert kwargs["metadata"]["scheduled_trigger"] == "scheduled"
        return {"run_id": "run-1", "thread_id": kwargs["thread_id"]}

    task_repo = DummyTaskRepo(
        [
            {
                "id": "task-1",
                "user_id": "user-1",
                "thread_id": "thread-1",
                "context_mode": "reuse_thread",
                "assistant_id": "lead_agent",
                "prompt": "Summarize thread",
                "schedule_type": "once",
                "schedule_spec": {"run_at": "2026-07-02T01:00:00+00:00"},
                "timezone": "UTC",
            }
        ]
    )
    run_repo = DummyRunRepo()
    service = ScheduledTaskService(
        task_repo=task_repo,
        task_run_repo=run_repo,
        launch_run=fake_launch,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_runs=3,
    )

    await service.run_once(now=datetime.now(UTC) + timedelta(days=1))

    assert run_repo.created["task_id"] == "task-1"
    assert run_repo.updated[0][1]["status"] == "running"
    assert run_repo.updated[0][1]["protect_terminal"] is True
    # `once` terminal status is owned by handle_run_completion, not the launch.
    assert task_repo.updated[1]["status"] == "running"


@pytest.mark.asyncio
async def test_manual_trigger_keeps_paused_cron_task_paused():
    async def fake_launch(**kwargs):
        return {"run_id": "run-2", "thread_id": kwargs["thread_id"]}

    task_repo = DummyTaskRepo(
        [
            {
                "id": "task-2",
                "user_id": "user-1",
                "thread_id": "thread-1",
                "context_mode": "reuse_thread",
                "assistant_id": "lead_agent",
                "prompt": "Summarize thread",
                "schedule_type": "cron",
                "schedule_spec": {"cron": "0 9 * * *"},
                "timezone": "UTC",
                "status": "paused",
            }
        ]
    )
    run_repo = DummyRunRepo()
    service = ScheduledTaskService(
        task_repo=task_repo,
        task_run_repo=run_repo,
        launch_run=fake_launch,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_runs=3,
    )

    await service.dispatch_task(
        task_repo.rows[0],
        now=datetime.now(UTC),
        trigger="manual",
    )

    assert task_repo.updated[1]["status"] == "paused"


@pytest.mark.asyncio
async def test_fresh_thread_per_run_creates_new_execution_thread():
    async def fake_launch(**kwargs):
        assert kwargs["thread_id"] != "thread-template"
        return {"run_id": "run-3", "thread_id": kwargs["thread_id"]}

    task_repo = DummyTaskRepo(
        [
            {
                "id": "task-3",
                "user_id": "user-1",
                "thread_id": "thread-template",
                "context_mode": "fresh_thread_per_run",
                "assistant_id": "lead_agent",
                "prompt": "Summarize thread",
                "schedule_type": "cron",
                "schedule_spec": {"cron": "0 9 * * *"},
                "timezone": "UTC",
                "status": "enabled",
            }
        ]
    )
    run_repo = DummyRunRepo()
    service = ScheduledTaskService(
        task_repo=task_repo,
        task_run_repo=run_repo,
        launch_run=fake_launch,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_runs=3,
    )

    await service.dispatch_task(
        task_repo.rows[0],
        now=datetime.now(UTC),
        trigger="scheduled",
    )

    assert run_repo.created["thread_id"] != "thread-template"
    assert task_repo.updated[1]["last_thread_id"] == run_repo.created["thread_id"]


@pytest.mark.asyncio
async def test_scheduled_overlap_conflict_is_recorded_as_skip():
    async def fake_launch(**_kwargs):
        raise ConflictError("Thread thread-1 already has an active run")

    task_repo = DummyTaskRepo(
        [
            {
                "id": "task-4",
                "user_id": "user-1",
                "thread_id": "thread-1",
                "context_mode": "reuse_thread",
                "assistant_id": "lead_agent",
                "prompt": "Summarize thread",
                "schedule_type": "cron",
                "schedule_spec": {"cron": "0 9 * * *"},
                "timezone": "UTC",
                "status": "running",
                "overlap_policy": "skip",
                "last_run_id": "run-old",
                "last_thread_id": "thread-1",
                "last_run_at": "2026-07-01T00:00:00+00:00",
            }
        ]
    )
    run_repo = DummyRunRepo()
    service = ScheduledTaskService(
        task_repo=task_repo,
        task_run_repo=run_repo,
        launch_run=fake_launch,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_runs=3,
    )

    result = await service.dispatch_task(
        task_repo.rows[0],
        now=datetime.now(UTC),
        trigger="scheduled",
    )

    assert result["outcome"] == "skipped"
    assert run_repo.updated[-1][1]["status"] == "skipped"
    assert task_repo.updated[1]["status"] == "enabled"


@pytest.mark.asyncio
async def test_manual_overlap_conflict_returns_conflict():
    async def fake_launch(**_kwargs):
        raise ConflictError("Thread thread-1 already has an active run")

    task_repo = DummyTaskRepo(
        [
            {
                "id": "task-5",
                "user_id": "user-1",
                "thread_id": "thread-1",
                "context_mode": "reuse_thread",
                "assistant_id": "lead_agent",
                "prompt": "Summarize thread",
                "schedule_type": "cron",
                "schedule_spec": {"cron": "0 9 * * *"},
                "timezone": "UTC",
                "status": "enabled",
                "overlap_policy": "skip",
            }
        ]
    )
    run_repo = DummyRunRepo()
    service = ScheduledTaskService(
        task_repo=task_repo,
        task_run_repo=run_repo,
        launch_run=fake_launch,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_runs=3,
    )

    result = await service.dispatch_task(
        task_repo.rows[0],
        now=datetime.now(UTC),
        trigger="manual",
    )

    assert result["outcome"] == "conflict"
    assert run_repo.updated[-1][1]["status"] == "failed"


@pytest.mark.asyncio
async def test_handle_run_completion_persists_success():
    task_repo = DummyTaskRepo(
        [
            {
                "id": "task-6",
                "user_id": "user-1",
                "thread_id": None,
                "context_mode": "fresh_thread_per_run",
                "assistant_id": "lead_agent",
                "prompt": "Summarize thread",
                "schedule_type": "cron",
                "schedule_spec": {"cron": "0 9 * * *"},
                "timezone": "UTC",
                "status": "enabled",
            }
        ]
    )
    run_repo = DummyRunRepo()
    service = ScheduledTaskService(
        task_repo=task_repo,
        task_run_repo=run_repo,
        launch_run=lambda **_kwargs: None,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_runs=3,
    )

    record = RunRecord(
        run_id="run-6",
        thread_id="thread-6",
        assistant_id="lead_agent",
        status=RunStatus.success,
        on_disconnect=DisconnectMode.continue_,
        metadata={
            "scheduled_task_id": "task-6",
            "scheduled_task_run_id": "task-run-6",
        },
        user_id="user-1",
    )

    await service.handle_run_completion(record)

    assert run_repo.updated[-1][0] == "task-run-6"
    assert run_repo.updated[-1][1]["status"] == "success"
    assert task_repo.rows[0]["last_error"] is None


def _make_service(task_repo, run_repo):
    return ScheduledTaskService(
        task_repo=task_repo,
        task_run_repo=run_repo,
        launch_run=lambda **_kwargs: None,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_runs=3,
    )


def _once_task_row(task_id="task-once", status="running"):
    return {
        "id": task_id,
        "user_id": "user-1",
        "thread_id": None,
        "context_mode": "fresh_thread_per_run",
        "assistant_id": "lead_agent",
        "prompt": "Summarize thread",
        "schedule_type": "once",
        "schedule_spec": {"run_at": "2026-07-02T01:00:00+00:00"},
        "timezone": "UTC",
        "status": status,
    }


def _completion_record(status, *, task_id="task-once", error=None):
    return RunRecord(
        run_id="run-x",
        thread_id="thread-x",
        assistant_id="lead_agent",
        status=status,
        on_disconnect=DisconnectMode.continue_,
        metadata={
            "scheduled_task_id": task_id,
            "scheduled_task_run_id": "task-run-x",
        },
        user_id="user-1",
        error=error,
    )


@pytest.mark.asyncio
async def test_once_task_completes_only_via_completion_hook():
    task_repo = DummyTaskRepo([_once_task_row()])
    run_repo = DummyRunRepo()
    service = _make_service(task_repo, run_repo)

    await service.handle_run_completion(_completion_record(RunStatus.success))

    assert run_repo.updated[-1][1]["status"] == "success"
    assert task_repo.rows[0]["status"] == "completed"


@pytest.mark.asyncio
async def test_once_task_failed_run_marks_task_failed():
    task_repo = DummyTaskRepo([_once_task_row()])
    run_repo = DummyRunRepo()
    service = _make_service(task_repo, run_repo)

    await service.handle_run_completion(_completion_record(RunStatus.error, error="boom"))

    assert run_repo.updated[-1][1]["status"] == "failed"
    assert run_repo.updated[-1][1]["error"] == "boom"
    assert task_repo.rows[0]["status"] == "failed"
    assert task_repo.rows[0]["last_error"] == "boom"


@pytest.mark.asyncio
async def test_interrupted_run_is_distinct_and_cancels_once_task():
    task_repo = DummyTaskRepo([_once_task_row()])
    run_repo = DummyRunRepo()
    service = _make_service(task_repo, run_repo)

    await service.handle_run_completion(_completion_record(RunStatus.interrupted))

    run_update = run_repo.updated[-1][1]
    assert run_update["status"] == "interrupted"
    assert run_update["error"] == "run was interrupted before completion"
    assert task_repo.rows[0]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_interrupted_cron_run_keeps_task_enabled():
    row = _once_task_row(task_id="task-cron")
    row.update({"schedule_type": "cron", "schedule_spec": {"cron": "0 9 * * *"}, "status": "enabled"})
    task_repo = DummyTaskRepo([row])
    run_repo = DummyRunRepo()
    service = _make_service(task_repo, run_repo)

    await service.handle_run_completion(_completion_record(RunStatus.interrupted, task_id="task-cron"))

    assert run_repo.updated[-1][1]["status"] == "interrupted"
    assert task_repo.rows[0]["status"] == "enabled"


@pytest.mark.asyncio
async def test_skip_policy_applies_to_fresh_thread_runs():
    launched = []

    async def fake_launch(**kwargs):
        launched.append(kwargs)
        return {"run_id": "run-9", "thread_id": kwargs["thread_id"]}

    row = _once_task_row(task_id="task-9")
    row.update({"schedule_type": "cron", "schedule_spec": {"cron": "* * * * *"}, "status": "running", "overlap_policy": "skip"})
    task_repo = DummyTaskRepo([row])
    run_repo = DummyRunRepo(active=True)
    service = ScheduledTaskService(
        task_repo=task_repo,
        task_run_repo=run_repo,
        launch_run=fake_launch,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_runs=3,
    )

    result = await service.dispatch_task(row, now=datetime.now(UTC), trigger="scheduled")

    assert result["outcome"] == "skipped"
    assert launched == []
    assert run_repo.created["status"] == "queued"
    assert run_repo.updated[-1][1]["status"] == "skipped"
    assert task_repo.updated[1]["status"] == "enabled"
    assert task_repo.updated[1]["increment_run_count"] is False


@pytest.mark.asyncio
async def test_startup_sweep_reconciles_stale_runs_and_stuck_once_tasks():
    task_repo = DummyTaskRepo([])
    run_repo = DummyRunRepo()
    service = _make_service(task_repo, run_repo)

    await service.start()
    await service.stop()

    assert run_repo.stale_marked is not None
    assert task_repo.cancelled_stuck_once == run_repo.stale_marked


@pytest.mark.asyncio
async def test_manual_trigger_with_active_run_returns_conflict_without_launching():
    launched = []

    async def fake_launch(**kwargs):
        launched.append(kwargs)
        return {"run_id": "run-x", "thread_id": kwargs["thread_id"]}

    row = _once_task_row(task_id="task-manual-busy")
    row.update({"schedule_type": "cron", "schedule_spec": {"cron": "* * * * *"}, "status": "enabled", "overlap_policy": "skip"})
    task_repo = DummyTaskRepo([row])
    run_repo = DummyRunRepo(active=True)
    service = ScheduledTaskService(
        task_repo=task_repo,
        task_run_repo=run_repo,
        launch_run=fake_launch,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_runs=3,
    )

    result = await service.dispatch_task(row, now=datetime.now(UTC), trigger="manual")

    assert result["outcome"] == "conflict"
    assert launched == []
    # Nothing was scheduled to happen, so no run-history row is recorded.
    assert run_repo.created is None
    assert result["task_run_id"] is None


@pytest.mark.asyncio
async def test_run_once_claims_only_into_remaining_global_budget():
    claim_limits = []

    class BudgetTaskRepo(DummyTaskRepo):
        async def claim_due_tasks(self, **kwargs):
            claim_limits.append(kwargs["limit"])
            return []

    task_repo = BudgetTaskRepo([])
    run_repo = DummyRunRepo(active_count=2)
    service = _make_service(task_repo, run_repo)

    await service.run_once(now=datetime.now(UTC))
    assert claim_limits == [1]

    run_repo.active_count = 3
    await service.run_once(now=datetime.now(UTC))
    # Budget exhausted: no claim at all this cycle.
    assert claim_limits == [1]


@pytest.mark.asyncio
async def test_launch_bookkeeping_passes_protect_terminal():
    async def fake_launch(**kwargs):
        return {"run_id": "run-pt", "thread_id": kwargs["thread_id"]}

    task_repo = DummyTaskRepo([_once_task_row(task_id="task-pt", status="enabled")])
    run_repo = DummyRunRepo()
    service = ScheduledTaskService(
        task_repo=task_repo,
        task_run_repo=run_repo,
        launch_run=fake_launch,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_runs=3,
    )

    await service.dispatch_task(task_repo.rows[0], now=datetime.now(UTC), trigger="scheduled")

    assert task_repo.updated[1]["protect_terminal"] is True
