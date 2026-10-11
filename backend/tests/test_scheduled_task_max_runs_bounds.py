"""Schedule safety caps must fit the integer columns of both SQL backends."""

from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.gateway.authz import AuthContext
from app.gateway.routers import scheduled_tasks
from deerflow.config.scheduler_config import SchedulerConfig
from deerflow.persistence.scheduled_task_runs.model import ScheduledTaskRunRow
from deerflow.persistence.scheduled_tasks import ScheduledTaskRepository
from deerflow.persistence.scheduled_tasks.model import ScheduledTaskRow

OWNER = "bounds-user"
PAYLOAD = {"title": "Report", "prompt": "Write a report", "schedule_type": "interval", "schedule_spec": {"every_seconds": 3600}, "timezone": "UTC"}


@pytest_asyncio.fixture
async def http(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'bounds.db'}")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(ScheduledTaskRow.__table__.create)
            await connection.run_sync(ScheduledTaskRunRow.__table__.create)
        repo = ScheduledTaskRepository(async_sessionmaker(engine, expire_on_commit=False))
        app = FastAPI()
        app.include_router(scheduled_tasks.router)

        @app.middleware("http")
        async def authenticate(request, call_next):
            request.state.auth = AuthContext(user=SimpleNamespace(id=OWNER), permissions=["threads:write", "runs:create"])
            return await call_next(request)

        async def user_from_request(request):
            return request.state.auth.user

        monkeypatch.setattr(scheduled_tasks, "get_optional_user_from_request", user_from_request)
        monkeypatch.setattr(scheduled_tasks, "get_config", lambda: SimpleNamespace(scheduler=SchedulerConfig(enabled=True)))
        monkeypatch.setattr(scheduled_tasks, "get_scheduled_task_repo", lambda request: repo)
        monkeypatch.setattr(scheduled_tasks, "get_thread_store", lambda request: None)
        monkeypatch.setattr(scheduled_tasks, "is_scheduler_running", lambda request: True)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test") as client:
            yield SimpleNamespace(client=client, repo=repo)
    finally:
        await engine.dispose()


async def _change_limit(http, operation, max_runs):
    if operation == "create":
        return await http.client.post("/api/scheduled-tasks", json={**PAYLOAD, "max_runs": max_runs}), None
    created = await http.client.post("/api/scheduled-tasks", json={**PAYLOAD, "max_runs": 3})
    assert created.status_code == 200, created.text
    task_id = created.json()["id"]
    if operation == "resume":
        await http.repo.update(task_id, user_id=OWNER, updates={"status": "paused"})
    before = await http.repo.get(task_id, user_id=OWNER)
    url = f"/api/scheduled-tasks/{task_id}"
    if operation == "update":
        response = await http.client.patch(url, json={"max_runs": max_runs})
    else:
        response = await http.client.post(f"{url}/resume", json={"max_runs": max_runs})
    return response, before


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["create", "update", "resume"])
@pytest.mark.parametrize("max_runs", [2147483648, 9223372036854775808])
async def test_http_rejects_max_runs_outside_storage_range_without_mutation(http, operation, max_runs):
    response, before = await _change_limit(http, operation, max_runs)

    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "invalid_max_runs"
    if before is None:
        assert await http.repo.list_by_user(OWNER) == []
    else:
        assert await http.repo.get(before["id"], user_id=OWNER) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["create", "update", "resume"])
async def test_http_accepts_max_runs_at_cross_backend_storage_boundary(http, operation):
    response, _ = await _change_limit(http, operation, 2147483647)

    assert response.status_code == 200, response.text
    assert response.json()["max_runs"] == 2147483647
    stored = await http.repo.get(response.json()["id"], user_id=OWNER)
    assert stored["max_runs"] == 2147483647
    assert stored["status"] == "enabled"


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["create", "update"])
@pytest.mark.parametrize("max_runs", [2147483648, 9223372036854775808])
async def test_repository_rejects_max_runs_outside_storage_range_before_binding(http, operation, max_runs):
    created = await http.client.post("/api/scheduled-tasks", json={**PAYLOAD, "max_runs": 3})
    assert created.status_code == 200, created.text
    task_id = created.json()["id"]
    before = await http.repo.get(task_id, user_id=OWNER)

    with pytest.raises(ValueError, match="max_runs"):
        if operation == "create":
            await http.repo.create(task_id="invalid-limit", user_id=OWNER, thread_id=None, context_mode="fresh_thread_per_run", assistant_id="lead_agent", next_run_at=None, max_runs=max_runs, **PAYLOAD)
        else:
            await http.repo.update(task_id, user_id=OWNER, updates={"max_runs": max_runs})

    assert await http.repo.get("invalid-limit", user_id=OWNER) is None
    assert await http.repo.get(task_id, user_id=OWNER) == before
