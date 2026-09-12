from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.gateway.authz import AuthContext
from app.gateway.routers import scheduled_tasks
from deerflow.persistence.scheduled_task_runs import ScheduledTaskRunRepository
from deerflow.persistence.scheduled_task_runs.model import ScheduledTaskRunRow
from deerflow.persistence.scheduled_tasks import ScheduledTaskRepository
from deerflow.persistence.scheduled_tasks.model import ScheduledTaskRow

URL = "/api/scheduled-tasks/task-1/runs"
NOW = datetime(2026, 9, 12, tzinfo=UTC)


def occurrence(record_id, status, *, task_id="task-1", created_at=NOW):
    return ScheduledTaskRunRow(id=record_id, task_id=task_id, thread_id="thread-1", scheduled_for=created_at, trigger="scheduled", status=status, created_at=created_at)


@pytest_asyncio.fixture
async def history(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(ScheduledTaskRow.__table__.create)
            await connection.run_sync(ScheduledTaskRunRow.__table__.create)
        sf = async_sessionmaker(engine, expire_on_commit=False)
        async with sf() as session:
            for task_id, owner in [("task-1", "user-1"), ("task-other", "user-1"), ("task-foreign", "user-2"), ("task-empty", "user-1")]:
                session.add(ScheduledTaskRow(id=task_id, user_id=owner, title="History example", prompt="Example", schedule_type="cron", schedule_spec={"cron": "0 9 * * *"}, timezone="UTC"))
            session.add_all([occurrence(f"success-{i:02}", "success", created_at=NOW + timedelta(hours=1, seconds=i)) for i in range(60)])
            session.add_all([occurrence(f"failed-{letter}", "failed") for letter in "abc"])
            session.add_all(
                [
                    occurrence("skipped-old", "skipped", created_at=NOW - timedelta(days=1)),
                    occurrence("interrupted-old", "interrupted", created_at=NOW - timedelta(days=2)),
                    occurrence("other-failure", "failed", task_id="task-other", created_at=NOW + timedelta(days=1)),
                    occurrence("foreign-failure", "failed", task_id="task-foreign", created_at=NOW + timedelta(days=1)),
                ]
            )
            await session.commit()
        task_repo = ScheduledTaskRepository(sf)
        run_repo = ScheduledTaskRunRepository(sf)
        spy = AsyncMock(wraps=run_repo.list_by_task)
        monkeypatch.setattr(run_repo, "list_by_task", spy)
        monkeypatch.setattr(scheduled_tasks, "get_scheduled_task_repo", lambda request: task_repo)
        monkeypatch.setattr(scheduled_tasks, "get_scheduled_task_run_repo", lambda request: run_repo)

        async def user_from_request(request):
            return request.state.auth.user

        monkeypatch.setattr(scheduled_tasks, "get_optional_user_from_request", user_from_request)
        app = FastAPI()
        app.include_router(scheduled_tasks.router)

        @app.middleware("http")
        async def authenticate(request, call_next):
            user = None if request.headers.get("x-test-auth") == "anonymous" else SimpleNamespace(id="user-1")
            permissions = [] if request.headers.get("x-test-auth") == "denied" else ["threads:read"]
            request.state.auth = AuthContext(user=user, permissions=permissions)
            return await call_next(request)

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            yield SimpleNamespace(client=client, sf=sf, repo=run_repo, spy=spy)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_filter_finds_older_failures_and_paginates_matching_rows(history):
    response = await history.client.get(URL, params={"status": "failed", "limit": 2})
    assert response.status_code == 200
    assert [row["id"] for row in response.json()] == ["failed-c", "failed-b"]
    response = await history.client.get(URL, params={"status": "failed", "limit": 2, "offset": 2})
    assert [row["id"] for row in response.json()] == ["failed-a"]
    response = await history.client.get(URL, params={"status": "failed", "offset": 3})
    assert response.json() == []


@pytest.mark.asyncio
async def test_repository_applies_status_before_limit_and_offset(history):
    rows = await history.repo.list_by_task("task-1", status="failed", limit=1, offset=1)
    assert [row["id"] for row in rows] == ["failed-b"]


@pytest.mark.asyncio
async def test_omitted_status_preserves_mixed_history_and_pagination(history):
    response = await history.client.get(URL, params={"limit": 200})
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 65
    assert [row["id"] for row in rows[:2]] == ["success-59", "success-58"]
    assert {row["status"] for row in rows} == {"success", "failed", "skipped", "interrupted"}
    assert all(row["task_id"] == "task-1" for row in rows)
    response = await history.client.get(URL, params={"limit": 2, "offset": 60})
    assert [row["id"] for row in response.json()] == ["failed-c", "failed-b"]
    assert len((await history.client.get(URL)).json()) == 50


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["queued", "launching", "running", "success", "failed", "skipped", "interrupted"])
async def test_each_occurrence_status_is_supported(history, status):
    async with history.sf() as session:
        session.add(occurrence("new-occurrence", status, created_at=NOW + timedelta(days=2)))
        await session.commit()
    response = await history.client.get(URL, params={"status": status, "limit": 200})
    assert response.status_code == 200
    rows = response.json()
    assert rows[0]["id"] == "new-occurrence"
    assert all(row["status"] == status and row["task_id"] == "task-1" for row in rows)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["", "completed", "error", "FAILED", "failed,success"])
async def test_unknown_status_is_rejected_before_reading_history(history, status):
    response = await history.client.get(URL, params={"status": status})
    assert response.status_code == 422
    history.spy.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("task_id", ["task-foreign", "missing-task"])
async def test_filter_cannot_read_another_owner_or_missing_task(history, task_id):
    response = await history.client.get(f"/api/scheduled-tasks/{task_id}/runs", params={"status": "failed"})
    assert response.status_code == 404
    history.spy.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(("auth", "status"), [("anonymous", 401), ("denied", 403)])
async def test_filter_keeps_authentication_and_read_permission_checks(history, auth, status):
    response = await history.client.get(URL, params={"status": "failed"}, headers={"x-test-auth": auth})
    assert response.status_code == status
    history.spy.assert_not_awaited()


@pytest.mark.asyncio
async def test_empty_or_unmatched_history_returns_empty_array(history):
    assert (await history.client.get("/api/scheduled-tasks/task-empty/runs", params={"status": "failed"})).json() == []
    assert (await history.client.get(URL, params={"status": "running"})).json() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 201}, {"offset": -1}])
async def test_filter_preserves_pagination_bounds(history, params):
    response = await history.client.get(URL, params={"status": "failed", **params})
    assert response.status_code == 422
    history.spy.assert_not_awaited()
