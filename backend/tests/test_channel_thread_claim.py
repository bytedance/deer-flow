"""First-binding claims for IM conversations: two replicas converge on one thread.

When the first message of a conversation reaches two Gateway replicas at the
same time (or a replica and a peer that has not committed yet), both miss the
binding lookup and each creates a Gateway thread. ``set_thread_id`` overwrites,
so whichever replica writes last wins and the other replica's run lands on a
thread the conversation no longer points to. ``claim_thread_id`` is the
insert-if-absent primitive the manager uses for that first binding instead: the
first claim wins and every later claim returns the winner, so the losers can
adopt it. ``set_thread_id`` keeps its overwrite semantics for ``/new``.

Each case runs on SQLite and, when ``TEST_POSTGRES_URI`` is set, on PostgreSQL in
a throwaway schema, with two engines over one database standing in for two
Gateway replicas.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from support.postgres import asyncpg_test_url

from app.channels.store import JsonChannelStore, SqlChannelStore
from deerflow.persistence.base import Base
from deerflow.persistence.channel_connections import ChannelConnectionRepository, ChannelConnectionRow, ChannelConversationRow, ChannelCredentialCipher
from deerflow.persistence.channel_thread_bindings import ChannelThreadBindingRow
from deerflow.persistence.postgres_schema import build_asyncpg_connect_args

pytestmark = pytest.mark.asyncio

_TABLES = [ChannelConnectionRow.__table__, ChannelConversationRow.__table__, ChannelThreadBindingRow.__table__]
# Enough concurrent first writers that a lost race would show on either dialect.
_WRITERS = 8


@dataclass
class Replicas:
    dialect: str
    engines: list[AsyncEngine]

    def connections(self, index: int) -> ChannelConnectionRepository:
        return ChannelConnectionRepository(async_sessionmaker(self.engines[index], expire_on_commit=False), cipher=ChannelCredentialCipher.from_key("k"))

    def store(self, index: int) -> SqlChannelStore:
        return SqlChannelStore(async_sessionmaker(self.engines[index], expire_on_commit=False))


@pytest_asyncio.fixture(params=["sqlite", "postgres"])
async def replicas(request, tmp_path) -> AsyncIterator[Replicas]:
    if request.param == "sqlite":
        url = f"sqlite+aiosqlite:///{(tmp_path / 'claims.db').as_posix()}"
        engines = [create_async_engine(url) for _ in range(2)]
        async with engines[0].begin() as conn:
            await conn.run_sync(Base.metadata.create_all, tables=_TABLES)
        try:
            yield Replicas("sqlite", engines)
        finally:
            for engine in engines:
                await engine.dispose()
        return

    uri = os.environ.get("TEST_POSTGRES_URI")
    if not uri:
        pytest.skip("requires TEST_POSTGRES_URI (channel conversation claims on PostgreSQL)")
    schema = f"channel_thread_claim_{uuid.uuid4().hex}"
    engines = [create_async_engine(asyncpg_test_url(uri), connect_args=build_asyncpg_connect_args(schema)) for _ in range(2)]
    try:
        async with engines[0].begin() as conn:
            await conn.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
            await conn.run_sync(Base.metadata.create_all, tables=_TABLES)
        yield Replicas("postgresql", engines)
    finally:
        async with engines[0].begin() as conn:
            await conn.execute(sa.text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        for engine in engines:
            await engine.dispose()


async def _connection_binding(replicas: Replicas, conversation: str = "C1") -> dict:
    connection = await replicas.connections(0).upsert_connection(owner_user_id="alice", provider="slack", external_account_id="U1", workspace_id="T1")
    return {
        "connection_id": connection["id"],
        "owner_user_id": "alice",
        "provider": "slack",
        "external_conversation_id": conversation,
        "external_topic_id": "1700000000.000100",
    }


async def _conversation_rows(replicas: Replicas, conversation: str) -> list[str]:
    async with replicas.engines[0].connect() as conn:
        rows = await conn.execute(sa.select(ChannelConversationRow.thread_id).where(ChannelConversationRow.external_conversation_id == conversation))
        return [row[0] for row in rows]


# -- channel_conversations (connection-bound conversations) -------------------


async def test_first_claim_binds_and_a_peer_claim_adopts_it(replicas):
    binding = await _connection_binding(replicas)
    a, b = replicas.connections(0), replicas.connections(1)

    assert await a.claim_thread_id(**binding, thread_id="thread-a") == "thread-a"
    assert await b.claim_thread_id(**binding, thread_id="thread-b") == "thread-a"

    assert await b.get_thread_id(binding["connection_id"], "C1", "1700000000.000100") == "thread-a"
    assert await _conversation_rows(replicas, "C1") == ["thread-a"]


async def test_concurrent_first_claims_converge_on_one_thread(replicas):
    binding = await _connection_binding(replicas)
    repos = [replicas.connections(index % 2) for index in range(_WRITERS)]

    winners = await asyncio.gather(*(repo.claim_thread_id(**binding, thread_id=f"thread-{index}") for index, repo in enumerate(repos)))

    assert len(set(winners)) == 1
    assert await _conversation_rows(replicas, "C1") == [winners[0]]


async def test_set_thread_id_still_rebinds_a_claimed_conversation(replicas):
    """``/new`` rebinds the conversation on purpose; a claim must not pin it."""
    binding = await _connection_binding(replicas)
    repo = replicas.connections(0)
    await repo.claim_thread_id(**binding, thread_id="thread-first")

    await repo.set_thread_id(**binding, thread_id="thread-after-new")

    assert await repo.claim_thread_id(**binding, thread_id="thread-late-peer") == "thread-after-new"
    assert await _conversation_rows(replicas, "C1") == ["thread-after-new"]


async def test_claims_are_scoped_by_topic(replicas):
    binding = await _connection_binding(replicas)
    repo = replicas.connections(0)

    assert await repo.claim_thread_id(**binding, thread_id="thread-topic") == "thread-topic"
    assert await repo.claim_thread_id(**{**binding, "external_topic_id": None}, thread_id="thread-base") == "thread-base"


async def test_concurrent_first_set_thread_id_leaves_one_row(replicas):
    """Pins #6852 on real concurrency and both dialects: racing first binds neither fail nor duplicate."""
    binding = await _connection_binding(replicas, "C-race")
    repos = [replicas.connections(index % 2) for index in range(_WRITERS)]

    await asyncio.gather(*(repo.set_thread_id(**binding, thread_id=f"thread-{index}") for index, repo in enumerate(repos)))

    rows = await _conversation_rows(replicas, "C-race")
    assert len(rows) == 1 and rows[0].startswith("thread-")


