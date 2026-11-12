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
        yield SimpleNamespace(checkpointer=checkpointer, store=MemoryRunStore(), schema=None, session_factory=None)
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
                )
    finally:
        async with admin.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()
        await engine.dispose()


@pytest.mark.anyio
async def test_lost_owner_cannot_replace_recovered_checkpoint_head(saver) -> None:
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
        await old_manager._renew_leases()
        assert old_run.ownership_lost

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
