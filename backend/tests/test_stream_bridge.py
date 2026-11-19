"""Tests for StreamBridge implementations."""

import asyncio
import os
import re
import uuid
from collections import defaultdict
from unittest.mock import AsyncMock, Mock

import anyio
import pytest
from pydantic import ValidationError

from deerflow.config.stream_bridge_config import (
    MAX_HEARTBEAT_INTERVAL_SECONDS,
    MAX_RECOVERED_STREAM_CLEANUP_DELAY_SECONDS,
    StreamBridgeConfig,
    set_stream_bridge_config,
)
from deerflow.runtime import END_SENTINEL, HEARTBEAT_SENTINEL, MemoryStreamBridge, StreamGap, StreamProducerLeaseState, make_stream_bridge

# RedisStreamBridge is no longer re-exported from deerflow.runtime (redis is an
# optional extra; see the NOTE in runtime/stream_bridge/__init__.py). Import it
# directly from the submodule.
from deerflow.runtime.stream_bridge.redis import RedisStreamBridge

_INVALID_NUMERIC_REDIS_CURSORS = [
    pytest.param("9" * 5000 + "-0", id="oversized-milliseconds"),
    pytest.param("1-" + "9" * 5000, id="oversized-sequence"),
    pytest.param("18446744073709551616-0", id="milliseconds-overflow"),
    pytest.param("1-18446744073709551616", id="sequence-overflow"),
    pytest.param("١-٠", id="non-ascii-digits"),
]


def _stream_id_gt(left: str, right: str) -> bool:
    left_ms, left_seq = left.split("-", 1)
    right_ms, right_seq = right.split("-", 1)
    return (int(left_ms), int(left_seq)) > (int(right_ms), int(right_seq))


class _FakeRedis:
    def __init__(self) -> None:
        self.streams = defaultdict(list)
        self.conditions = defaultdict(asyncio.Condition)
        self.counters = defaultdict(int)
        self.deleted = []
        self.expirations = []
        self.values = {}
        self.closed = False
        self.ping_calls = 0
        self.ping_error: Exception | None = None
        self._eval_lock = asyncio.Lock()

    async def ping(self):
        self.ping_calls += 1
        if self.ping_error is not None:
            raise self.ping_error
        return True

    async def xadd(self, name, fields, maxlen=None, approximate=True):
        self.counters[name] += 1
        event_id = f"{self.counters[name]}-0"
        async with self.conditions[name]:
            self.streams[name].append((event_id, dict(fields)))
            if maxlen is not None and len(self.streams[name]) > maxlen:
                del self.streams[name][: len(self.streams[name]) - maxlen]
            self.conditions[name].notify_all()
        return event_id

    async def xread(self, streams, count=None, block=None):
        [(name, last_id)] = list(streams.items())
        timeout = None if block is None else block / 1000
        while True:
            async with self.conditions[name]:
                entries = [(event_id, fields) for event_id, fields in self.streams.get(name, []) if _stream_id_gt(event_id, last_id)]
                if entries:
                    return [(name, entries[:count] if count is not None else entries)]
                if timeout is None:
                    return []
                try:
                    await asyncio.wait_for(self.conditions[name].wait(), timeout=timeout)
                except TimeoutError:
                    return []

    async def xrevrange(self, name, max="+", min="-", count=None):
        entries = list(reversed(self.streams.get(name, [])))
        return entries[:count] if count is not None else entries

    async def xrange(self, name, min="-", max="+", count=None):
        entries = list(self.streams.get(name, []))
        return entries[:count] if count is not None else entries

    async def set(self, name, value, *, ex=None, nx=False, xx=False):
        exists = name in self.values
        if nx and exists:
            return False
        if xx and not exists:
            return False
        self.values[name] = value
        if ex is not None:
            self.expirations.append((name, ex))
        return True

    async def get(self, name):
        return self.values.get(name)

    async def mget(self, *names):
        return [self.values.get(name) for name in names]

    def _tail_is_end(self, stream_key):
        entries = self.streams.get(stream_key, [])
        return bool(entries and entries[-1][1].get("kind") == "end")

    def _has_end_marker(self, stream_key):
        return any(fields.get("kind") == "end" for _event_id, fields in self.streams.get(stream_key, []))

    async def eval(self, script, numkeys, *args):
        # Redis executes a Lua script atomically. Keep the fake's assertion
        # surface faithful even though individual emulated commands yield.
        async with self._eval_lock:
            return await self._eval(script, numkeys, *args)

    async def _eval(self, script, numkeys, *args):
        keys = args[:numkeys]
        values = args[numkeys:]
        if numkeys == 2 and not values:
            tracking_key, active_key = keys
            if active_key in self.values:
                return 0
            if tracking_key not in self.values:
                return 2
            self.values.pop(tracking_key, None)
            self.deleted.append(tracking_key)
            return 1
        if numkeys == 3 and not values:
            stream_key, tracking_key, active_key = keys
            if active_key in self.values:
                return 0
            return await self.delete(stream_key, tracking_key)
        if numkeys == 3 and len(values) == 1:
            stream_key, tracking_key, active_key = keys
            (token,) = values
            tracked = self.values.get(tracking_key)
            active = self.values.get(active_key)
            if tracked is not None and tracked != token or active is not None and active != token:
                return 0
            await self.delete(stream_key, tracking_key, active_key)
            return 1
        if numkeys == 2 and len(values) == 6:
            active_key, stream_key = keys
            maxlen, stream_ttl, kind, event, data, legacy_scan_enabled = values
            if active_key in self.values:
                return 0
            if kind == "end" and stream_key not in self.streams:
                return 2
            if kind == "end":
                if self._tail_is_end(stream_key) or (int(legacy_scan_enabled) and self._has_end_marker(stream_key)):
                    return 1
            elif self._tail_is_end(stream_key):
                return 1
            event_id = await self.xadd(
                stream_key,
                {"kind": kind, "event": event, "data": data},
                maxlen=int(maxlen),
                approximate=False,
            )
            if int(stream_ttl) > 0:
                await self.expire(stream_key, int(stream_ttl))
            return event_id
        if numkeys == 1:
            (name,) = keys
            (token,) = values
            if self.values.get(name) != token:
                return 0
            self.values.pop(name, None)
            self.deleted.append(name)
            return 1
        if numkeys == 2:
            active_key, tracking_key = keys
            token, active_ttl, tracking_ttl = values
            if self.values.get(active_key) != token or self.values.get(tracking_key) != token:
                return 0
            await self.expire(active_key, int(active_ttl))
            if int(tracking_ttl) > 0:
                await self.expire(tracking_key, int(tracking_ttl))
            return 1
        if numkeys == 3:
            active_key, tracking_key, stream_key = keys
            token, maxlen, stream_ttl, kind, event, data, legacy_scan_enabled = values
            if self.values.get(active_key) != token or self.values.get(tracking_key) != token:
                return 0
            if kind == "end":
                if self._tail_is_end(stream_key) or (int(legacy_scan_enabled) and self._has_end_marker(stream_key)):
                    return 1
            elif self._tail_is_end(stream_key):
                return 1
            event_id = await self.xadd(
                stream_key,
                {"kind": kind, "event": event, "data": data},
                maxlen=int(maxlen),
                approximate=False,
            )
            if int(stream_ttl) > 0:
                await self.expire(stream_key, int(stream_ttl))
            return event_id
        raise AssertionError(f"unexpected eval key count: {numkeys}")

    async def delete(self, *names):
        deleted = 0
        for name in names:
            self.deleted.append(name)
            deleted += int(name in self.streams or name in self.values)
            self.streams.pop(name, None)
            self.values.pop(name, None)
        return deleted

    async def exists(self, name):
        return 1 if name in self.streams or name in self.values else 0

    async def expire(self, name, seconds):
        self.expirations.append((name, seconds))
        return name in self.streams or name in self.values

    def pipeline(self, *, transaction=True):
        return _FakeRedisPipeline(self)

    async def aclose(self):
        self.closed = True


class _DelayedBlockingReadRedis:
    """Hold the first blocking XREAD response while the stream is trimmed."""

    def __init__(self, redis) -> None:
        self._delegate = redis
        self.blocking_read_started = asyncio.Event()
        self.wake_response_captured = asyncio.Event()
        self.release_wake_response = asyncio.Event()

    def __getattr__(self, name):
        return getattr(self._delegate, name)

    async def xread(self, streams, count=None, block=None):
        if block is None:
            return await self._delegate.xread(streams, count=count, block=block)

        self.blocking_read_started.set()
        response = await self._delegate.xread(streams, count=count, block=block)
        if response:
            self.wake_response_captured.set()
            await self.release_wake_response.wait()
        return response


class _LostAckRedis:
    """Delegate to Redis but drop one successful EVAL response."""

    def __init__(self, redis) -> None:
        self._delegate = redis
        self.drop_next_successful_eval = False

    def __getattr__(self, name):
        return getattr(self._delegate, name)

    async def eval(self, script, numkeys, *args):
        result = await self._delegate.eval(script, numkeys, *args)
        if self.drop_next_successful_eval and result:
            self.drop_next_successful_eval = False
            raise TimeoutError("simulated lost Redis EVAL acknowledgement")
        return result


class _FakeRedisPipeline:
    def __init__(self, redis: _FakeRedis) -> None:
        self.redis = redis
        self.ops = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    def xadd(self, name, fields, maxlen=None, approximate=True):
        self.ops.append(("xadd", name, fields, maxlen, approximate))
        return self

    def expire(self, name, seconds):
        self.ops.append(("expire", name, seconds))
        return self

    def xrange(self, name, min="-", max="+", count=None):
        self.ops.append(("xrange", name, min, max, count))
        return self

    def xrevrange(self, name, max="+", min="-", count=None):
        self.ops.append(("xrevrange", name, max, min, count))
        return self

    def xread(self, streams, count=None, block=None):
        self.ops.append(("xread", streams, count, block))
        return self

    async def execute(self):
        results = []
        for op in self.ops:
            if op[0] == "xadd":
                _, name, fields, maxlen, approximate = op
                results.append(await self.redis.xadd(name, fields, maxlen=maxlen, approximate=approximate))
            elif op[0] == "expire":
                _, name, seconds = op
                results.append(await self.redis.expire(name, seconds))
            elif op[0] == "xrange":
                _, name, min_id, max_id, count = op
                results.append(await self.redis.xrange(name, min=min_id, max=max_id, count=count))
            elif op[0] == "xrevrange":
                _, name, max_id, min_id, count = op
                results.append(await self.redis.xrevrange(name, max=max_id, min=min_id, count=count))
            elif op[0] == "xread":
                _, streams, count, block = op
                results.append(await self.redis.xread(streams, count=count, block=block))
        return results


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
    bridge._get_or_create_stream(run_id)  # ensure stream exists

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
async def test_memory_bridge_uses_configured_default_heartbeat():
    """A subscriber may omit its override and inherit the bridge setting."""
    bridge = MemoryStreamBridge(queue_maxsize=256, heartbeat_interval=0.01)
    run_id = "run-configured-heartbeat"
    bridge._get_or_create_stream(run_id)

    entry = await asyncio.wait_for(anext(bridge.subscribe(run_id)), timeout=1.0)

    assert entry is HEARTBEAT_SENTINEL
    assert bridge.heartbeat_interval == 0.01


@pytest.mark.anyio
async def test_cleanup(bridge: MemoryStreamBridge):
    """After cleanup, the run's stream/event log is removed."""
    run_id = "run-cleanup"
    await bridge.publish(run_id, "test", {})
    assert run_id in bridge._streams

    await bridge.cleanup(run_id)
    assert run_id not in bridge._streams
    assert run_id not in bridge._counters


@pytest.mark.anyio
async def test_stream_exists_reports_cleanup(bridge: MemoryStreamBridge):
    """Callers can detect when the in-process event log has been cleaned up.

    Before cleanup a completed run's retained history still exists; after
    cleanup ``stream_exists`` reports False so a reconnecting subscriber does
    not hang waiting on a stream whose data is already gone.
    """
    run_id = "run-post-cleanup"
    await bridge.publish(run_id, "event-1", {"n": 1})
    await bridge.publish_end(run_id)

    assert await bridge.stream_exists(run_id) is True
    await bridge.cleanup(run_id)
    assert await bridge.stream_exists(run_id) is False


