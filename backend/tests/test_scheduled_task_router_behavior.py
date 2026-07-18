from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.gateway.routers import scheduled_tasks


class _Repo:
    def __init__(self) -> None:
        self.created = []
        self.items = {}

    async def list_by_user(self, user_id: str):
        return [item for item in self.items.values() if item["user_id"] == user_id]

    async def list_by_user_and_thread(self, user_id: str, thread_id: str):
        return [item for item in self.items.values() if item["user_id"] == user_id and item["thread_id"] == thread_id]

    async def create(self, **kwargs):
        item = {
            "id": kwargs["task_id"],
            "user_id": kwargs["user_id"],
            "thread_id": kwargs["thread_id"],
            "context_mode": kwargs["context_mode"],
            "title": kwargs["title"],
            "prompt": kwargs["prompt"],
            "schedule_type": kwargs["schedule_type"],
            "schedule_spec": kwargs["schedule_spec"],
            "timezone": kwargs["timezone"],
            "status": "enabled",
            "next_run_at": kwargs["next_run_at"],
        }
        self.items[item["id"]] = item
        self.created.append(item)
        return item

    async def get(self, task_id: str, *, user_id: str):
        item = self.items.get(task_id)
        if item is None or item["user_id"] != user_id:
            return None
        return item

    async def update(self, task_id: str, *, user_id: str, updates):
        item = await self.get(task_id, user_id=user_id)
        if item is None:
            return None
        item.update(updates)
        return item

    async def delete(self, task_id: str, *, user_id: str):
        item = await self.get(task_id, user_id=user_id)
        if item is None:
            return False
        self.items.pop(task_id, None)
        return True

    async def list_by_task(self, task_id: str):
        return []


class _Service:
    def __init__(self) -> None:
        self.calls = []
        self.result = {"outcome": "launched"}

    async def dispatch_task(self, task, *, now, trigger):
        self.calls.append((task, now, trigger))
        return self.result


class _RunStore:
    def __init__(self, runs):
        self.runs = runs

    async def get(self, run_id: str, *, user_id: str):
        run = self.runs.get(run_id)
        if run is None or run.get("user_id") != user_id:
            return None
        return run


class _Config:
    def __init__(self, min_once_delay_seconds: int = 60) -> None:
        self.scheduler = SimpleNamespace(min_once_delay_seconds=min_once_delay_seconds)


