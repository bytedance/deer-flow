"""Off-mode INSERT contention and atomic cutover on independent PostgreSQL sessions."""

import asyncio
import os
import time

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from support.postgres import asyncpg_test_url
from test_run_producer_cutover import cutover_db as cutover_db

from deerflow.persistence.run.producer import activate_producer_fencing
from deerflow.persistence.run.sql import RunRepository
from deerflow.runtime.events.store.db import DbRunEventStore

INSERT = text("INSERT INTO run_events(thread_id,run_id,user_id,event_type,category,content,event_metadata,seq,created_at) VALUES ('thread','run','alice','middleware:off','trace','','{}',:seq,clock_timestamp())")
GATE = "SELECT pg_advisory_xact_lock(hashtext('deerflow.event_fence/' || current_schema())::bigint)"


@pytest_asyncio.fixture(params=["missing", "false"])
async def off_db(cutover_db, request):
    if request.param == "false":
        async with cutover_db[0].begin() as conn:
            await conn.execute(text("INSERT INTO run_producer_policy(id,strict) VALUES (1,false)"))
    return cutover_db


def peer_engine(schema, **kwargs):
    return create_async_engine(asyncpg_test_url(os.environ["TEST_POSTGRES_URI"]), pool_size=2, max_overflow=0, connect_args={"server_settings": {"search_path": schema, "statement_timeout": "6000"}}, **kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize(("lock", "api"), [("thread", False), ("run", False), ("run", True)])
async def test_off_insert_ignores_trigger_added_thread_and_run_locks(off_db, lock, api):
    engine, sf, schema = off_db
    await RunRepository(sf).put("run", thread_id="thread", user_id="alice", status="success")
    holder = peer_engine(schema)
    try:
        async with holder.begin() as conn:
            await conn.execute(text("SELECT pg_advisory_xact_lock(hashtext('thread')::bigint)" if lock == "thread" else "SELECT run_id FROM runs WHERE run_id='run' FOR UPDATE"))
            async with engine.begin() as writer:
                await writer.execute(text("SET LOCAL lock_timeout='250ms'"))
                if not api:
                    await writer.execute(INSERT, {"seq": 1})
                    locks = (await writer.execute(text("SELECT mode FROM pg_locks WHERE pid=pg_backend_pid() AND locktype='advisory'"))).scalars().all()
                    assert locks == ["ShareLock"]
            if api:
                await asyncio.wait_for(DbRunEventStore(sf).put_batch([dict(thread_id="thread", run_id="run", user_id="alice", event_type="middleware:off", category="trace")]), 1)
        assert len(await DbRunEventStore(sf).list_events("thread", "run", user_id="alice")) == 1
    finally:
        await holder.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "SERIALIZABLE"])
async def test_off_snapshot_isolation_is_fail_closed(off_db, isolation):
    _, sf, schema = off_db
    await RunRepository(sf).put("run", thread_id="thread", user_id="alice", status="success")
    writer = peer_engine(schema, isolation_level=isolation)
    try:
        with pytest.raises(DBAPIError) as caught:
            async with writer.begin() as conn:
                await conn.execute(INSERT, {"seq": 1})
        assert caught.value.orig.sqlstate == "0A000"
    finally:
        await writer.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("writer_first", [False, True])