@pytest.mark.anyio
async def test_history_is_bounded():
    """Retained history should be bounded by queue_maxsize."""
    bridge = MemoryStreamBridge(queue_maxsize=1)
    run_id = "run-bp"

    await bridge.publish(run_id, "first", {})
    await bridge.publish(run_id, "second", {})
    await bridge.publish_end(run_id)

    received = []
    async for entry in bridge.subscribe(run_id, heartbeat_interval=1.0):
        received.append(entry)
        if entry is END_SENTINEL:
            break

    assert len(received) == 2
    assert received[0].event == "second"
    assert received[1] is END_SENTINEL


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


@pytest.mark.anyio
async def test_subscribe_replays_after_last_event_id(bridge: MemoryStreamBridge):
    """Reconnect should replay buffered events after the provided Last-Event-ID."""
    run_id = "run-replay"
    await bridge.publish(run_id, "metadata", {"run_id": run_id})
    await bridge.publish(run_id, "values", {"step": 1})
    await bridge.publish(run_id, "updates", {"step": 2})
    await bridge.publish_end(run_id)

    first_pass = []
    async for entry in bridge.subscribe(run_id, heartbeat_interval=1.0):
        first_pass.append(entry)
        if entry is END_SENTINEL:
            break

    received = []
    async for entry in bridge.subscribe(
        run_id,
        last_event_id=first_pass[0].id,
        heartbeat_interval=1.0,
    ):
        received.append(entry)
        if entry is END_SENTINEL:
            break

    assert [entry.event for entry in received[:-1]] == ["values", "updates"]
    assert received[-1] is END_SENTINEL


@pytest.mark.anyio
async def test_evicted_last_event_id_yields_gap_before_partial_replay():
    """A valid cursor older than retained history must not silently partial-replay."""
    bridge = MemoryStreamBridge(queue_maxsize=2)
    run_id = "run-evicted-cursor"
    await bridge.publish(run_id, "e1", {"step": 1})
    await bridge.publish(run_id, "e2", {"step": 2})

    stream = bridge._streams[run_id]
    e1_id = stream.events[0].id
    await bridge.publish(run_id, "e3", {"step": 3})  # trims e1
    await bridge.publish(run_id, "e4", {"step": 4})  # trims the unread e2
    await bridge.publish_end(run_id)

    received = []
    async for entry in bridge.subscribe(
        run_id,
        last_event_id=e1_id,
        heartbeat_interval=1.0,
    ):
        received.append(entry)

    assert received == [
        StreamGap(
            requested_event_id=e1_id,
            earliest_available_event_id=stream.events[0].id,
            latest_available_event_id=stream.events[-1].id,
        )
    ]


@pytest.mark.anyio
async def test_slow_subscriber_yields_gap_after_buffer_trim():
    """A live subscriber that falls behind must not silently jump forward."""
    bridge = MemoryStreamBridge(queue_maxsize=2)
    run_id = "run-slow-subscriber"
    await bridge.publish(run_id, "e1", {"step": 1})
    await bridge.publish(run_id, "e2", {"step": 2})

    subscriber = bridge.subscribe(run_id, heartbeat_interval=1.0)
    first = await anext(subscriber)
    assert first.event == "e1"

    await bridge.publish(run_id, "e3", {"step": 3})
    await bridge.publish(run_id, "e4", {"step": 4})

    stream = bridge._streams[run_id]
    assert await anext(subscriber) == StreamGap(
        requested_event_id=first.id,
        earliest_available_event_id=stream.events[0].id,
        latest_available_event_id=stream.events[-1].id,
    )
    with pytest.raises(StopAsyncIteration):
        await anext(subscriber)


# ---------------------------------------------------------------------------
# Stream termination tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_publish_end_terminates_even_when_history_is_full():
    """publish_end() should terminate subscribers without mutating retained history."""
    bridge = MemoryStreamBridge(queue_maxsize=2)
    run_id = "run-end-history-full"

    await bridge.publish(run_id, "event-1", {"n": 1})
    await bridge.publish(run_id, "event-2", {"n": 2})
    stream = bridge._streams[run_id]
    assert [entry.event for entry in stream.events] == ["event-1", "event-2"]

    await bridge.publish_end(run_id)
    assert [entry.event for entry in stream.events] == ["event-1", "event-2"]

    events = []
    async for entry in bridge.subscribe(run_id, heartbeat_interval=0.1):
        events.append(entry)
        if entry is END_SENTINEL:
            break

    assert [entry.event for entry in events[:-1]] == ["event-1", "event-2"]
    assert events[-1] is END_SENTINEL


@pytest.mark.anyio
async def test_publish_end_without_history_yields_end_immediately():
    """Subscribers should still receive END when a run completes without events."""
    bridge = MemoryStreamBridge(queue_maxsize=2)
    run_id = "run-end-empty"
    await bridge.publish_end(run_id)

    events = []
    async for entry in bridge.subscribe(run_id, heartbeat_interval=0.1):
        events.append(entry)
        if entry is END_SENTINEL:
            break

    assert len(events) == 1
    assert events[0] is END_SENTINEL


