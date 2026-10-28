"""History seed grants retain thread lifecycle and reservation fencing."""

import json
import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from support.postgres import asyncpg_test_url

from deerflow.persistence.models.run_event import RunEventRow, RunEventThreadSeqRow
from deerflow.persistence.run.model import CompletedRunSnapshotRow, RunChangeClockRow, RunProducerPolicyRow, RunRow
from deerflow.persistence.run.sql import RunRepository
from deerflow.persistence.thread_meta.model import ThreadMetaRow
from deerflow.persistence.thread_meta.sql import ThreadMetaRepository
from deerflow.runtime import RunManager
from deerflow.runtime.events import producer
from deerflow.runtime.events.store.db import DbRunEventStore
from deerflow.runtime.journal import build_checkpoint_history_seed_events
from deerflow.runtime.runs.schemas import ThreadOperationKind


@pytest_asyncio.fixture
async def seed_db():
    uri = os.environ.get("TEST_POSTGRES_URI")
    if not uri:
        pytest.skip("requires TEST_POSTGRES_URI")
    schema = "history_seed_" + uuid4().hex
    engine = create_async_engine(asyncpg_test_url(uri), pool_size=1, max_overflow=0, pool_timeout=2, connect_args={"server_settings": {"search_path": schema}})
    sf = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as conn:
            await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
            await conn.run_sync(
                lambda c: RunRow.metadata.create_all(
                    c, tables=[RunRow.__table__, RunChangeClockRow.__table__, CompletedRunSnapshotRow.__table__, RunProducerPolicyRow.__table__, RunEventRow.__table__, RunEventThreadSeqRow.__table__, ThreadMetaRow.__table__]
                )
            )
            await conn.execute(text("INSERT INTO run_producer_policy(id,strict) VALUES (1,true)"))
        runs = RunRepository(sf)
        threads = ThreadMetaRepository(sf)
        thread = await threads.create("thread", user_id="alice")
        yield SimpleNamespace(
            uri=asyncpg_test_url(uri), schema=schema, engine=engine, sf=sf, runs=runs, threads=threads, thread=thread, manager=RunManager(store=runs, worker_id="host"), events=DbRunEventStore(sf, producer_fencing="strict")
        )
    finally:
        async with engine.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await engine.dispose()


def history():
    return build_checkpoint_history_seed_events(
        [HumanMessage(id="h1", content="one"), AIMessage(id="a1", content="answer"), HumanMessage(id="h2", content="two"), AIMessage(id="a2", content="answer two")], thread_id="thread", run_id_prefix="checkpoint-seed-thread"
    )


@pytest.mark.asyncio
async def test_host_seed_commits_multiple_synthetic_turns(seed_db):
    db = seed_db
    async with db.manager.reserve_thread_operation("thread", kind=ThreadOperationKind.checkpoint_write, user_id="alice") as reservation:
        authority = producer.history_seed_authority(reservation, db.thread, seed_kind="checkpoint")
        with producer.producer_scope(authority):
            rows = await db.events.put_batch(history())
    assert [row["run_id"] for row in rows] == ["checkpoint-seed-thread-1", "checkpoint-seed-thread-1", "checkpoint-seed-thread-2", "checkpoint-seed-thread-2"]
    assert [row["seq"] for row in rows] == [1, 2, 3, 4]
    assert all(row["user_id"] == "alice" for row in rows)


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["thread", "owner", "incarnation", "reservation", "worker", "revision", "run_id", "category", "type"])
async def test_invalid_seed_grant_rejects_whole_batch(seed_db, mutation):
    db = seed_db
    async with db.manager.reserve_thread_operation("thread", kind=ThreadOperationKind.checkpoint_write, user_id="alice") as reservation:
        authority = producer.history_seed_authority(reservation, db.thread, seed_kind="checkpoint")
        batch = history()
        if mutation == "thread":
            batch[-1]["thread_id"] = "other"
        elif mutation == "owner":
            batch[-1]["user_id"] = "mallory"
        elif mutation == "incarnation":
            authority = replace(authority, thread_incarnation="stale")
        elif mutation == "reservation":
            authority = replace(authority, reservation_incarnation="stale")
        elif mutation == "worker":
            authority = replace(authority, owner_worker_id="other")
        elif mutation == "revision":
            authority = replace(authority, retention_revision=99)
        elif mutation == "run_id":
            batch[-1]["run_id"] = "checkpoint-seed-thread-arbitrary"
        elif mutation == "category":
            batch[-1]["category"] = "trace"
        else:
            batch[-1]["event_type"] = "run.terminal"
        with producer.producer_scope(authority), pytest.raises((producer.RunEventProducerRejected, ValueError)):
            await db.events.put_batch(batch)
    async with db.sf() as session:
        assert await session.scalar(select(RunEventRow.id).limit(1)) is None
        assert await session.scalar(select(RunEventThreadSeqRow.seq).limit(1)) is None


