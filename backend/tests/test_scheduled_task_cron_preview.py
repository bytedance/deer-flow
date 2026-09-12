from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from app.gateway.authz import AuthContext
from app.gateway.routers import scheduled_tasks
from deerflow.scheduler.schedules import next_run_at

URL = "/api/scheduled-tasks/preview-cron"
PAYLOAD = {"cron": "0 9 * * 1-5", "timezone": "Asia/Shanghai", "count": 3, "start_at": "2026-09-12T00:00:00Z"}


@pytest_asyncio.fixture
async def client(monkeypatch):
    app = FastAPI()
    app.include_router(scheduled_tasks.router)

    @app.middleware("http")
    async def authenticate(request, call_next):
        user = None if request.headers.get("x-test-auth") == "anonymous" else SimpleNamespace(id="preview-user")
        permissions = [] if request.headers.get("x-test-auth") == "denied" else ["threads:read"]
        request.state.auth = AuthContext(user=user, permissions=permissions)
        return await call_next(request)

    async def user_from_request(request):
        return request.state.auth.user

    monkeypatch.setattr(scheduled_tasks, "get_optional_user_from_request", user_from_request)
    # A preview must remain usable without a task database, thread store or worker.
    for name in ("get_scheduled_task_repo", "get_scheduled_task_run_repo", "get_thread_store", "get_scheduled_task_service", "get_config"):
        monkeypatch.setattr(scheduled_tasks, name, Mock(side_effect=AssertionError(f"Preview accessed {name}")))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as session:
        yield session


@pytest.mark.asyncio
async def test_preview_returns_exact_utc_and_local_times_without_persistence(client):
    response = await client.post(URL, json={**PAYLOAD, "cron": "  0\t9  * * 1-5  "})
    assert response.status_code == 200, response.text
    assert response.json() == {
        "cron": "0 9 * * 1-5",
        "timezone": "Asia/Shanghai",
        "start_at": "2026-09-12T00:00:00Z",
        "occurrences": [
            {"run_at": "2026-09-14T01:00:00Z", "local_time": "2026-09-14T09:00:00+08:00"},
            {"run_at": "2026-09-15T01:00:00Z", "local_time": "2026-09-15T09:00:00+08:00"},
            {"run_at": "2026-09-16T01:00:00Z", "local_time": "2026-09-16T09:00:00+08:00"},
        ],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(("auth", "status"), [("anonymous", 401), ("denied", 403)])
async def test_preview_enforces_authentication_and_read_permission(client, auth, status):
    response = await client.post(URL, json=PAYLOAD, headers={"x-test-auth": auth})
    assert response.status_code == status


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "override",
    [
        {"count": 0},
        {"count": 11},
        {"count": True},
        {"count": "3"},
        {"cron": ""},
        {"cron": " " * 257},
        {"cron": "0 0 * * * *"},
        {"cron": "61 * * * *"},
        {"cron": "0 0 31 2 *"},
        {"timezone": "Not/A_Zone"},
        {"timezone": "../UTC"},
        {"timezone": "/UTC"},
        {"timezone": ""},
        {"timezone": "x" * 129},
        {"start_at": "2026-09-12T00:00:00"},
        {"start_at": "invalid"},
        {"start_at": "9999-12-31T23:59:59Z"},
    ],
)
async def test_preview_rejects_invalid_or_unfulfillable_inputs(client, override):
    response = await client.post(URL, json={**PAYLOAD, **override})
    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_preview_default_reference_is_captured_once_and_count_defaults_to_five(client, monkeypatch):
    class FixedDatetime(datetime):
        calls = 0

        @classmethod
        def now(cls, tz=None):
            cls.calls += 1
            return datetime(2026, 9, 12, 0, 0, tzinfo=UTC)

    monkeypatch.setattr(scheduled_tasks, "datetime", FixedDatetime)
    response = await client.post(URL, json={"cron": "0 * * * *", "timezone": "UTC"})
    assert response.status_code == 200, response.text
    data = response.json()
    assert FixedDatetime.calls == 1
    assert data["start_at"] == "2026-09-12T00:00:00Z"
    assert [row["run_at"] for row in data["occurrences"]] == [f"2026-09-12T0{hour}:00:00Z" for hour in range(1, 6)]