@pytest.mark.asyncio
async def test_create_scheduled_task_uses_repo():
    repo = _Repo()
    request = SimpleNamespace()
    body = scheduled_tasks.ScheduledTaskCreateRequest(
        thread_id="thread-1",
        title="Daily summary",
        prompt="Summarize thread",
        schedule_type="once",
        schedule_spec={"run_at": "2027-01-01T01:00:00+00:00"},
        timezone="UTC",
    )

    user = SimpleNamespace(id="user-1")
    thread_store = SimpleNamespace(check_access=AsyncMock(return_value=True))
    config = _Config()

    old_repo = scheduled_tasks.get_scheduled_task_repo
    old_thread_store = scheduled_tasks.get_thread_store
    old_config = scheduled_tasks.get_config
    old_user = scheduled_tasks.get_optional_user_from_request
    try:
        scheduled_tasks.get_scheduled_task_repo = lambda _request: repo
        scheduled_tasks.get_thread_store = lambda _request: thread_store
        scheduled_tasks.get_config = lambda: config
        scheduled_tasks.get_optional_user_from_request = AsyncMock(return_value=user)

        created = await scheduled_tasks.create_scheduled_task.__wrapped__(
            request=request,
            body=body,
        )
    finally:
        scheduled_tasks.get_scheduled_task_repo = old_repo
        scheduled_tasks.get_thread_store = old_thread_store
        scheduled_tasks.get_config = old_config
        scheduled_tasks.get_optional_user_from_request = old_user

    assert created["title"] == "Daily summary"
    assert created["user_id"] == "user-1"
    assert created["next_run_at"] == datetime(2027, 1, 1, 1, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_create_fresh_thread_task_does_not_require_thread_id():
    repo = _Repo()
    request = SimpleNamespace()
    body = scheduled_tasks.ScheduledTaskCreateRequest(
        context_mode="fresh_thread_per_run",
        thread_id=None,
        title="Fresh task",
        prompt="Run in fresh thread",
        schedule_type="cron",
        schedule_spec={"cron": "0 9 * * *"},
        timezone="UTC",
    )

    user = SimpleNamespace(id="user-1")
    thread_store = SimpleNamespace(check_access=AsyncMock(return_value=True))
    config = _Config()

    old_repo = scheduled_tasks.get_scheduled_task_repo
    old_thread_store = scheduled_tasks.get_thread_store
    old_config = scheduled_tasks.get_config
    old_user = scheduled_tasks.get_optional_user_from_request
    try:
        scheduled_tasks.get_scheduled_task_repo = lambda _request: repo
        scheduled_tasks.get_thread_store = lambda _request: thread_store
        scheduled_tasks.get_config = lambda: config
        scheduled_tasks.get_optional_user_from_request = AsyncMock(return_value=user)

        created = await scheduled_tasks.create_scheduled_task.__wrapped__(
            request=request,
            body=body,
        )
    finally:
        scheduled_tasks.get_scheduled_task_repo = old_repo
        scheduled_tasks.get_thread_store = old_thread_store
        scheduled_tasks.get_config = old_config
        scheduled_tasks.get_optional_user_from_request = old_user

    assert created["context_mode"] == "fresh_thread_per_run"
    assert created["thread_id"] is None


@pytest.mark.asyncio
async def test_trigger_scheduled_task_dispatches_manual_run():
    repo = _Repo()
    service = _Service()
    task = await repo.create(
        task_id="task-1",
        user_id="user-1",
        thread_id="thread-1",
        context_mode="reuse_thread",
        assistant_id="lead_agent",
        title="Daily summary",
        prompt="Summarize thread",
        schedule_type="cron",
        schedule_spec={"cron": "0 9 * * *"},
        timezone="UTC",
        next_run_at=None,
    )
    request = SimpleNamespace()
    user = SimpleNamespace(id="user-1")

    old_repo = scheduled_tasks.get_scheduled_task_repo
    old_service = scheduled_tasks.get_scheduled_task_service
    old_user = scheduled_tasks.get_optional_user_from_request
    try:
        scheduled_tasks.get_scheduled_task_repo = lambda _request: repo
        scheduled_tasks.get_scheduled_task_service = lambda _request: service
        scheduled_tasks.get_optional_user_from_request = AsyncMock(return_value=user)

        result = await scheduled_tasks.trigger_scheduled_task.__wrapped__(
            task_id=task["id"],
            request=request,
        )
    finally:
        scheduled_tasks.get_scheduled_task_repo = old_repo
        scheduled_tasks.get_scheduled_task_service = old_service
        scheduled_tasks.get_optional_user_from_request = old_user

    assert result == {"id": "task-1", "triggered": True}
    assert len(service.calls) == 1
    assert service.calls[0][2] == "manual"


@pytest.mark.asyncio
async def test_trigger_scheduled_task_returns_conflict_when_dispatch_conflicts():
    repo = _Repo()
    service = _Service()
    service.result = {"outcome": "conflict", "error": "Thread thread-1 already has an active run"}
    task = await repo.create(
        task_id="task-1",
        user_id="user-1",
        thread_id="thread-1",
        context_mode="reuse_thread",
        assistant_id="lead_agent",
        title="Daily summary",
        prompt="Summarize thread",
        schedule_type="cron",
        schedule_spec={"cron": "0 9 * * *"},
        timezone="UTC",
        next_run_at=None,
    )
    request = SimpleNamespace()
    user = SimpleNamespace(id="user-1")

    old_repo = scheduled_tasks.get_scheduled_task_repo
    old_service = scheduled_tasks.get_scheduled_task_service
    old_user = scheduled_tasks.get_optional_user_from_request
    try:
        scheduled_tasks.get_scheduled_task_repo = lambda _request: repo
        scheduled_tasks.get_scheduled_task_service = lambda _request: service
        scheduled_tasks.get_optional_user_from_request = AsyncMock(return_value=user)

        with pytest.raises(Exception) as exc_info:
            await scheduled_tasks.trigger_scheduled_task.__wrapped__(
                task_id=task["id"],
                request=request,
            )
    finally:
        scheduled_tasks.get_scheduled_task_repo = old_repo
        scheduled_tasks.get_scheduled_task_service = old_service
        scheduled_tasks.get_optional_user_from_request = old_user

    assert "already has an active run" in str(exc_info.value)


@pytest.mark.asyncio
async def test_update_scheduled_task_writes_repo():
    repo = _Repo()
    task = await repo.create(
        task_id="task-1",
        user_id="user-1",
        thread_id="thread-1",
        context_mode="reuse_thread",
        assistant_id="lead_agent",
        title="Daily summary",
        prompt="Summarize thread",
        schedule_type="cron",
        schedule_spec={"cron": "0 9 * * *"},
        timezone="UTC",
        next_run_at=None,
    )
    request = SimpleNamespace()
    user = SimpleNamespace(id="user-1")
    config = _Config()
    thread_store = SimpleNamespace(check_access=AsyncMock(return_value=True))

    old_repo = scheduled_tasks.get_scheduled_task_repo
    old_thread_store = scheduled_tasks.get_thread_store
    old_config = scheduled_tasks.get_config
    old_user = scheduled_tasks.get_optional_user_from_request
    try:
        scheduled_tasks.get_scheduled_task_repo = lambda _request: repo
        scheduled_tasks.get_thread_store = lambda _request: thread_store
        scheduled_tasks.get_config = lambda: config
        scheduled_tasks.get_optional_user_from_request = AsyncMock(return_value=user)

        result = await scheduled_tasks.update_scheduled_task.__wrapped__(
            task_id=task["id"],
            request=request,
            body=scheduled_tasks.ScheduledTaskUpdateRequest(title="Updated title"),
        )
    finally:
        scheduled_tasks.get_scheduled_task_repo = old_repo
        scheduled_tasks.get_thread_store = old_thread_store
        scheduled_tasks.get_config = old_config
        scheduled_tasks.get_optional_user_from_request = old_user

    assert result["title"] == "Updated title"


@pytest.mark.asyncio
async def test_delete_scheduled_task_deletes_repo_row():
    repo = _Repo()
    task = await repo.create(
        task_id="task-1",
        user_id="user-1",
        thread_id="thread-1",
        context_mode="reuse_thread",
        assistant_id="lead_agent",
        title="Daily summary",
        prompt="Summarize thread",
        schedule_type="cron",
        schedule_spec={"cron": "0 9 * * *"},
        timezone="UTC",
        next_run_at=None,
    )
    request = SimpleNamespace()
    user = SimpleNamespace(id="user-1")

    old_repo = scheduled_tasks.get_scheduled_task_repo
    old_user = scheduled_tasks.get_optional_user_from_request
    try:
        scheduled_tasks.get_scheduled_task_repo = lambda _request: repo
        scheduled_tasks.get_optional_user_from_request = AsyncMock(return_value=user)

        result = await scheduled_tasks.delete_scheduled_task.__wrapped__(
            task_id=task["id"],
            request=request,
        )
    finally:
        scheduled_tasks.get_scheduled_task_repo = old_repo
        scheduled_tasks.get_optional_user_from_request = old_user

    assert result == {"id": "task-1", "deleted": True}
    assert repo.items == {}


@pytest.mark.asyncio
async def test_pause_and_resume_scheduled_task_update_status():
    repo = _Repo()
    task = await repo.create(
        task_id="task-1",
        user_id="user-1",
        thread_id="thread-1",
        context_mode="reuse_thread",
        assistant_id="lead_agent",
        title="Daily summary",
        prompt="Summarize thread",
        schedule_type="cron",
        schedule_spec={"cron": "0 9 * * *"},
        timezone="UTC",
        next_run_at=None,
    )
    request = SimpleNamespace()
    user = SimpleNamespace(id="user-1")

    old_repo = scheduled_tasks.get_scheduled_task_repo
    old_user = scheduled_tasks.get_optional_user_from_request
    try:
        scheduled_tasks.get_scheduled_task_repo = lambda _request: repo
        scheduled_tasks.get_optional_user_from_request = AsyncMock(return_value=user)

        paused = await scheduled_tasks.pause_scheduled_task.__wrapped__(
            task_id=task["id"],
            request=request,
        )
        paused_status = paused["status"]
        resumed = await scheduled_tasks.resume_scheduled_task.__wrapped__(
            task_id=task["id"],
            request=request,
        )
    finally:
        scheduled_tasks.get_scheduled_task_repo = old_repo
        scheduled_tasks.get_optional_user_from_request = old_user

    assert paused_status == "paused"
    assert resumed["status"] == "enabled"


@pytest.mark.asyncio
async def test_pause_rejects_running_task():
    repo = _Repo()
    task = await repo.create(
        task_id="task-1",
        user_id="user-1",
        thread_id="thread-1",
        context_mode="reuse_thread",
        assistant_id="lead_agent",
        title="Daily summary",
        prompt="Summarize thread",
        schedule_type="cron",
        schedule_spec={"cron": "0 9 * * *"},
        timezone="UTC",
        next_run_at=None,
    )
    task["status"] = "running"
    request = SimpleNamespace()
    user = SimpleNamespace(id="user-1")

    old_repo = scheduled_tasks.get_scheduled_task_repo
    old_user = scheduled_tasks.get_optional_user_from_request
    try:
        scheduled_tasks.get_scheduled_task_repo = lambda _request: repo
        scheduled_tasks.get_optional_user_from_request = AsyncMock(return_value=user)

        with pytest.raises(Exception) as exc_info:
            await scheduled_tasks.pause_scheduled_task.__wrapped__(
                task_id=task["id"],
                request=request,
            )
    finally:
        scheduled_tasks.get_scheduled_task_repo = old_repo
        scheduled_tasks.get_optional_user_from_request = old_user

    assert "currently running" in str(exc_info.value)


@pytest.mark.asyncio
async def test_update_rejects_running_task():
    repo = _Repo()
    task = await repo.create(
        task_id="task-1",
        user_id="user-1",
        thread_id="thread-1",
        context_mode="reuse_thread",
        assistant_id="lead_agent",
        title="Daily summary",
        prompt="Summarize thread",
        schedule_type="cron",
        schedule_spec={"cron": "0 9 * * *"},
        timezone="UTC",
        next_run_at=None,
    )
    task["status"] = "running"
    request = SimpleNamespace()
    user = SimpleNamespace(id="user-1")
    config = _Config()
    thread_store = SimpleNamespace(check_access=AsyncMock(return_value=True))

    old_repo = scheduled_tasks.get_scheduled_task_repo
    old_thread_store = scheduled_tasks.get_thread_store
    old_config = scheduled_tasks.get_config
    old_user = scheduled_tasks.get_optional_user_from_request
    try:
        scheduled_tasks.get_scheduled_task_repo = lambda _request: repo
        scheduled_tasks.get_thread_store = lambda _request: thread_store
        scheduled_tasks.get_config = lambda: config
        scheduled_tasks.get_optional_user_from_request = AsyncMock(return_value=user)

        with pytest.raises(Exception) as exc_info:
            await scheduled_tasks.update_scheduled_task.__wrapped__(
                task_id=task["id"],
                request=request,
                body=scheduled_tasks.ScheduledTaskUpdateRequest(title="Updated title"),
            )
    finally:
        scheduled_tasks.get_scheduled_task_repo = old_repo
        scheduled_tasks.get_thread_store = old_thread_store
        scheduled_tasks.get_config = old_config
        scheduled_tasks.get_optional_user_from_request = old_user

    assert "currently running" in str(exc_info.value)


@pytest.mark.asyncio
async def test_list_thread_scheduled_tasks_filters_by_thread_id():
    repo = _Repo()
    await repo.create(
        task_id="task-1",
        user_id="user-1",
        thread_id="thread-1",
        context_mode="reuse_thread",
        assistant_id="lead_agent",
        title="Thread one task",
        prompt="Prompt",
        schedule_type="cron",
        schedule_spec={"cron": "0 9 * * *"},
        timezone="UTC",
        next_run_at=None,
    )
    await repo.create(
        task_id="task-2",
        user_id="user-1",
        thread_id="thread-2",
        context_mode="reuse_thread",
        assistant_id="lead_agent",
        title="Thread two task",
        prompt="Prompt",
        schedule_type="cron",
        schedule_spec={"cron": "0 9 * * *"},
        timezone="UTC",
        next_run_at=None,
    )

    request = SimpleNamespace()
    user = SimpleNamespace(id="user-1")

    old_repo = scheduled_tasks.get_scheduled_task_repo
    old_user = scheduled_tasks.get_optional_user_from_request
    try:
        scheduled_tasks.get_scheduled_task_repo = lambda _request: repo
        scheduled_tasks.get_optional_user_from_request = AsyncMock(return_value=user)

        result = await scheduled_tasks.list_thread_scheduled_tasks.__wrapped__(
            thread_id="thread-1",
            request=request,
        )
    finally:
        scheduled_tasks.get_scheduled_task_repo = old_repo
        scheduled_tasks.get_optional_user_from_request = old_user

    assert [task["id"] for task in result] == ["task-1"]


@pytest.mark.asyncio
async def test_list_scheduled_task_runs_returns_persisted_rows_without_side_effects():
    repo = _Repo()
    task = await repo.create(
        task_id="task-1",
        user_id="user-1",
        thread_id="thread-1",
        context_mode="reuse_thread",
        assistant_id="lead_agent",
        title="Task",
        prompt="Prompt",
        schedule_type="cron",
        schedule_spec={"cron": "0 9 * * *"},
        timezone="UTC",
        next_run_at=None,
    )
    run_repo = SimpleNamespace(
        list_by_task=AsyncMock(
            return_value=[
                {
                    "id": "task-run-1",
                    "task_id": "task-1",
                    "thread_id": "thread-1",
                    "run_id": "run-1",
                    "status": "running",
                    "error": None,
                }
            ]
        ),
    )
    request = SimpleNamespace()
    user = SimpleNamespace(id="user-1")

    old_task_repo = scheduled_tasks.get_scheduled_task_repo
    old_run_repo = scheduled_tasks.get_scheduled_task_run_repo
    old_user = scheduled_tasks.get_optional_user_from_request
    try:
        scheduled_tasks.get_scheduled_task_repo = lambda _request: repo
        scheduled_tasks.get_scheduled_task_run_repo = lambda _request: run_repo
        scheduled_tasks.get_optional_user_from_request = AsyncMock(return_value=user)

        result = await scheduled_tasks.list_scheduled_task_runs.__wrapped__(
            task_id=task["id"],
            request=request,
        )
    finally:
        scheduled_tasks.get_scheduled_task_repo = old_task_repo
        scheduled_tasks.get_scheduled_task_run_repo = old_run_repo
        scheduled_tasks.get_optional_user_from_request = old_user

    assert result[0]["status"] == "running"


@pytest.mark.asyncio
async def test_create_once_task_enforces_minimum_delay():
    repo = _Repo()
    request = SimpleNamespace()
    body = scheduled_tasks.ScheduledTaskCreateRequest(
        thread_id="thread-1",
        title="Soon task",
        prompt="Run soon",
        schedule_type="once",
        schedule_spec={"run_at": (datetime.now(UTC) + timedelta(seconds=30)).isoformat()},
        timezone="UTC",
    )
    user = SimpleNamespace(id="user-1")
    thread_store = SimpleNamespace(check_access=AsyncMock(return_value=True))
    config = _Config(min_once_delay_seconds=60)

    old_repo = scheduled_tasks.get_scheduled_task_repo
    old_thread_store = scheduled_tasks.get_thread_store
    old_config = scheduled_tasks.get_config
    old_user = scheduled_tasks.get_optional_user_from_request
    try:
        scheduled_tasks.get_scheduled_task_repo = lambda _request: repo
        scheduled_tasks.get_thread_store = lambda _request: thread_store
        scheduled_tasks.get_config = lambda: config
        scheduled_tasks.get_optional_user_from_request = AsyncMock(return_value=user)

        with pytest.raises(Exception) as exc_info:
            await scheduled_tasks.create_scheduled_task.__wrapped__(
                request=request,
                body=body,
            )
    finally:
        scheduled_tasks.get_scheduled_task_repo = old_repo
        scheduled_tasks.get_thread_store = old_thread_store
        scheduled_tasks.get_config = old_config
        scheduled_tasks.get_optional_user_from_request = old_user

    assert "once schedule must be at least" in str(exc_info.value)


@pytest.mark.asyncio
async def test_update_terminal_once_task_with_future_run_at_rearms_it():
    """PATCHing a fresh future run_at onto a completed/failed/cancelled once
    task must reset status to enabled — claim_due_tasks only admits enabled
    rows, so keeping the terminal status returns a next_run_at that never fires."""
    repo = _Repo()
    task = await repo.create(
        task_id="task-terminal",
        user_id="user-1",
        thread_id=None,
        context_mode="fresh_thread_per_run",
        assistant_id="lead_agent",
        title="Once done",
        prompt="p",
        schedule_type="once",
        schedule_spec={"run_at": "2026-07-01T00:00:00+00:00"},
        timezone="UTC",
        next_run_at=None,
    )
    task["status"] = "completed"
    future_run_at = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    request = SimpleNamespace()
    user = SimpleNamespace(id="user-1")

    old_repo = scheduled_tasks.get_scheduled_task_repo
    old_config = scheduled_tasks.get_config
    old_user = scheduled_tasks.get_optional_user_from_request
    try:
        scheduled_tasks.get_scheduled_task_repo = lambda _request: repo
        scheduled_tasks.get_config = lambda: _Config()
        scheduled_tasks.get_optional_user_from_request = AsyncMock(return_value=user)

        result = await scheduled_tasks.update_scheduled_task.__wrapped__(
            task_id=task["id"],
            request=request,
            body=scheduled_tasks.ScheduledTaskUpdateRequest(schedule_spec={"run_at": future_run_at}),
        )
    finally:
        scheduled_tasks.get_scheduled_task_repo = old_repo
        scheduled_tasks.get_config = old_config
        scheduled_tasks.get_optional_user_from_request = old_user

    assert result["status"] == "enabled"
    assert result["next_run_at"] is not None
