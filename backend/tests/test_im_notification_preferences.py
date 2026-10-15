"""Owner-controlled IM notices, including durable cancellation on opt-out."""

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from support.postgres import asyncpg_test_url

from deerflow.persistence.base import Base
from deerflow.persistence.notification_deliveries import NotificationDeliveryRepository
from deerflow.persistence.notification_deliveries.model import NotificationDeliveryRow
from deerflow.persistence.postgres_schema import build_asyncpg_connect_args
from deerflow.persistence.user.model import UserRow


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(params=["sqlite", "postgres"])
async def repositories(tmp_path, request):
    import deerflow.persistence.models  # noqa: F401 -- production ORM registration
    from deerflow.persistence.user.im_notifications import ImNotificationPreferencesRepository

    schema = None
    if request.param == "postgres":
        uri = os.environ.get("TEST_POSTGRES_URI")
        if not uri:
            pytest.skip("requires TEST_POSTGRES_URI (real IM preference transactions)")
        schema = f"im_notice_{uuid.uuid4().hex}"
        engine = create_async_engine(asyncpg_test_url(uri), connect_args=build_asyncpg_connect_args(schema))
    else:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/preferences.db")

        @event.listens_for(engine.sync_engine, "connect")
        def foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

    try:
        async with engine.begin() as connection:
            if schema:
                await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            await connection.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as session, session.begin():
            session.add_all([UserRow(id="alice", email="alice@example.com"), UserRow(id="bob", email="bob@example.com")])
        yield ImNotificationPreferencesRepository(sessions), NotificationDeliveryRepository(sessions)
    finally:
        if schema:
            async with engine.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()


async def enqueue(repo, *, owner="alice", provider="feishu", suffix="one"):
    return await repo.enqueue(task_id="task", task_run_id=suffix, provider=provider, target=f"recipient-{suffix}", owner_user_id=owner, event="run_completed")


@pytest.mark.anyio
async def test_defaults_persist_and_disjoint_channel_edits_do_not_clobber(repositories):
    preferences, _ = repositories
    assert await preferences.get("alice") == dict.fromkeys(("feishu", "wecom", "wechat", "qq"), True)
    await asyncio.gather(preferences.patch("alice", {"feishu": False}), preferences.patch("alice", {"qq": False}))
    values = await type(preferences)(preferences.sessions).get("alice")
    assert values == {"feishu": False, "wecom": True, "wechat": True, "qq": False}
    assert (await preferences.get("bob"))["feishu"] is True
    assert (await preferences.patch("alice", {"feishu": None}))["feishu"] is True
    assert (await preferences.get("alice"))["qq"] is False
    # The actual local synthetic owner has no auth-users row. Do not fabricate
    # a login account or disable production FK enforcement to store its choice.
    assert (await preferences.patch("default", {"qq": False}))["qq"] is False


@pytest.mark.anyio
async def test_disable_cancels_pending_parked_claimed_and_group_but_not_other_owners_or_channels(repositories):
    preferences, deliveries = repositories
    pending = await enqueue(deliveries)
    parked = await enqueue(deliveries, suffix="parked")
    claimed = await enqueue(deliveries, suffix="claimed")
    group = await deliveries.enqueue(task_id="task", task_run_id="group", provider="feishu", target="group-binding", owner_user_id="alice", event="run_completed", payload={"target_type": "group"})
    other_owner = await enqueue(deliveries, owner="bob", suffix="bob")
    other_channel = await enqueue(deliveries, provider="wecom", suffix="wecom")
    sent = await enqueue(deliveries, suffix="sent")
    await deliveries.mark_sent(sent["id"])
    async with deliveries.session_factory() as session, session.begin():
        row = await session.get(NotificationDeliveryRow, parked["id"])
        row.available_at = datetime.now(UTC) + timedelta(days=1)
        row.parked_attempts = 3
        row = await session.get(NotificationDeliveryRow, claimed["id"])
        row.status, row.claim_token = "sending", "old-claim"
    await preferences.patch("alice", {"feishu": False})
    await preferences.patch("alice", {"feishu": True})
    # Opting in again must not resurrect the historical backlog.
    async with deliveries.session_factory() as session:
        for item in (pending, parked, claimed, group):
            row = await session.get(NotificationDeliveryRow, item["id"])
            assert (row.status, row.last_error, row.claim_token, row.attempts) == ("failed", "disabled_by_owner", None, 0)
        assert (await session.get(NotificationDeliveryRow, sent["id"])).status == "sent"
    assert {row["id"] for row in await deliveries.claim_due_deliveries(now=datetime.now(UTC), limit=20)} == {other_owner["id"], other_channel["id"]}
    # A stale worker cannot overwrite the opt-out or enqueue another retry.
    row = await deliveries.mark_failed(claimed["id"], claim_token="old-claim", error="temporary", count_attempt=False)
    assert row["status"] == "failed"


