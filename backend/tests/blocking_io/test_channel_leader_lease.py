"""Regression anchors: the IM leader lease must not block the event loop.

``ChannelService`` acquires, renews and releases ``channel_leases`` rows on the
Gateway event loop: at startup, on every supervision tick (every
``lease_seconds // 3`` seconds per provider), from readiness requests and at
shutdown. Every statement goes through the async session (aiosqlite /
asyncpg) and every ``wait_for`` bound is a loop timer. If any of it regresses
onto the loop — a synchronous driver call, a blocking clock or lock — the
strict Blockbuster gate raises ``BlockingError`` here.

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
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

# Pre-import so lazy imports inside the service are cached no-ops under the gate.
import deerflow.persistence.models  # noqa: F401
from app.channels.leadership import ChannelLeadership, RenewOutcome
from app.channels.service import ChannelService
from app.channels.store import JsonChannelStore
from deerflow import reflection
from deerflow.persistence.base import Base
from deerflow.persistence.channel_leases import ChannelLeaseRow, SqlChannelLeaseRepository

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
