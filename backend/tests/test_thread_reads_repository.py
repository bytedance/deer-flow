"""Per-user unread state over the run-change clock (``ThreadReadRepository``).

A thread is unread for a user while one of that user's server-originated runs
in it changed after the user last read it. Runs are written through the real
``RunRepository`` so ``runs.origin_kind`` is derived exactly as in production.
Runs on SQLite, and on Postgres with ``TEST_POSTGRES_URI``.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from contextlib import asynccontextmanager
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from deerflow.persistence.base import Base
from deerflow.persistence.postgres_schema import build_asyncpg_connect_args
from deerflow.persistence.run import RunRepository
from deerflow.persistence.run.model import RunChangeClockRow, RunRow
from deerflow.persistence.thread_reads import ThreadReadMarkerRow, ThreadReadRepository, ThreadReadVersionRow
from deerflow.runtime.run_origin import DEERFLOW_ORIGIN_KEY, make_origin

ALICE = "user-alice"
BOB = "user-bob"
_TABLES = [RunRow, RunChangeClockRow, ThreadReadMarkerRow, ThreadReadVersionRow]


@pytest.fixture(params=["sqlite", "postgres"])
def database_backend(request):
    return request.param


@asynccontextmanager
async def database(tmp_path, *, backend="sqlite"):
    schema = None
    if backend == "postgres":
        uri = os.environ.get("TEST_POSTGRES_URI")
        if not uri:
            pytest.skip("requires TEST_POSTGRES_URI (real Postgres upsert path)")
        parts = urlsplit(uri)
        scheme = "postgresql+asyncpg" if parts.scheme in {"postgres", "postgresql"} else parts.scheme
        query = urlencode([(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key not in {"sslmode", "channel_binding"}])
        schema = f"thread_reads_{uuid.uuid4().hex}"
        engine = create_async_engine(urlunsplit(parts._replace(scheme=scheme, query=query)), connect_args=build_asyncpg_connect_args(schema))
    else:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'thread-reads.db'}")
    try:
        async with engine.begin() as conn:
            if schema:
                await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
            await conn.run_sync(lambda sync: Base.metadata.create_all(sync, tables=[model.__table__ for model in _TABLES]))
        sf = async_sessionmaker(engine, expire_on_commit=False)
        yield sf, RunRepository(sf), ThreadReadRepository(sf)
    finally:
        if schema:
            async with engine.begin() as conn:
                await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()


async def put_run(runs, run_id, thread_id, *, user_id=ALICE, origin=None, status="success"):
    """Write a run as RunManager does; ``origin`` is the server-stamped origin kind."""
    metadata = {DEERFLOW_ORIGIN_KEY: make_origin(origin)} if origin else {}
    await runs.put(run_id, thread_id=thread_id, user_id=user_id, status=status, metadata=metadata)


async def marker(sf, user_id, thread_id):
    async with sf() as session:
        return await session.get(ThreadReadMarkerRow, (user_id, thread_id))


@pytest.mark.asyncio
async def test_server_origin_run_is_unread_until_read_and_again_after_a_new_run(tmp_path, database_backend):
    async with database(tmp_path, backend=database_backend) as (_sf, runs, reads):
        await put_run(runs, "run-1", "sched-thread", origin="schedule")
        assert await reads.unread_thread_ids(user_id=ALICE, thread_ids=["sched-thread"]) == {"sched-thread"}

        await reads.mark_read(user_id=ALICE, thread_id="sched-thread")
        assert await reads.unread_thread_ids(user_id=ALICE, thread_ids=["sched-thread"]) == set()

        await put_run(runs, "run-2", "sched-thread", origin="schedule", status="running")
        assert await reads.unread_thread_ids(user_id=ALICE, thread_ids=["sched-thread"]) == {"sched-thread"}


@pytest.mark.asyncio
async def test_interactive_and_legacy_runs_never_mark_unread(tmp_path, database_backend):
    async with database(tmp_path, backend=database_backend) as (sf, runs, reads):
        await put_run(runs, "run-chat", "chat-thread")
        # A legacy row written before 0032: no origin metadata, origin_kind NULL.
        async with sf() as session:
            session.add(RunRow(run_id="run-legacy", thread_id="legacy-thread", user_id=ALICE, status="success", change_seq=999, metadata_json={}))
            await session.commit()
        assert await reads.unread_thread_ids(user_id=ALICE, thread_ids=["chat-thread", "legacy-thread"]) == set()


@pytest.mark.asyncio
async def test_every_server_origin_kind_marks_unread(tmp_path, database_backend):
    async with database(tmp_path, backend=database_backend) as (_sf, runs, reads):
        for kind in ("schedule", "im_channel", "github", "extension", "mcp_notification"):
            await put_run(runs, f"run-{kind}", f"thread-{kind}", origin=kind)
        ids = [f"thread-{kind}" for kind in ("schedule", "im_channel", "github", "extension", "mcp_notification")]
        assert await reads.unread_thread_ids(user_id=ALICE, thread_ids=ids) == set(ids)


@pytest.mark.asyncio
async def test_mark_read_never_lowers_seen_change_seq(tmp_path, database_backend):
    async with database(tmp_path, backend=database_backend) as (sf, runs, reads):
        await put_run(runs, "run-1", "thread", origin="schedule")
        first = await reads.mark_read(user_id=ALICE, thread_id="thread")
        await put_run(runs, "run-2", "thread", origin="schedule")
        second = await reads.mark_read(user_id=ALICE, thread_id="thread")
        assert second > first

        # A stale read (another device that computed an older position) loses.
        async with sf() as session:
            await session.execute(RunRow.__table__.delete().where(RunRow.run_id == "run-2"))
            await session.commit()
        assert await reads.mark_read(user_id=ALICE, thread_id="thread") == second
        assert (await marker(sf, ALICE, "thread")).seen_change_seq == second


@pytest.mark.asyncio
async def test_concurrent_reads_keep_the_maximum(tmp_path, database_backend):
    async with database(tmp_path, backend=database_backend) as (sf, runs, reads):
        await put_run(runs, "run-1", "thread", origin="schedule")
        await put_run(runs, "run-2", "thread", origin="schedule")
        results = await asyncio.gather(*(reads.mark_read(user_id=ALICE, thread_id="thread") for _ in range(4)))
        stored = (await marker(sf, ALICE, "thread")).seen_change_seq
        assert set(results) == {stored}
        # Exactly one of the four raised the marker, so the clock moved once.
        assert await reads.read_version(user_id=ALICE) == 1


@pytest.mark.asyncio
async def test_mark_read_on_an_already_read_thread_writes_nothing(tmp_path, database_backend):
    async with database(tmp_path, backend=database_backend) as (sf, runs, reads):
        assert await reads.read_version(user_id=ALICE) == 0
        await put_run(runs, "run-1", "thread", origin="schedule")
        await reads.mark_read(user_id=ALICE, thread_id="thread")
        assert await reads.read_version(user_id=ALICE) == 1
        before = await marker(sf, ALICE, "thread")

        await reads.mark_read(user_id=ALICE, thread_id="thread")
        after = await marker(sf, ALICE, "thread")
        assert after.updated_at == before.updated_at
        assert after.seen_change_seq == before.seen_change_seq
        assert await reads.read_version(user_id=ALICE) == 1

        # A real raise increments the clock by exactly one.
        await put_run(runs, "run-2", "thread", origin="schedule")
        await reads.mark_read(user_id=ALICE, thread_id="thread")
        assert await reads.read_version(user_id=ALICE) == 2


@pytest.mark.asyncio
async def test_mark_read_without_runs_writes_no_marker(tmp_path, database_backend):
    async with database(tmp_path, backend=database_backend) as (sf, _runs, reads):
        assert await reads.mark_read(user_id=ALICE, thread_id="empty") == 0
        assert await marker(sf, ALICE, "empty") is None
        assert await reads.read_version(user_id=ALICE) == 0


@pytest.mark.asyncio
async def test_shared_thread_other_users_runs_do_not_mark_unread(tmp_path, database_backend):
    async with database(tmp_path, backend=database_backend) as (_sf, runs, reads):
        # Bob's schedule and IM runs in a thread Alice can also see.
        await put_run(runs, "run-bob-1", "shared", user_id=BOB, origin="schedule")
        await put_run(runs, "run-bob-2", "shared", user_id=BOB, origin="im_channel")
        assert await reads.unread_thread_ids(user_id=ALICE, thread_ids=["shared"]) == set()
        assert await reads.unread_thread_ids(user_id=BOB, thread_ids=["shared"]) == {"shared"}

        # Alice's read does not clear Bob's state, and vice versa.
        await reads.mark_read(user_id=ALICE, thread_id="shared")
        assert await reads.unread_thread_ids(user_id=BOB, thread_ids=["shared"]) == {"shared"}
        await reads.mark_read(user_id=BOB, thread_id="shared")
        assert await reads.unread_thread_ids(user_id=BOB, thread_ids=["shared"]) == set()
        assert await reads.read_version(user_id=ALICE) == 0
        assert await reads.read_version(user_id=BOB) == 1


@pytest.mark.asyncio
async def test_thread_operations_never_carry_an_origin(tmp_path, database_backend):
    async with database(tmp_path, backend=database_backend) as (sf, runs, reads):
        await runs.put("op-1", thread_id="thread", user_id=ALICE, operation_kind="checkpoint_write", metadata={DEERFLOW_ORIGIN_KEY: make_origin("schedule")})
        async with sf() as session:
            assert (await session.get(RunRow, "op-1")).origin_kind is None
        assert await reads.unread_thread_ids(user_id=ALICE, thread_ids=["thread"]) == set()


@pytest.mark.asyncio
async def test_unread_query_handles_empty_and_unknown_ids(tmp_path, database_backend):
    async with database(tmp_path, backend=database_backend) as (_sf, runs, reads):
        await put_run(runs, "run-1", "thread", origin="schedule")
        assert await reads.unread_thread_ids(user_id=ALICE, thread_ids=[]) == set()
        assert await reads.unread_thread_ids(user_id=ALICE, thread_ids=["missing", "thread", "thread"]) == {"thread"}


@pytest.mark.asyncio
async def test_delete_by_thread_drops_every_users_marker(tmp_path, database_backend):
    async with database(tmp_path, backend=database_backend) as (sf, runs, reads):
        await put_run(runs, "run-a", "thread", origin="schedule")
        await put_run(runs, "run-b", "thread", user_id=BOB, origin="schedule")
        await put_run(runs, "run-c", "other", origin="schedule")
        await reads.mark_read(user_id=ALICE, thread_id="thread")
        await reads.mark_read(user_id=BOB, thread_id="thread")
        await reads.mark_read(user_id=ALICE, thread_id="other")

        await reads.delete_by_thread("thread")
        async with sf() as session:
            remaining = (await session.execute(select(ThreadReadMarkerRow.user_id, ThreadReadMarkerRow.thread_id))).all()
        assert [tuple(row) for row in remaining] == [(ALICE, "other")]
