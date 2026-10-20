from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.gateway.auth_disabled import AUTH_SOURCE_SESSION
from app.gateway.authz import AuthContext
from app.gateway.routers import mcp_tasks
from deerflow.mcp.tasks import POLLABLE_TASK_STATUSES, TaskStatus
from deerflow.persistence.mcp_tasks import McpTaskRepository
from deerflow.persistence.mcp_tasks.model import McpTaskRow
from deerflow.persistence.thread_meta.model import ThreadMetaRow
from deerflow.persistence.thread_meta.sql import ThreadMetaRepository

URL = "/api/threads/thread-1/mcp-tasks"
NOW = datetime(2026, 10, 1, tzinfo=UTC)


def _row(task_id, status, *, offset=0, user_id="user-1", thread_id="thread-1", incarnation="current"):
    return McpTaskRow(
        id=task_id,
        user_id=user_id,
        thread_id=thread_id,
        thread_incarnation=incarnation,
        server_name="test",
        driver_name="test",
        remote_task_id=f"remote-{task_id}",
        task_name="Report generation",
        status=status,
        created_at=NOW + timedelta(seconds=offset),
    )


@pytest_asyncio.fixture
async def history(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(ThreadMetaRow.__table__.create)
            await connection.run_sync(McpTaskRow.__table__.create)
        sf = async_sessionmaker(engine, expire_on_commit=False)
        async with sf() as session:
            session.add_all(
                ThreadMetaRow(thread_id=thread_id, user_id=owner, incarnation="current", metadata_json={})
                for thread_id, owner in [("thread-1", "user-1"), ("thread-other", "user-1"), ("thread-foreign", "user-2"), ("thread-empty", "user-1")]
            )
            session.add_all(_row(f"recent-{i:02}", "completed", offset=i + 1) for i in range(60))
            session.add_all(_row(f"state-{status.value}", status.value) for status in TaskStatus)
            session.add_all(_row(f"failed-{letter}", "failed") for letter in "abc")
            session.add_all(
                [
                    _row("other-owner", "failed", user_id="user-2"),
                    _row("other-thread", "failed", thread_id="thread-other"),
                    _row("old-generation", "failed", incarnation="old"),
                    _row("foreign-thread", "failed", user_id="user-2", thread_id="thread-foreign"),
                ]
            )
            await session.commit()
        repo = McpTaskRepository(sf)
        spy = AsyncMock(wraps=repo.list_by_thread)
        monkeypatch.setattr(repo, "list_by_thread", spy)
        app = FastAPI()
        app.state.mcp_task_repo = repo
        app.state.mcp_task_service = SimpleNamespace(tracking_degraded_after_errors=3)
        app.state.thread_store = ThreadMetaRepository(sf)
        app.include_router(mcp_tasks.router)

        @app.middleware("http")
        async def authenticate(request, call_next):
            user = None if request.headers.get("x-test-auth") == "anonymous" else SimpleNamespace(id="user-1", system_role="user")
            permissions = [] if request.headers.get("x-test-auth") == "denied" else ["threads:read"]
            request.state.user = user
            request.state.auth_source = AUTH_SOURCE_SESSION
            request.state.auth = AuthContext(user=user, permissions=permissions)
            return await call_next(request)

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            yield SimpleNamespace(client=client, sf=sf, spy=spy)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["failed", "input_required"])
async def test_status_filter_finds_older_matches_before_limit(history, status):
    response = await history.client.get(URL, params={"status": status, "limit": 2})
    assert response.status_code == 200
    expected = ["state-failed", "failed-c"] if status == "failed" else ["state-input_required"]
    assert [row["task_id"] for row in response.json()] == expected
    assert all(row["status"] == status and "remote_task_id" not in row for row in response.json())


@pytest.mark.asyncio
@pytest.mark.parametrize("active_only", [False, True])
@pytest.mark.parametrize("status", list(TaskStatus))
async def test_status_intersects_active_only(history, status, active_only):
    response = await history.client.get(URL, params={"status": status.value, "active_only": str(active_only).lower(), "limit": 100})
    assert response.status_code == 200
    rows = response.json()
    if active_only and status not in POLLABLE_TASK_STATUSES:
        assert rows == []
    else:
        assert rows
        assert all(row["status"] == status.value for row in rows)


@pytest.mark.asyncio
async def test_omitted_filters_preserve_defaults_and_active_only(history):
    response = await history.client.get(URL)
    assert response.status_code == 200
    assert [row["task_id"] for row in response.json()] == [f"recent-{i:02}" for i in range(59, 9, -1)]
    response = await history.client.get(URL, params={"active_only": "true"})
    assert response.status_code == 200
    assert {row["status"] for row in response.json()} == {status.value for status in POLLABLE_TASK_STATUSES}


@pytest.mark.asyncio
@pytest.mark.parametrize("incarnation", ["current", None])
async def test_status_filter_preserves_owner_thread_and_incarnation_scope(history, incarnation):
    async with history.sf() as session:
        thread = await session.get(ThreadMetaRow, "thread-1")
        thread.incarnation = incarnation
        session.add(_row("visible", "failed", incarnation=incarnation, offset=100))
        await session.commit()
    response = await history.client.get(URL, params={"status": "failed"})
    assert response.status_code == 200
    expected = ["visible", "state-failed", "failed-c", "failed-b", "failed-a"] if incarnation else ["visible"]
    assert [row["task_id"] for row in response.json()] == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["", "running", "unknown", "FAILED", "failed,completed"])
async def test_invalid_status_rejected_before_repository_read(history, status):
    response = await history.client.get(URL, params={"status": status})
    assert response.status_code == 422
    history.spy.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"active_only": "unknown"}])
async def test_invalid_query_parameters_rejected(history, params):
    response = await history.client.get(URL, params={"status": "failed", **params})
    assert response.status_code == 422
    history.spy.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(("auth", "status"), [("anonymous", 401), ("denied", 403)])
async def test_status_filter_keeps_authentication_and_read_permissions(history, auth, status):
    response = await history.client.get(URL, params={"status": "failed"}, headers={"x-test-auth": auth})
    assert response.status_code == status
    history.spy.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("thread_id", ["thread-foreign", "missing-thread"])
async def test_status_filter_rejects_foreign_or_missing_thread(history, thread_id):
    response = await history.client.get(f"/api/threads/{thread_id}/mcp-tasks", params={"status": "failed"})
    assert response.status_code == 404
    history.spy.assert_not_awaited()


@pytest.mark.asyncio
async def test_empty_history_returns_empty_array(history):
    response = await history.client.get("/api/threads/thread-empty/mcp-tasks", params={"status": "failed"})
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_openapi_exposes_existing_task_statuses(history):
    response = await history.client.get("/openapi.json")
    assert response.status_code == 200
    assert set(response.json()["components"]["schemas"]["TaskStatus"]["enum"]) == {status.value for status in TaskStatus}