@pytest.mark.anyio
async def test_publish_end_preserves_history_when_space_available():
    """When history has spare capacity, publish_end should preserve prior events."""
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
async def test_concurrent_slow_consumers_receive_gap():
    """Concurrent consumers must all receive a gap when producers outrun retention.

    Each producer fills a four-entry bridge without yielding, so subscribers
    that started at offset zero cannot observe the first six events.
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

    run_ids = [f"concurrent-{i}" for i in range(num_runs)]
    results: dict[str, list] = {}

    async def consume_into(run_id: str) -> None:
        results[run_id] = await consumer(run_id)

    with anyio.fail_after(10):
        async with anyio.create_task_group() as task_group:
            for run_id in run_ids:
                task_group.start_soon(consume_into, run_id)
            await anyio.sleep(0)
            for run_id in run_ids:
                task_group.start_soon(producer, run_id)

    for run_id in run_ids:
        events = results[run_id]
        assert len(events) == 1
        assert isinstance(events[0], StreamGap), f"Run {run_id} did not receive a gap"
        assert events[0].requested_event_id is None


# ---------------------------------------------------------------------------
# Unit tests for RedisStreamBridge
# ---------------------------------------------------------------------------


@pytest.fixture
def redis_bridge() -> RedisStreamBridge:
    return RedisStreamBridge(redis_url="redis://fake", queue_maxsize=2, client=_FakeRedis())


# ---------------------------------------------------------------------------
# Readiness ping
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_memory_bridge_ping_has_no_external_backend():
    """The in-process bridge has nothing external to probe and never reports unreachable."""
    bridge = MemoryStreamBridge()

    assert bridge.supports_cross_process is False
    assert await bridge.ping() is True


@pytest.mark.anyio
async def test_redis_bridge_ping_reports_reachable_backend():
    fake = _FakeRedis()
    bridge = RedisStreamBridge(redis_url="redis://fake", queue_maxsize=2, client=fake)

    assert bridge.supports_cross_process is True
    assert await bridge.ping() is True
    assert fake.ping_calls == 1


@pytest.mark.anyio
async def test_redis_bridge_ping_reports_unreachable_backend_on_redis_error():
    """A Redis-side failure is a readiness answer (False), not an exception for the probe to unpack."""
    from redis.exceptions import ConnectionError as RedisConnectionError

    fake = _FakeRedis()
    fake.ping_error = RedisConnectionError("connection refused")
    bridge = RedisStreamBridge(redis_url="redis://fake", queue_maxsize=2, client=fake)

    assert await bridge.ping() is False


@pytest.mark.anyio
async def test_redis_publish_subscribe(redis_bridge: RedisStreamBridge):
    """Redis bridge should deliver events in order and terminate on end."""
    run_id = "redis-run-1"

    await redis_bridge.publish(run_id, "metadata", {"run_id": run_id})
    await redis_bridge.publish(run_id, "values", {"messages": []})
    await redis_bridge.publish_end(run_id)

    received = []
    async for entry in redis_bridge.subscribe(run_id, heartbeat_interval=1.0):
        received.append(entry)
        if entry is END_SENTINEL:
            break

    assert [entry.event for entry in received[:-1]] == ["metadata", "values"]
    assert received[0].data == {"run_id": run_id}
    assert received[-1] is END_SENTINEL


@pytest.mark.anyio
async def test_redis_publish_end_is_idempotent(redis_bridge: RedisStreamBridge):
    """Concurrent and repeated END publication must append at most one marker."""
    fake = redis_bridge._redis
    run_id = "redis-run-idempotent-end"
    key = redis_bridge._stream_key(run_id)

    await redis_bridge.start_producer_lease(run_id)
    try:
        await redis_bridge.publish(run_id, "metadata", {"run_id": run_id})
        await asyncio.gather(*(redis_bridge.publish_end(run_id) for _ in range(8)))
        await redis_bridge.publish_end(run_id)

        entries = fake.streams[key]
        assert [fields["kind"] for _event_id, fields in entries] == ["event", "end"]

        received = [entry async for entry in redis_bridge.subscribe(run_id, heartbeat_interval=1.0)]
        assert [entry.event for entry in received[:-1]] == ["metadata"]
        assert received[-1] is END_SENTINEL
    finally:
        await redis_bridge.finish_producer_lease(run_id)


@pytest.mark.anyio
async def test_redis_publish_end_recognizes_legacy_end_before_late_events(redis_bridge: RedisStreamBridge):
    """An END written by the old buggy writer still prevents a duplicate END."""
    fake = redis_bridge._redis
    run_id = "redis-run-legacy-end-not-tail"
    key = redis_bridge._stream_key(run_id)
    fake.streams[key] = [
        ("1-0", {"kind": "event", "event": "metadata", "data": "{}"}),
        ("2-0", {"kind": "end"}),
        ("3-0", {"kind": "event", "event": "late", "data": "{}"}),
    ]

    await redis_bridge.publish_end(run_id)

    assert [fields["kind"] for _event_id, fields in fake.streams[key]].count("end") == 1


@pytest.mark.anyio
@pytest.mark.parametrize("owned", [False, True], ids=["recovery", "owner"])
async def test_redis_legacy_midstream_end_allows_data_but_deduplicates_end(owned: bool):
    """Data checks only the tail; END retries still inspect the retained window."""
    fake = _FakeRedis()
    bridge = RedisStreamBridge(redis_url="redis://fake", queue_maxsize=8, client=fake)
    run_id = "redis-run-legacy-data-after-end"
    key = bridge._stream_key(run_id)
    if owned:
        await bridge.start_producer_lease(run_id)
    try:
        await fake.xadd(key, {"kind": "end"})
        await fake.xadd(key, {"kind": "event", "event": "legacy-late", "data": "{}"})
        before = list(fake.streams[key])

        await bridge.publish(run_id, "current-data", {"step": 2})

        entries = list(fake.streams[key])
        assert entries[:2] == before
        assert len(entries) == 3
        assert entries[-1][1]["event"] == "current-data"
        await bridge.publish_end(run_id)
        assert fake.streams[key] == entries
    finally:
        if owned:
            await bridge.finish_producer_lease(run_id)


@pytest.mark.anyio
async def test_redis_owned_end_recreates_missing_buffer_with_live_lease():
    """Only unowned recovery END is a no-op on a missing buffer."""
    fake = _FakeRedis()
    bridge = RedisStreamBridge(redis_url="redis://fake", client=fake)
    run_id = "redis-run-owned-missing-buffer"
    key = bridge._stream_key(run_id)
    await bridge.start_producer_lease(run_id)
    try:
        await bridge.publish(run_id, "metadata", {})
        await fake.delete(key)

        await bridge.publish_end(run_id)

        assert [fields["kind"] for _event_id, fields in fake.streams[key]] == ["end"]
    finally:
        await bridge.finish_producer_lease(run_id)


@pytest.mark.anyio
async def test_redis_publish_after_end_is_rejected_without_appending(redis_bridge: RedisStreamBridge):
    """Once END is retained, later event publication cannot corrupt terminal order."""
    fake = redis_bridge._redis
    run_id = "redis-run-publish-after-end"
    key = redis_bridge._stream_key(run_id)

    await redis_bridge.publish(run_id, "metadata", {"run_id": run_id})
    await redis_bridge.publish_end(run_id)
    before = list(fake.streams[key])

    with pytest.raises(RuntimeError, match="already ended"):
        await redis_bridge.publish(run_id, "late", {"step": 2})

    assert fake.streams[key] == before


@pytest.mark.anyio
async def test_redis_event_end_race_never_appends_after_end(redis_bridge: RedisStreamBridge):
    """The atomic terminal check keeps END last even when an event races it."""
    fake = redis_bridge._redis
    run_id = "redis-run-event-end-race"
    key = redis_bridge._stream_key(run_id)

    await redis_bridge.publish(run_id, "metadata", {"run_id": run_id})
    event_result, end_result = await asyncio.gather(
        redis_bridge.publish(run_id, "racing-event", {"step": 2}),
        redis_bridge.publish_end(run_id),
        return_exceptions=True,
    )

    assert end_result is None
    assert event_result is None or "already ended" in str(event_result)
    kinds = [fields["kind"] for _event_id, fields in fake.streams[key]]
    assert kinds.count("end") == 1
    assert kinds[-1] == "end"


@pytest.mark.anyio
async def test_redis_recovery_end_after_cleanup_does_not_resurrect_stream(redis_bridge: RedisStreamBridge):
    """A delayed recovery END is a no-op when cleanup already removed the stream."""
    fake = redis_bridge._redis
    run_id = "redis-run-cleaned-end-retry"
    key = redis_bridge._stream_key(run_id)

    await redis_bridge.publish(run_id, "metadata", {"run_id": run_id})
    await redis_bridge.publish_end(run_id)
    await redis_bridge.cleanup(run_id)
    assert key not in fake.streams

    await redis_bridge.publish_end(run_id)

    assert key not in fake.streams


@pytest.mark.anyio
async def test_redis_replays_after_last_event_id(redis_bridge: RedisStreamBridge):
    """Redis XREAD should resume after Last-Event-ID."""
    run_id = "redis-run-replay"

    await redis_bridge.publish(run_id, "metadata", {"run_id": run_id})
    await redis_bridge.publish(run_id, "values", {"step": 1})
    await redis_bridge.publish_end(run_id)

    first_pass = []
    async for entry in redis_bridge.subscribe(run_id, heartbeat_interval=1.0):
        first_pass.append(entry)
        if entry is END_SENTINEL:
            break

    received = []
    async for entry in redis_bridge.subscribe(run_id, last_event_id=first_pass[0].id, heartbeat_interval=1.0):
        received.append(entry)
        if entry is END_SENTINEL:
            break

    assert [entry.event for entry in received[:-1]] == ["values"]
    assert received[-1] is END_SENTINEL


@pytest.mark.anyio
async def test_redis_evicted_last_event_id_yields_gap_before_partial_replay(
    redis_bridge: RedisStreamBridge,
):
    """Redis must distinguish a trimmed cursor from a complete replay."""
    run_id = "redis-run-evicted-cursor"
    await redis_bridge.publish(run_id, "e1", {"step": 1})
    key = redis_bridge._stream_key(run_id)
    e1_id = redis_bridge._redis.streams[key][0][0]
    await redis_bridge.publish(run_id, "e2", {"step": 2})
    await redis_bridge.publish(run_id, "e3", {"step": 3})

    retained_ids = [event_id for event_id, _fields in redis_bridge._redis.streams[key]]
    received = [
        entry
        async for entry in redis_bridge.subscribe(
            run_id,
            last_event_id=e1_id,
            heartbeat_interval=1.0,
        )
    ]

    assert received == [
        StreamGap(
            requested_event_id=e1_id,
            earliest_available_event_id=retained_ids[0],
            latest_available_event_id=retained_ids[-1],
        )
    ]


@pytest.mark.anyio
async def test_redis_slow_subscriber_yields_gap_after_buffer_trim(
    redis_bridge: RedisStreamBridge,
):
    """A live Redis subscriber must detect trimming after its last batch."""
    run_id = "redis-run-slow-subscriber"
    await redis_bridge.publish(run_id, "e1", {"step": 1})
    subscriber = redis_bridge.subscribe(run_id, heartbeat_interval=1.0)
    first = await anext(subscriber)
    assert first.event == "e1"

    await redis_bridge.publish(run_id, "e2", {"step": 2})
    await redis_bridge.publish(run_id, "e3", {"step": 3})
    await redis_bridge.publish(run_id, "e4", {"step": 4})
    key = redis_bridge._stream_key(run_id)
    retained_ids = [event_id for event_id, _fields in redis_bridge._redis.streams[key]]

    assert await anext(subscriber) == StreamGap(
        requested_event_id=first.id,
        earliest_available_event_id=retained_ids[0],
        latest_available_event_id=retained_ids[-1],
    )
    with pytest.raises(StopAsyncIteration):
        await anext(subscriber)


@pytest.mark.anyio
async def test_redis_initial_subscriber_yields_gap_when_first_wake_falls_behind():
    """An established no-cursor wait must not silently replay a trimmed tail."""
    fake = _FakeRedis()
    delayed = _DelayedBlockingReadRedis(fake)
    bridge = RedisStreamBridge(
        redis_url="redis://fake",
        queue_maxsize=2,
        client=delayed,
    )
    run_id = "redis-run-initial-subscriber-gap"
    subscriber = bridge.subscribe(run_id, heartbeat_interval=1.0)
    first_item = asyncio.create_task(anext(subscriber))

    with anyio.fail_after(2):
        await delayed.blocking_read_started.wait()
        await bridge.publish(run_id, "e1", {"step": 1})
        await delayed.wake_response_captured.wait()
        await bridge.publish(run_id, "e2", {"step": 2})
        await bridge.publish(run_id, "e3", {"step": 3})
        await bridge.publish(run_id, "e4", {"step": 4})
        delayed.release_wake_response.set()
        gap = await first_item

    key = bridge._stream_key(run_id)
    retained_ids = [event_id for event_id, _fields in fake.streams[key]]
    assert gap == StreamGap(
        requested_event_id=None,
        earliest_available_event_id=retained_ids[0],
        latest_available_event_id=retained_ids[-1],
    )
    with pytest.raises(StopAsyncIteration):
        await anext(subscriber)


@pytest.mark.anyio
async def test_redis_recovery_cursor_at_end_yields_end_immediately(
    redis_bridge: RedisStreamBridge,
):
    """The latest gap cursor may be the internal end marker."""
    run_id = "redis-run-end-cursor"
    await redis_bridge.publish(run_id, "event", {})
    await redis_bridge.publish_end(run_id)
    key = redis_bridge._stream_key(run_id)
    end_id = redis_bridge._redis.streams[key][-1][0]

    received = [
        entry
        async for entry in redis_bridge.subscribe(
            run_id,
            last_event_id=end_id,
            heartbeat_interval=0.01,
        )
    ]

    assert received == [END_SENTINEL]


@pytest.mark.anyio
async def test_redis_invalid_last_event_id_tails_live_events(redis_bridge: RedisStreamBridge):
    """Malformed reconnect ids should not replay retained Redis events."""
    run_id = "redis-run-invalid-last-event-id"

    await redis_bridge.publish(run_id, "metadata", {"run_id": run_id})
    received = []

    async def publish_later() -> None:
        await anyio.sleep(0.05)
        await redis_bridge.publish(run_id, "values", {"step": 1})
        await redis_bridge.publish_end(run_id)

    with anyio.fail_after(2):
        async with anyio.create_task_group() as task_group:
            task_group.start_soon(publish_later)
            async for entry in redis_bridge.subscribe(run_id, last_event_id="-1", heartbeat_interval=0.01):
                if entry is HEARTBEAT_SENTINEL:
                    continue
                received.append(entry)
                if entry is END_SENTINEL:
                    break

    assert [entry.event for entry in received[:-1]] == ["values"]
    assert received[-1] is END_SENTINEL


@pytest.mark.anyio
async def test_redis_invalid_last_event_id_tails_empty_stream(redis_bridge: RedisStreamBridge):
    """Malformed reconnect ids should still wait for the first Redis event."""
    run_id = "redis-run-invalid-empty"
    received = []

    async def publish_later() -> None:
        await anyio.sleep(0.05)
        await redis_bridge.publish(run_id, "metadata", {"run_id": run_id})
        await redis_bridge.publish_end(run_id)

    with anyio.fail_after(2):
        async with anyio.create_task_group() as task_group:
            task_group.start_soon(publish_later)
            async for entry in redis_bridge.subscribe(run_id, last_event_id="-1", heartbeat_interval=0.01):
                if entry is HEARTBEAT_SENTINEL:
                    continue
                received.append(entry)
                if entry is END_SENTINEL:
                    break

    assert [entry.event for entry in received[:-1]] == ["metadata"]
    assert received[-1] is END_SENTINEL


@pytest.mark.anyio
@pytest.mark.parametrize("last_event_id", [pytest.param("-1", id="sentinel"), *_INVALID_NUMERIC_REDIS_CURSORS])
async def test_redis_invalid_last_event_id_on_terminal_run_replays_end(redis_bridge: RedisStreamBridge, last_event_id: str):
    """Malformed reconnect ids on terminal streams should drain END instead of hanging."""
    run_id = "redis-run-invalid-terminal"

    await redis_bridge.publish(run_id, "metadata", {"run_id": run_id})
    await redis_bridge.publish_end(run_id)

    received = []
    with anyio.fail_after(2):
        async for entry in redis_bridge.subscribe(run_id, last_event_id=last_event_id, heartbeat_interval=1.0):
            received.append(entry)
            if entry is END_SENTINEL:
                break

    assert [entry.event for entry in received[:-1]] == ["metadata"]
    assert received[-1] is END_SENTINEL


@pytest.mark.anyio
async def test_redis_heartbeat(redis_bridge: RedisStreamBridge):
    """Redis bridge should yield heartbeats when XREAD times out on an existing stream."""
    run_id = "redis-run-heartbeat"
    await redis_bridge.publish(run_id, "init", {})

    received = []
    async for entry in redis_bridge.subscribe(run_id, heartbeat_interval=0.01):
        received.append(entry)
        if entry is HEARTBEAT_SENTINEL:
            break

    assert len(received) == 2
    assert received[0].event == "init"
    assert received[1] is HEARTBEAT_SENTINEL


@pytest.mark.anyio
async def test_redis_publish_end_preserves_data_history_capacity(redis_bridge: RedisStreamBridge):
    """The internal end marker should not evict the configured data history."""
    run_id = "redis-run-end-capacity"

    await redis_bridge.publish(run_id, "event-1", {"n": 1})
    await redis_bridge.publish(run_id, "event-2", {"n": 2})
    await redis_bridge.publish_end(run_id)

    received = []
    async for entry in redis_bridge.subscribe(run_id, heartbeat_interval=1.0):
        received.append(entry)
        if entry is END_SENTINEL:
            break

    assert [entry.event for entry in received[:-1]] == ["event-1", "event-2"]
    assert received[-1] is END_SENTINEL


@pytest.mark.anyio
async def test_redis_cleanup_deletes_stream(redis_bridge: RedisStreamBridge):
    fake = redis_bridge._redis
    run_id = "redis-run-cleanup"

    await redis_bridge.publish(run_id, "event", {})
    await redis_bridge.cleanup(run_id)

    assert fake.deleted == [
        "deerflow:stream_bridge:redis-run-cleanup",
        "deerflow:stream_bridge:redis-run-cleanup:producer-tracked",
    ]


@pytest.mark.anyio
async def test_redis_producer_lease_distinguishes_active_expired_and_untracked():
    fake = _FakeRedis()
    bridge = RedisStreamBridge(redis_url="redis://fake", client=fake)
    run_id = "redis-run-producer-state"

    assert await bridge.producer_lease_state(run_id) == StreamProducerLeaseState.untracked

    await bridge.start_producer_lease(run_id)
    assert await bridge.producer_lease_state(run_id) == StreamProducerLeaseState.active

    await bridge.finish_producer_lease(run_id)
    assert await bridge.producer_lease_state(run_id) == StreamProducerLeaseState.expired

    await bridge.cleanup(run_id)
    assert await bridge.producer_lease_state(run_id) == StreamProducerLeaseState.untracked


@pytest.mark.anyio
async def test_redis_recovery_cleanup_deletes_only_expired_tracking_marker():
    fake = _FakeRedis()
    bridge = RedisStreamBridge(
        redis_url="redis://fake",
        stream_ttl_seconds=0,
        client=fake,
    )
    run_id = "redis-run-expired-tracking-cleanup"

    await bridge.start_producer_lease(run_id)
    assert await bridge.cleanup_expired_producer(run_id) is False
    assert await bridge.producer_lease_state(run_id) == StreamProducerLeaseState.active

    await bridge.finish_producer_lease(run_id)
    assert await bridge.cleanup_expired_producer(run_id) is True
    assert await bridge.producer_lease_state(run_id) == StreamProducerLeaseState.untracked
    await bridge.cleanup(run_id)


@pytest.mark.anyio
async def test_redis_recovery_cleanup_rejects_active_registration_window():
    fake = _FakeRedis()
    bridge = RedisStreamBridge(redis_url="redis://fake", client=fake)
    run_id = "redis-run-active-registration-window"

    await bridge.start_producer_lease(run_id)
    fake.values.pop(bridge._producer_tracking_key(run_id))
    try:
        assert await bridge.cleanup_expired_producer(run_id) is False
        assert bridge._producer_active_key(run_id) in fake.values
    finally:
        await bridge.abort_producer_lease(run_id)


@pytest.mark.anyio
async def test_redis_lost_producer_lease_cancels_the_owning_task(monkeypatch):
    import deerflow.runtime.stream_bridge.redis as redis_bridge_module

    monkeypatch.setattr(
        redis_bridge_module,
        "_PRODUCER_LEASE_RENEW_INTERVAL_SECONDS",
        0.01,
    )
    fake = _FakeRedis()
    bridge = RedisStreamBridge(redis_url="redis://fake", client=fake)
    run_id = "redis-run-producer-lost"
    started = asyncio.Event()
    cancelled = asyncio.Event()
    release = asyncio.Event()

    async def producer():
        await bridge.start_producer_lease(run_id)
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            await release.wait()
            raise
        finally:
            await bridge.finish_producer_lease(run_id)

    owner = asyncio.create_task(producer())
    await asyncio.wait_for(started.wait(), timeout=1)
    fake.values.pop(bridge._producer_active_key(run_id))

    try:
        await asyncio.wait_for(cancelled.wait(), timeout=1)
        with pytest.raises(RuntimeError, match="producer lease was lost"):
            await bridge.publish(run_id, "late", {})
        with pytest.raises(RuntimeError, match="producer lease was lost"):
            await bridge.publish_end(run_id)
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError, match="producer lease expired"):
            await asyncio.wait_for(owner, timeout=1)


@pytest.mark.anyio
async def test_redis_tracking_marker_outlives_short_stream_ttl():
    fake = _FakeRedis()
    bridge = RedisStreamBridge(
        redis_url="redis://fake",
        stream_ttl_seconds=1,
        client=fake,
    )
    run_id = "redis-run-short-stream-ttl"

    await bridge.start_producer_lease(run_id)
    try:
        assert (
            bridge._producer_tracking_key(run_id),
            120,
        ) in fake.expirations
        assert await bridge.producer_lease_state(run_id) == StreamProducerLeaseState.active
    finally:
        await bridge.finish_producer_lease(run_id)


@pytest.mark.anyio
async def test_redis_finish_does_not_delete_a_successor_token():
    fake = _FakeRedis()
    bridge = RedisStreamBridge(redis_url="redis://fake", client=fake)
    run_id = "redis-run-successor-token"
    active_key = bridge._producer_active_key(run_id)

    await bridge.start_producer_lease(run_id)
    fake.values[active_key] = "successor-token"
    await bridge.finish_producer_lease(run_id)

    assert fake.values[active_key] == "successor-token"


@pytest.mark.anyio
async def test_redis_lost_owner_does_not_get_idempotent_end_success():
    """Lease validation precedes retained-END detection for a stale owner."""
    fake = _FakeRedis()
    bridge = RedisStreamBridge(redis_url="redis://fake", client=fake)
    run_id = "redis-run-lost-owner-existing-end"
    active_key = bridge._producer_active_key(run_id)
    key = bridge._stream_key(run_id)
    replacement_owner = asyncio.create_task(asyncio.Event().wait())

    await bridge.start_producer_lease(run_id)
    bridge.transfer_producer_lease(run_id, replacement_owner)
    await bridge.publish_end(run_id)
    fake.values[active_key] = "successor-token"
    try:
        with pytest.raises(RuntimeError, match="producer lease was lost"):
            await bridge.publish_end(run_id)
        assert [fields["kind"] for _event_id, fields in fake.streams[key]].count("end") == 1
    finally:
        await bridge.finish_producer_lease(run_id)
        replacement_owner.cancel()
        await asyncio.gather(replacement_owner, return_exceptions=True)


@pytest.mark.anyio
async def test_redis_publish_is_atomically_fenced_by_producer_token():
    fake = _FakeRedis()
    bridge = RedisStreamBridge(redis_url="redis://fake", client=fake)
    run_id = "redis-run-publish-token"
    active_key = bridge._producer_active_key(run_id)
    replacement_owner = asyncio.create_task(asyncio.Event().wait())

    await bridge.start_producer_lease(run_id)
    bridge.transfer_producer_lease(run_id, replacement_owner)
    fake.values[active_key] = "successor-token"
    try:
        with pytest.raises(RuntimeError, match="producer lease was lost"):
            await bridge.publish(run_id, "late", {"value": 1})
        assert bridge._stream_key(run_id) not in fake.streams
        with pytest.raises(asyncio.CancelledError):
            await replacement_owner
    finally:
        await bridge.finish_producer_lease(run_id)
        replacement_owner.cancel()
        await asyncio.gather(replacement_owner, return_exceptions=True)


@pytest.mark.anyio
async def test_redis_producer_lease_releases_when_owner_never_starts():
    fake = _FakeRedis()
    bridge = RedisStreamBridge(redis_url="redis://fake", client=fake)
    run_id = "redis-run-owner-never-started"

    await bridge.start_producer_lease(run_id)
    owner = asyncio.create_task(asyncio.sleep(3600))
    bridge.transfer_producer_lease(run_id, owner)
    owner.cancel()
    await asyncio.gather(owner, return_exceptions=True)
    for _ in range(10):
        lease = bridge._producer_leases.get(run_id)
        if lease is not None and lease.stopped and lease.renewal_task is None and await bridge.producer_lease_state(run_id) == StreamProducerLeaseState.expired:
            break
        await asyncio.sleep(0)

    lease = bridge._producer_leases[run_id]
    assert lease.stopped is True
    assert lease.renewal_task is None
    assert await bridge.producer_lease_state(run_id) == StreamProducerLeaseState.expired
    await bridge.cleanup(run_id)
    assert run_id not in bridge._producer_leases


@pytest.mark.anyio
async def test_redis_old_owner_exit_cannot_release_transferred_lease():
    fake = _FakeRedis()
    bridge = RedisStreamBridge(redis_url="redis://fake", client=fake)
    run_id = "redis-run-transferred-owner"
    old_owner = asyncio.create_task(asyncio.sleep(3600))
    current_owner = asyncio.create_task(asyncio.sleep(3600))

    await bridge.start_producer_lease(run_id)
    bridge.transfer_producer_lease(run_id, old_owner)
    bridge.transfer_producer_lease(run_id, current_owner)
    old_owner.cancel()
    await asyncio.gather(old_owner, return_exceptions=True)
    for _ in range(5):
        await asyncio.sleep(0)

    try:
        assert bridge._producer_leases[run_id].owner_task is current_owner
        assert await bridge.producer_lease_state(run_id) == StreamProducerLeaseState.active
    finally:
        current_owner.cancel()
        await asyncio.gather(current_owner, return_exceptions=True)
        await bridge.finish_producer_lease(run_id)


@pytest.mark.anyio
@pytest.mark.parametrize("operation", ["abort", "close"])
async def test_redis_explicit_stop_waits_for_owner_cleanup(operation):
    fake = _FakeRedis()
    bridge = RedisStreamBridge(redis_url="redis://fake", client=fake)
    run_id = f"redis-run-owner-cleanup-{operation}"
    owner = asyncio.create_task(asyncio.sleep(3600))
    release_started = asyncio.Event()
    allow_release = asyncio.Event()
    original_delete = bridge._delete_if_token

    async def block_active_release(name, token):
        if name == bridge._producer_active_key(run_id):
            release_started.set()
            await allow_release.wait()
        return await original_delete(name, token)

    await bridge.start_producer_lease(run_id)
    bridge.transfer_producer_lease(run_id, owner)
    bridge._delete_if_token = block_active_release
    owner.cancel()
    await asyncio.gather(owner, return_exceptions=True)
    await asyncio.wait_for(release_started.wait(), timeout=1)

    if operation == "abort":
        explicit_stop = asyncio.create_task(bridge.abort_producer_lease(run_id))
    else:
        explicit_stop = asyncio.create_task(bridge.close())
    await asyncio.sleep(0)
    assert not explicit_stop.done()

    allow_release.set()
    await asyncio.wait_for(explicit_stop, timeout=1)
    expected = StreamProducerLeaseState.untracked if operation == "abort" else StreamProducerLeaseState.expired
    assert await bridge.producer_lease_state(run_id) == expected
    assert run_id not in bridge._producer_leases


@pytest.mark.anyio
async def test_redis_unowned_end_cannot_bypass_an_active_remote_producer():
    fake = _FakeRedis()
    owner = RedisStreamBridge(
        redis_url="redis://fake",
        producer_lease_recovery_enabled=True,
        client=fake,
    )
    recovering_peer = RedisStreamBridge(
        redis_url="redis://fake",
        producer_lease_recovery_enabled=True,
        client=fake,
    )
    run_id = "redis-run-active-remote-producer"

    await owner.start_producer_lease(run_id)
    try:
        with pytest.raises(RuntimeError, match="active producer"):
            await recovering_peer.publish_end(run_id)
        assert owner._stream_key(run_id) not in fake.streams
    finally:
        await owner.abort_producer_lease(run_id)


@pytest.mark.anyio
async def test_redis_abort_discards_unadmitted_tracking_marker():
    fake = _FakeRedis()
    bridge = RedisStreamBridge(redis_url="redis://fake", client=fake)
    run_id = "redis-run-unadmitted"

    await bridge.start_producer_lease(run_id)
    await bridge.abort_producer_lease(run_id)

    assert await bridge.producer_lease_state(run_id) == StreamProducerLeaseState.untracked


@pytest.mark.anyio
async def test_redis_abort_retries_transient_release_failure():
    from redis.exceptions import RedisError

    fake = _FakeRedis()
    bridge = RedisStreamBridge(
        redis_url="redis://fake",
        stream_ttl_seconds=0,
        client=fake,
    )
    run_id = "redis-run-abort-failure"

    await bridge.start_producer_lease(run_id)
    assert all(name != bridge._producer_tracking_key(run_id) for name, _seconds in fake.expirations)

    original_delete = bridge._delete_if_token
    failed_once = False

    async def fail_delete_once(name, token):
        nonlocal failed_once
        if not failed_once:
            failed_once = True
            raise RedisError("delete temporarily unavailable")
        return await original_delete(name, token)

    bridge._delete_if_token = fail_delete_once
    await bridge.abort_producer_lease(run_id)

    assert run_id not in bridge._producer_leases
    assert await bridge.producer_lease_state(run_id) == StreamProducerLeaseState.untracked


@pytest.mark.anyio
async def test_redis_close_retries_failed_abort_cleanup():
    fake = _FakeRedis()
    bridge = RedisStreamBridge(redis_url="redis://fake", client=fake)
    run_id = "redis-run-abort-close-retry"
    await bridge.start_producer_lease(run_id)
    bridge._rollback_producer_lease = AsyncMock(
        side_effect=[False, True],
    )

    await bridge.abort_producer_lease(run_id)
    assert bridge._producer_leases[run_id].discard_tracking_requested is True

    await bridge.close()

    assert bridge._rollback_producer_lease.await_count == 2
    assert run_id not in bridge._producer_leases


@pytest.mark.anyio
async def test_redis_delayed_cleanup_preserves_successor_stream_and_lease():
    fake = _FakeRedis()
    bridge = RedisStreamBridge(redis_url="redis://fake", client=fake)
    run_id = "redis-run-cleanup-successor"
    stream_key = bridge._stream_key(run_id)
    tracking_key = bridge._producer_tracking_key(run_id)
    active_key = bridge._producer_active_key(run_id)

    await bridge.start_producer_lease(run_id)
    await bridge.publish(run_id, "values", {"owner": "old"})
    await bridge.finish_producer_lease(run_id)
    fake.values[tracking_key] = "successor-token"
    fake.values[active_key] = "successor-token"
    await fake.xadd(
        stream_key,
        {"kind": "event", "event": "values", "data": '{"owner":"successor"}'},
    )

    await bridge.cleanup(run_id)

    assert fake.values[tracking_key] == "successor-token"
    assert fake.values[active_key] == "successor-token"
    assert fake.streams[stream_key]


@pytest.mark.anyio
async def test_redis_unowned_cleanup_preserves_active_successor():
    fake = _FakeRedis()
    owner = RedisStreamBridge(redis_url="redis://fake", client=fake)
    recovering_peer = RedisStreamBridge(redis_url="redis://fake", client=fake)
    run_id = "redis-run-unowned-cleanup-successor"
    stream_key = owner._stream_key(run_id)
    tracking_key = owner._producer_tracking_key(run_id)
    active_key = owner._producer_active_key(run_id)

    await owner.start_producer_lease(run_id)
    await owner.publish(run_id, "values", {"owner": "successor"})

    try:
        await recovering_peer.cleanup(run_id)
        assert fake.values[tracking_key] == fake.values[active_key]
        assert fake.streams[stream_key]
    finally:
        await owner.abort_producer_lease(run_id)
        await owner.cleanup(run_id)


@pytest.mark.anyio
async def test_redis_producer_starts_for_unrelated_runs_do_not_serialize():
    fake = _FakeRedis()
    bridge = RedisStreamBridge(redis_url="redis://fake", client=fake)
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    original_set = fake.set

    async def delayed_set(name, value, **kwargs):
        if name == bridge._producer_active_key("run-a"):
            first_started.set()
            await release_first.wait()
        return await original_set(name, value, **kwargs)

    fake.set = delayed_set
    first = asyncio.create_task(bridge.start_producer_lease("run-a"))
    second = None
    try:
        await asyncio.wait_for(first_started.wait(), timeout=1)
        second = asyncio.create_task(bridge.start_producer_lease("run-b"))
        assert await asyncio.wait_for(asyncio.shield(second), timeout=0.2)
        assert not first.done()
    finally:
        release_first.set()
        await asyncio.wait_for(first, timeout=1)
        if second is not None:
            await asyncio.gather(second, return_exceptions=True)
        await bridge.finish_producer_lease("run-a")
        await bridge.finish_producer_lease("run-b")


@pytest.mark.anyio
async def test_redis_producer_start_failure_rolls_back_before_falling_back():
    from redis.exceptions import RedisError

    fake = _FakeRedis()
    bridge = RedisStreamBridge(redis_url="redis://fake", client=fake)
    run_id = "redis-run-producer-start-failure"
    original_set = fake.set

    async def fail_tracking_write(name, value, **kwargs):
        created = await original_set(name, value, **kwargs)
        if name == bridge._producer_tracking_key(run_id):
            raise RedisError("tracking write acknowledgement unavailable")
        return created

    fake.set = fail_tracking_write

    assert await bridge.start_producer_lease(run_id) is False
    assert await bridge.producer_lease_state(run_id) == StreamProducerLeaseState.untracked
    assert run_id not in bridge._producer_leases


@pytest.mark.anyio
async def test_redis_ambiguous_producer_start_fails_closed():
    from redis.exceptions import RedisError

    fake = _FakeRedis()
    bridge = RedisStreamBridge(redis_url="redis://fake", client=fake)
    run_id = "redis-run-producer-start-ambiguous"
    original_set = fake.set

    async def fail_tracking_write(name, value, **kwargs):
        created = await original_set(name, value, **kwargs)
        if name == bridge._producer_tracking_key(run_id):
            raise RedisError("tracking write acknowledgement unavailable")
        return created

    async def fail_readback(*names):
        raise RedisError("rollback read unavailable")

    fake.set = fail_tracking_write
    fake.mget = fail_readback

    with pytest.raises(
        RuntimeError,
        match="Could not safely establish stream producer lease",
    ):
        await bridge.start_producer_lease(run_id)
    assert run_id not in bridge._producer_leases


@pytest.mark.anyio
async def test_redis_producer_start_rollback_drains_repeated_cancellation():
    fake = _FakeRedis()
    bridge = RedisStreamBridge(
        redis_url="redis://fake",
        stream_ttl_seconds=0,
        client=fake,
    )
    run_id = "redis-run-repeated-start-cancellation"
    tracking_written = asyncio.Event()
    rollback_started = asyncio.Event()
    allow_rollback = asyncio.Event()
    original_set = fake.set
    original_delete = bridge._delete_if_token

    async def block_after_tracking_write(name, value, **kwargs):
        created = await original_set(name, value, **kwargs)
        if name == bridge._producer_tracking_key(run_id):
            tracking_written.set()
            await asyncio.Event().wait()
        return created

    async def block_rollback(name, token):
        rollback_started.set()
        await allow_rollback.wait()
        return await original_delete(name, token)

    fake.set = block_after_tracking_write
    bridge._delete_if_token = block_rollback
    task = asyncio.create_task(bridge.start_producer_lease(run_id))
    try:
        await asyncio.wait_for(tracking_written.wait(), timeout=1)
        task.cancel()
        await asyncio.wait_for(rollback_started.wait(), timeout=1)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()

        allow_rollback.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=1)
        assert await bridge.producer_lease_state(run_id) == StreamProducerLeaseState.untracked
    finally:
        allow_rollback.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await fake.delete(
            bridge._producer_active_key(run_id),
            bridge._producer_tracking_key(run_id),
        )


@pytest.mark.anyio
async def test_redis_close_releases_producer_leases_concurrently():
    fake = _FakeRedis()
    bridge = RedisStreamBridge(redis_url="redis://fake", client=fake)
    run_ids = ("close-run-a", "close-run-b", "close-run-c")
    for run_id in run_ids:
        await bridge.start_producer_lease(run_id)

    releases_started = 0
    all_releases_started = asyncio.Event()
    allow_releases = asyncio.Event()
    original_delete = bridge._delete_if_token

    async def block_active_release(name, token):
        nonlocal releases_started
        if name.endswith(":producer-active"):
            releases_started += 1
            if releases_started == len(run_ids):
                all_releases_started.set()
            await allow_releases.wait()
        return await original_delete(name, token)

    bridge._delete_if_token = block_active_release
    close_task = asyncio.create_task(bridge.close())
    try:
        await asyncio.wait_for(all_releases_started.wait(), timeout=0.2)
    finally:
        allow_releases.set()
        await asyncio.wait_for(close_task, timeout=1)


@pytest.mark.anyio
async def test_redis_close_waits_for_inflight_producer_start():
    fake = _FakeRedis()
    bridge = RedisStreamBridge(redis_url="redis://fake", client=fake)
    run_id = "redis-run-close-during-start"
    tracking_write_started = asyncio.Event()
    allow_tracking_write = asyncio.Event()
    original_set = fake.set

    async def block_tracking_write(name, value, **kwargs):
        if name == bridge._producer_tracking_key(run_id):
            tracking_write_started.set()
            await allow_tracking_write.wait()
        return await original_set(name, value, **kwargs)

    fake.set = block_tracking_write
    start_task = asyncio.create_task(bridge.start_producer_lease(run_id))
    close_task = None
    try:
        await asyncio.wait_for(tracking_write_started.wait(), timeout=1)
        close_task = asyncio.create_task(bridge.close())
        await asyncio.sleep(0)
        assert not close_task.done()

        allow_tracking_write.set()
        assert await asyncio.wait_for(start_task, timeout=1)
        await asyncio.wait_for(close_task, timeout=1)
        assert run_id not in bridge._producer_leases
        assert await bridge.producer_lease_state(run_id) == StreamProducerLeaseState.expired
    finally:
        allow_tracking_write.set()
        if not start_task.done():
            start_task.cancel()
        await asyncio.gather(start_task, return_exceptions=True)
        if close_task is not None and not close_task.done():
            await bridge.close()
            await asyncio.gather(close_task, return_exceptions=True)


@pytest.mark.anyio
async def test_redis_close_honors_abort_intent_declared_while_stopping():
    fake = _FakeRedis()
    bridge = RedisStreamBridge(
        redis_url="redis://fake",
        stream_ttl_seconds=0,
        client=fake,
    )
    run_id = "redis-run-close-abort-intent"
    active_release_started = asyncio.Event()
    allow_active_release = asyncio.Event()
    original_delete = bridge._delete_if_token

    async def block_active_release(name, token):
        if name == bridge._producer_active_key(run_id):
            active_release_started.set()
            await allow_active_release.wait()
        return await original_delete(name, token)

    await bridge.start_producer_lease(run_id)
    bridge._delete_if_token = block_active_release
    close_task = asyncio.create_task(bridge.close())
    abort_task = None
    try:
        await asyncio.wait_for(active_release_started.wait(), timeout=1)
        abort_task = asyncio.create_task(bridge.abort_producer_lease(run_id))
        await asyncio.sleep(0)
        assert bridge._producer_leases[run_id].discard_tracking_requested is True

        allow_active_release.set()
        await asyncio.wait_for(close_task, timeout=1)
        await asyncio.wait_for(abort_task, timeout=1)
        assert await bridge.producer_lease_state(run_id) == StreamProducerLeaseState.untracked
    finally:
        allow_active_release.set()
        await asyncio.gather(close_task, return_exceptions=True)
        if abort_task is not None:
            await asyncio.gather(abort_task, return_exceptions=True)


@pytest.mark.anyio
async def test_redis_publish_refreshes_stream_ttl():
    """Redis stream TTL should be rolling on publish and publish_end."""
    fake = _FakeRedis()
    bridge = RedisStreamBridge(
        redis_url="redis://fake",
        queue_maxsize=2,
        stream_ttl_seconds=42,
        client=fake,
    )
    run_id = "redis-run-ttl"
    key = "deerflow:stream_bridge:redis-run-ttl"

    await bridge.publish(run_id, "event-1", {"n": 1})
    await bridge.publish(run_id, "event-2", {"n": 2})
    await bridge.publish_end(run_id)

    assert fake.expirations == [(key, 42), (key, 42), (key, 42)]


@pytest.mark.anyio
async def test_redis_stream_ttl_can_be_disabled():
    """A zero TTL disables the Redis leak safety net for installations that need it."""
    fake = _FakeRedis()
    bridge = RedisStreamBridge(
        redis_url="redis://fake",
        queue_maxsize=2,
        stream_ttl_seconds=0,
        client=fake,
    )

    await bridge.publish("redis-run-no-ttl", "event", {})
    await bridge.publish_end("redis-run-no-ttl")

    assert fake.expirations == []


@pytest.mark.anyio
async def test_redis_subscribe_waits_for_first_publish(redis_bridge: RedisStreamBridge):
    """A subscriber that starts before the first XADD must not receive END."""
    run_id = "redis-run-first-publish"
    received = []

    async def publish_later() -> None:
        await anyio.sleep(0.05)
        await redis_bridge.publish(run_id, "metadata", {"run_id": run_id})
        await redis_bridge.publish_end(run_id)

    with anyio.fail_after(2):
        async with anyio.create_task_group() as task_group:
            task_group.start_soon(publish_later)
            async for entry in redis_bridge.subscribe(run_id, heartbeat_interval=0.01):
                if entry is HEARTBEAT_SENTINEL:
                    continue
                received.append(entry)
                if entry is END_SENTINEL:
                    break

    assert [entry.event for entry in received[:-1]] == ["metadata"]
    assert received[-1] is END_SENTINEL


@pytest.mark.anyio
async def test_redis_stream_exists_reports_cleanup(redis_bridge: RedisStreamBridge):
    """Callers can detect when retained Redis stream data has been cleaned up."""
    run_id = "redis-run-post-cleanup"
    await redis_bridge.publish(run_id, "event-1", {"n": 1})
    await redis_bridge.publish_end(run_id)

    assert await redis_bridge.stream_exists(run_id) is True
    await redis_bridge.cleanup(run_id)
    assert await redis_bridge.stream_exists(run_id) is False


@pytest.mark.anyio
async def test_redis_transient_error_retries():
    """Transient RedisError during XREAD should be retried, not propagated."""
    from redis.exceptions import RedisError

    fake = _FakeRedis()
    call_count = 0
    original_xread = fake.xread

    async def flaky_xread(streams, count=None, block=None):
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            raise RedisError("Transient connection error")
        return await original_xread(streams, count=count, block=block)

    fake.xread = flaky_xread
    bridge = RedisStreamBridge(redis_url="redis://fake", queue_maxsize=2, client=fake)

    run_id = "redis-run-retry"
    await bridge.publish(run_id, "event-1", {"n": 1})
    await bridge.publish_end(run_id)

    received = []
    with anyio.fail_after(5):
        async for entry in bridge.subscribe(run_id, heartbeat_interval=0.01):
            received.append(entry)
            if entry is END_SENTINEL:
                break

    assert call_count > 2
    assert [e.event for e in received[:-1]] == ["event-1"]
    assert received[-1] is END_SENTINEL


@pytest.mark.anyio
async def test_redis_transient_error_gives_up_after_max_retries():
    """After exceeding max consecutive errors, RedisError should propagate."""
    from redis.exceptions import RedisError

    fake = _FakeRedis()

    async def always_fail_xread(streams, count=None, block=None):
        raise RedisError("Persistent connection error")

    fake.xread = always_fail_xread
    bridge = RedisStreamBridge(redis_url="redis://fake", queue_maxsize=2, client=fake)

    with pytest.raises(RedisError, match="Persistent connection error"):
        async for _ in bridge.subscribe("redis-run-fail", heartbeat_interval=0.01):
            pass


@pytest.mark.anyio
async def test_redis_blocking_wakeup_error_gives_up_after_max_retries():
    """Successful snapshots must not hide a permanently failing blocking XREAD."""
    from redis.exceptions import RedisError

    fake = _FakeRedis()
    original_xread = fake.xread

    async def fail_blocking_xread(streams, count=None, block=None):
        if block is not None:
            raise RedisError("Persistent blocking connection error")
        return await original_xread(streams, count=count, block=block)

    fake.xread = fail_blocking_xread
    bridge = RedisStreamBridge(redis_url="redis://fake", queue_maxsize=2, client=fake)

    with pytest.raises(RedisError, match="Persistent blocking connection error"):
        async for _ in bridge.subscribe("redis-run-blocking-fail", heartbeat_interval=0.01):
            pass


# ---------------------------------------------------------------------------
# Factory tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "heartbeat_interval",
    [
        True,
        False,
        0,
        -1,
        float("inf"),
        float("-inf"),
        float("nan"),
        MAX_HEARTBEAT_INTERVAL_SECONDS + 1,
    ],
)
def test_stream_bridge_config_rejects_invalid_heartbeat_interval(heartbeat_interval):
    with pytest.raises(ValidationError):
        StreamBridgeConfig(heartbeat_interval_seconds=heartbeat_interval)


def test_stream_bridge_config_accepts_numeric_heartbeat_string():
    config = StreamBridgeConfig(heartbeat_interval_seconds="2.5")

    assert config.heartbeat_interval_seconds == 2.5


def test_stream_bridge_producer_lease_recovery_requires_explicit_activation():
    assert StreamBridgeConfig().producer_lease_recovery_enabled is False
    assert StreamBridgeConfig(producer_lease_recovery_enabled=True).producer_lease_recovery_enabled is True


@pytest.mark.parametrize(
    "cleanup_delay",
    [
        True,
        False,
        -1,
        float("inf"),
        float("-inf"),
        float("nan"),
        MAX_RECOVERED_STREAM_CLEANUP_DELAY_SECONDS + 1,
    ],
)
def test_stream_bridge_config_rejects_invalid_recovered_stream_cleanup_delay(cleanup_delay):
    with pytest.raises(ValidationError, match="recovered_stream_cleanup_delay_seconds"):
        StreamBridgeConfig(recovered_stream_cleanup_delay_seconds=cleanup_delay)


@pytest.mark.parametrize("cleanup_delay", [0, 60, MAX_RECOVERED_STREAM_CLEANUP_DELAY_SECONDS])
def test_stream_bridge_config_accepts_valid_recovered_stream_cleanup_delay(cleanup_delay):
    """A delay of 0 is a valid 'delete as soon as END is published' setting."""
    config = StreamBridgeConfig(recovered_stream_cleanup_delay_seconds=cleanup_delay)

    assert config.recovered_stream_cleanup_delay_seconds == float(cleanup_delay)


@pytest.mark.parametrize("heartbeat_interval", [True, MAX_HEARTBEAT_INTERVAL_SECONDS + 1])
def test_memory_bridge_rejects_invalid_default_heartbeat(heartbeat_interval):
    with pytest.raises(ValueError, match="heartbeat_interval"):
        MemoryStreamBridge(heartbeat_interval=heartbeat_interval)


@pytest.mark.anyio
async def test_redis_bridge_rejects_oversized_subscription_heartbeat_before_io():
    fake = _FakeRedis()

    async def fail_if_called(*_args, **_kwargs):
        pytest.fail("Redis I/O must not start for an invalid heartbeat interval")

    fake.xrange = fail_if_called
    bridge = RedisStreamBridge(redis_url="redis://fake", client=fake)

    with pytest.raises(ValueError, match="heartbeat_interval"):
        await anext(
            bridge.subscribe(
                "redis-run-oversized-heartbeat",
                heartbeat_interval=MAX_HEARTBEAT_INTERVAL_SECONDS + 1,
            )
        )


@pytest.mark.anyio
async def test_make_stream_bridge_defaults():
    """make_stream_bridge() with no config yields a MemoryStreamBridge."""
    async with make_stream_bridge() as bridge:
        assert isinstance(bridge, MemoryStreamBridge)
        assert bridge.heartbeat_interval == 15.0


@pytest.mark.anyio
async def test_make_stream_bridge_passes_memory_heartbeat():
    set_stream_bridge_config(
        StreamBridgeConfig(
            type="memory",
            heartbeat_interval_seconds=2.5,
        )
    )
    try:
        async with make_stream_bridge() as bridge:
            assert isinstance(bridge, MemoryStreamBridge)
            assert bridge.heartbeat_interval == 2.5
    finally:
        set_stream_bridge_config(None)


# ---------------------------------------------------------------------------
# _resolve_start_offset: O(1) seq-indexed resolution
# ---------------------------------------------------------------------------


def _linear_resolve(stream, last_event_id):
    """The original linear-scan resolver, kept as a parity reference."""
    if last_event_id is None:
        return stream.start_offset
    for index, entry in enumerate(stream.events):
        if entry.id == last_event_id:
            return stream.start_offset + index + 1
    return stream.start_offset


@pytest.mark.parametrize(
    "event_id,expected",
    [
        ("1718000000000-0", 0),
        ("1718000000000-42", 42),
        ("١-0", None),
        ("1-٠", None),
        ("١-٠", None),
        ("1-" + "9" * 5000, None),
        ("-1", None),  # malformed live-tail sentinel, not a valid event id
        ("garbage", None),  # no separator
        ("1718000000000-x", None),  # non-integer seq
        ("", None),
    ],
)
def test_parse_event_seq(event_id, expected):
    assert MemoryStreamBridge._parse_event_seq(event_id) == expected


@pytest.mark.parametrize(
    "event_id,expected",
    [
        ("0", (0, 0)),
        ("0-0", (0, 0)),
        ("1718000000000", (1718000000000, 0)),
        ("1718000000000-42", (1718000000000, 42)),
        ("18446744073709551615", (18446744073709551615, 0)),
        ("18446744073709551615-0", (18446744073709551615, 0)),
        ("1-18446744073709551615", (1, 18446744073709551615)),
        ("18446744073709551615-18446744073709551615", (18446744073709551615, 18446744073709551615)),
        ("18446744073709551616", None),
        ("18446744073709551616-0", None),
        ("1-18446744073709551616", None),
        ("9" * 5000 + "-0", None),
        ("1-" + "9" * 5000, None),
        ("١-0", None),
        ("1-٠", None),
        ("١-٠", None),
        ("", None),
        ("-1", None),
        ("garbage", None),
        ("1-", None),
        ("1--1", None),
        ("1-0-0", None),
        ("1-0\n", None),
    ],
)
def test_parse_stream_id(event_id, expected):
    assert RedisStreamBridge._parse_stream_id(event_id) == expected


@pytest.mark.anyio
async def test_resolve_start_offset_matches_linear_scan():
    """Retained and unknown cursors preserve the previous linear-scan behavior."""
    bridge = MemoryStreamBridge(queue_maxsize=4)
    run_id = "run-parity"
    ids = []
    for i in range(10):
        await bridge.publish(run_id, f"e{i}", {"i": i})
        ids.append(bridge._streams[run_id].events[-1].id)  # includes ids that later evict
    stream = bridge._streams[run_id]
    assert stream.start_offset == 6  # 10 published, buffer of 4 retains seq 6..9

    # A foreign id: a retained event's seq but a different timestamp -> must NOT match.
    ts, _, seq_text = stream.events[0].id.rpartition("-")
    foreign_id = f"{int(ts) + 1}-{seq_text}"

    candidates = [None, "garbage", "1718000000000-x", "999999-999999", foreign_id, *ids[5:]]
    for eid in candidates:
        assert bridge._resolve_start_offset(stream, eid) == _linear_resolve(stream, eid), eid

    for evicted_id in ids[:5]:
        assert bridge._resolve_start_offset(stream, evicted_id) == StreamGap(
            requested_event_id=evicted_id,
            earliest_available_event_id=stream.events[0].id,
            latest_available_event_id=stream.events[-1].id,
        )


@pytest.mark.anyio
async def test_memory_low_numeric_foreign_cursor_conservatively_yields_gap():
    """An unverifiable numeric cursor below the watermark takes the safe path."""
    bridge = MemoryStreamBridge(queue_maxsize=2)
    run_id = "run-low-foreign-cursor"
    for index in range(3):
        await bridge.publish(run_id, f"e{index}", {"index": index})

    stream = bridge._streams[run_id]
    timestamp, _, _sequence = stream.events[0].id.rpartition("-")
    foreign_evicted_id = f"{int(timestamp) + 1}-0"

    assert bridge._resolve_start_offset(stream, foreign_evicted_id) == StreamGap(
        requested_event_id=foreign_evicted_id,
        earliest_available_event_id=stream.events[0].id,
        latest_available_event_id=stream.events[-1].id,
    )


@pytest.mark.anyio
async def test_subscribe_with_unknown_last_event_id_replays_from_earliest():
    """A foreign/garbage Last-Event-ID falls back to replaying retained events."""
    bridge = MemoryStreamBridge(queue_maxsize=10)
    run_id = "run-unknown-id"
    await bridge.publish(run_id, "first", {})
    await bridge.publish(run_id, "second", {})
    await bridge.publish_end(run_id)

    received = []
    async for entry in bridge.subscribe(run_id, last_event_id="not-a-real-id", heartbeat_interval=1.0):
        received.append(entry)
        if entry is END_SENTINEL:
            break

    assert [entry.event for entry in received[:-1]] == ["first", "second"]
    assert received[-1] is END_SENTINEL


@pytest.mark.anyio
@pytest.mark.parametrize(
    "last_event_id",
    [
        pytest.param("-1", id="sentinel"),
        pytest.param("1-" + "9" * 5000, id="oversized-sequence"),
        pytest.param("١-0", id="non-ascii-milliseconds"),
        pytest.param("1-٠", id="non-ascii-sequence"),
        pytest.param("١-٠", id="non-ascii-both-components"),
    ],
)
async def test_memory_malformed_last_event_id_is_not_reported_as_gap(last_event_id: str):
    """Malformed cursor policy stays separate from valid evicted cursors."""
    bridge = MemoryStreamBridge(queue_maxsize=2)
    run_id = "run-malformed-id"
    await bridge.publish(run_id, "evicted", {})
    await bridge.publish(run_id, "first", {})
    await bridge.publish(run_id, "second", {})
    await bridge.publish_end(run_id)

    received = [
        entry
        async for entry in bridge.subscribe(
            run_id,
            last_event_id=last_event_id,
            heartbeat_interval=1.0,
        )
    ]

    assert [entry.event for entry in received[:-1]] == ["first", "second"]
    assert received[-1] is END_SENTINEL
    assert all(not isinstance(entry, StreamGap) for entry in received)


@pytest.mark.anyio
async def test_memory_make_gap_handles_empty_events_buffer():
    """_make_gap returns StreamGap with None bounds when events deque is empty."""
    bridge = MemoryStreamBridge(queue_maxsize=2)
    run_id = "run-empty-stream-gap"
    stream = bridge._get_or_create_stream(run_id)
    assert len(stream.events) == 0

    gap = bridge._make_gap(stream, "100-0")
    assert gap == StreamGap(
        requested_event_id="100-0",
        earliest_available_event_id=None,
        latest_available_event_id=None,
    )


def test_memory_stream_bridge_clamps_queue_maxsize():
    """queue_maxsize <= 0 is clamped to at least 1."""
    bridge = MemoryStreamBridge(queue_maxsize=0)
    assert bridge._maxsize == 1
    bridge_neg = MemoryStreamBridge(queue_maxsize=-5)
    assert bridge_neg._maxsize == 1


def test_stream_bridge_config_validates_queue_maxsize():
    """StreamBridgeConfig rejects queue_maxsize < 1."""
    with pytest.raises(ValidationError):
        StreamBridgeConfig(queue_maxsize=0)
    with pytest.raises(ValidationError):
        StreamBridgeConfig(queue_maxsize=-1)


@pytest.mark.anyio
async def test_memory_subscribe_replays_gap_when_buffer_empty_and_cursor_behind_watermark():
    """Subscribing with a cursor behind start_offset when buffer is empty yields StreamGap with None bounds."""
    bridge = MemoryStreamBridge(queue_maxsize=2)
    run_id = "run-empty-retained-gap"
    stream = bridge._get_or_create_stream(run_id)
    # Simulate a stream whose retained buffer was cleared / advanced
    stream.start_offset = 10
    stream.events.clear()

    received = [
        entry
        async for entry in bridge.subscribe(
            run_id,
            last_event_id="5-0",
            heartbeat_interval=0.1,
        )
    ]
    assert len(received) == 1
    assert received[0] == StreamGap(
        requested_event_id="5-0",
        earliest_available_event_id=None,
        latest_available_event_id=None,
    )


@pytest.mark.anyio
async def test_make_stream_bridge_uses_docker_redis_env(monkeypatch):
    """Docker can enable Redis bridge without editing config.yaml."""
    set_stream_bridge_config(None)
    monkeypatch.setenv("DEER_FLOW_STREAM_BRIDGE_REDIS_URL", "redis://redis:6379/0")
    try:
        async with make_stream_bridge() as bridge:
            assert isinstance(bridge, RedisStreamBridge)
            assert bridge._redis_url == "redis://redis:6379/0"
    finally:
        set_stream_bridge_config(None)


@pytest.mark.anyio
async def test_make_stream_bridge_passes_redis_options(monkeypatch):
    """Redis options from config should be forwarded to Redis bridge setup."""
    import deerflow.runtime.stream_bridge.redis as redis_module

    captured: dict = {}

    def fake_from_url(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return _FakeRedis()

    monkeypatch.setattr(redis_module.Redis, "from_url", staticmethod(fake_from_url))
    set_stream_bridge_config(
        StreamBridgeConfig(
            type="redis",
            redis_url="redis://fake:6379/0",
            heartbeat_interval_seconds=2.5,
            max_connections=50,
            stream_ttl_seconds=42,
            producer_lease_recovery_enabled=True,
            legacy_end_scan_enabled=False,
        )
    )
    try:
        async with make_stream_bridge() as bridge:
            assert isinstance(bridge, RedisStreamBridge)
            assert bridge.heartbeat_interval == 2.5
            assert bridge._stream_ttl_seconds == 42
            assert bridge.producer_lease_recovery_enabled is True
            assert bridge._legacy_end_scan_enabled is False
        assert captured["max_connections"] == 50
        assert captured["decode_responses"] is True
    finally:
        set_stream_bridge_config(None)


# ---------------------------------------------------------------------------
# Integration tests against a real Redis server
# ---------------------------------------------------------------------------
#
# Opt-in and self-skipping: when no Redis is reachable these are skipped so
# `make test` stays green without Redis. Point at a server with
# DEER_FLOW_TEST_REDIS_URL (defaults to redis://localhost:6379/15 — DB 15 to
# avoid clobbering real data) and select with `pytest -m integration`. They
# cover what _FakeRedis only approximates: real XADD/XREAD semantics, live-tail
# reconnects for malformed Last-Event-ID values, the server <ms>-<seq> ID
# format, and MAXLEN trimming.

REDIS_TEST_URL = os.environ.get("DEER_FLOW_TEST_REDIS_URL", "redis://localhost:6379/15")


def _redis_available() -> bool:
    try:
        import redis  # sync client, used only for the connectivity probe
    except ImportError:
        return False
    try:
        client = redis.Redis.from_url(REDIS_TEST_URL, socket_connect_timeout=0.5)
        try:
            client.ping()
        finally:
            client.close()
        return True
    except Exception:
        return False


requires_redis = pytest.mark.skipif(not _redis_available(), reason=f"Redis not reachable at {REDIS_TEST_URL}")


@pytest.fixture
async def real_redis_bridge():
    from redis.asyncio import Redis

    client = Redis.from_url(REDIS_TEST_URL, decode_responses=True)
    key_prefix = f"deerflow:test:{uuid.uuid4().hex}"
    bridge = RedisStreamBridge(redis_url=REDIS_TEST_URL, queue_maxsize=2, key_prefix=key_prefix, client=client)
    try:
        yield bridge
    finally:
        async for key in client.scan_iter(f"{key_prefix}:*"):
            await client.delete(key)
        await client.aclose()


@pytest.mark.integration
@requires_redis
@pytest.mark.anyio
async def test_redis_integration_publish_subscribe_and_id_format(real_redis_bridge):
    run_id = "integ-basic"
    await real_redis_bridge.publish(run_id, "metadata", {"run_id": run_id})
    await real_redis_bridge.publish(run_id, "values", {"step": 1})
    await real_redis_bridge.publish_end(run_id)

    received = []
    async for entry in real_redis_bridge.subscribe(run_id, heartbeat_interval=1.0):
        received.append(entry)
        if entry is END_SENTINEL:
            break

    assert [e.event for e in received[:-1]] == ["metadata", "values"]
    assert received[0].data == {"run_id": run_id}
    assert received[-1] is END_SENTINEL
    # Real Redis stream IDs use the <ms>-<seq> format the fake only approximates.
    assert re.match(r"^\d+-\d+$", received[0].id), received[0].id


@pytest.mark.integration
@requires_redis
@pytest.mark.anyio
async def test_redis_integration_end_is_idempotent_across_independent_clients():
    """Concurrent END writers must serialize through Redis, not local process state."""
    from redis.asyncio import Redis

    clients = [
        Redis.from_url(REDIS_TEST_URL, decode_responses=True),
        Redis.from_url(REDIS_TEST_URL, decode_responses=True),
    ]
    key_prefix = f"deerflow:test:{uuid.uuid4().hex}"
    bridges = [
        RedisStreamBridge(
            redis_url=REDIS_TEST_URL,
            queue_maxsize=2,
            key_prefix=key_prefix,
            client=client,
        )
        for client in clients
    ]
    run_id = "integ-end-idempotent"
    key = bridges[0]._stream_key(run_id)
    try:
        await bridges[0].publish(run_id, "metadata", {"run_id": run_id})
        await asyncio.gather(*(bridge.publish_end(run_id) for bridge in bridges))
        await asyncio.gather(*(bridge.publish_end(run_id) for bridge in bridges))

        entries = await clients[0].xrange(key)
        assert [fields["kind"] for _event_id, fields in entries] == ["event", "end"]

        first_event_id = entries[0][0]
        replayed = [
            entry
            async for entry in bridges[1].subscribe(
                run_id,
                last_event_id=first_event_id,
                heartbeat_interval=1.0,
            )
        ]
        assert replayed == [END_SENTINEL]
    finally:
        async for existing_key in clients[0].scan_iter(f"{key_prefix}:*"):
            await clients[0].delete(existing_key)
        await asyncio.gather(*(client.aclose() for client in clients))


@pytest.mark.integration
@requires_redis
@pytest.mark.anyio
async def test_redis_integration_recovery_end_cannot_race_active_owner(real_redis_bridge):
    """Recovery may append END only after the valid producer's lease is released."""
    from redis.asyncio import Redis

    recovery_client = Redis.from_url(REDIS_TEST_URL, decode_responses=True)
    recovery = RedisStreamBridge(
        redis_url=REDIS_TEST_URL,
        queue_maxsize=2,
        key_prefix=real_redis_bridge._key_prefix,
        client=recovery_client,
    )
    run_id = "integ-end-owner-recovery-race"
    key = real_redis_bridge._stream_key(run_id)
    try:
        await real_redis_bridge.publish(run_id, "metadata", {"run_id": run_id})
        await real_redis_bridge.start_producer_lease(run_id)

        owner_result, recovery_result = await asyncio.gather(
            real_redis_bridge.publish_end(run_id),
            recovery.publish_end(run_id),
            return_exceptions=True,
        )
        assert owner_result is None
        assert isinstance(recovery_result, RuntimeError)
        assert "active producer" in str(recovery_result)

        entries = await recovery_client.xrange(key)
        assert [fields["kind"] for _event_id, fields in entries] == ["event", "end"]

        await real_redis_bridge.finish_producer_lease(run_id)
        await recovery.publish_end(run_id)
        entries = await recovery_client.xrange(key)
        assert [fields["kind"] for _event_id, fields in entries] == ["event", "end"]
    finally:
        await real_redis_bridge.finish_producer_lease(run_id)
        await recovery_client.aclose()


