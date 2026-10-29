"""Owner-selected Feishu groups round-trip through the scheduled-task API."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import httpx
import pytest
import pytest_asyncio
from _router_auth_helpers import make_authed_test_app
from _scheduled_rows import occurrence

from app.gateway.auth.models import User
from app.gateway.auth_disabled import AUTH_SOURCE_SESSION
from app.gateway.routers import scheduled_tasks
from deerflow.config.channel_connections_config import ChannelConnectionsConfig
from deerflow.config.database_config import DatabaseConfig
from deerflow.persistence.channel_connections import ChannelConnectionRepository
from deerflow.persistence.engine import close_engine, get_session_factory, init_engine_from_config
from deerflow.persistence.scheduled_tasks import ScheduledTaskRepository
from deerflow.persistence.scheduled_tasks.model import ScheduledTaskRow

OWNER = "00000000-0000-0000-0000-000000000111"
OTHER = "00000000-0000-0000-0000-000000000222"
FIELD = "notification_group_connection_id"


@pytest_asyncio.fixture
async def env(tmp_path, monkeypatch):
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    sf = get_session_factory()
    tasks, connections = ScheduledTaskRepository(sf), ChannelConnectionRepository(sf)
    user = User(email="groups@example.com", password_hash="test", system_role="user", id=UUID(OWNER))
    app = make_authed_test_app(user_factory=lambda: user, bind_current_user=True)

    @app.middleware("http")
    async def session_source(request, call_next):
        request.state.auth_source = AUTH_SOURCE_SESSION
        return await call_next(request)

    app.state.scheduled_task_repo = tasks
    app.state.channel_connection_repo = connections
    app.state.channel_connections_config = ChannelConnectionsConfig(enabled=True)
    app.include_router(scheduled_tasks.router)
    monkeypatch.setattr(scheduled_tasks, "is_scheduler_running", lambda _request: True)
    monkeypatch.setattr(scheduled_tasks, "get_config", lambda: SimpleNamespace(scheduler=SimpleNamespace(min_once_delay_seconds=60)))
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://groups.test") as client:
            yield SimpleNamespace(client=client, app=app, tasks=tasks, connections=connections, sf=sf)
    finally:
        await close_engine()


def _body(**extra):
    return {"title": "Weekly report", "prompt": "Prepare the report", "schedule_type": "cron", "schedule_spec": {"cron": "0 9 * * 1"}, "timezone": "UTC", **extra}


async def _bind(env, **extra):
    fields = {"owner_user_id": OWNER, "provider": "feishu", "external_account_id": "ou_member", "workspace_id": "oc_group", "metadata": {"chat_type": "group", "chat_id": "oc_group"}, **extra}
    return await env.connections.upsert_connection(**fields)


async def _create(env, **extra):
    response = await env.client.post("/api/scheduled-tasks", json=_body(**extra))
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.asyncio
@pytest.mark.parametrize("selected", [False, True])
async def test_group_destination_round_trips_create_get_and_list(env, selected):
    group = await _bind(env)
    target = group["id"] if selected else None
    task = await _create(env, **({FIELD: target} if selected else {}))
    assert task[FIELD] == target
    assert (await env.client.get(f"/api/scheduled-tasks/{task['id']}")).json()[FIELD] == target
    assert (await env.client.get("/api/scheduled-tasks")).json()[0][FIELD] == target
    assert (await env.tasks.get(task["id"], user_id=OWNER))[FIELD] == target


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["post", "patch"])
@pytest.mark.parametrize(
    "overrides",
    [
        {"owner_user_id": OTHER},
        {"provider": "wecom"},
        {"status": "revoked"},
        {"metadata": {"chat_type": "p2p", "chat_id": "oc_group"}},
        {"metadata": {"chat_id": "oc_group"}},
        {"metadata": {"chat_type": "group", "chat_id": "oc_different"}},
        {"workspace_id": "", "metadata": {"chat_type": "group", "chat_id": ""}},
    ],
)
async def test_group_destination_rejects_unowned_or_unverified_bindings(env, method, overrides):
    group = await _bind(env, **overrides)
    existing = await _create(env) if method == "patch" else None
    url = f"/api/scheduled-tasks/{existing['id']}" if existing else "/api/scheduled-tasks"
    payload = {FIELD: group["id"]} if existing else _body(**{FIELD: group["id"]})
    response = await env.client.request(method, url, json=payload)
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "invalid_notification_group"
    if existing:
        assert (await env.tasks.get(existing["id"], user_id=OWNER))[FIELD] is None
    else:
        assert await env.tasks.list_by_user(OWNER) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("target", ["unknown", "", "  ", "x" * 65])
async def test_invalid_group_identifier_is_coded_and_does_not_create_task(env, target):
    response = await env.client.post("/api/scheduled-tasks", json=_body(**{FIELD: target}))
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "invalid_notification_group"
    assert await env.tasks.list_by_user(OWNER) == []


@pytest.mark.asyncio
async def test_title_patch_keeps_a_revoked_selection_and_null_clears_without_lookup(env, monkeypatch):
    group = await _bind(env)
    task = await _create(env, **{FIELD: group["id"]})
    assert await env.connections.disconnect_connection(connection_id=group["id"], owner_user_id=OWNER)
    renamed = await env.client.patch(f"/api/scheduled-tasks/{task['id']}", json={"title": "Renamed"})
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()[FIELD] == group["id"]
    lookup = AsyncMock(side_effect=OSError("lookup should not run"))
    monkeypatch.setattr(env.connections, "list_connections", lookup)
    cleared = await env.client.patch(f"/api/scheduled-tasks/{task['id']}", json={FIELD: None})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()[FIELD] is None
    lookup.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["post", "patch"])
async def test_group_lookup_failure_is_503_not_invalid_target(env, monkeypatch, method):
    existing = await _create(env) if method == "patch" else None
    monkeypatch.setattr(env.connections, "list_connections", AsyncMock(side_effect=OSError("private connection failure")))
    url = f"/api/scheduled-tasks/{existing['id']}" if existing else "/api/scheduled-tasks"
    payload = {FIELD: "conn-group"} if existing else _body(**{FIELD: "conn-group"})
    response = await env.client.request(method, url, json=payload)
    assert response.status_code == 503, response.text
    assert response.json()["detail"]["code"] == "scheduler_unavailable"
    assert "private connection failure" not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["completed", "paused", "enabled"])
async def test_group_only_edit_preserves_schedule_goal_history_and_used_budget(env, status):
    group = await _bind(env)
    task = await _create(env, goal_objective="Finish the report", max_runs=1)
    async with env.sf() as session:
        row = await session.get(ScheduledTaskRow, task["id"])
        row.status = status
        row.run_count = 7
        row.last_occurrence_seq = 9
        row.unmet_streak_after_seq = 4
        row.standing_notes = ["Preserve the report format"]
        row.end_at = datetime.now(UTC) - timedelta(days=1)
        if status == "completed":
            row.next_run_at = None
        session.add(occurrence("prior-run", task["id"], seq=9))
        await session.commit()
    before = (await env.client.get(f"/api/scheduled-tasks/{task['id']}")).json()
    response = await env.client.patch(f"/api/scheduled-tasks/{task['id']}", json={FIELD: group["id"]})
    assert response.status_code == 200, response.text
    after = response.json()
    assert after[FIELD] == group["id"]
    for key in ("status", "next_run_at", "schedule_type", "schedule_spec", "timezone", "goal_objective", "max_runs", "end_at", "run_count", "automatic_runs_used", "standing_notes"):
        assert after[key] == before[key], key
    assert after["automatic_runs_used"] == 1
    async with env.sf() as session:
        row = await session.get(ScheduledTaskRow, task["id"])
        assert row.last_occurrence_seq == 9
        assert row.unmet_streak_after_seq == 4


@pytest.mark.asyncio
async def test_group_selection_requires_enabled_channel_connections(env):
    group = await _bind(env)
    env.app.state.channel_connections_config.enabled = False
    response = await env.client.post("/api/scheduled-tasks", json=_body(**{FIELD: group["id"]}))
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "invalid_notification_group"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider", "workspace_id", "metadata", "allowed"),
    [
        ("qq", "app1:group:group-openid", {"chat_type": "group", "group_openid": "group-openid"}, True),
        ("wecom", "bot1:group:wr_chat_1", {"aibotid": "bot1", "chattype": "group", "chatid": "wr_chat_1"}, True),
        ("wechat", "group:wx_chat_1", {"chat_type": "group", "chat_id": "group:wx_chat_1"}, False),
    ],
)
async def test_qq_and_wecom_group_destinations_round_trip_and_wechat_is_rejected(env, provider, workspace_id, metadata, allowed):
    group = await _bind(env, provider=provider, workspace_id=workspace_id, metadata=metadata)
    response = await env.client.post("/api/scheduled-tasks", json=_body(**{FIELD: group["id"]}))
    if allowed:
        assert response.status_code == 200, response.text
        assert response.json()[FIELD] == group["id"]
    else:
        assert response.status_code == 422, response.text
        assert response.json()["detail"]["code"] == "invalid_notification_group"
