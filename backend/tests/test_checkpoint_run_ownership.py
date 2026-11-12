"""A recovered run keeps its checkpoint head after the old worker stops."""

import asyncio
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import TypedDict
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from deerflow.config.run_ownership_config import RunOwnershipConfig
from deerflow.persistence.postgres_schema import dsn_with_search_path
from deerflow.persistence.postgres_url import normalize_asyncpg_url
from deerflow.persistence.run.model import CompletedRunSnapshotRow, RunChangeClockRow, RunProducerPolicyRow, RunRow
from deerflow.persistence.run.sql import RunRepository
from deerflow.runtime import ORPHAN_RECOVERY_STOP_REASON, RunManager, RunStatus
from deerflow.runtime.checkpointer.run_owned_saver import CheckpointOwnershipLostError, RunOwnedSaver
from deerflow.runtime.runs.store.memory import MemoryRunStore
from deerflow.runtime.runs.worker import RunContext, run_agent


class _State(TypedDict):
    value: str


class _YieldingSaver(InMemorySaver):
    async def aput(self, config, checkpoint, metadata, new_versions):
        await asyncio.sleep(0)
        return await super().aput(config, checkpoint, metadata, new_versions)

    async def aput_writes(self, config, writes, task_id, task_path=""):
        await asyncio.sleep(0)
        return await super().aput_writes(config, writes, task_id, task_path)


def _graph(saver, node):
    builder = StateGraph(_State)
    builder.add_node("node", node)
    builder.add_edge(START, "node")
    builder.add_edge("node", END)
    return builder.compile(checkpointer=saver)


@pytest.fixture(params=["memory", "postgres", "postgres-pool", "postgres-cached"])
async def saver(request):
    if request.param == "memory":
        checkpointer = _YieldingSaver()
        yield SimpleNamespace(checkpointer=checkpointer, store=MemoryRunStore(), schema=None, session_factory=None, kind=request.param)
        return
    uri = os.environ.get("TEST_POSTGRES_URI")
    if not uri:
        pytest.skip("TEST_POSTGRES_URI is not set")
    aio = pytest.importorskip("langgraph.checkpoint.postgres.aio")
    schema = "checkpoint_lease_" + uuid4().hex
    admin = create_async_engine(normalize_asyncpg_url(uri))
    async with admin.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(
        normalize_asyncpg_url(uri),
        connect_args={"server_settings": {"search_path": schema}},
    )
    try:
        async with engine.begin() as conn:
            await conn.run_sync(
                lambda c: RunRow.metadata.create_all(
                    c,
                    tables=[RunRow.__table__, RunChangeClockRow.__table__, CompletedRunSnapshotRow.__table__, RunProducerPolicyRow.__table__],
                )
            )
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        if request.param == "postgres-pool":
            from psycopg.rows import dict_row
            from psycopg_pool import AsyncConnectionPool

            pool = AsyncConnectionPool(
                dsn_with_search_path(uri, schema),
                kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
                open=False,
            )
            async with pool:
                checkpointer = aio.AsyncPostgresSaver(conn=pool)
                await checkpointer.setup()
                yield SimpleNamespace(
                    checkpointer=checkpointer,
                    store=RunRepository(session_factory),
                    schema=schema,
                    session_factory=session_factory,
                    kind=request.param,
                )
        else:
            async with aio.AsyncPostgresSaver.from_conn_string(dsn_with_search_path(uri, schema)) as checkpointer:
                await checkpointer.setup()
                if request.param == "postgres-cached":
                    from deerflow.runtime.checkpoint_cache.memory import MemoryCheckpointHistoryCache
                    from deerflow.runtime.checkpointer.cached_saver import CachedHistorySaver

                    checkpointer = CachedHistorySaver(checkpointer, MemoryCheckpointHistoryCache(max_entries=16), key_prefix="test")
                yield SimpleNamespace(
                    checkpointer=checkpointer,
                    store=RunRepository(session_factory),
                    schema=schema,
                    session_factory=session_factory,
                    kind=request.param,
                )
    finally:
        async with admin.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()
        await engine.dispose()


