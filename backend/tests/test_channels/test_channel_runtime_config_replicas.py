"""Runtime IM channel configuration across Gateway instances (``channel_runtime_configs``).

Two routers, or two ``ChannelService`` instances under ``channels.leader_lease``,
share one runtime config table, as two Gateway replicas share the application
database. Before the table each replica read its own ``runtime-config.json``
once and cached the merged config in ``app.state``: credentials saved on one
replica never reached the other, and a disconnect on a replica that did not
hold the provider's lease left the holder connected with the old credentials.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID

import anyio
import pytest
import pytest_asyncio
import sqlalchemy as sa
from _router_auth_helpers import make_authed_test_app
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

from app.channels.leadership import ChannelLeadership
from app.channels.runtime_config_store import SqlChannelRuntimeConfigStore
from app.channels.service import ChannelService
from app.channels.store import JsonChannelStore
from app.gateway.auth.models import User
from app.gateway.routers import channel_connections
from deerflow import reflection
from deerflow.config.app_config import AppConfig, reset_app_config, set_app_config
from deerflow.config.credentials_key import CredentialsCipher
from deerflow.persistence.base import Base
from deerflow.persistence.channel_leases import ChannelLeaseRow, SqlChannelLeaseRepository
from deerflow.persistence.channel_runtime_configs import ChannelRuntimeConfigRow, SqlChannelRuntimeConfigRepository

CIPHER = CredentialsCipher.from_keys([Fernet.generate_key()])


@pytest.fixture(autouse=True)
def _app_config(monkeypatch):
    monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "0")
    monkeypatch.delenv("DEER_FLOW_MULTI_INSTANCE", raising=False)
    set_app_config(
        AppConfig.model_validate(
            {
                "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
                "channel_connections": {"enabled": True, "slack": {"enabled": True}, "telegram": {"enabled": True, "bot_username": "deerflow_bot"}, "discord": {"enabled": True}},
            }
        )
    )
    yield
    reset_app_config()


@pytest.fixture
def runtime_sessions(tmp_path) -> sessionmaker[Session]:
    engine = sa.create_engine(f"sqlite:///{(tmp_path / 'runtime.db').as_posix()}")
    Base.metadata.create_all(engine, tables=[ChannelRuntimeConfigRow.__table__])
    yield sessionmaker(engine, expire_on_commit=False)
    engine.dispose()


def _runtime_store(runtime_sessions, *, cipher: CredentialsCipher | None = CIPHER) -> SqlChannelRuntimeConfigStore:
    return SqlChannelRuntimeConfigStore(SqlChannelRuntimeConfigRepository(runtime_sessions), cipher=cipher)


# -- router ----------------------------------------------------------------


def _admin() -> User:
    return User(id=UUID("11111111-2222-3333-4444-555555555555"), email="admin@example.com", password_hash="x", system_role="admin")


async def _connection_repo(tmp_path):
    from deerflow.persistence.channel_connections import ChannelConnectionRepository
    from deerflow.persistence.engine import get_session_factory, init_engine

    await init_engine("sqlite", url=f"sqlite+aiosqlite:///{tmp_path / 'router.db'}", sqlite_dir=str(tmp_path))
    return ChannelConnectionRepository(get_session_factory())


def _replica(connection_repo, runtime_store):
    app = make_authed_test_app(user_factory=_admin)
    app.state.channel_connection_repo = connection_repo
    app.state.channel_runtime_config_store = runtime_store
    app.include_router(channel_connections.router)
    return app


def _provider(client: TestClient, name: str) -> dict:
    response = client.get("/api/channels/providers")
    assert response.status_code == 200
    return next(provider for provider in response.json()["providers"] if provider["provider"] == name)


def test_credentials_saved_on_one_replica_are_served_by_the_other(tmp_path, runtime_sessions):
    connection_repo = anyio.run(_connection_repo, tmp_path)
    replica_a = _replica(connection_repo, _runtime_store(runtime_sessions))
    replica_b = _replica(connection_repo, _runtime_store(runtime_sessions))

    with TestClient(replica_a) as client_a, TestClient(replica_b) as client_b:
        # B has served the provider list before A saves anything.
        assert _provider(client_b, "slack")["configured"] is False

        saved = client_a.post("/api/channels/slack/runtime-config", json={"values": {"bot_token": "xoxb-ui", "app_token": "xapp-ui"}})
        assert saved.status_code == 200

        slack_on_b = _provider(client_b, "slack")
        assert slack_on_b["configured"] is True
        assert slack_on_b["credential_values"] == {"bot_token": "********", "app_token": "********"}

        # The telegram deep-link username follows the same path.
        assert client_b.post("/api/channels/telegram/runtime-config", json={"values": {"bot_token": "123:abc", "bot_username": "ui_bot"}}).status_code == 200
        assert _provider(client_a, "telegram")["credential_values"]["bot_username"] == "ui_bot"

        disconnected = client_b.delete("/api/channels/slack/runtime-config")
        assert disconnected.status_code == 200
        assert _provider(client_a, "slack")["configured"] is False

    anyio.run(connection_repo.close)


def test_saving_credentials_without_an_encryption_key_is_refused(tmp_path, runtime_sessions):
    connection_repo = anyio.run(_connection_repo, tmp_path)
    app = _replica(connection_repo, _runtime_store(runtime_sessions, cipher=None))

    with TestClient(app) as client:
        response = client.post("/api/channels/slack/runtime-config", json={"values": {"bot_token": "xoxb-ui", "app_token": "xapp-ui"}})

    assert response.status_code == 503
    assert "DEER_FLOW_CREDENTIALS_KEY" in response.json()["detail"]
    assert _runtime_store(runtime_sessions).load_all() == {}
    anyio.run(connection_repo.close)


# -- ChannelService under the leader lease --------------------------------


class FakeTransport:
    started: list[FakeTransport] = []
    #: Credentials the platform rejects: a transport started on one of them never comes up.
    rejected_tokens: set[str] = set()

    def __init__(self, *, bus: object, config: dict) -> None:
        self.config = config
        self.is_running = False

    async def start(self) -> None:
        if self.config.get("bot_token") in FakeTransport.rejected_tokens:
            return
        self.is_running = True
        FakeTransport.started.append(self)

    async def stop(self) -> None:
        self.is_running = False


@pytest.fixture
def fake_transports(monkeypatch):
    FakeTransport.started = []
    FakeTransport.rejected_tokens = set()
    monkeypatch.setattr(reflection, "resolve_class", lambda *_args, **_kwargs: FakeTransport)
    yield


@pytest_asyncio.fixture
async def lease_engine(tmp_path) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'leases.db').as_posix()}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=[ChannelLeaseRow.__table__])
    try:
        yield engine
    finally:
        await engine.dispose()


def _service(lease_engine, owner: str, tmp_path: Path, runtime_store: SqlChannelRuntimeConfigStore) -> ChannelService:
    leadership = ChannelLeadership(SqlChannelLeaseRepository(async_sessionmaker(lease_engine, expire_on_commit=False)), owner_id=owner, lease_seconds=30, grace_seconds=10, clock=time.monotonic)
    # What from_app_config hands over: config.yaml has no channels, the runtime table has the rest.
    channels = {name: dict(config) for name, config in runtime_store.load_all().items() if config.get("enabled")}
    service = ChannelService(channels_config=channels, store=JsonChannelStore(tmp_path / owner / "store.json"), leadership=leadership, runtime_config_store=runtime_store)

    async def noop() -> None:
        return None

    service.manager.start = noop
    service.manager.stop = noop
    service._start_supervisor = lambda: None
    return service


async def _round(service: ChannelService) -> None:
    """One supervision round, then wait for the transport actions it scheduled."""
    await service._supervise_once()
    while service._lease_actions:
        await asyncio.gather(*list(service._lease_actions.values()))


async def _lease(lease_engine, provider: str) -> ChannelLeaseRow | None:
    async with async_sessionmaker(lease_engine)() as session:
        return await session.get(ChannelLeaseRow, provider)


pytest_lease = pytest.mark.usefixtures("fake_transports")


@pytest_lease
@pytest.mark.asyncio
async def test_the_holder_reconnects_with_credentials_saved_on_a_peer(lease_engine, runtime_sessions, tmp_path):
    shared = _runtime_store(runtime_sessions)
    shared.set_provider_config("telegram", {"enabled": True, "bot_token": "t-1"})
    holder, peer = _service(lease_engine, "A", tmp_path, shared), _service(lease_engine, "B", tmp_path, shared)
    await holder.start()
    await peer.start()
    try:
        assert holder._channels["telegram"].config["bot_token"] == "t-1"
        assert "telegram" not in peer._channels
        for service in (holder, peer):
            await _round(service)  # first rounds only record the versions they started from
        starts = len(FakeTransport.started)

        # The peer's router saved new credentials (it cannot restart the holder's transport itself).
        assert await peer.configure_channel("telegram", {"enabled": True, "bot_token": "t-2"}) is True
        shared.set_provider_config("telegram", {"enabled": True, "bot_token": "t-2"})
        await _round(holder)

        assert holder._channels["telegram"].config["bot_token"] == "t-2"
        assert holder._channels["telegram"].is_running
        assert len(FakeTransport.started) == starts + 1
        await _round(holder)
        await _round(peer)
        assert len(FakeTransport.started) == starts + 1  # applied once, on the holder only
        assert "telegram" not in peer._channels
    finally:
        await holder.stop()
        await peer.stop()


@pytest_lease
@pytest.mark.asyncio
async def test_a_holder_whose_transport_is_down_connects_on_new_credentials_in_the_same_round(lease_engine, runtime_sessions, tmp_path):
    shared = _runtime_store(runtime_sessions)
    shared.set_provider_config("telegram", {"enabled": True, "bot_token": "revoked"})
    FakeTransport.rejected_tokens = {"revoked"}
    holder, peer = _service(lease_engine, "A", tmp_path, shared), _service(lease_engine, "B", tmp_path, shared)
    await holder.start()
    await peer.start()
    try:
        # The holder took the lease but its transport cannot start on the old credentials.
        await _round(holder)
        assert holder.get_status()["channels"]["telegram"]["leader_here"] is True
        assert not holder._transport_running("telegram")

        shared.set_provider_config("telegram", {"enabled": True, "bot_token": "t-2"})
        await _round(holder)  # one renewal interval, not one to apply the config and another to start

        assert holder._channels["telegram"].is_running
        assert holder._channels["telegram"].config["bot_token"] == "t-2"
        assert "telegram" not in holder._lease_start_backoff
        assert "telegram" not in peer._channels
    finally:
        await holder.stop()
        await peer.stop()


@pytest_lease
@pytest.mark.asyncio
async def test_a_disconnect_saved_on_a_peer_stops_the_holder_and_nobody_takes_over(lease_engine, runtime_sessions, tmp_path):
    shared = _runtime_store(runtime_sessions)
    shared.set_provider_config("telegram", {"enabled": True, "bot_token": "t-1"})
    holder, peer = _service(lease_engine, "A", tmp_path, shared), _service(lease_engine, "B", tmp_path, shared)
    await holder.start()
    await peer.start()
    try:
        # The peer's router: stop locally (nothing runs here), then persist the tombstone.
        assert await peer.remove_channel("telegram") is True
        shared.set_provider_disconnected("telegram")
        await _round(holder)

        assert "telegram" not in holder._channels
        assert (await _lease(lease_engine, "telegram")).lease_expires_at == 0.0  # handed back
        for _ in range(2):
            await _round(peer)
            await _round(holder)
        assert "telegram" not in peer._channels and "telegram" not in holder._channels
        assert all(not service.get_status()["channels"]["telegram"]["enabled"] for service in (holder, peer))
    finally:
        await holder.stop()
        await peer.stop()


@pytest_lease
@pytest.mark.asyncio
async def test_the_instance_that_saved_the_config_does_not_restart_twice(lease_engine, runtime_sessions, tmp_path):
    shared = _runtime_store(runtime_sessions)
    shared.set_provider_config("telegram", {"enabled": True, "bot_token": "t-1"})
    holder = _service(lease_engine, "A", tmp_path, shared)
    await holder.start()
    try:
        await _round(holder)
        # The holder's own router: restart with the new config first, then persist it.
        assert await holder.configure_channel("telegram", {"enabled": True, "bot_token": "t-2"}) is True
        shared.set_provider_config("telegram", {"enabled": True, "bot_token": "t-2"})
        starts = len(FakeTransport.started)

        await _round(holder)

        assert len(FakeTransport.started) == starts
        assert holder._channels["telegram"].config["bot_token"] == "t-2"
    finally:
        await holder.stop()


@pytest_lease
@pytest.mark.asyncio
async def test_a_peer_learns_a_provider_connected_elsewhere_and_takes_it_over(lease_engine, runtime_sessions, tmp_path):
    shared = _runtime_store(runtime_sessions)
    holder, peer = _service(lease_engine, "A", tmp_path, shared), _service(lease_engine, "B", tmp_path, shared)
    await holder.start()
    await peer.start()
    try:
        discord = {"enabled": True, "bot_token": "d-1"}
        assert await holder.configure_channel("discord", discord) is True
        shared.set_provider_config("discord", discord)
        await _round(peer)
        assert peer.get_channel_config("discord") == discord
        assert "discord" not in peer._channels

        await holder.stop()  # releases the lease
        await _round(peer)

        assert peer._channels["discord"].is_running
        assert peer._channels["discord"].config["bot_token"] == "d-1"
    finally:
        await holder.stop()
        await peer.stop()


@pytest_lease
@pytest.mark.asyncio
async def test_a_takeover_reads_a_disconnect_instead_of_reviving_cached_credentials(lease_engine, runtime_sessions, tmp_path):
    shared = _runtime_store(runtime_sessions)
    shared.set_provider_config("telegram", {"enabled": True, "bot_token": "t-1"})
    holder, peer = _service(lease_engine, "A", tmp_path, shared), _service(lease_engine, "B", tmp_path, shared)
    await holder.start()
    await peer.start()
    try:
        await holder.stop()  # releases the lease
        shared.set_provider_disconnected("telegram")

        # The peer has not reconciled yet: its cached config still says enabled.
        # A takeover (what its next lease round would run) must read the
        # disconnect, not fall back to the cached credentials.
        await peer._take_over_channel("telegram")

        assert "telegram" not in peer._channels
        assert peer.get_status()["channels"]["telegram"]["enabled"] is False
    finally:
        await holder.stop()
        await peer.stop()


def test_startup_imports_the_legacy_file_before_overlaying_runtime_config(runtime_sessions, tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace

    from app.channels import service as service_module
    from deerflow.config import paths as paths_module
    from deerflow.config.channel_connections_config import ChannelConnectionsConfig

    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr(paths_module, "_paths", None)
    legacy = tmp_path / "channels" / "runtime-config.json"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(json.dumps({"slack": {"enabled": True, "bot_token": "xoxb-ui", "app_token": "xapp-ui"}, "feishu": {"enabled": False, "_runtime_disabled": True}}), encoding="utf-8")
    store = SqlChannelRuntimeConfigStore(SqlChannelRuntimeConfigRepository(runtime_sessions), cipher=CIPHER, legacy_path=legacy)
    monkeypatch.setattr(service_module, "resolve_runtime_config_store", lambda app_config, *, cipher: store)
    app_config = SimpleNamespace(
        model_extra={"channels": {"feishu": {"enabled": True, "app_id": "file-app", "app_secret": "file-secret"}}},
        channel_connections=ChannelConnectionsConfig.model_validate({"enabled": True, "slack": {"enabled": True}, "feishu": {"enabled": True}}),
    )

    service = ChannelService.from_app_config(app_config, credentials_cipher=CIPHER)

    # The very first start after the upgrade already runs on the imported config.
    assert service._config["slack"] == {"enabled": True, "bot_token": "xoxb-ui", "app_token": "xapp-ui"}
    assert "feishu" not in service._config  # the imported disconnect still suppresses config.yaml
    assert not legacy.exists()
    assert service._runtime_config_store is store
