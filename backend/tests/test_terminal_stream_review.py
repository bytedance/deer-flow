"""Missing-stream recovery must remain bounded without cutting a live tail."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.gateway.services import _terminal_record_stream_missing, sse_consumer, wait_for_run_completion
from deerflow.runtime import HEARTBEAT_SENTINEL, LOCAL_FINALIZER_PENDING_STOP_REASON, RunManager, RunStatus
from deerflow.runtime.events.store.memory import MemoryRunEventStore
from deerflow.runtime.runs.store.memory import MemoryRunStore
from deerflow.runtime.stream_bridge.memory import MemoryStreamBridge


def _request():
    return SimpleNamespace(headers={}, is_disconnected=AsyncMock(return_value=False))


async def _terminal_run(*, stop_reason=None, lease_expires_at=None):
    store = MemoryRunStore()
    await store.put(
        "run-1",
        thread_id="thread-1",
        user_id="alice",
        status="success",
        owner_worker_id="previous-worker",
        stop_reason=stop_reason,
        lease_expires_at=lease_expires_at,
    )
    store._runs["run-1"]["updated_at"] = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    manager = RunManager(store=store, event_store=MemoryRunEventStore())
    record = await manager.get("run-1", user_id="alice")
    assert record is not None and record.store_only
    return store, manager, record


@pytest.mark.anyio
@pytest.mark.parametrize("consumer_kind", ["join", "retry", "wait"])
@pytest.mark.parametrize("event_history", ["lost_memory", "legacy_end"])
async def test_missing_stream_and_unavailable_receipt_recovers(consumer_kind, event_history):
    _, manager, record = await _terminal_run()
    if event_history == "legacy_end":
        await manager._event_store.put(
            thread_id=record.thread_id,
            run_id=record.run_id,
            event_type="run.end",
            category="outputs",
            content={},
            metadata={"status": "success"},
        )
    bridge = MemoryStreamBridge()
    if consumer_kind == "wait":
        assert await asyncio.wait_for(wait_for_run_completion(bridge, record, _request(), manager), timeout=1)
    else:
        consumer = sse_consumer(bridge, record, _request(), manager, emit_gap_on_missing_stream=consumer_kind == "retry")
        frame = await asyncio.wait_for(anext(consumer), timeout=1)
        assert frame.startswith("event: gap\n" if consumer_kind == "retry" else "event: end\n")
        with pytest.raises(StopAsyncIteration):
            await anext(consumer)


@pytest.mark.anyio
@pytest.mark.parametrize("stop_reason", [None, LOCAL_FINALIZER_PENDING_STOP_REASON])
async def test_missing_stream_with_live_remote_lease_waits_for_real_tail(stop_reason):
    _, manager, record = await _terminal_run(stop_reason=stop_reason, lease_expires_at=(datetime.now(UTC) + timedelta(minutes=5)).isoformat())
    bridge = MemoryStreamBridge(heartbeat_interval=0.001)
    assert not await _terminal_record_stream_missing(bridge, record, manager)
    consumer = sse_consumer(bridge, record, _request(), manager)
    assert await anext(consumer) == ": heartbeat\n\n"
    await bridge.publish(record.run_id, "error", {"message": "final error"})
    await bridge.publish_end(record.run_id)
    frames = [frame async for frame in consumer]
    assert frames[0].startswith("event: error\n")
    assert frames[1].startswith("event: end\n")


@pytest.mark.anyio
async def test_missing_stream_does_not_overtake_local_task():
    _, manager, record = await _terminal_run()
    record.store_only = False
    record.task = asyncio.create_task(asyncio.Event().wait())
    try:
        assert not await _terminal_record_stream_missing(MemoryStreamBridge(), record, manager)
    finally:
        record.task.cancel()
        await asyncio.gather(record.task, return_exceptions=True)


@pytest.mark.anyio
async def test_recent_missing_stream_rechecks_after_grace_without_caching_absence():
    store, manager, record = await _terminal_run()
    store._runs[record.run_id]["updated_at"] = datetime.now(UTC).isoformat()
    bridge = MemoryStreamBridge(heartbeat_interval=0.001)
    consumer = sse_consumer(bridge, record, _request(), manager, emit_gap_on_missing_stream=True)
    assert await anext(consumer) == ": heartbeat\n\n"
    store._runs[record.run_id]["updated_at"] = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    assert (await anext(consumer)).startswith("event: gap\n")
    await consumer.aclose()


@pytest.mark.anyio
async def test_recent_missing_stream_becomes_retained_and_preserves_tail():
    store, manager, record = await _terminal_run()
    store._runs[record.run_id]["updated_at"] = datetime.now(UTC).isoformat()
    bridge = MemoryStreamBridge(heartbeat_interval=0.001)
    consumer = sse_consumer(bridge, record, _request(), manager)
    assert await anext(consumer) == ": heartbeat\n\n"
    await bridge.publish(record.run_id, "values", {"messages": ["answer"]})
    assert (await anext(consumer)).startswith("event: values\n")
    store._runs[record.run_id]["updated_at"] = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    assert await anext(consumer) == ": heartbeat\n\n"
    await bridge.publish(record.run_id, "error", {"message": "late error"})
    await bridge.publish_end(record.run_id)
    assert [frame.splitlines()[0] async for frame in consumer] == ["event: error", "event: end"]


@pytest.mark.anyio
async def test_absent_probe_does_not_trust_stale_terminal_record():
    store, manager, record = await _terminal_run()
    # Model a stale observation without asking the store to perform the
    # forbidden terminal-to-running lifecycle transition.
    store._runs[record.run_id]["status"] = RunStatus.running.value
    assert not await _terminal_record_stream_missing(MemoryStreamBridge(), record, manager)


@pytest.mark.anyio
async def test_empty_memory_subscription_is_not_retained_stream_data():
    bridge = MemoryStreamBridge(heartbeat_interval=0.001)
    subscription = bridge.subscribe("run-1")
    assert await anext(subscription) is HEARTBEAT_SENTINEL
    assert not await bridge.stream_exists("run-1")
    await bridge.publish("run-1", "values", {"messages": []})
    assert await bridge.stream_exists("run-1")
    await subscription.aclose()