@pytest.mark.asyncio
async def test_metadata_and_prefix_do_not_authorize_seeding(seed_db):
    with pytest.raises(producer.RunEventProducerRejected):
        await seed_db.events.put_batch(history())


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["release", "recreate", "delete_events", "expire", "takeover"])
async def test_seed_grant_cannot_outlive_its_lifecycle(seed_db, change):
    db = seed_db
    async with db.manager.reserve_thread_operation("thread", kind=ThreadOperationKind.checkpoint_write, user_id="alice") as reservation:
        authority = producer.history_seed_authority(reservation, db.thread, seed_kind="checkpoint")
        if change == "release":
            await db.runs.delete_thread_operation(reservation.run_id, user_id="alice")
        elif change == "recreate":
            await db.threads.delete("thread", user_id="alice")
            await db.threads.create("thread", user_id="alice")
        elif change == "delete_events":
            await db.events.delete_by_thread("thread", user_id="alice")
            assert await db.threads.get("thread", user_id="alice") is not None
        else:
            async with db.sf() as session, session.begin():
                await session.execute(update(RunRow).where(RunRow.run_id == reservation.run_id).values(lease_expires_at=datetime.now(UTC) - timedelta(seconds=60)))
            if change == "takeover":
                assert await db.runs.claim_for_takeover(reservation.run_id, grace_seconds=0, error="expired")
        with producer.producer_scope(authority), pytest.raises(producer.RunEventProducerRejected):
            await db.events.put_batch(history())
    assert await db.events.list_messages("thread", user_id=None) == []


@pytest.mark.asyncio
async def test_trigger_independently_checks_seed_grant(seed_db):
    db = seed_db
    async with db.manager.reserve_thread_operation("thread", kind=ThreadOperationKind.checkpoint_write, user_id="alice") as reservation:
        authority = producer.history_seed_authority(reservation, db.thread, seed_kind="checkpoint")
        async with db.sf() as session, session.begin():
            await session.execute(text("SELECT set_config('deerflow.event_authority', :value, true)"), {"value": json.dumps(authority.to_storage())})
            session.add(RunEventRow(thread_id="thread", run_id="checkpoint-seed-thread-1", user_id="alice", event_type="llm.human.input", category="message", seq=1))
        await db.events.delete_by_thread("thread", user_id="alice")
        with pytest.raises(DBAPIError):
            async with db.sf() as session, session.begin():
                await session.execute(text("SELECT set_config('deerflow.event_authority', :value, true)"), {"value": json.dumps(authority.to_storage())})
                session.add(RunEventRow(thread_id="thread", run_id="checkpoint-seed-thread-1", user_id="alice", event_type="llm.human.input", category="message", seq=2))
    assert await db.events.list_messages("thread", user_id=None) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("seed_first", [False, True])
