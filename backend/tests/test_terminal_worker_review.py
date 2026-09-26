"""Regressions for terminal stream ownership and same-thread admission."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from deerflow.runtime.events.store.memory import MemoryRunEventStore
from deerflow.runtime.journal import RunJournal
from deerflow.runtime.runs.manager import ConflictError, RunManager
from deerflow.runtime.runs.schemas import RunStatus
from deerflow.runtime.runs.store.memory import MemoryRunStore
from deerflow.runtime.runs.worker import RunContext, _persist_authoritative_terminal_event, _persist_delivery_receipt, run_agent
from deerflow.runtime.stream_bridge import END_SENTINEL
from deerflow.runtime.stream_bridge.memory import MemoryStreamBridge


@pytest.mark.anyio
@pytest.mark.parametrize("cleanup_stage", ["journal", "sandbox"])
async def test_stream_end_allows_next_run_while_local_cleanup_is_blocked(monkeypatch, cleanup_stage):
    completion_entered = asyncio.Event()
    release_completion = asyncio.Event()
    cleanup_entered = asyncio.Event()
    release_cleanup = asyncio.Event()
    stream_ended = asyncio.Event()

    async def completion_hook(_record):
        completion_entered.set()
        await release_completion.wait()

    async def block_cleanup():
        cleanup_entered.set()
        await release_cleanup.wait()

    original_close = RunJournal.close

    async def close_journal(journal, *, flush=True):
        await block_cleanup()
        await original_close(journal, flush=flush)

    if cleanup_stage == "journal":
        monkeypatch.setattr(RunJournal, "close", close_journal)

    async def block_cleanup_with_context(_context):
        await block_cleanup()

    # The blocked stage is local teardown, after every checkpoint/output write.
    if cleanup_stage == "sandbox":
        monkeypatch.setattr("deerflow.sandbox.lease.release_sandbox_execution_lease_async", block_cleanup_with_context)

    run_manager = RunManager(store=MemoryRunStore())
    monkeypatch.setattr(run_manager, "cleanup", AsyncMock())
    record = await run_manager.create_or_reject("thread-terminal-admission")
    bridge = MemoryStreamBridge()
    monkeypatch.setattr(bridge, "cleanup", AsyncMock())

    class Agent:
        async def astream(self, *_args, **_kwargs):
            yield {"messages": []}

    async def consume_stream():
        async for item in bridge.subscribe(record.run_id):
            if item is END_SENTINEL:
                stream_ended.set()

    consumer = asyncio.create_task(consume_stream())
    worker = asyncio.create_task(
        run_agent(
            bridge,
            run_manager,
            record,
            ctx=RunContext(checkpointer=None, event_store=MemoryRunEventStore(), on_run_completed=completion_hook),
            agent_factory=lambda **_kwargs: Agent(),
            graph_input={},
            config={},
        )
    )
    record.task = worker
    try:
        await asyncio.wait_for(completion_entered.wait(), timeout=5)
        assert record.finalizing
        assert not stream_ended.is_set()
        with pytest.raises(ConflictError):
            await run_manager.create_or_reject(record.thread_id)

        release_completion.set()
        await asyncio.wait_for(stream_ended.wait(), timeout=5)
        await asyncio.wait_for(cleanup_entered.wait(), timeout=5)
        assert not worker.done()
        replacement = await run_manager.create_or_reject(record.thread_id)
        assert replacement.run_id != record.run_id
        assert not record.finalizing
    finally:
        release_completion.set()
        release_cleanup.set()
        await asyncio.wait_for(worker, timeout=5)
        await asyncio.wait_for(consumer, timeout=5)
        await bridge.close()


@pytest.mark.anyio
async def test_fenced_worker_does_not_end_or_delete_the_new_owners_stream(monkeypatch):
    manager = RunManager()
    record = await manager.create("thread-fenced-stream")
    record.ownership_lost = True
    record.abort_event.set()
    record.status = RunStatus.error
    bridge = SimpleNamespace(publish=AsyncMock(), publish_end=AsyncMock(), cleanup=AsyncMock())
    local_cleanup_done = asyncio.Event()

    async def local_cleanup(_run_id):
        local_cleanup_done.set()

    monkeypatch.setattr(manager, "cleanup", local_cleanup)
    await run_agent(
        bridge,
        manager,
        record,
        ctx=RunContext(checkpointer=None, event_store=MemoryRunEventStore()),
        agent_factory=MagicMock(side_effect=AssertionError("fenced worker started")),
        graph_input={},
        config={},
    )
    await asyncio.wait_for(local_cleanup_done.wait(), timeout=5)
    bridge.publish_end.assert_not_awaited()
    bridge.cleanup.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize("event_type", ["run.delivery", "run.end"])
@pytest.mark.parametrize("failure", ["transient", "exhausted", "cancelled"])
async def test_terminal_event_retries_preserve_failure_and_cancellation_semantics(monkeypatch, event_type, failure):
    monkeypatch.setattr("deerflow.runtime.runs.worker._DELIVERY_RECEIPT_RETRY_DELAYS_SECONDS", (0, 0))
    outcomes = {
        "transient": [RuntimeError("unavailable"), ({}, True)],
        "exhausted": [RuntimeError("unavailable")] * 3,
        "cancelled": [asyncio.CancelledError("stop")],
    }
    store = SimpleNamespace(put_if_absent=AsyncMock(side_effect=outcomes[failure]))
    manager = RunManager()
    record = await manager.create("thread-terminal-retries")
    record.status = RunStatus.success
    if event_type == "run.delivery":
        operation = _persist_delivery_receipt(store, thread_id=record.thread_id, run_id=record.run_id, content={})
    else:
        operation = _persist_authoritative_terminal_event(store, record=record, content={})
    if failure == "cancelled":
        with pytest.raises(asyncio.CancelledError, match="stop"):
            await operation
    else:
        assert await operation is (failure == "transient")
    assert store.put_if_absent.await_count == {"transient": 2, "exhausted": 3, "cancelled": 1}[failure]
    assert {call.kwargs["event_type"] for call in store.put_if_absent.await_args_list} == {event_type}
