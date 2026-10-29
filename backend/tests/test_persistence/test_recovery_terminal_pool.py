"""Recovery publication must work with only one free pooled connection."""

from __future__ import annotations

import asyncio
import os
from contextlib import AsyncExitStack
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from support.postgres import asyncpg_test_url

from deerflow.persistence.models.run_event import RunEventRow, RunEventThreadSeqRow
from deerflow.persistence.run.model import RunChangeClockRow, RunRow
from deerflow.persistence.run.sql import RunRepository
from deerflow.runtime.events.store.base import RunEventLifecycleRejected
from deerflow.runtime.events.store.db import DbRunEventStore
from deerflow.runtime.events.store.memory import MemoryRunEventStore
from deerflow.runtime.events.terminal import RecoveryTerminalPublisher, TerminalEventConfirmation


@pytest_asyncio.fixture(params=["sqlite", "postgresql"])
async def pooled_database(request, tmp_path):
    schema = None
    options = {}
    if request.param == "postgresql":
        uri = os.getenv("TEST_POSTGRES_URI")
        if not uri:
            pytest.skip("requires TEST_POSTGRES_URI for real pooled PostgreSQL recovery")
        schema = f"recovery_pool_{uuid4().hex}"
        url = asyncpg_test_url(uri)
        options["connect_args"] = {"server_settings": {"search_path": schema}}
    else:
        url = f"sqlite+aiosqlite:///{tmp_path / 'recovery.db'}"
    engine = create_async_engine(url, pool_size=5, max_overflow=10, pool_timeout=0.1, **options)
    try:
        async with engine.begin() as connection:
            if schema:
                await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            await connection.run_sync(lambda c: RunRow.metadata.create_all(c, tables=[RunRow.__table__, RunChangeClockRow.__table__, RunEventRow.__table__, RunEventThreadSeqRow.__table__]))
        # Separate factories sharing an engine are still the same connection pool.
        run_store = RunRepository(async_sessionmaker(engine, expire_on_commit=False))
        events = DbRunEventStore(async_sessionmaker(engine, expire_on_commit=False))
        yield SimpleNamespace(engine=engine, runs=run_store, events=events)
    finally:
        if schema:
            async with engine.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await engine.dispose()


@pytest.mark.asyncio
async def test_recovery_uses_last_available_pool_connection(pooled_database):
    db = pooled_database
    await db.runs.put("run", thread_id="thread", user_id="alice", status="running")
    claimed = await db.runs.claim_for_takeover("run", grace_seconds=0, error="owner expired")
    assert claimed
    publisher = RecoveryTerminalPublisher(db.events, db.runs)
    target = publisher.authorize_takeover(claimed=claimed, thread_id="thread", run_id="run", user_id="alice", operation_kind="run")
    async with AsyncExitStack() as occupied:
        for _ in range(14):
            await occupied.enter_async_context(db.engine.connect())
        assert await publisher.publish(target) == TerminalEventConfirmation.CONFIRMED_NEW
    events = await db.events.list_events("thread", "run", user_id="alice")
    assert [event["event_type"] for event in events] == ["run.delivery", "run.terminal"]
    assert events[-1]["content"] == {"status": "error"}
    assert events[-1]["metadata"]["recovered"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["deleted", "owner", "thread", "operation", "status"])
async def test_pooled_guard_still_rejects_stale_run(pooled_database, change):
    db = pooled_database
    row = {"thread_id": "thread", "user_id": "alice", "operation_kind": "run", "status": "error"}
    if change != "deleted":
        key, value = {"owner": ("user_id", "bob"), "thread": ("thread_id", "other"), "operation": ("operation_kind", "checkpoint_write"), "status": ("status", "success")}[change]
        row[key] = value
        await db.runs.put("run", **row)
    guard = RecoveryTerminalPublisher(db.events, db.runs).lifecycle_guard(thread_id="thread", run_id="run", user_id="alice")
    async with AsyncExitStack() as occupied:
        for _ in range(14):
            await occupied.enter_async_context(db.engine.connect())
        with pytest.raises(RunEventLifecycleRejected):
            await db.events.put_if_absent(thread_id="thread", run_id="run", event_type="run.terminal", category="trace", user_id="alice", lifecycle_guard=guard)
    assert await db.events.list_events("thread", "run", user_id="alice") == []


@pytest.mark.asyncio
async def test_transaction_guard_keeps_differently_bound_run_store(pooled_database):
    db = pooled_database
    await db.runs.put("run", thread_id="thread", user_id="alice", status="error")
    guard = RecoveryTerminalPublisher(db.events, db.runs).lifecycle_guard(thread_id="thread", run_id="run", user_id="alice")
    # No tables: using the caller's unrelated database would fail or read the
    # wrong Run. Compatibility is engine identity, not session-factory identity.
    unrelated_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with async_sessionmaker(unrelated_engine)() as session:
            assert await guard.check_in_session(session)
    finally:
        await unrelated_engine.dispose()


@pytest.mark.asyncio
async def test_transaction_guard_preserves_custom_run_lookup(pooled_database):
    db = pooled_database
    await db.runs.put("run", thread_id="thread", user_id="alice", status="error")

    class RejectingRunRepository(RunRepository):
        async def get(self, run_id, *, user_id):
            assert (run_id, user_id) == ("run", "alice")
            return None

    custom = RejectingRunRepository(async_sessionmaker(db.engine, expire_on_commit=False))
    guard = RecoveryTerminalPublisher(db.events, custom).lifecycle_guard(thread_id="thread", run_id="run", user_id="alice")
    with pytest.raises(RunEventLifecycleRejected):
        await db.events.put_if_absent(thread_id="thread", run_id="run", event_type="run.terminal", category="trace", lifecycle_guard=guard)
    assert await db.events.list_events("thread", "run", user_id="alice") == []


@pytest.mark.asyncio
async def test_memory_guard_does_not_block_another_thread():
    store = MemoryRunEventStore()
    entered, release = asyncio.Event(), asyncio.Event()

    async def guard():
        entered.set()
        await release.wait()
        return True

    pending = asyncio.create_task(store.put_if_absent(thread_id="slow", run_id="run", event_type="run.terminal", category="trace", lifecycle_guard=guard))
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        await asyncio.wait_for(store.put_if_absent(thread_id="other", run_id="run", event_type="run.terminal", category="trace"), timeout=1)
        assert await asyncio.wait_for(store.delete_by_run("other", "run"), timeout=1) == 1
        assert await asyncio.wait_for(store.delete_by_thread("other"), timeout=1) == 0
    finally:
        release.set()
        await pending