@pytest.mark.integration
@requires_redis
@pytest.mark.anyio
async def test_redis_integration_end_retry_after_lost_ack_is_idempotent(real_redis_bridge):
    """A retry confirms the retained END without appending a duplicate."""
    run_id = "integ-end-lost-ack"
    key = real_redis_bridge._stream_key(run_id)

    await real_redis_bridge.start_producer_lease(run_id)
    try:
        await real_redis_bridge.publish(run_id, "metadata", {"run_id": run_id})
        lossy = _LostAckRedis(real_redis_bridge._redis)
        real_redis_bridge._redis = lossy
        lossy.drop_next_successful_eval = True

        with pytest.raises(TimeoutError, match="lost Redis EVAL acknowledgement"):
            await real_redis_bridge.publish_end(run_id)

        await real_redis_bridge.publish_end(run_id)

        entries = await lossy.xrange(key)
        assert [fields["kind"] for _event_id, fields in entries] == ["event", "end"]
    finally:
        await real_redis_bridge.finish_producer_lease(run_id)


@pytest.mark.integration
@requires_redis
@pytest.mark.anyio
async def test_redis_integration_cleanup_prevents_late_end_from_recreating_stream(real_redis_bridge):
    """An END retry after cleanup is acknowledged as a no-op, not a resurrection."""
    run_id = "integ-end-after-cleanup"
    key = real_redis_bridge._stream_key(run_id)

    await real_redis_bridge.publish(run_id, "metadata", {"run_id": run_id})
    await real_redis_bridge.publish_end(run_id)
    await real_redis_bridge.cleanup(run_id)
    assert await real_redis_bridge._redis.exists(key) == 0

    await real_redis_bridge.publish_end(run_id)

    assert await real_redis_bridge._redis.exists(key) == 0


