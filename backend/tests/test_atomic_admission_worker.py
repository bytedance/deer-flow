import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import MessagesState, StateGraph
from test_terminal_store_contract import store as store

from deerflow.config.run_ownership_config import RunOwnershipConfig
from deerflow.runtime import RunManager, RunStatus
from deerflow.runtime.events.store.memory import MemoryRunEventStore
from deerflow.runtime.runs.worker import RunContext, run_agent


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "action,host_finalization_cancel,stale_renewal_race",
    [
        ("interrupt", False, False),
        ("rollback", False, False),
        ("rollback", True, False),
        ("rollback", False, True),
    ],
)
@pytest.mark.parametrize("with_event_store", [True, False])
async def test_real_worker_atomic_replacement_retains_finalization_authority(store, action, with_event_store, host_finalization_cancel, stale_renewal_race):
    manager = RunManager(store=store, worker_id="owner", run_ownership_config=RunOwnershipConfig(heartbeat_enabled=True, lease_seconds=10, grace_seconds=0))
    record = await manager.create_or_reject("thread", user_id="review")
    started, rollback_entered, release_rollback = (asyncio.Event() for _ in range(3))
    error_committed, release_error_ack = asyncio.Event(), asyncio.Event()
    hold_rollback = False

    class Saver(InMemorySaver):
        async def aput(self, config, checkpoint, metadata, new_versions):
            if hold_rollback and metadata.get("source") == "update" and not rollback_entered.is_set():
                rollback_entered.set()
                await release_rollback.wait()
            return await super().aput(config, checkpoint, metadata, new_versions)

    saver = Saver()

    async def blocked_node(state):
        started.set()
        await asyncio.Event().wait()
        return {}

    builder = StateGraph(MessagesState)
    builder.add_node("step", blocked_node)
    builder.set_entry_point("step")
    builder.set_finish_point("step")
    graph = builder.compile(checkpointer=saver)
    config = {"configurable": {"thread_id": "thread"}}
    await graph.aupdate_state(config, {"messages": [HumanMessage(content="before")]}, as_node="step")
    completion = AsyncMock()
    bridge = SimpleNamespace(publish=AsyncMock(), publish_end=AsyncMock(), cleanup=AsyncMock())
    record.task = asyncio.create_task(
        run_agent(
            bridge,
            manager,
            record,
            ctx=RunContext(checkpointer=saver, event_store=MemoryRunEventStore() if with_event_store else None, on_run_completed=completion),
            agent_factory=lambda **kwargs: graph,
            graph_input={"messages": [HumanMessage(content="cancelled input")]},
            config=config,
        )
    )
    renewal = None
    stale_renewal = None
    stale_renewal_entered, release_stale_renewal = asyncio.Event(), asyncio.Event()
    stale_renewal_calls = []
    original_status = store.update_status
    original_renew = store.renew_lease

    async def hold_first_active_renewal(run_id, **kwargs):
        stale_renewal_calls.append(kwargs.get("allow_interrupted", False))
        if stale_renewal_race and len(stale_renewal_calls) == 1:
            stale_renewal_entered.set()
            await release_stale_renewal.wait()
        return await original_renew(run_id, **kwargs)

    store.renew_lease = hold_first_active_renewal

    async def hold_final_ack(run_id, status, **kwargs):
        result = await original_status(run_id, status, **kwargs)
        if run_id == record.run_id and status == "error" and result is True:
            error_committed.set()
            await release_error_ack.wait()
        return result

    try:
        await asyncio.wait_for(started.wait(), 2)
        if stale_renewal_race:
            stale_renewal = asyncio.create_task(manager._renew_leases())
            await asyncio.wait_for(stale_renewal_entered.wait(), 2)
        # Model a nearing lease deadline with a real persisted timestamp. The
        # replacement and rollback checkpoint may take longer than 150 ms on a
        # loaded CI runner, before this test explicitly requests renewal.
        deadline = datetime.now(UTC) + timedelta(seconds=4)
        row = await store.get(record.run_id, user_id="review")
        await store.put(record.run_id, thread_id="thread", status="running", user_id="review", owner_worker_id="owner", lease_expires_at=deadline.isoformat(), created_at=row["created_at"])
        record.lease_expires_at = deadline.isoformat()
        hold_rollback = action == "rollback"
        if action == "rollback":
            store.update_status = hold_final_ack
        replacement = await manager.create_or_reject("thread", multitask_strategy=action, user_id="review")
        assert replacement.status == RunStatus.pending
        assert not record.ownership_lost
        if action == "rollback":
            await asyncio.wait_for(rollback_entered.wait(), 2)
            assert not record.ownership_lost
            assert record.terminal_commit_proof.status == RunStatus.interrupted
            assert record.terminal_commit_proof.error == "Cancelled by newer run"
            assert not manager.can_release_terminal_barrier(record)
            assert not record.terminal_status_persisted
            if stale_renewal_race:
                release_stale_renewal.set()
                await asyncio.wait_for(stale_renewal, 2)
                assert record.status in (RunStatus.interrupted, RunStatus.error)
                assert record.owner_worker_id == "owner"
                assert manager._runs.get(record.run_id) is record
                assert stale_renewal_calls == [False, True]
                assert not record.ownership_lost
                assert record.rollback_finalization_pending
            await manager._renew_leases()
            elapsed = asyncio.Event()
            asyncio.get_running_loop().call_later(max(0, (deadline - datetime.now(UTC)).total_seconds()) + 0.03, elapsed.set)
            await elapsed.wait()
            row = await store.get(record.run_id, user_id="review")
            assert datetime.now(UTC) > deadline
            assert datetime.fromisoformat(row["lease_expires_at"]) > datetime.now(UTC)
            assert row["status"] == "interrupted"
            assert not record.task.done()
            assert not record.ownership_lost
            release_rollback.set()
            await asyncio.wait_for(error_committed.wait(), 2)
            assert not record.terminal_status_persisted
            renewal = asyncio.create_task(manager._renew_leases())
            await asyncio.sleep(0)
            if host_finalization_cancel:
                record.task.cancel("host cancellation during rollback terminal ACK")
                await asyncio.sleep(0)
                record.task.cancel("repeated host cancellation")
                await asyncio.sleep(0)
                assert not record.task.done()
                assert not record.terminal_status_persisted
                assert record.rollback_finalization_pending
                assert not record.ownership_lost
            release_error_ack.set()
        if host_finalization_cancel:
            with pytest.raises(asyncio.CancelledError, match="host cancellation during rollback terminal ACK"):
                await asyncio.wait_for(record.task, 2)
        else:
            await asyncio.wait_for(record.task, 2)
        if renewal:
            await asyncio.wait_for(renewal, 1)
        row = await store.get(record.run_id, user_id="review")
        expected = "error" if action == "rollback" else "interrupted"
        assert row["status"] == expected
        assert record.status.value == expected
        assert not record.ownership_lost
        assert manager._has_terminal_ack(record)
        assert record.run_id not in manager._lease_deadlines
        completion.assert_awaited_once_with(record)
        bridge.publish_end.assert_awaited_once_with(record.run_id)
        if action == "rollback":
            assert row["error"] == "Rolled back by user"
            snapshot = await graph.aget_state(config)
            assert [m.content for m in snapshot.values["messages"]] == ["before"]
    finally:
        release_rollback.set()
        release_error_ack.set()
        release_stale_renewal.set()
        if not record.task.done():
            record.task.cancel()
        await asyncio.gather(record.task, *([renewal] if renewal else []), *([stale_renewal] if stale_renewal else []), return_exceptions=True)
        await manager.stop_heartbeat(timeout=0.1)


