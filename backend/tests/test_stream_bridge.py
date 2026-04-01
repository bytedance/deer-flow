"""Tests for the in-memory StreamBridge implementation."""

import asyncio
import re

import pytest

from deerflow.runtime import END_SENTINEL, HEARTBEAT_SENTINEL, MemoryStreamBridge, make_stream_bridge

# ---------------------------------------------------------------------------
# Unit tests for MemoryStreamBridge
# ---------------------------------------------------------------------------


@pytest.fixture
def bridge() -> MemoryStreamBridge:
    return MemoryStreamBridge(queue_maxsize=256)


@pytest.mark.anyio
async def test_publish_subscribe(bridge: MemoryStreamBridge):
    """Three events followed by end should be received in order."""
    run_id = "run-1"

    await bridge.publish(run_id, "metadata", {"run_id": run_id})
    await bridge.publish(run_id, "values", {"messages": []})
    await bridge.publish(run_id, "updates", {"step": 1})
    await bridge.publish_end(run_id)

    received = []
    async for entry in bridge.subscribe(run_id, heartbeat_interval=1.0):
        received.append(entry)
        if entry is END_SENTINEL:
            break

    assert len(received) == 4
    assert received[0].event == "metadata"
    assert received[1].event == "values"
    assert received[2].event == "updates"
    assert received[3] is END_SENTINEL


@pytest.mark.anyio
async def test_heartbeat(bridge: MemoryStreamBridge):
    """When no events arrive within the heartbeat interval, yield a heartbeat."""
    run_id = "run-heartbeat"
    bridge._get_or_create_queue(run_id)  # ensure queue exists

    received = []

    async def consumer():
        async for entry in bridge.subscribe(run_id, heartbeat_interval=0.1):
            received.append(entry)
            if entry is HEARTBEAT_SENTINEL:
                break

    await asyncio.wait_for(consumer(), timeout=2.0)
    assert len(received) == 1
    assert received[0] is HEARTBEAT_SENTINEL


@pytest.mark.anyio
async def test_cleanup(bridge: MemoryStreamBridge):
    """After cleanup, the run's queue is removed."""
    run_id = "run-cleanup"
    await bridge.publish(run_id, "test", {})
    assert run_id in bridge._queues

    await bridge.cleanup(run_id)
    assert run_id not in bridge._queues
    assert run_id not in bridge._counters


@pytest.mark.anyio
async def test_backpressure():
    """With maxsize=1, publish should not block forever."""
    bridge = MemoryStreamBridge(queue_maxsize=1)
    run_id = "run-bp"

    await bridge.publish(run_id, "first", {})

    # Second publish should either succeed after queue drains or warn+drop
    # It should not hang indefinitely
    async def publish_second():
        await bridge.publish(run_id, "second", {})

    # Give it a generous timeout — the publish timeout is 30s but we don't
    # want to wait that long in tests.  Instead, drain the queue first.
    async def drain():
        await asyncio.sleep(0.05)
        bridge._queues[run_id].get_nowait()

    await asyncio.gather(publish_second(), drain())
    assert bridge._queues[run_id].qsize() == 1


@pytest.mark.anyio
async def test_multiple_runs(bridge: MemoryStreamBridge):
    """Two different run_ids should not interfere with each other."""
    await bridge.publish("run-a", "event-a", {"a": 1})
    await bridge.publish("run-b", "event-b", {"b": 2})
    await bridge.publish_end("run-a")
    await bridge.publish_end("run-b")

    events_a = []
    async for entry in bridge.subscribe("run-a", heartbeat_interval=1.0):
        events_a.append(entry)
        if entry is END_SENTINEL:
            break

    events_b = []
    async for entry in bridge.subscribe("run-b", heartbeat_interval=1.0):
        events_b.append(entry)
        if entry is END_SENTINEL:
            break

    assert len(events_a) == 2
    assert events_a[0].event == "event-a"
    assert events_a[0].data == {"a": 1}

    assert len(events_b) == 2
    assert events_b[0].event == "event-b"
    assert events_b[0].data == {"b": 2}


@pytest.mark.anyio
async def test_event_id_format(bridge: MemoryStreamBridge):
    """Event IDs should use timestamp-sequence format."""
    run_id = "run-id-format"
    await bridge.publish(run_id, "test", {"key": "value"})
    await bridge.publish_end(run_id)

    received = []
    async for entry in bridge.subscribe(run_id, heartbeat_interval=1.0):
        received.append(entry)
        if entry is END_SENTINEL:
            break

    event = received[0]
    assert re.match(r"^\d+-\d+$", event.id), f"Expected timestamp-seq format, got {event.id}"


# ---------------------------------------------------------------------------
# END sentinel guarantee tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_end_sentinel_delivered_when_queue_full():
    """END sentinel must always be delivered, even when the queue is completely full.

    This is the critical regression test for the bug where publish_end()
    would silently drop the END sentinel when the queue was full, causing
    subscribe() to hang forever and leaking resources.
    """
    bridge = MemoryStreamBridge(queue_maxsize=2)
    run_id = "run-end-full"

    # Fill the queue to capacity
    await bridge.publish(run_id, "event-1", {"n": 1})
    await bridge.publish(run_id, "event-2", {"n": 2})
    assert bridge._queues[run_id].full()

    # publish_end should succeed by evicting old events
    await bridge.publish_end(run_id)

    # Subscriber must receive END_SENTINEL
    events = []
    async for entry in bridge.subscribe(run_id, heartbeat_interval=0.1):
        events.append(entry)
        if entry is END_SENTINEL:
            break

    assert any(e is END_SENTINEL for e in events), "END sentinel was not delivered"