@pytest.mark.integration
@requires_redis
@pytest.mark.anyio
@pytest.mark.parametrize("owned", [False, True], ids=["recovery", "owner"])
async def test_redis_integration_legacy_midstream_end_allows_data_but_deduplicates_end(real_redis_bridge, owned: bool):
    """Pin the fake's legacy-stream decisions against the real Lua scripts."""
    client = real_redis_bridge._redis
    bridge = RedisStreamBridge(redis_url=REDIS_TEST_URL, queue_maxsize=8, key_prefix=real_redis_bridge._key_prefix, client=client)
    run_id = "integ-legacy-data-after-end"
    key = bridge._stream_key(run_id)
    if owned:
        await bridge.start_producer_lease(run_id)
    try:
        await client.xadd(key, {"kind": "end"})
        await client.xadd(key, {"kind": "event", "event": "legacy-late", "data": "{}"})
        before = await client.xrange(key)

        await bridge.publish(run_id, "current-data", {"step": 2})

        entries = await client.xrange(key)
        assert entries[:2] == before
        assert len(entries) == 3
        assert entries[-1][1]["event"] == "current-data"
        await bridge.publish_end(run_id)
        assert await client.xrange(key) == entries
    finally:
        if owned:
            await bridge.finish_producer_lease(run_id)