async def _exercise_takeover(saver, *, detect_local_loss: bool) -> None:
    checkpointer = saver.checkpointer
    store = saver.store
    ownership = RunOwnershipConfig(lease_seconds=30, grace_seconds=1, heartbeat_enabled=True)
    old_manager = RunManager(store=store, worker_id="worker-a", run_ownership_config=ownership)
    new_manager = RunManager(store=store, worker_id="worker-b", run_ownership_config=ownership)
    old_run = await old_manager.create_or_reject("checkpoint-lease-race-" + uuid4().hex, user_id="alice")
    entered = asyncio.Event()
    release = asyncio.Event()

    async def old_node(state: _State) -> _State:
        entered.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            await release.wait()
        return {"value": "old"}

    async def new_node(state: _State) -> _State:
        return {"value": "new"}

    old_graph = _graph(checkpointer, old_node)
    bridge = SimpleNamespace(publish=AsyncMock(), publish_end=AsyncMock(), cleanup=AsyncMock())
    process = None
    old_run.task = asyncio.create_task(
        run_agent(
            bridge,
            old_manager,
            old_run,
            ctx=RunContext(checkpointer=checkpointer, event_store=None),
            agent_factory=lambda **kwargs: old_graph,
            graph_input={"value": "old"},
            config={"configurable": {"thread_id": old_run.thread_id}},
        )
    )
    try:
        await asyncio.wait_for(entered.wait(), 5)
        if saver.session_factory is None:
            store._runs[old_run.run_id]["lease_expires_at"] = (datetime.now(UTC) - timedelta(seconds=40)).isoformat()
        else:
            async with saver.session_factory() as session:
                await session.execute(update(RunRow).where(RunRow.run_id == old_run.run_id).values(lease_expires_at=datetime.now(UTC) - timedelta(seconds=40)))
                await session.commit()
        if detect_local_loss:
            await old_manager._renew_leases()
            assert old_run.ownership_lost
        else:
            assert not old_run.ownership_lost

        config = {"configurable": {"thread_id": old_run.thread_id}}
        if saver.schema is not None:
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                str(Path(__file__).parent / "support" / "checkpoint_peer_process.py"),
                old_run.thread_id,
                saver.schema,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), 5)
            assert process.returncode == 0, (stdout + stderr).decode()
        else:
            await new_manager.reconcile_orphaned_inflight_runs(
                error="reclaimed",
                stop_reason=ORPHAN_RECOVERY_STOP_REASON,
            )
            new_run = await new_manager.create_or_reject(old_run.thread_id, user_id="alice")
            await new_manager.set_status(new_run.run_id, RunStatus.running)
            await _graph(checkpointer, new_node).ainvoke({"value": "new"}, config=config)
        before = await checkpointer.aget_tuple(config)
        assert before is not None
        assert before.checkpoint["channel_values"]["value"] == "new"
        before_ids = {item.checkpoint["id"] async for item in checkpointer.alist(config)}

        if not detect_local_loss:
            assert not old_run.ownership_lost
            stale = dict(before.checkpoint)
            stale["id"] = str(uuid4())
            with pytest.raises(CheckpointOwnershipLostError):
                await RunOwnedSaver(checkpointer, old_manager, old_run).aput(before.config, stale, before.metadata, {})

        release.set()
        await asyncio.wait_for(old_run.task, 5)
        after = await checkpointer.aget_tuple(config)
        assert after is not None
        assert after.checkpoint["id"] == before.checkpoint["id"]
        assert after.parent_config == before.parent_config
        assert after.checkpoint["channel_values"]["value"] == "new"
        assert {item.checkpoint["id"] async for item in checkpointer.alist(config)} == before_ids
    finally:
        release.set()
        if process is not None and process.returncode is None:
            process.kill()
            await process.wait()
        if not old_run.task.done():
            old_run.task.cancel()
        await asyncio.gather(old_run.task, return_exceptions=True)
        if saver.schema is None:
            await checkpointer.adelete_thread(old_run.thread_id)


@pytest.mark.anyio
async def test_lost_owner_cannot_replace_recovered_checkpoint_head(saver) -> None:
    await _exercise_takeover(saver, detect_local_loss=True)


@pytest.mark.anyio
async def test_database_takeover_fences_checkpoint_write(saver) -> None:
    if saver.schema is None:
        pytest.skip("This test needs PostgreSQL")
    await _exercise_takeover(saver, detect_local_loss=False)


