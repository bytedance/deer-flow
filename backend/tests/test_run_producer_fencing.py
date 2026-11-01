"""Producer revocation must fence all event entry points, not only a new API."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from support.postgres import asyncpg_test_url

from deerflow.persistence.models.run_event import RunEventRow, RunEventThreadSeqRow
from deerflow.persistence.run.model import CompletedRunSnapshotRow, RunChangeClockRow, RunRow
from deerflow.persistence.run.sql import RunRepository
from deerflow.runtime.events.store.base import RunEventStoreNotCommittedError
from deerflow.runtime.events.store.db import DbRunEventStore


@pytest_asyncio.fixture(params=["sqlite", "postgresql"])
async def producer_db(request, tmp_path):
    schema = None
    if request.param == "postgresql":
        uri = os.environ.get("TEST_POSTGRES_URI")
        if not uri:
            pytest.skip("requires TEST_POSTGRES_URI")
        schema = "producer_" + uuid4().hex
        engine = create_async_engine(asyncpg_test_url(uri), connect_args={"server_settings": {"search_path": schema, "application_name": schema}})
    else:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'producer.db'}")
    try:
        async with engine.begin() as conn:
            if schema:
                await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
            await conn.run_sync(lambda c: RunRow.metadata.create_all(c, tables=[RunRow.__table__, RunChangeClockRow.__table__, RunEventRow.__table__, RunEventThreadSeqRow.__table__, CompletedRunSnapshotRow.__table__]))
        sf = async_sessionmaker(engine, expire_on_commit=False)
        yield SimpleNamespace(engine=engine, sf=sf, runs=RunRepository(sf), events=DbRunEventStore(sf), backend=request.param)
    finally:
        if schema:
            async with engine.begin() as conn:
                await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await engine.dispose()


async def admit(db, *, run_id="run", thread_id="thread", expired=False, status="running", owner="owner"):
    await db.runs.put(run_id, thread_id=thread_id, user_id="alice", status=status, owner_worker_id=owner, lease_expires_at=(datetime.now(UTC) + timedelta(seconds=-60 if expired else 60)).isoformat())
    return await db.runs.get(run_id, user_id="alice")


def batch(run_id="run", thread_id="thread"):
    return [{"thread_id": thread_id, "run_id": run_id, "user_id": "alice", "event_type": "middleware:test", "category": "trace"}]


@pytest.mark.asyncio
async def test_new_admission_persists_nonreusable_producer_identity(producer_db):
    db = producer_db
    old = await admit(db)
    assert old.get("run_incarnation"), "new Run has no durable incarnation"
    assert old.get("producer_epoch"), "new Run has no durable producer identity"
    assert old.get("producer_state") == "open"
    await db.runs.delete("run", user_id="alice")
    new = await admit(db)
    assert new["run_incarnation"] != old["run_incarnation"]
    assert new["producer_epoch"] != old["producer_epoch"]


@pytest.mark.asyncio
async def test_takeover_atomically_revokes_producer(producer_db):
    db = producer_db
    row = await admit(db, expired=True)
    assert await db.runs.claim_for_takeover("run", grace_seconds=0, error="expired")
    current = await db.runs.get("run", user_id="alice")
    assert current.get("producer_state") == "revoked", "takeover left old event producer admitted"
    assert current["producer_epoch"] != row["producer_epoch"]


@pytest.mark.asyncio
async def test_old_authority_cannot_write_after_takeover(producer_db):
    from deerflow.runtime.events.producer import producer_authority, producer_scope

    db = producer_db
    row = await admit(db, expired=True)
    authority = producer_authority(SimpleNamespace(**row))
    assert await db.runs.claim_for_takeover("run", grace_seconds=0, error="expired")
    with producer_scope(authority):
        with pytest.raises(RunEventStoreNotCommittedError):
            await db.events.put_batch(batch())
    assert await db.events.list_events("thread", "run", user_id="alice") == []


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["epoch", "incarnation", "mixed_run", "mixed_owner", "reserved_type"])
async def test_invalid_batch_commits_no_rows_or_watermark(producer_db, mutation):
    from dataclasses import replace

    from deerflow.runtime.events.producer import producer_authority, producer_scope

    db = producer_db
    authority = producer_authority(SimpleNamespace(**await admit(db)))
    events = batch() + batch()
    if mutation == "epoch":
        authority = replace(authority, producer_epoch="obsolete")
    elif mutation == "incarnation":
        authority = replace(authority, run_incarnation="obsolete")
    elif mutation == "mixed_run":
        events[1]["run_id"] = "other"
    elif mutation == "mixed_owner":
        events[1]["user_id"] = "mallory"
    else:
        events[1]["event_type"] = "run.terminal"
    with producer_scope(authority):
        with pytest.raises(RunEventStoreNotCommittedError):
            await db.events.put_batch(events)
    async with db.sf() as session:
        assert await session.scalar(select(RunEventRow.id).limit(1)) is None
        assert await session.scalar(select(RunEventThreadSeqRow.seq).limit(1)) is None


@pytest.mark.asyncio
async def test_terminal_status_does_not_close_live_producer(producer_db):
    from deerflow.runtime.events.producer import producer_authority, producer_scope

    db = producer_db
    authority = producer_authority(SimpleNamespace(**await admit(db)))
    assert (await db.runs.finalize_if_not_cancelled("run", status="success", owner_worker_id="owner")).finalized
    with producer_scope(authority):
        written = await db.events.put_batch(batch())
    assert written[0]["seq"] == 1
    assert (await db.runs.get("run", user_id="alice"))["producer_state"] == "open"


@pytest.mark.asyncio
@pytest.mark.parametrize("delete", ["events_run", "events_thread", "run"])
async def test_delete_fences_old_writer_including_same_id_recreation(producer_db, delete):
    from deerflow.runtime.events.producer import producer_authority, producer_scope

    db = producer_db
    authority = producer_authority(SimpleNamespace(**await admit(db)))
    if delete == "events_run":
        await db.events.delete_by_run("thread", "run", user_id="alice")
    elif delete == "events_thread":
        await db.events.delete_by_thread("thread", user_id="alice")
    else:
        await db.runs.delete("run", user_id="alice")
        await admit(db)
    with producer_scope(authority):
        with pytest.raises(RunEventStoreNotCommittedError):
            await db.events.put_batch(batch())
    assert await db.events.list_events("thread", "run", user_id="alice") == []


@pytest.mark.asyncio
async def test_explicit_close_is_idempotent_and_never_reopens(producer_db):
    from deerflow.runtime.events.producer import producer_authority, producer_scope

    db = producer_db
    authority = producer_authority(SimpleNamespace(**await admit(db)))
    assert await db.events.close_producer(authority)
    assert await db.events.close_producer(authority)
    with producer_scope(authority):
        with pytest.raises(RunEventStoreNotCommittedError):
            await db.events.put_batch(batch())
    await db.runs.put("run", thread_id="thread", user_id="alice", status="success")
    assert (await db.runs.get("run", user_id="alice"))["producer_state"] == "closed"


@pytest.mark.asyncio
@pytest.mark.parametrize("owner,expected", [("owner", "open"), ("peer", "revoked")])
async def test_atomic_admission_preserves_only_local_finalizer(producer_db, owner, expected):
    db = producer_db
    await admit(db, expired=True)
    await db.runs.create_thread_operation_atomic("replacement", thread_id="thread", owner_worker_id=owner, lease_expires_at=None, multitask_strategy="rollback", user_id="alice", grace_seconds=0)
    assert (await db.runs.get("run", user_id="alice")).get("producer_state") == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("admission", ["put", "atomic"])
async def test_manager_binds_committed_identity_without_post_commit_read(producer_db, admission):
    from deerflow.runtime.events.producer import producer_authority, producer_scope
    from deerflow.runtime.runs.manager import RunManager

    db = producer_db

    class RecreatedAdmission(RunRepository):
        original = None

        async def recreate(self, result):
            self.original = result.copy()
            await super().delete(result["run_id"], user_id="alice")
            await super().put(result["run_id"], thread_id="thread", user_id="alice", status="success", owner_worker_id="owner")

        async def put(self, *args, **kwargs):
            result = await super().put(*args, **kwargs)
            await self.recreate(result)
            return result

        async def create_thread_operation_atomic(self, *args, **kwargs):
            result = await super().create_thread_operation_atomic(*args, **kwargs)
            await self.recreate(result[0])
            return result

        async def get(self, *args, **kwargs):
            raise AssertionError("Admission must not await a later Row read to manufacture authority")

    store = RecreatedAdmission(db.sf)
    manager = RunManager(store=store, worker_id="owner")
    record = await (manager.create("thread", user_id="alice") if admission == "put" else manager.create_or_reject("thread", user_id="alice"))
    assert record.run_incarnation == store.original["run_incarnation"]
    with producer_scope(producer_authority(record)):
        with pytest.raises(RunEventStoreNotCommittedError):
            await db.events.put_batch(batch(run_id=record.run_id))
