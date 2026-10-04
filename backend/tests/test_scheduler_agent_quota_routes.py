"""HTTP quota conflicts use real SQLite task admission, with stubbed auth."""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest
import pytest_asyncio
from _router_auth_helpers import make_authed_test_app
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.gateway.auth.models import User
from app.gateway.auth_disabled import AUTH_SOURCE_SESSION
from app.gateway.routers import scheduled_tasks
from deerflow.persistence.base import Base
from deerflow.persistence.scheduled_task_runs.model import ScheduledTaskRunRow
from deerflow.persistence.scheduled_tasks import ScheduledTaskRepository
from deerflow.persistence.scheduled_tasks.model import ScheduledTaskRow


@pytest_asyncio.fixture
async def quota_routes(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'quota-routes.db'}")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(lambda sync: Base.metadata.create_all(sync, tables=[ScheduledTaskRow.__table__, ScheduledTaskRunRow.__table__]))
        repo = ScheduledTaskRepository(async_sessionmaker(engine, expire_on_commit=False))
        user = User(id=UUID("12345678-1234-1234-1234-123456789abc"), email="quota-test@example.com", password_hash="unused", system_role="user")
        app = make_authed_test_app(user_factory=lambda: user, bind_current_user=True)

        @app.middleware("http")
        async def mark_session_source(request, call_next):
            request.state.auth_source = AUTH_SOURCE_SESSION
            return await call_next(request)

        app.state.scheduled_task_repo = repo
        app.include_router(scheduled_tasks.router)
        monkeypatch.setattr(scheduled_tasks, "get_config", lambda: SimpleNamespace(scheduler=SimpleNamespace(min_once_delay_seconds=60)))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://quota.test") as client:
            yield client, repo, str(user.id)
    finally:
        await engine.dispose()


async def create_task(repo, owner, task_id, *, tool_created=True):
    return await repo.create(
        task_id=task_id,
        user_id=owner,
        thread_id=None,
        context_mode="fresh_thread_per_run",
        assistant_id=None,
        title="Report",
        prompt="Prepare report",
        schedule_type="interval",
        schedule_spec={"every_seconds": 3600},
        timezone="UTC",
        next_run_at=datetime.now(UTC),
        origin_thread_id="origin" if tool_created else None,
    )


async def reactivate(client, task_id, action):
    if action == "resume":
        return await client.post(f"/api/scheduled-tasks/{task_id}/resume")
    return await client.patch(f"/api/scheduled-tasks/{task_id}", json={"schedule_spec": {"every_seconds": 7200}})


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["resume", "patch"])
async def test_terminal_tool_task_quota_is_http_409_and_keeps_task_unchanged(quota_routes, action):
    client, repo, owner = quota_routes
    await create_task(repo, owner, "old-terminal")
    await repo.update("old-terminal", user_id=owner, updates={"status": "completed"})
    for index in range(20):
        await create_task(repo, owner, f"active-{index}")
    before = await repo.get("old-terminal", user_id=owner)
    response = await reactivate(client, "old-terminal", action)
    assert response.status_code == 409
    assert "20 live conversation-created" in response.json()["detail"]
    assert await repo.get("old-terminal", user_id=owner) == before


@pytest.mark.asyncio
async def test_paused_tool_task_resumes_successfully_at_full_quota(quota_routes):
    client, repo, owner = quota_routes
    for index in range(20):
        await create_task(repo, owner, f"active-{index}")
    await repo.update("active-0", user_id=owner, updates={"status": "paused"})
    response = await reactivate(client, "active-0", "resume")
    assert response.status_code == 200
    assert response.json()["status"] == "enabled"


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["resume", "patch"])
async def test_legacy_task_reactivation_ignores_conversation_quota(quota_routes, action):
    client, repo, owner = quota_routes
    for index in range(20):
        await create_task(repo, owner, f"active-{index}")
    await create_task(repo, owner, "legacy", tool_created=False)
    await repo.update("legacy", user_id=owner, updates={"status": "completed"})
    response = await reactivate(client, "legacy", action)
    assert response.status_code == 200
    assert response.json()["status"] == "enabled"


@pytest.mark.asyncio
async def test_goal_schedule_patch_to_reused_thread_is_422_and_preserves_row(quota_routes):
    client, repo, owner = quota_routes
    await create_task(repo, owner, "goal-task")
    await repo.update("goal-task", user_id=owner, updates={"goal_objective": "deliver report"}, require_mutable=True)
    before = await repo.get("goal-task", user_id=owner)
    response = await client.patch("/api/scheduled-tasks/goal-task", json={"context_mode": "reuse_thread", "thread_id": "reused-thread"})
    assert response.status_code == 422
    assert "fresh_thread_per_run" in response.json()["detail"]
    assert await repo.get("goal-task", user_id=owner) == before


@pytest.mark.asyncio
async def test_schedule_without_goal_can_patch_to_reused_thread(quota_routes):
    client, repo, owner = quota_routes
    await create_task(repo, owner, "ordinary-task")
    response = await client.patch("/api/scheduled-tasks/ordinary-task", json={"context_mode": "reuse_thread", "thread_id": "reused-thread"})
    assert response.status_code == 200
    assert response.json()["context_mode"] == "reuse_thread"


@pytest.mark.asyncio
@pytest.mark.parametrize("live_count", [19, 20])
async def test_pause_route_cannot_reactivate_terminal_task_beyond_quota(quota_routes, live_count):
    client, repo, owner = quota_routes
    await create_task(repo, owner, "terminal")
    await repo.update("terminal", user_id=owner, updates={"status": "completed"})
    for index in range(live_count):
        await create_task(repo, owner, f"live-{index}")
    before = await repo.get("terminal", user_id=owner)
    response = await client.post("/api/scheduled-tasks/terminal/pause")
    assert response.status_code == (409 if live_count == 20 else 200)
    if live_count == 20:
        assert "20 live" in response.json()["detail"]
        assert await repo.get("terminal", user_id=owner) == before
    else:
        assert response.json()["status"] == "paused"
        assert (await client.post("/api/scheduled-tasks/terminal/pause")).status_code == 200
    await create_task(repo, owner, "legacy", tool_created=False)
    await repo.update("legacy", user_id=owner, updates={"status": "completed"})
    assert (await client.post("/api/scheduled-tasks/legacy/pause")).status_code == 200