@pytest.mark.integration
@requires_redis
@pytest.mark.anyio
async def test_redis_integration_owned_end_recreates_missing_buffer_with_live_lease(real_redis_bridge):
    """A live owner retains the existing XADD behavior after buffer removal."""
    bridge = real_redis_bridge
    client = bridge._redis
    run_id = "integ-owned-missing-buffer"
    key = bridge._stream_key(run_id)
    await bridge.start_producer_lease(run_id)
    try:
        await bridge.publish(run_id, "metadata", {})
        await client.delete(key)

        await bridge.publish_end(run_id)

        assert [fields["kind"] for _event_id, fields in await client.xrange(key)] == ["end"]
    finally:
        await bridge.finish_producer_lease(run_id)


@pytest.mark.integration
@requires_redis
@pytest.mark.anyio
async def test_redis_integration_replays_after_last_event_id(real_redis_bridge):
    run_id = "integ-replay"
    await real_redis_bridge.publish(run_id, "metadata", {"run_id": run_id})
    await real_redis_bridge.publish(run_id, "values", {"step": 1})
    await real_redis_bridge.publish_end(run_id)

    first_pass = []
    async for entry in real_redis_bridge.subscribe(run_id, heartbeat_interval=1.0):
        first_pass.append(entry)
        if entry is END_SENTINEL:
            break

    received = []
    async for entry in real_redis_bridge.subscribe(run_id, last_event_id=first_pass[0].id, heartbeat_interval=1.0):
        received.append(entry)
        if entry is END_SENTINEL:
            break

    assert [e.event for e in received[:-1]] == ["values"]
    assert received[-1] is END_SENTINEL


