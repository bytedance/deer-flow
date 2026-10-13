import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID
from zoneinfo import ZoneInfo

import httpx
import pytest
import pytest_asyncio
from _router_auth_helpers import call_unwrapped, make_authed_test_app
from _scheduled_rows import occurrence
from fastapi import HTTPException

from app.gateway.auth.models import User
from app.gateway.auth_disabled import AUTH_SOURCE_SESSION
from app.gateway.routers import scheduled_tasks
from app.scheduler.service import ScheduledTaskService
from deerflow.config.database_config import DatabaseConfig
from deerflow.persistence.engine import close_engine, get_session_factory, init_engine_from_config
from deerflow.persistence.scheduled_task_runs import ScheduledTaskRunRepository
from deerflow.persistence.scheduled_task_runs.finalization import AGENT_STOP_LAST_ERROR_PREFIX
from deerflow.persistence.scheduled_tasks import ScheduledTaskRepository


@pytest.fixture(autouse=True)
def scheduler_running(monkeypatch):
    """Creation requires this process's poller (409 scheduler_not_running otherwise)."""
    monkeypatch.setattr(scheduled_tasks, "is_scheduler_running", lambda _request: True)


@pytest.mark.parametrize(
    "model",
    [
        scheduled_tasks.ScheduledTaskCreateRequest,
        scheduled_tasks.ScheduledTaskUpdateRequest,
    ],
)
@pytest.mark.parametrize("thread_id", ["", "thread.with.dot", "../escape", "x" * 65])
def test_scheduled_task_models_reject_invalid_thread_ids(model, thread_id):
    from pydantic import ValidationError

    kwargs = {"thread_id": thread_id}
    if model is scheduled_tasks.ScheduledTaskCreateRequest:
        kwargs.update(
            title="Task",
            prompt="Prompt",
            schedule_type="cron",
            schedule_spec={"cron": "0 * * * *"},
            timezone="UTC",
        )

    with pytest.raises(ValidationError):
        model(**kwargs)


@pytest.mark.parametrize(
    ("status", "offers_pause_cancellation"),
    [
        ("queued", True),
        ("launching", False),
        ("running", False),
    ],
)
def test_active_occurrence_conflict_detail_only_offers_pause_for_queued(status, offers_pause_cancellation):
    detail = scheduled_tasks._active_occurrence_conflict_detail(status)

    assert f"active {status} occurrence" in detail
    assert ("cancel the queued occurrence by pausing the task" in detail) is offers_pause_cancellation


