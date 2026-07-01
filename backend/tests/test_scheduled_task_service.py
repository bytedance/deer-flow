from datetime import UTC, datetime, timedelta

import pytest

from app.scheduler.service import ScheduledTaskService


class DummyTaskRepo:
    def __init__(self, rows):
        self.rows = rows
        self.claimed = False
        self.updated = None

    async def claim_due_tasks(self, **_kwargs):
        if self.claimed:
            return []
        self.claimed = True
        return self.rows

    async def update_after_launch(self, *args, **kwargs):
        self.updated = (args, kwargs)


class DummyRunRepo:
    def __init__(self):
        self.created = None
        self.updated = None

    async def create(self, **kwargs):
        self.created = kwargs
        return {"id": kwargs["run_record_id"]}

    async def update_status(self, run_record_id, **kwargs):
        self.updated = (run_record_id, kwargs)


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
    assert run_repo.updated[1]["status"] == "running"


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
