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
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from deerflow.config.run_ownership_config import RunOwnershipConfig
from deerflow.persistence.postgres_schema import dsn_with_search_path
from deerflow.persistence.postgres_url import normalize_asyncpg_url
from deerflow.persistence.run.model import CompletedRunSnapshotRow, RunChangeClockRow, RunProducerPolicyRow, RunRow
from deerflow.persistence.run.sql import RunRepository
from deerflow.runtime import ORPHAN_RECOVERY_STOP_REASON, RunManager, RunStatus, goal
from deerflow.runtime.checkpoint_state import CheckpointStateAccessor, build_state_mutation_graph
from deerflow.runtime.checkpointer.run_owned_saver import CheckpointOwnershipLostError, RunOwnedSaver
from deerflow.runtime.runs.store.memory import MemoryRunStore
from deerflow.runtime.runs.worker import RunContext, _clear_completed_goal, _GoalCompletionCandidate, run_agent


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
                # The host wall clock can step backward (WSL2, NTP). A future
                # ``before`` keeps this run inside the candidate window; the
                # expired lease still gates the takeover.
                before=(datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
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
            # The database ownership check rejected the write; local state did
            # not change. A local-state rejection would prove nothing about the
            # PostgreSQL lease fence.
            assert not old_run.ownership_lost

        release.set()
        await asyncio.wait_for(asyncio.gather(old_run.task, return_exceptions=True), 5)
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


@pytest.mark.anyio
async def test_real_rollback_restores_checkpoint_after_interrupted_status(saver) -> None:
    checkpointer = saver.checkpointer
    manager = RunManager(
        store=saver.store,
        worker_id="rollback-owner",
        run_ownership_config=RunOwnershipConfig(lease_seconds=30, grace_seconds=1, heartbeat_enabled=True),
    )
    run = await manager.create_or_reject("checkpoint-real-rollback-" + uuid4().hex, user_id="alice")
    config = {"configurable": {"thread_id": run.thread_id}}
    entered = asyncio.Event()
    release = asyncio.Event()

    async def baseline(state: _State) -> _State:
        return {"value": "before"}

    async def blocked(state: _State) -> _State:
        entered.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            await release.wait()
        return {"value": "during"}

    await _graph(checkpointer, baseline).ainvoke({"value": "before"}, config=config)
    bridge = SimpleNamespace(publish=AsyncMock(), publish_end=AsyncMock(), cleanup=AsyncMock())
    run.task = asyncio.create_task(
        run_agent(
            bridge,
            manager,
            run,
            ctx=RunContext(checkpointer=checkpointer, event_store=None),
            agent_factory=lambda **kwargs: _graph(checkpointer, blocked),
            graph_input={"value": "during"},
            config=config,
        )
    )
    try:
        await asyncio.wait_for(entered.wait(), 5)
        await manager.cancel(run.run_id, action="rollback")
        row = await saver.store.get(run.run_id, user_id="alice")
        assert row["status"] == "interrupted"
        assert row["cancel_action"] == "rollback"
        release.set()
        await asyncio.wait_for(asyncio.shield(run.task), 5)
        final = await checkpointer.aget_tuple(config)
        assert final is not None
        assert final.checkpoint["channel_values"]["value"] == "before"
        assert (await saver.store.get(run.run_id, user_id="alice"))["status"] == "error"
    finally:
        release.set()
        if not run.task.done():
            run.task.cancel()
        await asyncio.gather(run.task, return_exceptions=True)


@pytest.mark.anyio
async def test_duration_write_precedes_terminal_without_event_store(saver, monkeypatch) -> None:
    import deerflow.runtime.runs.worker as worker_module

    manager = RunManager(
        store=saver.store,
        worker_id="duration-owner",
        run_ownership_config=RunOwnershipConfig(lease_seconds=30, grace_seconds=1, heartbeat_enabled=True),
    )
    run = await manager.create_or_reject("checkpoint-duration-" + uuid4().hex, user_id="alice")
    config = {"configurable": {"thread_id": run.thread_id}}
    original = worker_module._persist_run_duration
    observed = []

    async def checked_duration(**kwargs):
        row = await saver.store.get(run.run_id, user_id="alice")
        observed.append(row["status"])
        await original(**kwargs)

    monkeypatch.setattr(worker_module, "_persist_run_duration", checked_duration)

    async def node(state: _State) -> _State:
        return {"value": "done"}

    bridge = SimpleNamespace(publish=AsyncMock(), publish_end=AsyncMock(), cleanup=AsyncMock())
    run.task = asyncio.create_task(
        run_agent(
            bridge,
            manager,
            run,
            ctx=RunContext(checkpointer=saver.checkpointer, event_store=None),
            agent_factory=lambda **kwargs: _graph(saver.checkpointer, node),
            graph_input={"value": "done"},
            config=config,
        )
    )
    await asyncio.wait_for(asyncio.shield(run.task), 5)
    checkpoint = await saver.checkpointer.aget_tuple(config)
    assert checkpoint is not None
    row = await saver.store.get(run.run_id, user_id="alice")
    assert row["status"] == "success", row
    assert observed == ["running"]
    assert checkpoint.metadata.get("run_durations", {}).get(run.run_id) is not None


@pytest.mark.anyio
async def test_completed_goal_uses_new_operation_after_terminal(saver) -> None:
    if saver.schema is None:
        pytest.skip("This test needs PostgreSQL")
    manager = RunManager(
        store=saver.store,
        worker_id="goal-owner",
        run_ownership_config=RunOwnershipConfig(lease_seconds=30, grace_seconds=1, heartbeat_enabled=True),
    )
    run = await manager.create_or_reject("checkpoint-goal-cleanup-" + uuid4().hex, user_id="alice")
    expected_goal = goal.build_goal_state("Complete the task")
    await goal.write_thread_goal(saver.checkpointer, run.thread_id, expected_goal, create_if_missing=True)
    await manager.set_status(run.run_id, RunStatus.running)
    await manager.set_status(run.run_id, RunStatus.success)
    run.finalizing = True
    assert (await saver.store.get(run.run_id, user_id="alice"))["status"] == "success"
    candidate = _GoalCompletionCandidate(
        goal=expected_goal,
        conversation_signature=goal.visible_conversation_signature([]),
        evaluation={"satisfied": True, "blocker": "none", "reason": "Complete"},
    )
    accessor = CheckpointStateAccessor.bind(build_state_mutation_graph("goal_evaluator", "full"), saver.checkpointer, mode="full")
    bridge = SimpleNamespace(publish=AsyncMock())
    await _clear_completed_goal(
        candidate=candidate,
        record=run,
        run_manager=manager,
        bridge=bridge,
        accessor=accessor,
        checkpointer=saver.checkpointer,
    )
    assert await goal.read_thread_goal(saver.checkpointer, run.thread_id) is None
    bridge.publish.assert_awaited()


@pytest.mark.anyio
async def test_interrupted_title_uses_new_operation_after_terminal(saver) -> None:
    if saver.schema is None:
        pytest.skip("This test needs PostgreSQL")
    manager = RunManager(
        store=saver.store,
        worker_id="title-owner",
        run_ownership_config=RunOwnershipConfig(lease_seconds=30, grace_seconds=1, heartbeat_enabled=True),
    )
    run = await manager.create_or_reject("checkpoint-interrupted-title-" + uuid4().hex, user_id="alice")
    entered = asyncio.Event()
    release = asyncio.Event()

    async def blocked(state: _State) -> _State:
        entered.set()
        await release.wait()
        return {"value": "interrupted"}

    bridge = SimpleNamespace(publish=AsyncMock(), publish_end=AsyncMock(), cleanup=AsyncMock())
    run.task = asyncio.create_task(
        run_agent(
            bridge,
            manager,
            run,
            ctx=RunContext(checkpointer=saver.checkpointer, event_store=None),
            agent_factory=lambda **kwargs: _graph(saver.checkpointer, blocked),
            graph_input={"value": "started", "messages": [HumanMessage(content="Name this interrupted task")]},
            config={"configurable": {"thread_id": run.thread_id}},
        )
    )
    try:
        await asyncio.wait_for(entered.wait(), 5)
        await manager.cancel(run.run_id, action="interrupt")
        await asyncio.wait_for(asyncio.shield(run.task), 5)
        checkpoint = await saver.checkpointer.aget_tuple({"configurable": {"thread_id": run.thread_id}})
        assert checkpoint is not None
        assert (await saver.store.get(run.run_id, user_id="alice"))["status"] == "interrupted"
        assert checkpoint.checkpoint["channel_values"].get("title")
    finally:
        release.set()
        if not run.task.done():
            run.task.cancel()
        await asyncio.gather(run.task, return_exceptions=True)


@pytest.mark.anyio
async def test_checkpoint_lease_loss_reports_checkpoint_context() -> None:
    store = MemoryRunStore()
    manager = RunManager(
        store=store,
        worker_id="diagnostic-owner",
        run_ownership_config=RunOwnershipConfig(lease_seconds=30, grace_seconds=1, heartbeat_enabled=True),
    )
    run = await manager.create_or_reject("checkpoint-reason-" + uuid4().hex, user_id="alice")
    await manager.set_status(run.run_id, RunStatus.running)
    store._runs[run.run_id]["lease_expires_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    owned = RunOwnedSaver(InMemorySaver(), manager, run)
    with pytest.raises(CheckpointOwnershipLostError):
        await owned.aput({"configurable": {"thread_id": run.thread_id}}, {}, {}, {})
    assert run.ownership_lost
    assert run.error == "Checkpoint write lost its active run lease."


@pytest.mark.anyio
@pytest.mark.parametrize(("local_pending", "cancel_action"), [(False, "rollback"), (True, "interrupt")])
async def test_interrupted_checkpoint_write_requires_rollback_authority(saver, local_pending, cancel_action) -> None:
    if saver.schema is None:
        pytest.skip("This test needs PostgreSQL")
    manager = RunManager(
        store=saver.store,
        worker_id="rollback-check-owner",
        run_ownership_config=RunOwnershipConfig(lease_seconds=30, grace_seconds=1, heartbeat_enabled=True),
    )
    run = await manager.create_or_reject("checkpoint-rollback-authority-" + uuid4().hex, user_id="alice")
    await manager.set_status(run.run_id, RunStatus.running)
    config = {"configurable": {"thread_id": run.thread_id}}

    async def node(state: _State) -> _State:
        return state

    await _graph(saver.checkpointer, node).ainvoke({"value": "preserve"}, config=config)
    before = await saver.checkpointer.aget_tuple(config)
    assert before is not None
    async with saver.session_factory() as session:
        await session.execute(update(RunRow).where(RunRow.run_id == run.run_id).values(status="interrupted", cancel_action=cancel_action))
        await session.commit()
    run.rollback_finalization_pending = local_pending
    stale = dict(before.checkpoint)
    stale["id"] = str(uuid4())
    with pytest.raises(CheckpointOwnershipLostError):
        await RunOwnedSaver(saver.checkpointer, manager, run).aput(before.config, stale, before.metadata, {})
    after = await saver.checkpointer.aget_tuple(config)
    assert after is not None
    assert after.checkpoint["id"] == before.checkpoint["id"]