class _Repo:
    def __init__(self) -> None:
        self.created = []
        self.items = {}
        self.active_status = None
        self.cancelled_queue = False

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
            "assistant_id": kwargs.get("assistant_id"),
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

    async def update(self, task_id: str, *, user_id: str, updates, require_mutable: bool = False):
        item = await self.get(task_id, user_id=user_id)
        if item is None:
            return None
        item.update(updates)
        return item

    async def get_active_run_status(self, task_id: str):
        return self.active_status

    async def active_run_status_for(self, task_ids):
        return {task_id: self.active_status for task_id in task_ids if self.active_status is not None}

    async def automatic_runs_used_for(self, task_ids):
        return {task_id: 0 for task_id in task_ids}

    async def pause_with_queue_cancellation(self, task_id: str, *, user_id: str, **_kwargs):
        item = await self.get(task_id, user_id=user_id)
        if item is None:
            return "not_found"
        if self.active_status in {"launching", "running"}:
            return "executing"
        if self.active_status == "queued":
            self.cancelled_queue = True
            self.active_status = None
        item["status"] = "paused"
        return "paused"

    async def delete_with_queue_cancellation(self, task_id: str, *, user_id: str, **_kwargs):
        item = await self.get(task_id, user_id=user_id)
        if item is None:
            return "not_found"
        if self.active_status in {"launching", "running"}:
            return "executing"
        if self.active_status == "queued":
            self.cancelled_queue = True
            self.active_status = None
        self.items.pop(task_id, None)
        return "deleted"

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

        created = await call_unwrapped(
            scheduled_tasks.create_scheduled_task,
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
    assert created["assistant_id"] == "lead_agent"
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

        created = await call_unwrapped(
            scheduled_tasks.create_scheduled_task,
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

        result = await call_unwrapped(
            scheduled_tasks.trigger_scheduled_task,
            task_id=task["id"],
            request=request,
        )
    finally:
        scheduled_tasks.get_scheduled_task_repo = old_repo
        scheduled_tasks.get_scheduled_task_service = old_service
        scheduled_tasks.get_optional_user_from_request = old_user

    assert result == {"id": "task-1", "triggered": True, "outcome": "launched", "existing": False, "thread_id": None}
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
            await call_unwrapped(
                scheduled_tasks.trigger_scheduled_task,
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

        result = await call_unwrapped(
            scheduled_tasks.update_scheduled_task,
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
async def test_update_rechecks_atomic_mutability_after_router_precheck(tmp_path):
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    old_repo = scheduled_tasks.get_scheduled_task_repo
    old_thread_store = scheduled_tasks.get_thread_store
    old_config = scheduled_tasks.get_config
    old_user = scheduled_tasks.get_optional_user_from_request
    try:
        sf = get_session_factory()
        assert sf is not None

        class PrecheckBarrierRepository(ScheduledTaskRepository):
            def __init__(self, session_factory):
                super().__init__(session_factory)
                self.prechecked = asyncio.Event()
                self.resume = asyncio.Event()

            async def get_active_run_status(self, task_id: str):
                status = await super().get_active_run_status(task_id)
                if status is None:
                    self.prechecked.set()
                    await self.resume.wait()
                return status

        repo = PrecheckBarrierRepository(sf)
        run_repo = ScheduledTaskRunRepository(sf)
        task = await repo.create(
            task_id="task-router-atomic-patch",
            user_id="user-1",
            thread_id="thread-1",
            context_mode="reuse_thread",
            assistant_id="lead_agent",
            title="Atomic patch",
            prompt="original prompt",
            schedule_type="cron",
            schedule_spec={"cron": "0 9 * * *"},
            timezone="UTC",
            next_run_at=None,
        )
        scheduled_tasks.get_scheduled_task_repo = lambda _request: repo
        scheduled_tasks.get_thread_store = lambda _request: SimpleNamespace(check_access=AsyncMock(return_value=True))
        scheduled_tasks.get_config = lambda: _Config()
        scheduled_tasks.get_optional_user_from_request = AsyncMock(return_value=SimpleNamespace(id="user-1"))

        patch_call = asyncio.create_task(
            call_unwrapped(
                scheduled_tasks.update_scheduled_task,
                task_id=task["id"],
                request=SimpleNamespace(),
                body=scheduled_tasks.ScheduledTaskUpdateRequest(prompt="changed after admission"),
            )
        )
        await repo.prechecked.wait()
        await run_repo.create(
            run_record_id="task-run-router-atomic-patch",
            task_id=task["id"],
            thread_id="thread-1",
            scheduled_for=datetime.now(UTC),
            trigger="manual",
            status="queued",
        )
        repo.resume.set()

        with pytest.raises(HTTPException) as exc_info:
            await patch_call
        assert exc_info.value.status_code == 409
        assert "active queued occurrence" in exc_info.value.detail["message"]
        current = await repo.get(task["id"], user_id="user-1")
        assert current is not None
        assert current["prompt"] == "original prompt"
    finally:
        scheduled_tasks.get_scheduled_task_repo = old_repo
        scheduled_tasks.get_thread_store = old_thread_store
        scheduled_tasks.get_config = old_config
        scheduled_tasks.get_optional_user_from_request = old_user
        await close_engine()


@pytest.mark.asyncio
@pytest.mark.parametrize("cadence_changed", [False, True], ids=["same-cadence", "new-cadence"])
async def test_update_interval_task_metadata_through_the_sql_repository(tmp_path, cadence_changed):
    """The edit dialog always sends ``schedule_spec`` beside the changed field. For an interval
    task whose cadence did not change the router keeps ``existing["next_run_at"]`` — which the
    repository hands back serialized as an ISO string — and passes it straight to
    ``repo.update``. The SQL store assigned it to a ``DateTime`` column untouched, so renaming an
    interval task failed with a 500 on SQLite and Postgres alike; the in-memory stand-in the other
    router tests use never noticed. Drive the real router against the real SQLite repository."""
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    old_repo = scheduled_tasks.get_scheduled_task_repo
    old_thread_store = scheduled_tasks.get_thread_store
    old_config = scheduled_tasks.get_config
    old_user = scheduled_tasks.get_optional_user_from_request
    try:
        sf = get_session_factory()
        assert sf is not None
        repo = ScheduledTaskRepository(sf)
        original_next_run_at = datetime(2030, 1, 1, 9, 0, tzinfo=UTC)
        task = await repo.create(
            task_id="task-router-interval-rename",
            user_id="user-1",
            thread_id=None,
            context_mode="fresh_thread_per_run",
            assistant_id="lead_agent",
            title="Hourly digest",
            prompt="summarize",
            schedule_type="interval",
            schedule_spec={"every_seconds": 3600},
            timezone="UTC",
            next_run_at=original_next_run_at,
        )
        assert isinstance(task["next_run_at"], str)  # the serialized form the router reuses
        scheduled_tasks.get_scheduled_task_repo = lambda _request: repo
        scheduled_tasks.get_thread_store = lambda _request: SimpleNamespace(check_access=AsyncMock(return_value=True))
        scheduled_tasks.get_config = lambda: _Config()
        scheduled_tasks.get_optional_user_from_request = AsyncMock(return_value=SimpleNamespace(id="user-1"))

        every_seconds = 7200 if cadence_changed else 3600
        updated = await call_unwrapped(
            scheduled_tasks.update_scheduled_task,
            task_id=task["id"],
            request=SimpleNamespace(),
            body=scheduled_tasks.ScheduledTaskUpdateRequest(title="Hourly digest (renamed)", schedule_spec={"every_seconds": every_seconds}),
        )

        assert updated["title"] == "Hourly digest (renamed)"
        assert updated["schedule_spec"] == {"every_seconds": every_seconds}
        stored = await repo.get(task["id"], user_id="user-1")
        assert stored is not None and stored["title"] == "Hourly digest (renamed)"
        stored_next_run_at = datetime.fromisoformat(stored["next_run_at"].replace("Z", "+00:00"))
        if cadence_changed:
            assert stored_next_run_at != original_next_run_at  # recomputed from the new cadence
        else:
            assert stored_next_run_at == original_next_run_at  # a pure rename keeps the next occurrence
    finally:
        scheduled_tasks.get_scheduled_task_repo = old_repo
        scheduled_tasks.get_thread_store = old_thread_store
        scheduled_tasks.get_config = old_config
        scheduled_tasks.get_optional_user_from_request = old_user
        await close_engine()


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

        result = await call_unwrapped(
            scheduled_tasks.delete_scheduled_task,
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

        paused = await call_unwrapped(
            scheduled_tasks.pause_scheduled_task,
            task_id=task["id"],
            request=request,
        )
        paused_status = paused["status"]
        resumed = await call_unwrapped(
            scheduled_tasks.resume_scheduled_task,
            task_id=task["id"],
            request=request,
        )
    finally:
        scheduled_tasks.get_scheduled_task_repo = old_repo
        scheduled_tasks.get_optional_user_from_request = old_user

    assert paused_status == "paused"
    assert resumed["status"] == "enabled"


@pytest.mark.asyncio
async def test_pause_cancels_waiting_occurrence_before_pausing_task():
    repo = _Repo()
    task = await repo.create(
        task_id="task-queued",
        user_id="user-1",
        thread_id="thread-1",
        context_mode="reuse_thread",
        assistant_id="lead_agent",
        title="Queued task",
        prompt="Prompt",
        schedule_type="cron",
        schedule_spec={"cron": "0 9 * * *"},
        timezone="UTC",
        next_run_at=None,
    )
    repo.active_status = "queued"
    request = SimpleNamespace()
    user = SimpleNamespace(id="user-1")

    old_repo = scheduled_tasks.get_scheduled_task_repo
    old_user = scheduled_tasks.get_optional_user_from_request
    try:
        scheduled_tasks.get_scheduled_task_repo = lambda _request: repo
        scheduled_tasks.get_optional_user_from_request = AsyncMock(return_value=user)
        result = await call_unwrapped(
            scheduled_tasks.pause_scheduled_task,
            task_id=task["id"],
            request=request,
        )
    finally:
        scheduled_tasks.get_scheduled_task_repo = old_repo
        scheduled_tasks.get_optional_user_from_request = old_user

    assert result["status"] == "paused"
    assert repo.cancelled_queue is True


@pytest.mark.asyncio
async def test_delete_rejects_occurrence_that_has_started_launching():
    repo = _Repo()
    task = await repo.create(
        task_id="task-launching",
        user_id="user-1",
        thread_id="thread-1",
        context_mode="reuse_thread",
        assistant_id="lead_agent",
        title="Launching task",
        prompt="Prompt",
        schedule_type="cron",
        schedule_spec={"cron": "0 9 * * *"},
        timezone="UTC",
        next_run_at=None,
    )
    repo.active_status = "launching"
    request = SimpleNamespace()
    user = SimpleNamespace(id="user-1")

    old_repo = scheduled_tasks.get_scheduled_task_repo
    old_user = scheduled_tasks.get_optional_user_from_request
    try:
        scheduled_tasks.get_scheduled_task_repo = lambda _request: repo
        scheduled_tasks.get_optional_user_from_request = AsyncMock(return_value=user)
        with pytest.raises(Exception) as exc_info:
            await call_unwrapped(
                scheduled_tasks.delete_scheduled_task,
                task_id=task["id"],
                request=request,
            )
    finally:
        scheduled_tasks.get_scheduled_task_repo = old_repo
        scheduled_tasks.get_optional_user_from_request = old_user

    assert "launching or running" in str(exc_info.value)
    assert task["id"] in repo.items


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
            await call_unwrapped(
                scheduled_tasks.pause_scheduled_task,
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
            await call_unwrapped(
                scheduled_tasks.update_scheduled_task,
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
async def test_update_rejects_queued_task_definition_until_occurrence_finishes():
    repo = _Repo()
    task = await repo.create(
        task_id="task-queued",
        user_id="user-1",
        thread_id="thread-1",
        context_mode="reuse_thread",
        assistant_id="lead_agent",
        title="Queued task",
        prompt="Original prompt",
        schedule_type="cron",
        schedule_spec={"cron": "0 9 * * *"},
        timezone="UTC",
        next_run_at=None,
    )
    repo.active_status = "queued"
    request = SimpleNamespace()
    user = SimpleNamespace(id="user-1")
    config = _Config()

    old_repo = scheduled_tasks.get_scheduled_task_repo
    old_config = scheduled_tasks.get_config
    old_user = scheduled_tasks.get_optional_user_from_request
    try:
        scheduled_tasks.get_scheduled_task_repo = lambda _request: repo
        scheduled_tasks.get_config = lambda: config
        scheduled_tasks.get_optional_user_from_request = AsyncMock(return_value=user)

        with pytest.raises(Exception) as exc_info:
            await call_unwrapped(
                scheduled_tasks.update_scheduled_task,
                task_id=task["id"],
                request=request,
                body=scheduled_tasks.ScheduledTaskUpdateRequest(prompt="Changed while queued"),
            )
    finally:
        scheduled_tasks.get_scheduled_task_repo = old_repo
        scheduled_tasks.get_config = old_config
        scheduled_tasks.get_optional_user_from_request = old_user

    assert "active queued occurrence" in str(exc_info.value)
    assert repo.items[task["id"]]["prompt"] == "Original prompt"


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

        result = await call_unwrapped(
            scheduled_tasks.list_thread_scheduled_tasks,
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

        result = await call_unwrapped(
            scheduled_tasks.list_scheduled_task_runs,
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
            await call_unwrapped(
                scheduled_tasks.create_scheduled_task,
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

        result = await call_unwrapped(
            scheduled_tasks.update_scheduled_task,
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


def _interval_create_request(**overrides):
    kwargs = {
        "title": "Every 90 minutes",
        "prompt": "Ping",
        "schedule_type": "interval",
        "schedule_spec": {"every_seconds": 90},
        "timezone": "UTC",
    }
    kwargs.update(overrides)
    return scheduled_tasks.ScheduledTaskCreateRequest(**kwargs)


async def _call_create(body, repo=None, config=None):
    repo = repo or _Repo()
    user = SimpleNamespace(id="user-1")
    thread_store = SimpleNamespace(check_access=AsyncMock(return_value=True))
    old_repo = scheduled_tasks.get_scheduled_task_repo
    old_thread_store = scheduled_tasks.get_thread_store
    old_config = scheduled_tasks.get_config
    old_user = scheduled_tasks.get_optional_user_from_request
    try:
        scheduled_tasks.get_scheduled_task_repo = lambda _request: repo
        scheduled_tasks.get_thread_store = lambda _request: thread_store
        scheduled_tasks.get_config = lambda: config or _Config()
        scheduled_tasks.get_optional_user_from_request = AsyncMock(return_value=user)
        return await call_unwrapped(
            scheduled_tasks.create_scheduled_task,
            request=SimpleNamespace(),
            body=body,
        )
    finally:
        scheduled_tasks.get_scheduled_task_repo = old_repo
        scheduled_tasks.get_thread_store = old_thread_store
        scheduled_tasks.get_config = old_config
        scheduled_tasks.get_optional_user_from_request = old_user


async def _call_update(repo, task_id, body):
    old_repo = scheduled_tasks.get_scheduled_task_repo
    old_config = scheduled_tasks.get_config
    old_user = scheduled_tasks.get_optional_user_from_request
    try:
        scheduled_tasks.get_scheduled_task_repo = lambda _request: repo
        scheduled_tasks.get_config = lambda: _Config()
        scheduled_tasks.get_optional_user_from_request = AsyncMock(return_value=SimpleNamespace(id="user-1"))
        return await call_unwrapped(
            scheduled_tasks.update_scheduled_task,
            task_id=task_id,
            request=SimpleNamespace(),
            body=body,
        )
    finally:
        scheduled_tasks.get_scheduled_task_repo = old_repo
        scheduled_tasks.get_config = old_config
        scheduled_tasks.get_optional_user_from_request = old_user


def _create_request(**overrides):
    kwargs = {
        "title": "Daily summary",
        "prompt": "Summarize thread",
        "schedule_type": "cron",
        "schedule_spec": {"cron": "0 9 * * *"},
        "timezone": "UTC",
    }
    kwargs.update(overrides)
    return scheduled_tasks.ScheduledTaskCreateRequest(**kwargs)


async def _seed_task(repo: _Repo | ScheduledTaskRepository, **overrides):
    kwargs = {
        "task_id": "task-1",
        "user_id": "user-1",
        "thread_id": None,
        "context_mode": "fresh_thread_per_run",
        "assistant_id": "lead_agent",
        "title": "Daily summary",
        "prompt": "Summarize thread",
        "schedule_type": "cron",
        "schedule_spec": {"cron": "0 9 * * *"},
        "timezone": "UTC",
        "next_run_at": None,
    }
    kwargs.update(overrides)
    return await repo.create(**kwargs)


@pytest.mark.asyncio
async def test_create_interval_task_sets_next_run_from_now():
    before = datetime.now(UTC)
    created = await _call_create(
        _interval_create_request(
            schedule_spec={"every_seconds": 90},
            timezone="Asia/Shanghai",
        )
    )
    after = datetime.now(UTC)
    assert created["schedule_type"] == "interval"
    assert created["schedule_spec"] == {"every_seconds": 90}
    assert created["timezone"] == "Asia/Shanghai"
    assert before + timedelta(seconds=90) <= created["next_run_at"] <= after + timedelta(seconds=90)
    assert created["next_run_at"].utcoffset() == timedelta(0)


@pytest.mark.asyncio
async def test_create_interval_task_rejects_below_minimum_delay():
    with pytest.raises(HTTPException) as exc_info:
        await _call_create(_interval_create_request(schedule_spec={"every_seconds": 30}))
    assert exc_info.value.status_code == 422
    assert "at least 60 seconds" in exc_info.value.detail["message"]


@pytest.mark.asyncio
async def test_create_interval_task_rejects_above_maximum():
    with pytest.raises(HTTPException) as exc_info:
        await _call_create(_interval_create_request(schedule_spec={"every_seconds": 30 * 24 * 3600 + 1}))
    assert exc_info.value.status_code == 422
    assert "at most" in exc_info.value.detail["message"]


@pytest.mark.asyncio
async def test_create_interval_task_rejects_missing_every_seconds():
    with pytest.raises(HTTPException) as exc_info:
        await _call_create(_interval_create_request(schedule_spec={}))
    assert exc_info.value.status_code == 422
    assert "every_seconds" in exc_info.value.detail["message"]


@pytest.mark.asyncio
async def test_update_interval_task_recomputes_next_run():
    repo = _Repo()
    task = await repo.create(
        task_id="task-interval",
        user_id="user-1",
        thread_id=None,
        context_mode="fresh_thread_per_run",
        assistant_id="lead_agent",
        title="Interval",
        prompt="p",
        schedule_type="interval",
        schedule_spec={"every_seconds": 90},
        timezone="UTC",
        next_run_at=datetime(2026, 7, 1, 0, 0, tzinfo=UTC),
    )
    before = datetime.now(UTC)
    updated = await _call_update(
        repo,
        task["id"],
        scheduled_tasks.ScheduledTaskUpdateRequest(schedule_spec={"every_seconds": 120}),
    )
    after = datetime.now(UTC)
    assert updated["schedule_spec"] == {"every_seconds": 120}
    assert before + timedelta(seconds=120) <= updated["next_run_at"] <= after + timedelta(seconds=120)


@pytest.mark.asyncio
async def test_update_interval_task_rejects_below_minimum_delay():
    repo = _Repo()
    task = await repo.create(
        task_id="task-interval",
        user_id="user-1",
        thread_id=None,
        context_mode="fresh_thread_per_run",
        assistant_id="lead_agent",
        title="Interval",
        prompt="p",
        schedule_type="interval",
        schedule_spec={"every_seconds": 90},
        timezone="UTC",
        next_run_at=datetime(2026, 7, 1, 0, 0, tzinfo=UTC),
    )
    with pytest.raises(HTTPException) as exc_info:
        await _call_update(
            repo,
            task["id"],
            scheduled_tasks.ScheduledTaskUpdateRequest(schedule_spec={"every_seconds": 30}),
        )
    assert exc_info.value.status_code == 422
    assert "at least 60 seconds" in exc_info.value.detail["message"]


@pytest.mark.asyncio
async def test_update_interval_task_keeps_next_run_when_spec_unchanged():
    repo = _Repo()
    original_next = datetime(2026, 7, 1, 0, 0, tzinfo=UTC)
    task = await repo.create(
        task_id="task-interval",
        user_id="user-1",
        thread_id=None,
        context_mode="fresh_thread_per_run",
        assistant_id="lead_agent",
        title="Interval",
        prompt="p",
        schedule_type="interval",
        schedule_spec={"every_seconds": 90},
        timezone="UTC",
        next_run_at=original_next,
    )
    updated = await _call_update(
        repo,
        task["id"],
        scheduled_tasks.ScheduledTaskUpdateRequest(
            schedule_spec={"every_seconds": 90},
            timezone="Asia/Shanghai",
        ),
    )
    assert updated["timezone"] == "Asia/Shanghai"
    assert updated["next_run_at"] == original_next


@pytest.mark.asyncio
async def test_create_interval_task_rejects_non_integer_every_seconds():
    with pytest.raises(HTTPException) as exc_info:
        await _call_create(_interval_create_request(schedule_spec={"every_seconds": True}))
    assert exc_info.value.status_code == 422
    assert "every_seconds" in exc_info.value.detail["message"]


@pytest.mark.asyncio
async def test_create_interval_task_uses_configured_minimum_delay():
    with pytest.raises(HTTPException) as exc_info:
        await _call_create(
            _interval_create_request(schedule_spec={"every_seconds": 90}),
            config=_Config(min_once_delay_seconds=120),
        )
    assert exc_info.value.status_code == 422
    assert "at least 120 seconds" in exc_info.value.detail["message"]


@pytest.mark.asyncio
async def test_create_explicit_lead_agent_is_accepted():
    created = await _call_create(_create_request(assistant_id="lead_agent"))
    assert created["assistant_id"] == "lead_agent"


@pytest.mark.asyncio
async def test_create_lead_agent_is_accepted_case_insensitively():
    # Callers writing LEAD_AGENT / lead-agent mean the default, not a custom agent.
    for raw in ("LEAD_AGENT", "Lead_Agent", "lead-agent"):
        created = await _call_create(_create_request(assistant_id=raw))
        assert created["assistant_id"] == "lead_agent"


@pytest.mark.asyncio
async def test_create_custom_assistant_id_is_normalized_and_persisted():
    with patch(
        "app.gateway.routers.scheduled_tasks.load_agent_config",
        return_value=object(),
    ) as loader:
        created = await _call_create(_create_request(assistant_id="Research_Bot"))
    assert created["assistant_id"] == "research-bot"
    loader.assert_called_once_with("research-bot", user_id="user-1")


@pytest.mark.asyncio
async def test_create_unknown_assistant_id_is_rejected():
    with patch(
        "app.gateway.routers.scheduled_tasks.load_agent_config",
        side_effect=FileNotFoundError("missing"),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await _call_create(_create_request(assistant_id="missing-bot"))
    assert exc_info.value.status_code == 422
    assert "Unknown assistant_id" in exc_info.value.detail["message"]


@pytest.mark.asyncio
async def test_create_invalid_assistant_id_is_rejected():
    with pytest.raises(HTTPException) as exc_info:
        await _call_create(_create_request(assistant_id="bad agent"))
    assert exc_info.value.status_code == 422
    assert "Invalid assistant_id" in exc_info.value.detail["message"]


@pytest.mark.asyncio
async def test_update_custom_assistant_id_is_persisted():
    repo = _Repo()
    task = await repo.create(
        task_id="task-1",
        user_id="user-1",
        thread_id=None,
        context_mode="fresh_thread_per_run",
        assistant_id="lead_agent",
        title="Daily summary",
        prompt="Summarize thread",
        schedule_type="cron",
        schedule_spec={"cron": "0 9 * * *"},
        timezone="UTC",
        next_run_at=None,
    )
    old_repo = scheduled_tasks.get_scheduled_task_repo
    old_config = scheduled_tasks.get_config
    old_user = scheduled_tasks.get_optional_user_from_request
    try:
        scheduled_tasks.get_scheduled_task_repo = lambda _request: repo
        scheduled_tasks.get_config = lambda: _Config()
        scheduled_tasks.get_optional_user_from_request = AsyncMock(return_value=SimpleNamespace(id="user-1"))
        with patch(
            "app.gateway.routers.scheduled_tasks.load_agent_config",
            return_value=object(),
        ):
            updated = await call_unwrapped(
                scheduled_tasks.update_scheduled_task,
                task_id=task["id"],
                request=SimpleNamespace(),
                body=scheduled_tasks.ScheduledTaskUpdateRequest(assistant_id="triage-bot"),
            )
    finally:
        scheduled_tasks.get_scheduled_task_repo = old_repo
        scheduled_tasks.get_config = old_config
        scheduled_tasks.get_optional_user_from_request = old_user
    assert updated["assistant_id"] == "triage-bot"


@pytest.mark.asyncio
async def test_update_unknown_assistant_id_is_rejected():
    repo = _Repo()
    task = await _seed_task(repo)
    with patch(
        "app.gateway.routers.scheduled_tasks.load_agent_config",
        side_effect=FileNotFoundError("missing"),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await _call_update(
                repo,
                task["id"],
                scheduled_tasks.ScheduledTaskUpdateRequest(assistant_id="missing-bot"),
            )
    assert exc_info.value.status_code == 422
    assert "Unknown assistant_id" in exc_info.value.detail["message"]
    assert repo.items[task["id"]]["assistant_id"] == "lead_agent"


@pytest.mark.asyncio
async def test_update_invalid_assistant_id_is_rejected():
    repo = _Repo()
    task = await _seed_task(repo)
    with pytest.raises(HTTPException) as exc_info:
        await _call_update(
            repo,
            task["id"],
            scheduled_tasks.ScheduledTaskUpdateRequest(assistant_id="bad agent"),
        )
    assert exc_info.value.status_code == 422
    assert "Invalid assistant_id" in exc_info.value.detail["message"]


@pytest.mark.asyncio
async def test_update_explicit_null_assistant_id_resets_to_lead_agent():
    repo = _Repo()
    task = await _seed_task(repo, assistant_id="research-bot")
    with patch(
        "app.gateway.routers.scheduled_tasks.load_agent_config",
        side_effect=FileNotFoundError("missing"),
    ) as loader:
        updated = await _call_update(
            repo,
            task["id"],
            scheduled_tasks.ScheduledTaskUpdateRequest(assistant_id=None),
        )
    loader.assert_not_called()
    assert updated["assistant_id"] == "lead_agent"
    assert repo.items[task["id"]]["assistant_id"] == "lead_agent"


@pytest.mark.asyncio
@pytest.mark.parametrize("payload,expected_assistant", [({"assistant_id": None}, "lead_agent"), ({}, "research-bot")], ids=["explicit-null", "omitted"])
async def test_update_assistant_id_through_the_sql_repository(tmp_path, payload, expected_assistant):
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    try:
        sf = get_session_factory()
        assert sf is not None
        repo = ScheduledTaskRepository(sf)
        task = await _seed_task(repo, assistant_id="research-bot")
        with patch(
            "app.gateway.routers.scheduled_tasks.load_agent_config",
            side_effect=FileNotFoundError("missing"),
        ) as loader:
            updated = await _call_update(
                repo,
                task["id"],
                scheduled_tasks.ScheduledTaskUpdateRequest.model_validate({"title": "Renamed", **payload}),
            )
        loader.assert_not_called()
        assert updated["assistant_id"] == expected_assistant
        stored = await repo.get(task["id"], user_id="user-1")
        assert stored is not None
        assert stored["assistant_id"] == expected_assistant
        assert stored["title"] == "Renamed"
    finally:
        await close_engine()


@pytest.mark.asyncio
async def test_update_omitting_assistant_id_keeps_existing_even_if_agent_is_gone():
    # Unrelated PATCH (rename, reschedule) must not re-resolve assistant_id.
    # Otherwise a since-deleted custom agent makes the task uneditable.
    repo = _Repo()
    task = await _seed_task(repo, assistant_id="research-bot")
    with patch(
        "app.gateway.routers.scheduled_tasks.load_agent_config",
        side_effect=FileNotFoundError("missing"),
    ) as loader:
        updated = await _call_update(
            repo,
            task["id"],
            scheduled_tasks.ScheduledTaskUpdateRequest(title="Renamed"),
        )
    loader.assert_not_called()
    assert updated["title"] == "Renamed"
    assert updated["assistant_id"] == "research-bot"


# --- PR1: lifecycle, limits, stop condition and coded errors over HTTP ----------------------


_CONTRACT = json.loads((Path(__file__).resolve().parents[2] / "contracts" / "scheduled_task_errors_contract.json").read_text(encoding="utf-8"))
_CONTRACT_CODES = set(_CONTRACT["ui_codes"]) | set(_CONTRACT["agent_only_codes"])
_OWNER = User(id=UUID("12345678-1234-1234-1234-123456789abc"), email="lifecycle@example.com", password_hash="unused", system_role="user")
OWNER = str(_OWNER.id)


def coded(response, status: int, code: str) -> dict:
    """Assert a well-typed request failed with a contract-coded ``{code, message}``."""
    assert response.status_code == status, response.text
    detail = response.json()["detail"]
    assert isinstance(detail, dict) and detail["code"] == code and isinstance(detail["message"], str) and detail["message"]
    assert detail["code"] in _CONTRACT_CODES
    return detail


@pytest_asyncio.fixture
async def http(tmp_path, monkeypatch):
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    sf = get_session_factory()
    repo, run_repo = ScheduledTaskRepository(sf), ScheduledTaskRunRepository(sf)
    launches = []

    async def launch(**kwargs):
        launches.append(kwargs)
        return {"run_id": f"run-{len(launches)}", "thread_id": kwargs["thread_id"]}

    app = make_authed_test_app(user_factory=lambda: _OWNER, bind_current_user=True)

    @app.middleware("http")
    async def mark_session_source(request, call_next):
        request.state.auth_source = AUTH_SOURCE_SESSION
        return await call_next(request)

    app.state.scheduled_task_repo = repo
    app.state.scheduled_task_run_repo = run_repo
    app.state.scheduled_task_service = ScheduledTaskService(task_repo=repo, task_run_repo=run_repo, launch_run=launch, poll_interval_seconds=60, lease_seconds=120, max_concurrent_runs=3)
    app.include_router(scheduled_tasks.router)
    monkeypatch.setattr(scheduled_tasks, "get_config", lambda: _Config())
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://lifecycle.test") as client:
            yield SimpleNamespace(client=client, app=app, repo=repo, runs=run_repo, sf=sf, launches=launches)
    finally:
        await close_engine()


async def _seed(repo, task_id="task-l", *, schedule_type="interval", schedule_spec=None, timezone="UTC", next_run_at=None, origin_thread_id=None, **extra):
    return await repo.create(
        task_id=task_id,
        user_id=OWNER,
        thread_id=None,
        context_mode="fresh_thread_per_run",
        assistant_id="lead_agent",
        title="Checklist",
        prompt="Check release-checklist.md.",
        schedule_type=schedule_type,
        schedule_spec=schedule_spec or {"every_seconds": 3600},
        timezone=timezone,
        next_run_at=next_run_at,
        origin_thread_id=origin_thread_id,
        **extra,
    )


async def _exhaust(env, task_id="task-l", runs=2):
    async with env.sf() as session:
        session.add_all([occurrence(f"{task_id}-{index}", task_id, seq=index) for index in range(1, runs + 1)])
        await session.commit()
    await env.repo.update(task_id, user_id=OWNER, updates={"status": "completed", "next_run_at": None})


def _when(body):
    return datetime.fromisoformat(body["next_run_at"].replace("Z", "+00:00"))


_CREATE = {"title": "Checklist", "prompt": "Check release-checklist.md.\nList the unchecked items.", "schedule_type": "interval", "schedule_spec": {"every_seconds": 3600}, "timezone": "UTC"}


@pytest.mark.asyncio
async def test_resume_recomputes_a_past_interval_run_from_now(http):
    await _seed(http.repo, next_run_at=datetime.now(UTC) - timedelta(hours=5))
    await http.repo.update("task-l", user_id=OWNER, updates={"status": "paused"})
    before = datetime.now(UTC)
    response = await http.client.post("/api/scheduled-tasks/task-l/resume")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "enabled"
    assert before + timedelta(seconds=3590) <= _when(body) <= datetime.now(UTC) + timedelta(seconds=3610)
    assert http.launches == []  # no catch-up run


@pytest.mark.asyncio
async def test_resume_of_a_daily_cron_paused_yesterday_moves_to_the_next_local_nine(http):
    yesterday = datetime.now(UTC) - timedelta(days=1)
    await _seed(http.repo, schedule_type="cron", schedule_spec={"cron": "0 9 * * *"}, timezone="Asia/Shanghai", next_run_at=yesterday)
    await http.repo.update("task-l", user_id=OWNER, updates={"status": "paused"})
    response = await http.client.post("/api/scheduled-tasks/task-l/resume")
    assert response.status_code == 200, response.text
    local = _when(response.json()).astimezone(ZoneInfo("Asia/Shanghai"))
    assert (local.hour, local.minute) == (9, 0)
    assert datetime.now(UTC) < _when(response.json()) <= datetime.now(UTC) + timedelta(days=1)


@pytest.mark.asyncio
async def test_resume_keeps_a_future_next_run_and_clears_the_agent_stop_marker(http):
    future = datetime(2031, 5, 6, 7, 8, tzinfo=UTC)
    await _seed(http.repo, next_run_at=future)
    await http.repo.update("task-l", user_id=OWNER, updates={"status": "paused", "last_error": f"{AGENT_STOP_LAST_ERROR_PREFIX}run-7"})
    response = await http.client.post("/api/scheduled-tasks/task-l/resume")
    assert response.status_code == 200, response.text
    assert _when(response.json()) == future
    assert response.json()["last_error"] is None
    again = await http.client.post("/api/scheduled-tasks/task-l/resume")
    assert again.status_code == 200 and again.json()["updated_at"] == response.json()["updated_at"]


@pytest.mark.asyncio
async def test_resume_of_a_one_time_task_whose_time_passed_asks_for_a_new_time(http):
    await _seed(http.repo, schedule_type="once", schedule_spec={"run_at": "2020-01-01T09:00:00+00:00"})
    await http.repo.update("task-l", user_id=OWNER, updates={"status": "paused"})
    coded(await http.client.post("/api/scheduled-tasks/task-l/resume"), 422, "once_time_passed")
    assert (await http.repo.get("task-l", user_id=OWNER))["status"] == "paused"


@pytest.mark.asyncio
async def test_resume_renewal_raises_the_cap_or_clears_it(http):
    await _seed(http.repo, max_runs=2)
    await _exhaust(http)
    detail = coded(await http.client.post("/api/scheduled-tasks/task-l/resume"), 409, "limits_exhausted")
    assert detail["params"] == {"limit": "max_runs", "used": 2, "max_runs": 2, "end_at": None}
    assert detail["message"] == "All 2 automatic runs are used. Raise max_runs above 2 or clear it (max_runs: null) in the same request to reactivate."
    # A later end time does not renew a used-up run limit.
    later = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    coded(await http.client.post("/api/scheduled-tasks/task-l/resume", json={"end_at": later}), 409, "limits_exhausted")
    coded(await http.client.post("/api/scheduled-tasks/task-l/resume", json={"max_runs": 2}), 422, "max_runs_not_above_used")
    raised = await http.client.post("/api/scheduled-tasks/task-l/resume", json={"max_runs": 5})
    assert raised.status_code == 200, raised.text
    assert (raised.json()["status"], raised.json()["max_runs"], raised.json()["automatic_runs_used"]) == ("enabled", 5, 2)
    await http.repo.update("task-l", user_id=OWNER, updates={"status": "completed", "max_runs": 2})
    cleared = await http.client.post("/api/scheduled-tasks/task-l/resume", json={"max_runs": None})
    assert cleared.status_code == 200, cleared.text
    assert (cleared.json()["status"], cleared.json()["max_runs"]) == ("enabled", None)


@pytest.mark.asyncio
async def test_clearing_the_only_cap_of_a_sub_hourly_chat_task_is_refused(http):
    await _seed(http.repo, schedule_spec={"every_seconds": 600}, origin_thread_id="origin", max_runs=2)
    await _exhaust(http)
    before = await http.repo.get("task-l", user_id=OWNER)
    coded(await http.client.post("/api/scheduled-tasks/task-l/resume", json={"max_runs": None}), 422, "frequent_requires_limit")
    assert await http.repo.get("task-l", user_id=OWNER) == before
    later = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    renewed = await http.client.post("/api/scheduled-tasks/task-l/resume", json={"max_runs": None, "end_at": later})
    assert renewed.status_code == 200, renewed.text
    assert renewed.json()["status"] == "enabled"


@pytest.mark.asyncio
async def test_resume_reports_an_end_time_that_passed(http):
    past = datetime.now(UTC) - timedelta(hours=1)
    await _seed(http.repo, end_at=past)
    await http.repo.update("task-l", user_id=OWNER, updates={"status": "completed"})
    detail = coded(await http.client.post("/api/scheduled-tasks/task-l/resume"), 409, "limits_exhausted")
    assert detail["params"]["limit"] == "end_at"
    assert detail["message"].startswith("The end time ") and detail["message"].endswith("has passed. Set a later end_at or clear it (end_at: null) in the same request to reactivate.")
    coded(await http.client.post("/api/scheduled-tasks/task-l/resume", json={"end_at": past.isoformat()}), 422, "end_at_in_past")


@pytest.mark.asyncio
async def test_patch_that_only_raises_the_cap_leaves_a_finished_task_finished(http):
    await _seed(http.repo, max_runs=2)
    await _exhaust(http)
    response = await http.client.patch("/api/scheduled-tasks/task-l", json={"max_runs": 10})
    assert response.status_code == 200, response.text
    assert (response.json()["status"], response.json()["max_runs"]) == ("completed", 10)


@pytest.mark.asyncio
async def test_patch_rearm_of_an_exhausted_task_needs_a_higher_cap_in_the_same_body(http):
    await _seed(http.repo, max_runs=2)
    await _exhaust(http)
    detail = coded(await http.client.patch("/api/scheduled-tasks/task-l", json={"schedule_spec": {"every_seconds": 7200}}), 409, "limits_exhausted")
    assert detail["params"]["used"] == 2
    assert (await http.repo.get("task-l", user_id=OWNER))["status"] == "completed"
    rearmed = await http.client.patch("/api/scheduled-tasks/task-l", json={"schedule_spec": {"every_seconds": 7200}, "max_runs": 4})
    assert rearmed.status_code == 200, rearmed.text
    assert (rearmed.json()["status"], rearmed.json()["max_runs"]) == ("enabled", 4)


@pytest.mark.asyncio
async def test_schedule_edits_and_resume_keep_room_before_a_future_end_time(http):
    now = datetime.now(UTC)
    await _seed(http.repo, next_run_at=now + timedelta(minutes=30), end_at=now + timedelta(minutes=90))
    url = "/api/scheduled-tasks/task-l"
    # A new cadence whose next run falls after the end time could never run.
    coded(await http.client.patch(url, json={"schedule_spec": {"every_seconds": 7200}}), 422, "end_at_before_first_run")
    assert (await http.client.patch(url, json={"title": "Renamed"})).status_code == 200
    await http.repo.update("task-l", user_id=OWNER, updates={"status": "paused", "next_run_at": now + timedelta(hours=3)})
    coded(await http.client.post(f"{url}/resume"), 422, "end_at_before_first_run")
    assert (await http.repo.get("task-l", user_id=OWNER))["status"] == "paused"
    renewed = await http.client.post(f"{url}/resume", json={"end_at": (now + timedelta(days=1)).isoformat()})
    assert renewed.status_code == 200, renewed.text
    assert renewed.json()["status"] == "enabled"
    # An end time that already passed is the reactivation check's job (409), not a 422.
    await http.repo.update("task-l", user_id=OWNER, updates={"status": "completed", "next_run_at": None, "end_at": now - timedelta(hours=1)})
    assert (await http.client.patch(url, json={"title": "Finished checklist"})).status_code == 200
    detail = coded(await http.client.patch(url, json={"schedule_spec": {"every_seconds": 3600}}), 409, "limits_exhausted")
    assert detail["params"]["limit"] == "end_at"


@pytest.mark.asyncio
async def test_task_responses_report_the_active_run_of_a_recurring_task(http):
    await _seed(http.repo, next_run_at=datetime.now(UTC) + timedelta(hours=1))
    idle = await http.client.get("/api/scheduled-tasks/task-l")
    assert (idle.json()["active_run_status"], idle.json()["automatic_runs_used"]) == (None, 0)
    async with http.sf() as session:
        session.add(occurrence("live", "task-l", seq=1, status="running", accounted=False))
        await session.commit()
    single = (await http.client.get("/api/scheduled-tasks/task-l")).json()
    listed = (await http.client.get("/api/scheduled-tasks")).json()
    assert single["status"] == "enabled"
    assert single["active_run_status"] == "running"
    assert [task["active_run_status"] for task in listed] == ["running"]
    coded(await http.client.patch("/api/scheduled-tasks/task-l", json={"title": "Renamed"}), 409, "task_running")


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["scheduled_task_repo", "scheduled_task_service"])
async def test_missing_scheduler_backend_is_a_coded_503(http, missing):
    kept = getattr(http.app.state, missing)
    setattr(http.app.state, missing, None)
    try:
        response = await (http.client.get("/api/scheduled-tasks") if missing == "scheduled_task_repo" else http.client.post("/api/scheduled-tasks/task-x/trigger"))
        coded(response, 503, "scheduler_unavailable")
    finally:
        setattr(http.app.state, missing, kept)


@pytest.mark.asyncio
async def test_wrong_types_keep_fastapis_list_detail(http):
    response = await http.client.post("/api/scheduled-tasks", json={**_CREATE, "max_runs": "abc"})
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("extra", "code", "params"),
    [
        ({"max_runs": 0}, "invalid_max_runs", None),
        ({"max_runs": -1}, "invalid_max_runs", None),
        ({"max_runs": True}, "invalid_max_runs", None),
        ({"stop_condition": "x" * 501}, "invalid_stop_condition", {"max_chars": 500}),
        ({"end_at": "2020-01-01T09:00:00"}, "end_at_in_past", None),
        ({"goal_objective": "   "}, "invalid_goal", {"max_chars": 4000}),
        ({"context_mode": "reuse_thread", "thread_id": "thread-1", "goal_objective": "report"}, "goal_requires_fresh_thread", None),
        ({"schedule_spec": {"every_seconds": 30}}, "interval_too_short", {"min_seconds": 60}),
        ({"timezone": "Mars/Base"}, "invalid_timezone", None),
        ({"timezone": "Europe"}, "invalid_timezone", None),
        ({"schedule_type": "cron", "schedule_spec": {"cron": "0 9 * * *"}, "timezone": "Europe"}, "invalid_timezone", None),
        ({"schedule_type": "weekly"}, "invalid_schedule_type", None),
    ],
)
async def test_value_rules_are_coded_errors(http, extra, code, params):
    detail = coded(await http.client.post("/api/scheduled-tasks", json={**_CREATE, **extra}), 422, code)
    assert detail.get("params") == params
    assert await http.repo.list_by_user(OWNER) == []


@pytest.mark.asyncio
async def test_patch_with_a_timezone_directory_name_is_invalid_timezone(http):
    created = (await http.client.post("/api/scheduled-tasks", json={**_CREATE, "schedule_type": "cron", "schedule_spec": {"cron": "0 9 * * *"}})).json()
    detail = coded(await http.client.patch(f"/api/scheduled-tasks/{created['id']}", json={"timezone": "Europe"}), 422, "invalid_timezone")
    assert "zoneinfo" not in detail["message"].lower()


@pytest.mark.asyncio
async def test_naive_end_at_is_wall_clock_time_in_the_task_timezone(http):
    response = await http.client.post("/api/scheduled-tasks", json={**_CREATE, "timezone": "Asia/Shanghai", "end_at": "2030-01-01T09:00:00"})
    assert response.status_code == 200, response.text
    assert datetime.fromisoformat(response.json()["end_at"]) == datetime(2030, 1, 1, 1, 0, tzinfo=UTC)
    patched = await http.client.patch(f"/api/scheduled-tasks/{response.json()['id']}", json={"end_at": "2030-06-01T18:30:00"})
    assert datetime.fromisoformat(patched.json()["end_at"]) == datetime(2030, 6, 1, 10, 30, tzinfo=UTC)


@pytest.mark.asyncio
async def test_create_keeps_the_prompt_and_stores_the_stop_condition_apart(http):
    response = await http.client.post(
        "/api/scheduled-tasks",
        json={**_CREATE, "goal_objective": "List every unchecked item with its owner", "max_runs": 30, "end_at": "2031-01-01T00:00:00+00:00", "stop_condition": "every item\n on the checklist   is checked"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["prompt"] == _CREATE["prompt"]
    assert body["stop_condition"] == "every item on the checklist is checked"
    assert (body["goal_objective"], body["max_runs"], body["automatic_runs_used"], body["active_run_status"]) == ("List every unchecked item with its owner", 30, 0, None)
    stored = await http.repo.get(body["id"], user_id=OWNER)
    assert stored["prompt"] == _CREATE["prompt"]
    assert "unmet_streak_after_seq" not in body
    blank = await http.client.post("/api/scheduled-tasks", json={**_CREATE, "stop_condition": "  \n "})
    assert blank.json()["stop_condition"] is None


@pytest.mark.asyncio
async def test_patch_sets_and_clears_goal_limits_and_stop_condition(http):
    created = (await http.client.post("/api/scheduled-tasks", json={**_CREATE, "stop_condition": "all checked"})).json()
    url = f"/api/scheduled-tasks/{created['id']}"
    only_stop = await http.client.patch(url, json={"stop_condition": "the release shipped"})
    assert (only_stop.json()["stop_condition"], only_stop.json()["prompt"]) == ("the release shipped", _CREATE["prompt"])
    for empty in (None, ""):
        await http.client.patch(url, json={"stop_condition": "the release shipped"})
        assert (await http.client.patch(url, json={"stop_condition": empty})).json()["stop_condition"] is None
    end_at = "2031-02-03T04:05:00+00:00"
    updated = (await http.client.patch(url, json={"goal_objective": "Report sent", "max_runs": 9, "end_at": end_at})).json()
    assert (updated["goal_objective"], updated["max_runs"], datetime.fromisoformat(updated["end_at"])) == ("Report sent", 9, datetime.fromisoformat(end_at))
    cleared = (await http.client.patch(url, json={"goal_objective": None, "max_runs": None, "end_at": None})).json()
    assert (cleared["goal_objective"], cleared["max_runs"], cleared["end_at"]) == (None, None, None)
    untouched = (await http.client.patch(url, json={"title": "Renamed", "prompt": None})).json()
    assert (untouched["title"], untouched["prompt"]) == ("Renamed", _CREATE["prompt"])
    await http.client.patch(url, json={"goal_objective": "Report sent"})
    coded(await http.client.patch(url, json={"context_mode": "reuse_thread", "thread_id": "thread-1"}), 422, "goal_requires_fresh_thread")


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal", ["completed", "failed", "cancelled"])
async def test_pause_of_a_finished_task_is_task_finished(http, terminal):
    await _seed(http.repo)
    await http.repo.update("task-l", user_id=OWNER, updates={"status": terminal})
    coded(await http.client.post("/api/scheduled-tasks/task-l/pause"), 409, "task_finished")
    assert (await http.repo.get("task-l", user_id=OWNER))["status"] == terminal


@pytest.mark.asyncio
async def test_create_and_duplicate_need_a_running_scheduler_but_validate_first(http, monkeypatch):
    monkeypatch.setattr(scheduled_tasks, "is_scheduler_running", lambda _request: False)
    coded(await http.client.post("/api/scheduled-tasks", json={**_CREATE, "schedule_spec": {"every_seconds": 1}}), 422, "interval_too_short")
    detail = coded(await http.client.post("/api/scheduled-tasks", json=_CREATE), 409, "scheduler_not_running")
    assert "this Gateway process" in detail["message"]
    # The page's Duplicate is a create with the copied definition.
    duplicate = {**_CREATE, "title": "Checklist (copy)", "goal_objective": "Report sent", "max_runs": 3, "stop_condition": "all checked"}
    coded(await http.client.post("/api/scheduled-tasks", json=duplicate), 409, "scheduler_not_running")
    assert await http.repo.list_by_user(OWNER) == []


def test_is_scheduler_running_reads_the_service_of_this_process():
    from app.gateway.deps import is_scheduler_running

    assert is_scheduler_running(SimpleNamespace()) is False
    assert is_scheduler_running(SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(scheduled_task_service=None)))) is False
    assert is_scheduler_running(SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(scheduled_task_service=SimpleNamespace(is_running=True))))) is True


@pytest.mark.asyncio
async def test_trigger_reports_outcome_thread_and_an_already_waiting_run(http):
    await _seed(http.repo, next_run_at=datetime.now(UTC) + timedelta(hours=1))
    launched = await http.client.post("/api/scheduled-tasks/task-l/trigger")
    assert launched.status_code == 200, launched.text
    body = launched.json()
    assert (body["id"], body["triggered"], body["outcome"], body["existing"]) == ("task-l", True, "launched", False)
    assert body["thread_id"] == http.launches[0]["thread_id"]
    await _seed(http.repo, "task-q", next_run_at=datetime.now(UTC) + timedelta(hours=1))
    async with http.sf() as session:
        session.add(occurrence("waiting", "task-q", seq=1, status="queued", accounted=False, thread_id="thread-waiting"))
        await session.commit()
    waiting = await http.client.post("/api/scheduled-tasks/task-q/trigger")
    assert waiting.status_code == 200, waiting.text
    assert {key: waiting.json()[key] for key in ("outcome", "existing", "thread_id")} == {"outcome": "queued", "existing": True, "thread_id": "thread-waiting"}
    assert len(await http.runs.list_by_task("task-q")) == 1


@pytest.mark.asyncio
async def test_missing_tasks_and_thread_relations_over_http(http):
    coded(await http.client.get("/api/scheduled-tasks/task-missing"), 404, "task_not_found")
    coded(await http.client.post("/api/scheduled-tasks/task-missing/resume"), 404, "task_not_found")
    coded(await http.client.get("/api/scheduled-tasks/task-missing/runs"), 404, "task_not_found")
    await _seed(http.repo, origin_thread_id="thread-origin")
    async with http.sf() as session:
        session.add(occurrence("ran", "task-l", seq=1, thread_id="thread-run"))
        await session.commit()
    origin = (await http.client.get("/api/threads/thread-origin/scheduled-tasks")).json()
    run = (await http.client.get("/api/threads/thread-run/scheduled-tasks")).json()
    assert [(task["id"], task["thread_relation"]) for task in origin] == [("task-l", "origin")]
    assert [(task["id"], task["thread_relation"], task["thread_run"]["run_number"]) for task in run] == [("task-l", "run", 1)]
    assert run[0]["automatic_runs_used"] == 1