@pytest.mark.anyio
async def test_fenced_worker_does_not_begin_rollback_checkpoint_writes(store):
    manager = RunManager(store=store, worker_id="owner", run_ownership_config=RunOwnershipConfig(heartbeat_enabled=True, lease_seconds=5, grace_seconds=0))
    record = await manager.create_or_reject("thread", user_id="review")
    started = asyncio.Event()
    saver = InMemorySaver()

    async def blocked_node(state):
        started.set()
        await asyncio.Event().wait()
        return {}

    builder = StateGraph(MessagesState)
    builder.add_node("step", blocked_node)
    builder.set_entry_point("step")
    builder.set_finish_point("step")
    graph = builder.compile(checkpointer=saver)
    config = {"configurable": {"thread_id": "thread"}}
    await graph.aupdate_state(config, {"messages": [HumanMessage(content="before")]}, as_node="step")
    completion = AsyncMock()
    bridge = SimpleNamespace(publish=AsyncMock(), publish_end=AsyncMock(), cleanup=AsyncMock())
    record.task = asyncio.create_task(
        run_agent(
            bridge,
            manager,
            record,
            ctx=RunContext(checkpointer=saver, event_store=MemoryRunEventStore(), on_run_completed=completion),
            agent_factory=lambda **kwargs: graph,
            graph_input={"messages": [HumanMessage(content="cancelled input")]},
            config=config,
        )
    )
    try:
        await asyncio.wait_for(started.wait(), 2)
        before = await graph.aget_state(config)
        # A rollback intent may already be local when its execution lease is
        # lost. Cancellation delivered by fencing cannot grant rollback rights.
        record.abort_action = "rollback"
        record.lease_expires_at = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
        await manager._renew_leases()
        await asyncio.wait_for(record.task, 2)
        assert record.ownership_lost
        after = await graph.aget_state(config)
        assert after.values == before.values
        completion.assert_not_awaited()
    finally:
        if not record.task.done():
            record.task.cancel()
        await asyncio.gather(record.task, return_exceptions=True)
        await manager.stop_heartbeat(timeout=0.1)
