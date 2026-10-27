"""Regression anchors: the IM leader lease must not block the event loop.

``ChannelService`` acquires, renews and releases ``channel_leases`` rows on the
Gateway event loop: at startup, on every supervision tick (every
``lease_seconds // 3`` seconds per provider), from readiness requests and at
shutdown. Every statement goes through the async session (aiosqlite /
asyncpg) and every ``wait_for`` bound is a loop timer. The same tick reads the
runtime config versions and re-reads a changed provider's config through the
synchronous runtime config store, both in worker threads. If any of it
regresses onto the loop — a synchronous driver call, a blocking clock or
lock — the strict Blockbuster gate raises ``BlockingError`` here.

The engine and schema are built off the loop: that is fixture work, not the
production path under test.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
import sqlalchemy as sa
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker

# Pre-import so lazy imports inside the service are cached no-ops under the gate.
import deerflow.persistence.models  # noqa: F401
from app.channels.leadership import ChannelLeadership, RenewOutcome
from app.channels.runtime_config_store import SqlChannelRuntimeConfigStore
from app.channels.service import ChannelService
from app.channels.store import JsonChannelStore
from deerflow import reflection
from deerflow.config.app_config import AppConfig, reset_app_config, set_app_config
from deerflow.config.credentials_key import CredentialsCipher
from deerflow.persistence.base import Base
from deerflow.persistence.channel_leases import ChannelLeaseRow, SqlChannelLeaseRepository
from deerflow.persistence.channel_runtime_configs import ChannelRuntimeConfigRow, SqlChannelRuntimeConfigRepository

pytestmark = pytest.mark.asyncio


def _build_sqlite_engine(path: Path) -> AsyncEngine:
    sync_engine = sa.create_engine(f"sqlite:///{path.as_posix()}")
    try:
        Base.metadata.create_all(sync_engine, tables=[ChannelLeaseRow.__table__])
    finally:
        sync_engine.dispose()
    return create_async_engine(f"sqlite+aiosqlite:///{path.as_posix()}")


@pytest_asyncio.fixture
async def repo(tmp_path) -> AsyncIterator[SqlChannelLeaseRepository]:
    engine = await asyncio.to_thread(_build_sqlite_engine, tmp_path / "leases.db")
    try:
        yield SqlChannelLeaseRepository(async_sessionmaker(engine, expire_on_commit=False))
    finally:
        await engine.dispose()


class _Transport:
    def __init__(self, *, bus: object, config: dict) -> None:
        self.config = config
        self.is_running = False

    async def start(self) -> None:
        self.is_running = True

    async def stop(self) -> None:
        self.is_running = False


async def test_lease_round_trip_does_not_block_loop(repo) -> None:
    holder = ChannelLeadership(repo, owner_id="A", lease_seconds=30, grace_seconds=10)
    peer = ChannelLeadership(repo, owner_id="B", lease_seconds=30, grace_seconds=10)
    assert await holder.acquire("telegram") is True
    assert await peer.acquire("telegram") is False  # refusal plus the observation read
    assert await holder.renew("telegram", transport_running=True) is RenewOutcome.RENEWED
    await holder.release("telegram")
    assert await peer.acquire("telegram") is True
    assert [state.owner_id for state in await repo.list_all()] == ["B"]


async def test_service_supervision_and_shutdown_do_not_block_loop(repo, tmp_path, monkeypatch) -> None:
    """The production caller: startup acquisition, a supervision round, and the releasing shutdown."""
    monkeypatch.setattr(reflection, "resolve_class", lambda *_args, **_kwargs: _Transport)
    store_path = await asyncio.to_thread(lambda: tmp_path / "store.json")
    service = ChannelService(
        channels_config={"telegram": {"enabled": True}, "github": {"enabled": True}},
        store=JsonChannelStore(store_path),
        leadership=ChannelLeadership(repo, owner_id="A", lease_seconds=30, grace_seconds=10),
    )

    async def noop() -> None:
        return None

    service.manager.start = noop
    service.manager.stop = noop
    service._start_supervisor = lambda: None
    await service.start()
    await service._supervise_once()
    assert service.get_status()["channels"]["telegram"]["leader"] == "A"
    await service.stop()
    assert (await repo.get("telegram")).live is False


def _build_runtime_store(path: Path) -> SqlChannelRuntimeConfigStore:
    engine = sa.create_engine(f"sqlite:///{path.as_posix()}")
    Base.metadata.create_all(engine, tables=[ChannelRuntimeConfigRow.__table__])
    cipher = CredentialsCipher.from_keys([Fernet.generate_key()])
    store = SqlChannelRuntimeConfigStore(SqlChannelRuntimeConfigRepository(sessionmaker(engine, expire_on_commit=False)), cipher=cipher)
    store.set_provider_config("telegram", {"enabled": True, "bot_token": "t-1"})
    return store


async def test_supervision_applies_a_peer_runtime_config_save_without_blocking_loop(repo, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(reflection, "resolve_class", lambda *_args, **_kwargs: _Transport)
    set_app_config(AppConfig.model_validate({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}, "channel_connections": {"enabled": True, "telegram": {"enabled": True}}}))
    runtime_store = await asyncio.to_thread(_build_runtime_store, tmp_path / "runtime.db")
    store_path = await asyncio.to_thread(lambda: tmp_path / "store.json")
    service = ChannelService(
        channels_config={"telegram": {"enabled": True, "bot_token": "t-1"}},
        store=JsonChannelStore(store_path),
        leadership=ChannelLeadership(repo, owner_id="A", lease_seconds=30, grace_seconds=10),
        runtime_config_store=runtime_store,
    )

    async def noop() -> None:
        return None

    service.manager.start = noop
    service.manager.stop = noop
    service._start_supervisor = lambda: None
    try:
        await service.start()
        await asyncio.to_thread(runtime_store.set_provider_config, "telegram", {"enabled": True, "bot_token": "t-2"})
        await service._supervise_once()
        await asyncio.gather(*list(service._lease_actions.values()))
        assert service.get_channel("telegram").config["bot_token"] == "t-2"
        await service.stop()
    finally:
        reset_app_config()