@pytest.mark.asyncio
async def test_preview_normalizes_offset_reference_and_excludes_reference_instant(client):
    response = await client.post(URL, json={**PAYLOAD, "cron": "0 * * * *", "count": 1, "start_at": "2026-09-12T08:00:00+08:00"})
    assert response.status_code == 200, response.text
    assert response.json()["start_at"] == "2026-09-12T00:00:00Z"
    assert response.json()["occurrences"][0]["run_at"] == "2026-09-12T01:00:00Z"


@pytest.mark.asyncio
@pytest.mark.parametrize("start_at", ["2026-03-07T12:00:00Z", "2026-10-31T12:00:00Z"])
async def test_preview_preserves_scheduler_dst_semantics(client, start_at):
    cron = "30 2 * * *"
    zone = "America/New_York"
    cursor = datetime.fromisoformat(start_at)
    expected = []
    for _ in range(10):
        cursor = next_run_at("cron", {"cron": cron}, zone, now=cursor)
        expected.append(cursor)
    response = await client.post(URL, json={"cron": cron, "timezone": zone, "count": 10, "start_at": start_at})
    assert response.status_code == 200, response.text
    rows = response.json()["occurrences"]
    assert [datetime.fromisoformat(row["run_at"]) for row in rows] == expected
    assert [row["local_time"] for row in rows] == [instant.astimezone(ZoneInfo(zone)).isoformat() for instant in expected]


@pytest.mark.asyncio
async def test_preview_calculates_off_the_request_thread(client, monkeypatch):
    import threading

    request_thread = threading.get_ident()
    observed = []
    original = scheduled_tasks.compute_next_run_at

    def calculate(*args, **kwargs):
        observed.append(threading.get_ident())
        return original(*args, **kwargs)

    monkeypatch.setattr(scheduled_tasks, "compute_next_run_at", calculate)
    response = await client.post(URL, json=PAYLOAD)
    assert response.status_code == 200, response.text
    assert len(observed) == 3
    assert all(ident != request_thread for ident in observed)


@pytest.mark.asyncio
async def test_preview_first_occurrence_matches_task_creation_at_same_clock(client, monkeypatch):
    from unittest.mock import AsyncMock

    from _router_auth_helpers import call_unwrapped

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 9, 12, 0, 0, tzinfo=UTC)

    monkeypatch.setattr(scheduled_tasks, "datetime", FixedDatetime)
    response = await client.post(URL, json={"cron": PAYLOAD["cron"], "timezone": PAYLOAD["timezone"], "count": 1})
    assert response.status_code == 200, response.text
    # Only the separate creation below is allowed to acquire persistence dependencies.
    repo = SimpleNamespace(create=AsyncMock())
    monkeypatch.setattr(scheduled_tasks, "get_scheduled_task_repo", lambda request: repo)
    monkeypatch.setattr(scheduled_tasks, "get_thread_store", lambda request: None)
    monkeypatch.setattr(scheduled_tasks, "get_config", lambda: SimpleNamespace())
    request = SimpleNamespace(state=SimpleNamespace(auth=AuthContext(user=SimpleNamespace(id="preview-user"))))
    body = scheduled_tasks.ScheduledTaskCreateRequest(title="Example", prompt="Example", schedule_type="cron", schedule_spec={"cron": PAYLOAD["cron"]}, timezone=PAYLOAD["timezone"])
    await call_unwrapped(scheduled_tasks.create_scheduled_task, request=request, body=body)
    assert repo.create.await_args.kwargs["next_run_at"] == datetime.fromisoformat(response.json()["occurrences"][0]["run_at"])