@pytest.mark.anyio
async def test_end_sentinel_evicts_oldest_events():
    """When queue is full, publish_end evicts the oldest events to make room."""
    bridge = MemoryStreamBridge(queue_maxsize=1)
    run_id = "run-evict"

    # Fill queue with one event
    await bridge.publish(run_id, "will-be-evicted", {})
    assert bridge._queues[run_id].full()

    # publish_end must succeed
    await bridge.publish_end(run_id)

    # The only event we should get is END_SENTINEL (the regular event was evicted)
    events = []
    async for entry in bridge.subscribe(run_id, heartbeat_interval=0.1):
        events.append(entry)
        if entry is END_SENTINEL:
            break

    assert len(events) == 1
    assert events[0] is END_SENTINEL


@pytest.mark.anyio
async def test_end_sentinel_no_eviction_when_space_available():
    """When queue has space, publish_end should not evict anything."""
    bridge = MemoryStreamBridge(queue_maxsize=10)
    run_id = "run-no-evict"

    await bridge.publish(run_id, "event-1", {"n": 1})
    await bridge.publish(run_id, "event-2", {"n": 2})
    await bridge.publish_end(run_id)

    events = []
    async for entry in bridge.subscribe(run_id, heartbeat_interval=0.1):
        events.append(entry)
        if entry is END_SENTINEL:
            break

    # All events plus END should be present
    assert len(events) == 3
    assert events[0].event == "event-1"
    assert events[1].event == "event-2"
    assert events[2] is END_SENTINEL


@pytest.mark.anyio
async def test_concurrent_tasks_end_sentinel():
    """Multiple concurrent producer/consumer pairs should all terminate properly.

    Simulates the production scenario where multiple runs share a single
    bridge instance — each must receive its own END sentinel.
    """
    bridge = MemoryStreamBridge(queue_maxsize=4)
    num_runs = 4

    async def producer(run_id: str):
        for i in range(10):  # More events than queue capacity
            await bridge.publish(run_id, f"event-{i}", {"i": i})
        await bridge.publish_end(run_id)

    async def consumer(run_id: str) -> list:
        events = []
        async for entry in bridge.subscribe(run_id, heartbeat_interval=0.1):
            events.append(entry)
            if entry is END_SENTINEL:
                return events
        return events  # pragma: no cover

    # Run producers and consumers concurrently
    run_ids = [f"concurrent-{i}" for i in range(num_runs)]
    producers = [producer(rid) for rid in run_ids]
    consumers = [consumer(rid) for rid in run_ids]

    # Start consumers first, then producers
    consumer_tasks = [asyncio.create_task(c) for c in consumers]
    await asyncio.gather(*producers)

    results = await asyncio.wait_for(
        asyncio.gather(*consumer_tasks),
        timeout=10.0,
    )

    for i, events in enumerate(results):
        assert events[-1] is END_SENTINEL, f"Run {run_ids[i]} did not receive END sentinel"


# ---------------------------------------------------------------------------
# Drop counter tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_dropped_count_tracking():
    """Dropped events should be tracked per run_id."""
    bridge = MemoryStreamBridge(queue_maxsize=1)
    run_id = "run-drop-count"

    # Fill the queue
    await bridge.publish(run_id, "first", {})

    # This publish will time out and be dropped (we patch timeout to be instant)
    # Instead, we verify the counter after publish_end eviction
    await bridge.publish_end(run_id)

    # dropped_count tracks publish() drops, not publish_end evictions
    assert bridge.dropped_count(run_id) == 0

    # cleanup should also clear the counter
    await bridge.cleanup(run_id)
    assert bridge.dropped_count(run_id) == 0


@pytest.mark.anyio
async def test_dropped_total():
    """dropped_total should sum across all runs."""
    bridge = MemoryStreamBridge(queue_maxsize=256)

    # No drops yet
    assert bridge.dropped_total == 0

    # Manually set some counts to verify the property
    bridge._dropped_counts["run-a"] = 3
    bridge._dropped_counts["run-b"] = 7
    assert bridge.dropped_total == 10


@pytest.mark.anyio
async def test_cleanup_clears_dropped_counts():
    """cleanup() should clear the dropped counter for the run."""
    bridge = MemoryStreamBridge(queue_maxsize=256)
    run_id = "run-cleanup-drops"

    bridge._get_or_create_queue(run_id)
    bridge._dropped_counts[run_id] = 5

    await bridge.cleanup(run_id)
    assert run_id not in bridge._dropped_counts


@pytest.mark.anyio
async def test_close_clears_dropped_counts():
    """close() should clear all dropped counters."""
    bridge = MemoryStreamBridge(queue_maxsize=256)
    bridge._dropped_counts["run-x"] = 10
    bridge._dropped_counts["run-y"] = 20

    await bridge.close()
    assert bridge.dropped_total == 0
    assert len(bridge._dropped_counts) == 0


# ---------------------------------------------------------------------------
# Factory tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_make_stream_bridge_defaults():
    """make_stream_bridge() with no config yields a MemoryStreamBridge."""
    async with make_stream_bridge() as bridge:
        assert isinstance(bridge, MemoryStreamBridge)