@pytest.mark.integration
@requires_redis
@pytest.mark.anyio
@pytest.mark.parametrize("last_event_id", [pytest.param("not-a-valid-id", id="malformed"), *_INVALID_NUMERIC_REDIS_CURSORS])
async def test_redis_integration_invalid_last_event_id_tails_live_events(real_redis_bridge, last_event_id: str):
    """A malformed Last-Event-ID should wait at the live tail."""
    run_id = "integ-bad-leid"
    await real_redis_bridge.publish(run_id, "metadata", {"run_id": run_id})
    received = []

    async def publish_later() -> None:
        await anyio.sleep(0.05)
        await real_redis_bridge.publish(run_id, "values", {"step": 1})
        await real_redis_bridge.publish_end(run_id)

    with anyio.fail_after(2):
        async with anyio.create_task_group() as task_group:
            task_group.start_soon(publish_later)
            async for entry in real_redis_bridge.subscribe(run_id, last_event_id=last_event_id, heartbeat_interval=0.01):
                if entry is HEARTBEAT_SENTINEL:
                    continue
                received.append(entry)
                if entry is END_SENTINEL:
                    break

    assert [e.event for e in received[:-1]] == ["values"]
    assert received[-1] is END_SENTINEL


@pytest.mark.integration
@requires_redis
@pytest.mark.anyio
@pytest.mark.parametrize("last_event_id", _INVALID_NUMERIC_REDIS_CURSORS)
async def test_redis_integration_invalid_numeric_cursor_replays_terminal_stream(real_redis_bridge, last_event_id: str):
    run_id = "integ-invalid-numeric-terminal"
    await real_redis_bridge.publish(run_id, "metadata", {"run_id": run_id})
    await real_redis_bridge.publish_end(run_id)

    with anyio.fail_after(2):
        received = [entry async for entry in real_redis_bridge.subscribe(run_id, last_event_id=last_event_id, heartbeat_interval=0.01)]

    assert [entry.event for entry in received[:-1]] == ["metadata"]
    assert received[-1] is END_SENTINEL