@pytest.mark.anyio
async def test_preference_and_outbox_cancellation_rollback_together(repositories, monkeypatch):
    preferences, deliveries = repositories
    item = await enqueue(deliveries)
    original = preferences.sessions

    class FailingSessions:
        def __call__(self):
            session = original()
            execute = session.execute

            async def fail_cancel(statement, *args, **kwargs):
                if statement.is_update and statement.table.name == "notification_deliveries":
                    raise RuntimeError("outbox write failed")
                return await execute(statement, *args, **kwargs)

            session.execute = fail_cancel
            return session

    monkeypatch.setattr(preferences, "sessions", FailingSessions())
    with pytest.raises(RuntimeError, match="outbox write failed"):
        await preferences.patch("alice", {"feishu": False})
    monkeypatch.setattr(preferences, "sessions", original)
    assert (await preferences.get("alice"))["feishu"] is True
    async with original() as session:
        assert (await session.get(NotificationDeliveryRow, item["id"])).status == "pending"


@pytest.fixture
async def api(repositories, monkeypatch):
    from app.gateway.routers import im_notification_preferences

    preferences, _ = repositories
    app = FastAPI()
    app.include_router(im_notification_preferences.router)
    identity = SimpleNamespace(id="alice", source="session")

    @app.middleware("http")
    async def identity_middleware(request, call_next):
        if identity.id:
            request.state.user = SimpleNamespace(id=identity.id)
            request.state.auth_source = identity.source
        return await call_next(request)

    monkeypatch.setattr(im_notification_preferences, "_repository", lambda: preferences)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers={"X-Expected-User-Id": "alice"}) as client:
        yield client, identity


@pytest.mark.anyio
async def test_api_partial_updates_auth_and_stale_tab_fencing(api):
    client, identity = api
    path = "/api/channels/notification-preferences"
    assert (await client.patch(path, json={"feishu": False})).json() == {"feishu": False, "wecom": True, "wechat": True, "qq": True}
    identity.id = "bob"
    assert (await client.patch(path, json={"qq": False})).status_code == 409
    assert (await client.get(path)).status_code == 409
    client.headers["X-Expected-User-Id"] = "bob"
    assert (await client.get(path)).json()["feishu"] is True
    identity.source = "auth_disabled"
    assert (await client.patch(path, json={"qq": False})).json()["qq"] is False
    identity.id = None
    assert (await client.get(path)).status_code == 401


@pytest.mark.anyio
@pytest.mark.parametrize("body", [{"qq": "false"}, {"qq": 0}, {"slack": False}, {"owner_user_id": "bob"}, {"notification_enabled": False}])
async def test_api_rejects_coercion_unknown_platforms_and_browser_settings(api, body):
    client, _ = api
    assert (await client.patch("/api/channels/notification-preferences", json=body)).status_code == 422


