"""Real PostgreSQL, actual Journal/Store APIs, independent OS-process races."""

import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from support.producer_process import ProducerActors, receive

from deerflow.persistence.models.run_event import RunEventRow, RunEventThreadSeqRow
from deerflow.persistence.run.model import CompletedRunSnapshotRow, RunChangeClockRow, RunProducerPolicyRow, RunRow
from deerflow.persistence.run.sql import RunRepository
from deerflow.runtime.events.producer import producer_authority, producer_scope
from deerflow.runtime.events.store.db import DbRunEventStore


@pytest_asyncio.fixture
async def producer_pg():
    uri = os.environ.get("TEST_POSTGRES_URI")
    if not uri:
        pytest.skip("requires TEST_POSTGRES_URI")
    schema = "producer_race_" + uuid4().hex
    engine = create_async_engine(uri, pool_size=1, max_overflow=0, pool_timeout=1, connect_args={"server_settings": {"search_path": schema}})
    sf = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        await conn.run_sync(
            lambda c: RunRow.metadata.create_all(c, tables=[RunRow.__table__, RunChangeClockRow.__table__, RunEventRow.__table__, RunEventThreadSeqRow.__table__, CompletedRunSnapshotRow.__table__, RunProducerPolicyRow.__table__])
        )
        # This fixture tests contention after activation; cutover itself has
        # separate tests requiring all other DB clients to be stopped.
        await conn.execute(text("INSERT INTO run_producer_policy(id,strict,cutover_id) VALUES (1,true,'race-fixture')"))
    runs = RunRepository(sf)
    await runs.put("run", thread_id="thread", user_id="alice", status="running", owner_worker_id="old", lease_expires_at=(datetime.now(UTC) - timedelta(seconds=60)).isoformat())
    identity = await runs.get("run", user_id="alice")
    actors = ProducerActors(uri, schema, identity, engine)
    try:
        yield SimpleNamespace(engine=engine, sf=sf, runs=runs, events=DbRunEventStore(sf, producer_fencing="strict"), identity=identity, actors=actors)
    finally:
        await actors.close()
        async with engine.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await engine.dispose()


@pytest.mark.asyncio
async def test_writer_first_takeover_waits_for_real_event_commit(producer_pg):
    db = producer_pg
    writer, writer_pid = await db.actors.start("writer_locked")
    writer.send("go")
    assert (await receive(writer))["stage"] == "admitted"
    taker, taker_pid = await db.actors.start("takeover")
    taker.send("go")
    await db.actors.blocked(taker_pid, writer_pid)
    writer.send("go")
    assert (await receive(writer))["written"] is True
    assert (await receive(taker))["taken"] is True
    events = await db.events.list_events("thread", "run", user_id="alice")
    assert [event["event_type"] for event in events] == ["middleware:race", "run.delivery", "run.terminal"]


@pytest.mark.asyncio
async def test_takeover_first_writer_waits_then_rejects_old_epoch(producer_pg):
    db = producer_pg
    taker, taker_pid = await db.actors.start("takeover_locked")
    taker.send("go")
    assert (await receive(taker))["stage"] == "revoked_uncommitted"
    writer, writer_pid = await db.actors.start("writer")
    writer.send("go")
    await db.actors.blocked(writer_pid, taker_pid)
    taker.send("go")
    assert (await receive(taker))["taken"] is True
    assert (await receive(writer))["written"] is False
    assert [event["event_type"] for event in await db.events.list_events("thread", "run", user_id="alice")] == ["run.delivery", "run.terminal"]


@pytest.mark.asyncio
@pytest.mark.parametrize("delete", [False, True])
async def test_delayed_journal_cannot_commit_after_recovery_publication(producer_pg, delete):
    db = producer_pg
    writer, _ = await db.actors.start("writer_late")
    writer.send("go")
    assert (await receive(writer))["stage"] == "before_admission"
    taker, _ = await db.actors.start("takeover")
    taker.send("go")
    assert (await receive(taker))["taken"] is True
    if delete:
        await db.events.delete_by_run("thread", "run", user_id="alice")
    writer.send("go")
    assert (await receive(writer))["written"] is False
    types = [event["event_type"] for event in await db.events.list_events("thread", "run", user_id="alice")]
    assert types == ([] if delete else ["run.delivery", "run.terminal"])


@pytest.mark.asyncio
async def test_delete_first_waiting_journal_cannot_resurrect_events(producer_pg):
    db = producer_pg
    deleter, delete_pid = await db.actors.start("delete_locked")
    deleter.send("go")
    assert (await receive(deleter))["stage"] == "deleted_uncommitted"
    writer, writer_pid = await db.actors.start("writer")
    writer.send("go")
    await db.actors.blocked(writer_pid, delete_pid)
    deleter.send("go")
    assert (await receive(deleter))["deleted"] is True
    assert (await receive(writer))["written"] is False
    assert await db.events.list_events("thread", "run", user_id="alice") == []


@pytest.mark.asyncio
async def test_fenced_write_uses_one_connection_and_never_needs_change_clock(producer_pg):
    db = producer_pg
    # pool_size=1, max_overflow=0: a nested guard Session would self-block.
    with producer_scope(producer_authority(SimpleNamespace(**db.identity))):
        result = await db.events.put_batch([{"thread_id": "thread", "run_id": "run", "event_type": "middleware:pool", "category": "trace"}])
    assert result[0]["seq"] == 1


@pytest.mark.asyncio
async def test_writer_can_commit_while_deletion_holds_clock_waiting_for_thread(producer_pg):
    db = producer_pg
    writer, writer_pid = await db.actors.start("writer_locked")
    writer.send("go")
    assert (await receive(writer))["stage"] == "admitted"
    deleter, delete_pid = await db.actors.start("delete_waiting")
    deleter.send("go")
    assert (await receive(deleter))["stage"] == "clock_held"
    deleter.send("go")
    await db.actors.blocked(delete_pid, writer_pid)
    # A writer acquiring C after T/R would deadlock against this deleter.
    writer.send("go")
    assert (await receive(writer))["written"] is True
    assert (await receive(deleter))["deleted"] is True
    assert await db.events.list_events("thread", "run", user_id="alice") == []


@pytest.mark.asyncio
async def test_cross_process_same_id_recreation_rejects_old_incarnation(producer_pg):
    db = producer_pg
    writer, _ = await db.actors.start("writer_late")
    writer.send("go")
    assert (await receive(writer))["stage"] == "before_admission"
    await db.runs.delete("run", user_id="alice")
    new = await db.runs.put("run", thread_id="thread", user_id="alice", status="success", owner_worker_id="old")
    assert new["run_incarnation"] != db.identity["run_incarnation"]
    writer.send("go")
    assert (await receive(writer))["written"] is False
    assert await db.events.list_events("thread", "run", user_id="alice") == []