@pytest.mark.parametrize("delete_run", [False, True])
async def test_cross_process_seed_and_delete_serialize_at_event_commit(seed_db, seed_first, delete_run):
    from support.history_seed_process import HistorySeedActors
    from support.producer_process import receive

    db = seed_db
    async with db.manager.reserve_thread_operation("thread", kind=ThreadOperationKind.checkpoint_write, user_id="alice") as reservation:
        authority = producer.history_seed_authority(reservation, db.thread, seed_kind="checkpoint")
        actors = HistorySeedActors(db.uri, db.schema, {"authority": authority.to_storage(), "events": history(), "delete_run": delete_run}, db.engine)
        try:
            first, first_pid = await actors.start("seed_locked" if seed_first else "delete_locked")
            first.send("go")
            assert (await receive(first))["stage"] == ("admitted" if seed_first else "revoked_uncommitted")
            second, second_pid = await actors.start("delete_locked" if seed_first else "seed")
            second.send("go")
            await actors.blocked(second_pid, first_pid)
            first.send("go")
            result = await receive(first)
            assert result.get("written" if seed_first else "deleted") is True, result
            if seed_first:
                assert (await receive(second))["stage"] == "revoked_uncommitted"
                second.send("go")
                assert (await receive(second))["deleted"] is True
            else:
                assert (await receive(second))["written"] is False
            # Metadata deliberately remains during the cleanup gap; existence
            # alone must never authorize resurrection after event deletion.
            assert await db.threads.get("thread", user_id="alice") is not None
            remaining = await db.events.list_messages("thread", user_id=None)
            assert [row["content"]["id"] for row in remaining] == (["h2", "a2"] if seed_first and delete_run else [])
        finally:
            await actors.close()


@pytest.mark.asyncio
async def test_cross_process_first_run_cannot_overtake_seed_reservation(seed_db):
    from support.history_seed_process import HistorySeedActors
    from support.producer_process import receive

    db = seed_db
    async with db.manager.reserve_thread_operation("thread", kind=ThreadOperationKind.checkpoint_write, user_id="alice") as reservation:
        authority = producer.history_seed_authority(reservation, db.thread, seed_kind="checkpoint")
        actors = HistorySeedActors(db.uri, db.schema, {"authority": authority.to_storage(), "events": history()}, db.engine)
        try:
            admission, _ = await actors.start("admission")
            admission.send("go")
            assert (await receive(admission))["admitted"] is False
            with producer.producer_scope(authority):
                await db.events.put_batch(history())
        finally:
            await actors.close()
    record = await db.manager.create_or_reject("thread", user_id="alice")
    with producer.producer_scope(producer.producer_authority(record)):
        result = await db.events.put(thread_id="thread", run_id=record.run_id, event_type="llm.human.input", category="message", content={"type": "human", "id": "new"})
    assert result["seq"] == 5


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["owner", "incarnation", "epoch", "kind", "prefix", "type", "category", "missing_incarnation"])
async def test_strict_trigger_rejects_forged_or_overbroad_seed_grants(seed_db, mutation):
    db = seed_db
    async with db.manager.reserve_thread_operation("thread", kind=ThreadOperationKind.checkpoint_write, user_id="alice") as reservation:
        grant = producer.history_seed_authority(reservation, db.thread, seed_kind="checkpoint").to_storage()
        event = {"thread_id": "thread", "run_id": "checkpoint-seed-thread-1", "user_id": "alice", "event_type": "llm.human.input", "category": "message"}
        if mutation == "owner":
            grant["user_id"] = "mallory"
        elif mutation == "incarnation":
            grant["thread_incarnation"] = "stale"
        elif mutation == "epoch":
            grant["producer_epoch"] = "stale"
        elif mutation == "kind":
            grant["seed_kind"] = "arbitrary"
        elif mutation == "prefix":
            event["run_id"] = "checkpoint-seed-thread-arbitrary"
        elif mutation == "type":
            event["event_type"] = "run.terminal"
        elif mutation == "category":
            event["category"] = "trace"
        else:
            async with db.sf() as session, session.begin():
                await session.execute(update(ThreadMetaRow).where(ThreadMetaRow.thread_id == "thread").values(incarnation=None))
            del grant["thread_incarnation"]
        with pytest.raises(DBAPIError):
            async with db.sf() as session, session.begin():
                await session.execute(text("SELECT set_config('deerflow.event_authority', :value, true)"), {"value": json.dumps(grant)})
                session.add(RunEventRow(**event, seq=1))
    assert await db.events.list_messages("thread", user_id=None) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("trigger_active", [False, True])