@pytest.mark.anyio
async def test_worker_rechecks_policy_after_summary_await_and_before_channel_down_parking(repositories):
    from app.scheduler.notification_delivery import NotificationDeliveryWorker

    preferences, deliveries = repositories
    item = await enqueue(deliveries)
    item["run_id"] = "run"
    item["payload"] = {"version": 2, "run_status": "success"}
    item["status"] = "sending"
    # Force a slow summary lookup to complete after the owner opts out.
    sends = []

    async def summary(*args):
        await preferences.patch("alice", {"feishu": False})
        return "done"

    class Channel:
        is_running = True

        async def send_notification_for_owner(self, **kwargs):
            sends.append(kwargs)

    worker = NotificationDeliveryWorker(delivery_repo=deliveries, resolve_channel=lambda _: Channel(), resolve_notification_preferences=preferences.get, resolve_run_summary=summary)
    await worker._deliver(item)
    assert sends == []
    # A disabled recipient does not sit parked until the channel returns.
    late = await enqueue(deliveries, suffix="late")
    worker = NotificationDeliveryWorker(delivery_repo=deliveries, resolve_channel=lambda _: None, resolve_notification_preferences=preferences.get)
    await worker._deliver(late)
    async with deliveries.session_factory() as session:
        assert (await session.get(NotificationDeliveryRow, late["id"])).status == "failed"


@pytest.mark.anyio
async def test_worker_preference_read_failure_parks_without_sending_or_spending_attempts(repositories):
    from app.scheduler.notification_delivery import NotificationDeliveryWorker

    _, deliveries = repositories
    item = await enqueue(deliveries)

    async def unavailable(_):
        raise RuntimeError("database unavailable")

    worker = NotificationDeliveryWorker(delivery_repo=deliveries, resolve_channel=lambda _: pytest.fail("must not reach channel"), resolve_notification_preferences=unavailable)
    await worker._deliver(item)
    async with deliveries.session_factory() as session:
        row = await session.get(NotificationDeliveryRow, item["id"])
        assert (row.status, row.attempts, row.parked_attempts) == ("pending", 0, 1)


@pytest.mark.anyio
@pytest.mark.parametrize("provider", ["feishu", "wecom", "wechat", "qq"])
async def test_normal_finalization_enqueues_only_enabled_channels_and_no_qq_group_fallback(repositories, provider):
    from app.scheduler.service import ScheduledTaskService
    from deerflow.persistence.channel_connections.model import ChannelConnectionRow

    preferences, deliveries = repositories
    sessions = deliveries.session_factory
    async with sessions() as session, session.begin():
        for channel in ("feishu", "wecom", "wechat", "qq"):
            session.add(
                ChannelConnectionRow(
                    id=channel,
                    owner_user_id="alice",
                    provider=channel,
                    status="connected",
                    external_account_id=f"{channel}-user",
                    workspace_id="app:c2c" if channel == "qq" else "private",
                    metadata_json={"chat_type": "c2c" if channel == "qq" else "p2p"},
                )
            )
        session.add(ChannelConnectionRow(id="qq-group", owner_user_id="alice", provider="qq", status="connected", external_account_id="group-member", workspace_id="app:group:one", metadata_json={"chat_type": "group"}))
    await preferences.patch("alice", {provider: False})
    # This is the production finalization observer and real transaction/outbox,
    # not a duplicate of enqueue policy in a test-specific scheduler.
    service = ScheduledTaskService(task_repo=SimpleNamespace(), task_run_repo=SimpleNamespace(), launch_run=None, connection_repo=object(), notification_repo=deliveries, poll_interval_seconds=5, lease_seconds=30, max_concurrent_runs=1)
    task = SimpleNamespace(id="task", user_id="alice", title="Digest", origin_thread_id=None, notification_group_connection_id="feishu-group")
    occurrence = SimpleNamespace(id="occurrence", trigger="scheduled", status="success", run_id="run", error=None)
    async with sessions() as session, session.begin():
        await service._on_finalization(session, task, occurrence, events=("run_completed",))
    async with sessions() as session:
        rows = (await session.scalars(select(NotificationDeliveryRow))).all()
    assert {row.provider for row in rows} == {"feishu", "wecom", "wechat", "qq"} - {provider}
    assert all(row.target != "group-member" for row in rows)
    assert sum(row.target == "feishu-group" for row in rows) == (0 if provider == "feishu" else 1)