# -- channel_thread_bindings (unbound conversations) ---------------------------


async def test_sql_store_first_claim_wins_across_replicas(replicas):
    a, b = replicas.store(0), replicas.store(1)

    assert await a.claim_thread_id("telegram", "chat-1", "thread-a", topic_id="t1", user_id="u1") == "thread-a"
    assert await b.claim_thread_id("telegram", "chat-1", "thread-b", topic_id="t1", user_id="u2") == "thread-a"

    assert await b.get_thread_id("telegram", "chat-1", topic_id="t1") == "thread-a"
    [entry] = await a.list_entries("telegram")
    assert (entry["thread_id"], entry["user_id"]) == ("thread-a", "u1")


async def test_sql_store_concurrent_first_claims_converge(replicas):
    stores = [replicas.store(index % 2) for index in range(_WRITERS)]

    winners = await asyncio.gather(*(store.claim_thread_id("discord", "chan-1", f"thread-{index}") for index, store in enumerate(stores)))

    assert len(set(winners)) == 1
    assert [entry["thread_id"] for entry in await stores[0].list_entries("discord")] == [winners[0]]


async def test_sql_store_set_thread_id_still_rebinds_after_a_claim(replicas):
    store = replicas.store(0)
    await store.claim_thread_id("slack", "C1", "thread-first")

    await store.set_thread_id("slack", "C1", "thread-after-new")

    assert await store.claim_thread_id("slack", "C1", "thread-late-peer") == "thread-after-new"


# -- JSON store (database.backend: memory, one process) ------------------------


async def test_json_store_claim_keeps_the_first_binding(tmp_path):
    store = JsonChannelStore(tmp_path / "store.json")

    assert await store.claim_thread_id("telegram", "chat-1", "thread-a", user_id="u1") == "thread-a"
    assert await store.claim_thread_id("telegram", "chat-1", "thread-b", user_id="u2") == "thread-a"
    await store.set_thread_id("telegram", "chat-1", "thread-after-new")
    assert await store.claim_thread_id("telegram", "chat-1", "thread-c") == "thread-after-new"

    # Persisted like any other write: a fresh process reads the claimed binding.
    assert await JsonChannelStore(tmp_path / "store.json").get_thread_id("telegram", "chat-1") == "thread-after-new"