async def test_off_cutover_serializes_without_acquiring_prior_locks(off_db, writer_first):
    engine, sf, schema = off_db
    await RunRepository(sf).put("run", thread_id="thread", user_id="alice", status="success")
    reached, release = asyncio.Event(), asyncio.Event()
    pid = {}

    class GatedCutover(AsyncSession):
        async def execute(self, statement, *args, **kwargs):
            if str(statement) == GATE:
                pid["cutover"] = await self.scalar(text("SELECT pg_backend_pid()"))
                if writer_first:
                    reached.set()
                    await release.wait()
                    return await super().execute(statement, *args, **kwargs)
                result = await super().execute(statement, *args, **kwargs)
                reached.set()
                await release.wait()
                return result
            return await super().execute(statement, *args, **kwargs)

    activation = asyncio.create_task(activate_producer_fencing(async_sessionmaker(engine, class_=GatedCutover, expire_on_commit=False), cutover_id="off-race"))
    peer = peer_engine(schema)
    writer_task = None
    try:
        # Production's stopped-client check runs before these racing peers
        # connect. Exercise the lock even against an unexpected reconnect.
        await asyncio.wait_for(reached.wait(), 3)
        async with peer.connect() as writer, peer.connect() as observer:
            writer_pid = await writer.scalar(text("SELECT pg_backend_pid()"))
            if writer_first:
                await writer.execute(INSERT, [{"seq": 1}, {"seq": 2}])
                release.set()
                await blocked_peer(observer, pid["cutover"], writer_pid)
                await writer.commit()
                await asyncio.wait_for(activation, 3)
            else:
                # Holding earlier locks makes reverse lock acquisition fail
                # visibly: the off writer must abort at the gate after cutover.
                await observer.execute(text("SELECT pg_advisory_xact_lock(hashtext('thread')::bigint)"))
                await observer.execute(text("SELECT run_id FROM runs WHERE run_id='run' FOR UPDATE"))
                writer_task = asyncio.create_task(writer.execute(INSERT, [{"seq": 1}, {"seq": 2}]))
                try:
                    await blocked_peer(observer, writer_pid, pid["cutover"])
                    release.set()
                    await asyncio.wait_for(activation, 3)
                    with pytest.raises(DBAPIError) as caught:
                        await asyncio.wait_for(writer_task, 3)
                    assert caught.value.orig.sqlstate == "40001"
                finally:
                    release.set()
                    await observer.rollback()
                    await asyncio.wait_for(asyncio.gather(writer_task, return_exceptions=True), 3)
                    await writer.rollback()
        async with engine.connect() as conn:
            assert await conn.scalar(text("SELECT count(*) FROM run_events")) == (2 if writer_first else 0)
            assert await conn.scalar(text("SELECT strict FROM run_producer_policy WHERE id=1")) is True
    finally:
        release.set()
        for task in (activation, writer_task):
            if task is not None:
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        await peer.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "SERIALIZABLE"])
async def test_retained_off_snapshot_cannot_bypass_committed_cutover(off_db, isolation):
    engine, sf, schema = off_db
    await RunRepository(sf).put("run", thread_id="thread", user_id="alice", status="success")
    reached, release = asyncio.Event(), asyncio.Event()

    class GatedCutover(AsyncSession):
        async def execute(self, statement, *args, **kwargs):
            if str(statement) == GATE:
                reached.set()
                await release.wait()
            return await super().execute(statement, *args, **kwargs)

    activation = asyncio.create_task(activate_producer_fencing(async_sessionmaker(engine, class_=GatedCutover), cutover_id="snapshot-race"))
    peer = peer_engine(schema, isolation_level=isolation)
    try:
        await asyncio.wait_for(reached.wait(), 3)
        async with peer.connect() as writer:
            assert not await writer.scalar(text("SELECT strict FROM run_producer_policy WHERE id=1"))
            release.set()
            await asyncio.wait_for(activation, 3)
            # The old snapshot still says off even after activation commits.
            assert not await writer.scalar(text("SELECT strict FROM run_producer_policy WHERE id=1"))
            with pytest.raises(DBAPIError) as caught:
                await writer.execute(INSERT, [{"seq": 1}, {"seq": 2}])
                await writer.commit()
            assert caught.value.orig.sqlstate == "0A000"
            await writer.rollback()
        async with engine.connect() as conn:
            assert await conn.scalar(text("SELECT count(*) FROM run_events")) == 0
    finally:
        release.set()
        await asyncio.wait_for(asyncio.gather(activation, return_exceptions=True), 3)
        await peer.dispose()


@pytest.mark.asyncio
async def test_off_read_uncommitted_remains_accepted(off_db):
    _, sf, schema = off_db
    await RunRepository(sf).put("run", thread_id="thread", user_id="alice", status="success")
    peer = peer_engine(schema)
    try:
        async with peer.begin() as writer:
            await writer.execute(text("SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED"))
            await writer.execute(INSERT, {"seq": 1})
    finally:
        await peer.dispose()


async def blocked_peer(observer, waiter, holder):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if holder in await observer.scalar(text("SELECT pg_blocking_pids(:pid)"), {"pid": waiter}):
            return
        await asyncio.sleep(0.01)
    raise AssertionError("Expected PostgreSQL blocking relationship was not observed")