@pytest.mark.anyio
async def test_checkpoint_writer_rechecks_lease_after_row_lock_wait(saver) -> None:
    if saver.kind != "postgres":
        pytest.skip("This test uses one PostgreSQL connection")
    checkpointer = saver.checkpointer
    manager = RunManager(
        store=saver.store,
        worker_id="worker-a",
        run_ownership_config=RunOwnershipConfig(lease_seconds=30, grace_seconds=1, heartbeat_enabled=True),
    )
    run = await manager.create_or_reject("checkpoint-lock-wait-" + uuid4().hex, user_id="alice")
    await manager.set_status(run.run_id, RunStatus.running)
    config = {"configurable": {"thread_id": run.thread_id}}

    async def node(state: _State) -> _State:
        return state

    await _graph(checkpointer, node).ainvoke({"value": "before"}, config=config)
    before = await checkpointer.aget_tuple(config)
    assert before is not None
    before_ids = {item.checkpoint["id"] async for item in checkpointer.alist(config)}
    stale = dict(before.checkpoint)
    stale["id"] = str(uuid4())
    pid_cursor = await checkpointer.conn.execute("SELECT pg_backend_pid()")
    writer_pid = (await pid_cursor.fetchone())["pg_backend_pid"]
    writer = None
    async with saver.session_factory() as session:
        async with session.begin():
            await session.execute(
                text("UPDATE runs SET lease_expires_at = clock_timestamp() + interval '2 seconds' WHERE run_id = :run_id"),
                {"run_id": run.run_id},
            )
            try:
                writer = asyncio.create_task(RunOwnedSaver(checkpointer, manager, run).aput(before.config, stale, before.metadata, {}))

                async def writer_waits_for_row_lock() -> None:
                    while True:
                        async with saver.session_factory() as observer:
                            wait_type = await observer.scalar(
                                text("SELECT wait_event_type FROM pg_stat_activity WHERE pid = :pid"),
                                {"pid": writer_pid},
                            )
                        if wait_type == "Lock":
                            return
                        await asyncio.sleep(0.01)

                await asyncio.wait_for(writer_waits_for_row_lock(), 5)
                await session.execute(
                    text("SELECT pg_sleep_until(lease_expires_at + interval '0.05 seconds') FROM runs WHERE run_id = :run_id"),
                    {"run_id": run.run_id},
                )
            except BaseException:
                if writer is not None:
                    writer.cancel()
                    await asyncio.gather(writer, return_exceptions=True)
                raise
    assert writer is not None
    assert not run.ownership_lost
    with pytest.raises(CheckpointOwnershipLostError):
        await asyncio.wait_for(writer, 5)
    assert {item.checkpoint["id"] async for item in checkpointer.alist(config)} == before_ids


@pytest.mark.anyio
async def test_rollback_checkpoint_delete_requires_active_lease(saver) -> None:
    checkpointer = saver.checkpointer
    manager = RunManager(
        store=saver.store,
        worker_id="worker-a",
        run_ownership_config=RunOwnershipConfig(lease_seconds=30, grace_seconds=1, heartbeat_enabled=True),
    )
    run = await manager.create_or_reject("checkpoint-rollback-delete-" + uuid4().hex, user_id="alice")
    await manager.set_status(run.run_id, RunStatus.running)
    config = {"configurable": {"thread_id": run.thread_id}}

    async def node(state: _State) -> _State:
        return state

    graph = _graph(checkpointer, node)
    await graph.ainvoke({"value": "before"}, config=config)
    owned = RunOwnedSaver(checkpointer, manager, run)
    await owned.adelete_thread(run.thread_id)
    assert await checkpointer.aget_tuple(config) is None

    await graph.ainvoke({"value": "preserve"}, config=config)
    preserved = await checkpointer.aget_tuple(config)
    assert preserved is not None
    if saver.session_factory is None:
        saver.store._runs[run.run_id]["lease_expires_at"] = (datetime.now(UTC) - timedelta(seconds=40)).isoformat()
    else:
        async with saver.session_factory() as session:
            await session.execute(update(RunRow).where(RunRow.run_id == run.run_id).values(lease_expires_at=datetime.now(UTC) - timedelta(seconds=40)))
            await session.commit()
    assert not run.ownership_lost
    with pytest.raises(CheckpointOwnershipLostError):
        await owned.adelete_thread(run.thread_id)
    after = await checkpointer.aget_tuple(config)
    assert after is not None
    assert after.checkpoint["id"] == preserved.checkpoint["id"]