@pytest.mark.anyio
@pytest.mark.parametrize("binding", [None, {"status": "disconnected"}, {"provider": "slack"}, {"owner_user_id": "bob"}, {"external_account_id": ""}, {"provider": ""}])
async def test_finalization_without_push_recipients_skips_preference_queries(repositories, binding):
    from app.scheduler.service import ScheduledTaskService
    from deerflow.persistence.channel_connections.model import ChannelConnectionRow

    _, deliveries = repositories
    sessions = deliveries.session_factory
    if binding is not None:
        async with sessions() as session, session.begin():
            values = {"id": "binding", "owner_user_id": "alice", "provider": "wecom", "status": "connected", "external_account_id": "recipient"}
            session.add(ChannelConnectionRow(**{**values, **binding}))
    service = ScheduledTaskService(task_repo=SimpleNamespace(), task_run_repo=SimpleNamespace(), launch_run=None, connection_repo=object(), notification_repo=deliveries, poll_interval_seconds=5, lease_seconds=30, max_concurrent_runs=1)
    task = SimpleNamespace(id="task", user_id="alice", title="Digest", origin_thread_id=None, notification_group_connection_id=None)
    occurrence = SimpleNamespace(id="occurrence", trigger="scheduled", status="success", run_id="run", error=None)
    statements = []

    def record_statement(_connection, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    async with sessions() as session, session.begin():
        engine = session.get_bind()
        event.listen(engine, "before_cursor_execute", record_statement)
        try:
            await service._on_finalization(session, task, occurrence, events=("run_completed",))
        finally:
            event.remove(engine, "before_cursor_execute", record_statement)
    assert any("channel_connections" in statement for statement in statements)
    assert not any("im_notification_preferences" in statement for statement in statements)
    async with sessions() as session:
        assert (await session.scalars(select(NotificationDeliveryRow))).all() == []


@pytest.mark.anyio
@pytest.mark.parametrize("enabled", [True, False])
async def test_group_only_finalization_still_locks_and_honors_preferences(repositories, monkeypatch, enabled):
    from app.scheduler.service import ScheduledTaskService
    from deerflow.persistence.user.im_notifications import ImNotificationPreferencesRepository

    preferences, deliveries = repositories
    await preferences.patch("alice", {"feishu": enabled})
    original = ImNotificationPreferencesRepository.get_in_session
    locks = []

    async def record_preference_lookup(session, user_id, *, lock_owner=False):
        locks.append((session, user_id, lock_owner))
        return await original(session, user_id, lock_owner=lock_owner)

    monkeypatch.setattr(ImNotificationPreferencesRepository, "get_in_session", staticmethod(record_preference_lookup))
    service = ScheduledTaskService(task_repo=SimpleNamespace(), task_run_repo=SimpleNamespace(), launch_run=None, connection_repo=object(), notification_repo=deliveries, poll_interval_seconds=5, lease_seconds=30, max_concurrent_runs=1)
    task = SimpleNamespace(id="task", user_id="alice", title="Digest", origin_thread_id=None, notification_group_connection_id="feishu-group")
    occurrence = SimpleNamespace(id="occurrence", trigger="scheduled", status="success", run_id="run", error=None)
    async with deliveries.session_factory() as session, session.begin():
        await service._on_finalization(session, task, occurrence, events=("run_completed",))
        assert locks == [(session, "alice", True)]
    async with deliveries.session_factory() as session:
        rows = (await session.scalars(select(NotificationDeliveryRow))).all()
    assert [(row.provider, row.target, row.payload_json["target_type"]) for row in rows] == ([("feishu", "feishu-group", "group")] if enabled else [])


@pytest.mark.anyio
async def test_worker_does_not_send_canceled_claim_after_fast_reenable(repositories):
    from app.scheduler.notification_delivery import NotificationDeliveryWorker

    preferences, deliveries = repositories
    await enqueue(deliveries)
    (claimed,) = await deliveries.claim_due_deliveries(now=datetime.now(UTC), limit=1)
    await preferences.patch("alice", {"feishu": False})
    await preferences.patch("alice", {"feishu": True})

    class Channel:
        is_running = True

        async def send_notification_for_owner(self, **_):
            pytest.fail("A canceled claim must not send after the channel is reenabled")

    worker = NotificationDeliveryWorker(delivery_repo=deliveries, resolve_channel=lambda _: Channel(), resolve_notification_preferences=preferences.get)
    await worker._deliver(claimed)


@pytest.mark.anyio
async def test_public_wechat_connection_metadata_omits_legacy_context_token(repositories, monkeypatch):
    from app.gateway.routers import channel_connections

    row = {"id": "binding", "provider": "wechat", "status": "connected", "metadata": {"context_token": "private-routing-token", "chat_type": "p2p"}}

    class Connections:
        async def list_connections(self, _):
            return [row]

    async def config(_):
        return SimpleNamespace(enabled=True)

    monkeypatch.setattr(channel_connections, "_get_channel_connections_config", config)
    monkeypatch.setattr(channel_connections, "_get_repository", lambda *_: Connections())
    request = SimpleNamespace(state=SimpleNamespace(user=SimpleNamespace(id="alice")))
    response = await channel_connections.get_channel_connections(request)
    assert response.connections[0].metadata == {"chat_type": "p2p"}
    assert row["metadata"]["context_token"] == "private-routing-token"


@pytest.mark.anyio
async def test_runtime_event_preferences_default_off_and_cancel_only_matching_runtime_backlog(repositories):
    preferences, deliveries = repositories
    assert await preferences.get_event_preferences("alice") == {
        "run_completed": False,
        "run_failed": False,
        "human_input_requested": False,
    }
    updated = await preferences.patch("alice", {"run_completed": True, "human_input_requested": True})
    assert updated["run_completed"] is True
    assert updated["human_input_requested"] is True
    assert "run_failed" not in updated
    assert await preferences.get_event_preferences("alice") == {
        "run_completed": True,
        "run_failed": False,
        "human_input_requested": True,
    }

    scheduled_row = await enqueue(deliveries, suffix="sched")
    runtime_completed = await deliveries.enqueue(
        source_kind="run",
        source_key="run-1",
        provider="feishu",
        target="recipient-rt-1",
        owner_user_id="alice",
        event="run_completed",
        run_id="run-1",
        payload={"source_kind": "run"},
    )
    runtime_input = await deliveries.enqueue(
        source_kind="human_input_request",
        source_key="run-2:call-1",
        provider="feishu",
        target="recipient-rt-2",
        owner_user_id="alice",
        event="human_input_requested",
        run_id="run-2",
        payload={"source_kind": "human_input_request"},
    )

    # Disabling `run_completed` cancels the pending runtime `run_completed` notice,
    # but leaves scheduled-task `run_completed` and runtime `human_input_requested` untouched.
    await preferences.patch("alice", {"run_completed": False})
    async with deliveries.session_factory() as session:
        sched = await session.get(NotificationDeliveryRow, scheduled_row["id"])
        rt_done = await session.get(NotificationDeliveryRow, runtime_completed["id"])
        rt_input = await session.get(NotificationDeliveryRow, runtime_input["id"])
        assert sched.status == "pending"
        assert (rt_done.status, rt_done.last_error) == ("failed", "disabled_by_owner")
        assert rt_input.status == "pending"
