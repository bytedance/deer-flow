"""Regression anchors: the chat-to-thread binding store must not block the event loop.

``ChannelManager`` resolves and records a conversation's thread on the Gateway
event loop for every inbound IM message (``_lookup_thread_id`` /
``_store_thread_id``), and ``ChannelService.start()`` runs the one-time
``store.json`` import there too. The SQL store runs every statement through the
async session (aiosqlite / asyncpg); the JSON store keeps the whole file on
disk and offloads its reads and atomic rewrites through ``asyncio.to_thread``.
If either regresses onto the loop — a synchronous driver call, a file read or
rename, a contended ``threading.Lock`` acquired from the loop — the strict
Blockbuster gate raises ``BlockingError`` here.

The engine and the legacy fixture file are built off the loop: that is test
fixture work, not the production path under test.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

# Pre-import so lazy imports inside the store are cached no-ops under the gate.
import deerflow.persistence.models  # noqa: F401
from app.channels.connection_identity import lookup_thread_id
from app.channels.manager import ChannelManager
from app.channels.message_bus import InboundMessage, MessageBus
from app.channels.store import ChannelStore, JsonChannelStore, SqlChannelStore
from deerflow.persistence.base import Base
from deerflow.persistence.channel_thread_bindings import ChannelThreadBindingRow

pytestmark = pytest.mark.asyncio


def _build_sqlite_engine(path: Path) -> AsyncEngine:
    """Create the schema with a sync engine and return the async one (runs in a worker thread)."""
    sync_engine = sa.create_engine(f"sqlite:///{path.as_posix()}")
    try:
        Base.metadata.create_all(sync_engine, tables=[ChannelThreadBindingRow.__table__])
    finally:
        sync_engine.dispose()
    return create_async_engine(f"sqlite+aiosqlite:///{path.as_posix()}")


def _write_legacy(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"slack:C-legacy": {"thread_id": "legacy-thread", "user_id": "U0", "created_at": 1.0, "updated_at": 1.0}}), encoding="utf-8")


@pytest_asyncio.fixture(params=["json", "sql"])
async def store(request, tmp_path) -> AsyncIterator[ChannelStore]:
    engine: AsyncEngine | None = None
    if request.param == "json":
        store: ChannelStore = JsonChannelStore(tmp_path / "channels" / "store.json")
    else:
        engine = await asyncio.to_thread(_build_sqlite_engine, tmp_path / "bindings.db")
        store = SqlChannelStore(async_sessionmaker(engine, expire_on_commit=False), legacy_path=tmp_path / "channels" / "store.json")
    try:
        yield store
    finally:
        if engine is not None:
            await engine.dispose()


async def test_store_round_trip_does_not_block_loop(store) -> None:
    """get / set / overwrite / list / remove on the loop, including the JSON file's atomic rewrite."""
    assert await store.get_thread_id("slack", "C1") is None
    await store.set_thread_id("slack", "C1", "thread-1", user_id="U1")
    await store.set_thread_id("slack", "C1", "thread-1b", topic_id="171.1", user_id="U1")
    await store.set_thread_id("slack", "C1", "thread-2", user_id="U2")  # overwrite
    assert await store.get_thread_id("slack", "C1") == "thread-2"
    assert await store.get_thread_id("slack", "C1", topic_id="171.1") == "thread-1b"
    assert {entry["thread_id"] for entry in await store.list_entries("slack")} == {"thread-2", "thread-1b"}
    assert await store.remove("slack", "C1", topic_id="171.1") is True
    assert await store.remove("slack", "C1") is True
    assert await store.list_entries() == []


async def test_manager_lookup_and_store_do_not_block_loop(store) -> None:
    """The production callers: ``ChannelManager`` resolving and recording a chat's thread."""
    manager = ChannelManager(bus=MessageBus(), store=store)
    msg = InboundMessage(channel_name="slack", chat_id="C1", user_id="U1", text="hi", topic_id="171.1")
    assert await manager._lookup_thread_id(msg) is None
    assert await lookup_thread_id(msg, repo=None, store=store) is None
    await manager._store_thread_id(msg, "thread-1")
    assert await manager._lookup_thread_id(msg) == "thread-1"
    assert await lookup_thread_id(msg, repo=None, store=store) == "thread-1"


async def test_legacy_import_does_not_block_loop(store, tmp_path) -> None:
    """``ChannelService.start()`` imports ``store.json`` on the loop: read, insert, rename all offloaded."""
    if not isinstance(store, SqlChannelStore):
        pytest.skip("the import exists only for the SQL store")
    await asyncio.to_thread(_write_legacy, tmp_path / "channels" / "store.json")
    assert await store.import_legacy_json() == 1
    assert await store.get_thread_id("slack", "C-legacy") == "legacy-thread"
    assert await store.import_legacy_json() == 0  # the file was renamed; the no-op path stays off the loop too