async def test_seed_lease_is_rechecked_after_metadata_lock_wait(seed_db, trigger_active):
    import asyncio

    from support.history_seed_process import HistorySeedActors
    from support.producer_process import receive

    db = seed_db
    async with db.manager.reserve_thread_operation("thread", kind=ThreadOperationKind.checkpoint_write, user_id="alice") as reservation:
        async with db.sf() as session, session.begin():
            await session.execute(update(RunProducerPolicyRow).values(strict=trigger_active))
            await session.execute(update(RunRow).where(RunRow.run_id == reservation.run_id).values(lease_expires_at=datetime.now(UTC) + timedelta(seconds=3)))
        authority = producer.history_seed_authority(reservation, db.thread, seed_kind="checkpoint")
        actors = HistorySeedActors(db.uri, db.schema, {"authority": authority.to_storage(), "events": history()}, db.engine)
        try:
            holder, holder_pid = await actors.start("metadata_locked")
            holder.send("go")
            assert (await receive(holder))["stage"] == "metadata_held"
            seed, seed_pid = await actors.start("seed")
            seed.send("go")
            await actors.blocked(seed_pid, holder_pid)
            async with asyncio.timeout(8):
                while True:
                    async with db.sf() as session:
                        expired = await session.scalar(select(RunRow.lease_expires_at <= text("clock_timestamp()")).where(RunRow.run_id == reservation.run_id))
                    if expired:
                        break
                    await asyncio.sleep(0.01)
            holder.send("go")
            assert (await receive(holder))["released"] is True
            assert (await receive(seed))["written"] is False
            assert await db.events.list_messages("thread", user_id=None) == []
        finally:
            await actors.close()


@pytest.mark.asyncio
async def test_deleting_synthetic_turn_revokes_outstanding_seed_grant(seed_db):
    db = seed_db
    async with db.manager.reserve_thread_operation("thread", kind=ThreadOperationKind.checkpoint_write, user_id="alice") as reservation:
        authority = producer.history_seed_authority(reservation, db.thread, seed_kind="checkpoint")
        with producer.producer_scope(authority):
            await db.events.put_batch(history())
        assert await db.events.delete_by_run("thread", "checkpoint-seed-thread-1", user_id="alice") == 2
        with producer.producer_scope(authority), pytest.raises(producer.RunEventProducerRejected):
            await db.events.put_batch(history()[:2])
    assert [row["content"]["id"] for row in await db.events.list_messages("thread", user_id=None)] == ["h2", "a2"]


@pytest.mark.asyncio
async def test_thread_create_returns_its_committed_incarnation_after_recreation(seed_db, monkeypatch):
    import asyncio

    from sqlalchemy.ext.asyncio import AsyncSession

    db = seed_db
    committed = asyncio.Event()
    release = asyncio.Event()
    original_commit = AsyncSession.commit
    creator = None

    async def pause_after_commit(session):
        await original_commit(session)
        if asyncio.current_task() is creator:
            committed.set()
            await release.wait()

    monkeypatch.setattr(AsyncSession, "commit", pause_after_commit)
    creator = asyncio.create_task(db.threads.create("branch", user_id="alice"))
    try:
        async with asyncio.timeout(5):
            await committed.wait()
        original = await db.threads.get("branch", user_id="alice")
        await db.threads.delete("branch", user_id="alice")
        replacement = await db.threads.create("branch", user_id="alice")
        assert replacement["incarnation"] != original["incarnation"]
        release.set()
        created = await asyncio.wait_for(asyncio.shield(creator), timeout=5)
        assert created["incarnation"] == original["incarnation"]
    finally:
        release.set()
        await asyncio.wait_for(asyncio.gather(creator, return_exceptions=True), timeout=5)