@pytest.mark.integration
@requires_redis
@pytest.mark.anyio
@pytest.mark.parametrize("last_event_id", ["18446744073709551615-0", "0-18446744073709551615", "18446744073709551615"])
async def test_redis_integration_uint64_boundary_cursor_reports_gap(real_redis_bridge, last_event_id: str):
    run_id = "integ-boundary-cursor"
    await real_redis_bridge.publish(run_id, "metadata", {})
    await real_redis_bridge.publish_end(run_id)

    with anyio.fail_after(2):
        received = [entry async for entry in real_redis_bridge.subscribe(run_id, last_event_id=last_event_id, heartbeat_interval=0.01)]

    assert len(received) == 1
    assert isinstance(received[0], StreamGap)
    assert received[0].requested_event_id == last_event_id


@pytest.mark.integration
@requires_redis
@pytest.mark.anyio
async def test_redis_integration_maxlen_trims_history(real_redis_bridge):
    """queue_maxsize should bound the retained stream via XADD MAXLEN (exact)."""
    run_id = "integ-maxlen"
    # Fixture sets queue_maxsize=2; publish more data events than that.
    for i in range(6):
        await real_redis_bridge.publish(run_id, f"event-{i}", {"i": i})

    key = real_redis_bridge._stream_key(run_id)
    length = await real_redis_bridge._redis.xlen(key)
    assert length == 2


@pytest.mark.integration
@requires_redis
@pytest.mark.anyio
async def test_redis_integration_evicted_cursor_yields_gap(real_redis_bridge):
    """Real Redis MAXLEN trimming must produce the same gap contract."""
    run_id = "integ-gap"
    await real_redis_bridge.publish(run_id, "event-1", {"i": 1})
    key = real_redis_bridge._stream_key(run_id)
    first_id = (await real_redis_bridge._redis.xrange(key, count=1))[0][0]
    await real_redis_bridge.publish(run_id, "event-2", {"i": 2})
    await real_redis_bridge.publish(run_id, "event-3", {"i": 3})

    retained = await real_redis_bridge._redis.xrange(key)
    received = [
        entry
        async for entry in real_redis_bridge.subscribe(
            run_id,
            last_event_id=first_id,
            heartbeat_interval=1.0,
        )
    ]

    assert received == [
        StreamGap(
            requested_event_id=first_id,
            earliest_available_event_id=retained[0][0],
            latest_available_event_id=retained[-1][0],
        )
    ]


@pytest.mark.integration
@requires_redis
@pytest.mark.anyio
async def test_redis_integration_initial_subscriber_yields_gap_when_first_wake_falls_behind(
    real_redis_bridge,
):
    """A real blocking XREAD wake must be validated before first delivery."""
    raw_redis = real_redis_bridge._redis
    delayed = _DelayedBlockingReadRedis(raw_redis)
    real_redis_bridge._redis = delayed
    run_id = "integ-initial-subscriber-gap"
    subscriber = real_redis_bridge.subscribe(run_id, heartbeat_interval=1.0)
    first_item = asyncio.create_task(anext(subscriber))

    with anyio.fail_after(2):
        await delayed.blocking_read_started.wait()
        await real_redis_bridge.publish(run_id, "e1", {"step": 1})
        await delayed.wake_response_captured.wait()
        await real_redis_bridge.publish(run_id, "e2", {"step": 2})
        await real_redis_bridge.publish(run_id, "e3", {"step": 3})
        await real_redis_bridge.publish(run_id, "e4", {"step": 4})
        delayed.release_wake_response.set()
        gap = await first_item

    key = real_redis_bridge._stream_key(run_id)
    retained = await raw_redis.xrange(key)
    assert gap == StreamGap(
        requested_event_id=None,
        earliest_available_event_id=retained[0][0],
        latest_available_event_id=retained[-1][0],
    )
    with pytest.raises(StopAsyncIteration):
        await anext(subscriber)


@pytest.mark.integration
@requires_redis
@pytest.mark.anyio
async def test_redis_integration_stream_ttl_reclaims_key():
    """Redis should reclaim retained stream data when cleanup never runs."""
    from redis.asyncio import Redis

    client = Redis.from_url(REDIS_TEST_URL, decode_responses=True)
    key_prefix = f"deerflow:test:{uuid.uuid4().hex}"
    bridge = RedisStreamBridge(
        redis_url=REDIS_TEST_URL,
        queue_maxsize=2,
        key_prefix=key_prefix,
        stream_ttl_seconds=1,
        client=client,
    )
    run_id = "integ-ttl"
    key = bridge._stream_key(run_id)
    try:
        await bridge.publish(run_id, "metadata", {"run_id": run_id})
        assert await client.exists(key) == 1
        assert await client.ttl(key) >= 0
        await anyio.sleep(2.0)

        assert await client.exists(key) == 0
    finally:
        async for existing_key in client.scan_iter(f"{key_prefix}:*"):
            await client.delete(existing_key)
        await client.aclose()


@pytest.mark.parametrize("enabled", [True, False])
def test_stream_bridge_config_legacy_end_scan_switch(enabled):
    assert StreamBridgeConfig().legacy_end_scan_enabled is True
    assert StreamBridgeConfig(legacy_end_scan_enabled=enabled).legacy_end_scan_enabled is enabled


@pytest.mark.anyio
@pytest.mark.parametrize("owned", [False, True], ids=["recovery", "owner"])
@pytest.mark.parametrize("enabled", [True, False], ids=["compatibility-scan", "tail-only"])
async def test_redis_end_scan_switch_and_tail_fast_path(owned, enabled):
    fake = _FakeRedis()
    fake._has_end_marker = Mock(wraps=fake._has_end_marker)
    bridge = RedisStreamBridge(redis_url="redis://fake", queue_maxsize=8, legacy_end_scan_enabled=enabled, client=fake)
    run_id = "scan-switch"
    if owned:
        await bridge.start_producer_lease(run_id)
    try:
        await bridge.publish(run_id, "values", {"content": "x" * 4096})
        assert fake._has_end_marker.call_count == 0
        await bridge.publish_end(run_id)
        assert fake._has_end_marker.call_count == int(enabled)
        await bridge.publish_end(run_id)
        with pytest.raises(RuntimeError, match="already ended"):
            await bridge.publish(run_id, "late", {})
        assert fake._has_end_marker.call_count == int(enabled)
        assert [fields["kind"] for _, fields in fake.streams[bridge._stream_key(run_id)]] == ["event", "end"]
    finally:
        if owned:
            await bridge.finish_producer_lease(run_id)
        await bridge.close()


@pytest.mark.integration
@requires_redis
@pytest.mark.anyio
@pytest.mark.parametrize("owned", [False, True], ids=["recovery", "owner"])
@pytest.mark.parametrize("enabled", [True, False], ids=["compatibility-scan", "tail-only"])
async def test_redis_integration_end_scan_switch_with_xrange_denied(real_redis_bridge, owned, enabled):
    """Deny XRANGE so real Lua proves that tail-only END never scans history."""
    from redis.asyncio import ConnectionPool, Redis
    from redis.exceptions import ResponseError

    admin = real_redis_bridge._redis
    server = await admin.info("server")
    if int(server["redis_version"].split(".", 1)[0]) < 6:
        pytest.skip("This scan-path probe uses Redis 6+ ACLs")
    username = "end-scan-" + uuid.uuid4().hex
    prefix = real_redis_bridge._key_prefix
    await admin.acl_setuser(username, enabled=True, reset=True, passwords=["+fixture-password"], keys=[f"{prefix}:*"], categories=["+all"], commands=["-xrange"])
    pool = ConnectionPool.from_url(REDIS_TEST_URL, decode_responses=True)
    pool.connection_kwargs.update(username=username, password="fixture-password")
    client = Redis(connection_pool=pool)
    bridge = RedisStreamBridge(redis_url=REDIS_TEST_URL, queue_maxsize=8, key_prefix=prefix, legacy_end_scan_enabled=enabled, client=client)
    run_id = "scan-switch-acl"
    try:
        if owned:
            await bridge.start_producer_lease(run_id)
        await bridge.publish(run_id, "values", {"content": "x" * 4096})
        if enabled:
            with pytest.raises(ResponseError, match="(?i)acl|permission|user executing|allowed"):
                await bridge.publish_end(run_id)
            assert await admin.xlen(bridge._stream_key(run_id)) == 1
        else:
            await bridge.publish_end(run_id)
            await bridge.publish_end(run_id)
            with pytest.raises(RuntimeError, match="already ended"):
                await bridge.publish(run_id, "late", {})
            assert [fields["kind"] for _, fields in await admin.xrange(bridge._stream_key(run_id))] == ["event", "end"]
    finally:
        try:
            await bridge.close()
        finally:
            await client.aclose()
            await pool.disconnect()
            await admin.acl_deluser(username)
