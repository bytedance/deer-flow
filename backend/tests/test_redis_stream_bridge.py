"""Tests for RedisStreamBridge and shared terminal helpers.

Redis-backed behaviour is exercised against ``fakeredis`` (no real server).
Pure module-level helpers and config validation run without any redis client.
"""

from __future__ import annotations

import asyncio

import pytest

fakeredis = pytest.importorskip("fakeredis")
import fakeredis.aioredis as fake_aioredis  # noqa: E402

from deerflow.config.stream_bridge_config import StreamBridgeConfig  # noqa: E402
from deerflow.runtime import END_SENTINEL, HEARTBEAT_SENTINEL  # noqa: E402
from deerflow.runtime.runs.manager import RunRecord  # noqa: E402
from deerflow.runtime.runs.schemas import DisconnectMode, RunStatus  # noqa: E402
from deerflow.runtime.runs.terminal import TERMINAL_STATUSES, build_end_payload  # noqa: E402
from deerflow.runtime.stream_bridge.redis import (  # noqa: E402
    RedisStreamBridge,
    _compare_stream_ids,
    _id_tuple,
    mask_redis_url,
)

RUN_ID = "11111111-2222-3333-4444-555555555555"
RUN_ID_2 = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


# ---------------------------------------------------------------------------
# Pure module-level helpers (no redis required)
# ---------------------------------------------------------------------------


def test_mask_redis_url_redacts_credentials():
    assert mask_redis_url("redis://:secret@host:6379/0") == "redis://***@host:6379/0"
    assert mask_redis_url("redis://user:secret@host:6379/0") == "redis://***@host:6379/0"
    assert mask_redis_url("redis://host:6379/0") == "redis://host:6379/0"
    assert mask_redis_url(None) == "<none>"
    assert mask_redis_url("") == "<none>"


def test_id_tuple_parses_both_forms():
    assert _id_tuple("5-2") == (5, 2)
    assert _id_tuple("7") == (7, 0)
    assert _id_tuple("0-0") == (0, 0)


def test_compare_stream_ids_orders_by_ms_then_seq():
    assert _compare_stream_ids("1-0", "1-1") == -1
    assert _compare_stream_ids("2-0", "1-9") == 1
    assert _compare_stream_ids("3-4", "3-4") == 0
    assert _compare_stream_ids("10-0", "9-0") == 1  # numeric, not lexicographic


# ---------------------------------------------------------------------------
# StreamBridgeConfig validation (problem E/M/P)
# ---------------------------------------------------------------------------


def test_config_memory_defaults_skip_redis_validation():
    cfg = StreamBridgeConfig(type="memory")
    assert cfg.redis_url is None
    assert cfg.redis_ttl_seconds == 86400


def test_config_redis_requires_url():
    with pytest.raises(ValueError, match="redis_url is required"):
        StreamBridgeConfig(type="redis")


def test_config_redis_ttl_floor():
    with pytest.raises(ValueError):
        StreamBridgeConfig(type="redis", redis_url="redis://h:6379/0", redis_ttl_seconds=30)


def test_config_redis_require_tls_rejects_plain_url():
    with pytest.raises(ValueError, match="rediss://"):
        StreamBridgeConfig(
            type="redis",
            redis_url="redis://h:6379/0",
            redis_require_tls=True,
        )


def test_config_redis_require_tls_accepts_rediss():
    cfg = StreamBridgeConfig(
        type="redis",
        redis_url="rediss://h:6379/0",
        redis_require_tls=True,
    )
    assert cfg.redis_url.startswith("rediss://")


def test_config_redis_max_payload_bytes_must_be_positive():
    with pytest.raises(ValueError):
        StreamBridgeConfig(
            type="redis",
            redis_url="redis://h:6379/0",
            redis_max_payload_bytes=0,
        )


def test_config_redis_rejects_negative_connection_pools():
    with pytest.raises(ValueError):
        StreamBridgeConfig(
            type="redis",
            redis_url="redis://h:6379/0",
            redis_max_command_connections=-1,
        )


# ---------------------------------------------------------------------------
# Shared terminal helpers (problem K-schema/T)
# ---------------------------------------------------------------------------


def _record(status: RunStatus, error: str | None = None) -> RunRecord:
    return RunRecord(
        run_id=RUN_ID,
        thread_id="t-1",
        assistant_id=None,
        status=status,
        on_disconnect=DisconnectMode.continue_,
        error=error,
    )


def test_terminal_statuses_include_timeout():
    assert RunStatus.timeout in TERMINAL_STATUSES
    assert RunStatus.success in TERMINAL_STATUSES
    assert RunStatus.error in TERMINAL_STATUSES
    assert RunStatus.interrupted in TERMINAL_STATUSES
    assert RunStatus.running not in TERMINAL_STATUSES
    assert RunStatus.pending not in TERMINAL_STATUSES


def test_build_end_payload_shape():
    assert build_end_payload(_record(RunStatus.success)) == {"status": "success", "error": None}
    assert build_end_payload(_record(RunStatus.error, "boom")) == {
        "status": "error",
        "error": "boom",
    }


# ---------------------------------------------------------------------------
# RedisStreamBridge against fakeredis
# ---------------------------------------------------------------------------


def _make_bridge(server: fakeredis.FakeServer, **kwargs) -> RedisStreamBridge:
    """Build a bridge, then swap real pools for fakeredis clients on *server*."""
    bridge = RedisStreamBridge(redis_url="redis://localhost:6379/0", **kwargs)
    bridge._redis = fake_aioredis.FakeRedis(server=server, decode_responses=True)
    bridge._blocking_redis = fake_aioredis.FakeRedis(server=server, decode_responses=True)
    return bridge


@pytest.fixture
def server() -> fakeredis.FakeServer:
    return fakeredis.FakeServer()


@pytest.fixture
async def bridge(server: fakeredis.FakeServer):
    b = _make_bridge(server)
    yield b
    await b._redis.aclose()
    await b._blocking_redis.aclose()


async def _drain(bridge: RedisStreamBridge, run_id: str, **kwargs) -> list:
    received = []
    async for entry in bridge.subscribe(run_id, heartbeat_interval=0.2, **kwargs):
        received.append(entry)
        if entry is END_SENTINEL:
            break
    return received


@pytest.mark.anyio
async def test_supports_cross_process_subscribe(bridge: RedisStreamBridge):
    assert bridge.supports_cross_process_subscribe is True


@pytest.mark.anyio
async def test_ttl_seconds_property():
    b = _make_bridge(fakeredis.FakeServer(), ttl_seconds=120)
    assert b.ttl_seconds == 120


@pytest.mark.anyio
async def test_invalid_run_id_rejected_in_stream_key(bridge: RedisStreamBridge):
    with pytest.raises(ValueError):
        bridge._stream_key("not-a-uuid")


@pytest.mark.anyio
async def test_publish_subscribe_in_order(bridge: RedisStreamBridge):
    await bridge.publish(RUN_ID, "metadata", {"run_id": RUN_ID})
    await bridge.publish(RUN_ID, "values", {"messages": []})
    await bridge.publish(RUN_ID, "updates", {"step": 1})
    await bridge.publish_end(RUN_ID)

    received = await _drain(bridge, RUN_ID)
    assert [e.event for e in received[:-1]] == ["metadata", "values", "updates"]
    assert received[0].data == {"run_id": RUN_ID}
    assert received[-1] is END_SENTINEL


@pytest.mark.anyio
async def test_event_id_is_redis_stream_id(bridge: RedisStreamBridge):
    await bridge.publish(RUN_ID, "test", {"k": "v"})
    await bridge.publish_end(RUN_ID)
    received = await _drain(bridge, RUN_ID)
    import re

    assert re.match(r"^\d+-\d+$", received[0].id)


@pytest.mark.anyio
async def test_multiple_runs_isolated(bridge: RedisStreamBridge):
    await bridge.publish(RUN_ID, "a", {"a": 1})
    await bridge.publish(RUN_ID_2, "b", {"b": 2})
    await bridge.publish_end(RUN_ID)
    await bridge.publish_end(RUN_ID_2)

    ra = await _drain(bridge, RUN_ID)
    rb = await _drain(bridge, RUN_ID_2)
    assert ra[0].event == "a" and ra[0].data == {"a": 1}
    assert rb[0].event == "b" and rb[0].data == {"b": 2}


@pytest.mark.anyio
async def test_heartbeat_when_idle(bridge: RedisStreamBridge):
    await bridge.publish(RUN_ID, "first", {})  # ensure key exists
    received = []
    async for entry in bridge.subscribe(RUN_ID, heartbeat_interval=0.1):
        received.append(entry)
        if entry is HEARTBEAT_SENTINEL:
            break
    assert received[-1] is HEARTBEAT_SENTINEL


@pytest.mark.anyio
async def test_serialize_fallback_uses_default_str(bridge: RedisStreamBridge):
    """Non-JSON-serialisable payloads fall back to default=str (problem C/M)."""

    class NotJson:
        def __repr__(self) -> str:
            return "NotJson()"

    payload_json, used_fallback = bridge._encode_payload(RUN_ID, "evt", {"obj": NotJson()})
    assert used_fallback is True
    assert "NotJson()" in payload_json


@pytest.mark.anyio
async def test_oversized_payload_dropped_not_raised(server: fakeredis.FakeServer):
    """Oversized data events are dropped, never raised, and not written (problem M/X)."""
    b = _make_bridge(server, max_payload_bytes=32)
    # Should not raise even though payload exceeds the limit.
    await b.publish(RUN_ID, "big", {"blob": "x" * 1000})
    # Nothing should have been written to the stream.
    assert await b._redis.exists(b._stream_key(RUN_ID)) == 0
    await b._redis.aclose()
    await b._blocking_redis.aclose()


@pytest.mark.anyio
async def test_publish_drops_after_retry_exhaustion(server: fakeredis.FakeServer, monkeypatch):
    """publish() must not raise when Redis keeps failing (problem N)."""
    import redis.asyncio as redis_async

    b = _make_bridge(server)

    def boom_pipeline(*args, **kwargs):
        raise redis_async.ConnectionError("redis down")

    monkeypatch.setattr(b._redis, "pipeline", boom_pipeline)
    monkeypatch.setattr(asyncio, "sleep", _no_sleep)

    # Best-effort: should swallow the error rather than propagate.
    await b.publish(RUN_ID, "evt", {"x": 1})
    await b._redis.aclose()
    await b._blocking_redis.aclose()


@pytest.mark.anyio
async def test_publish_retries_then_succeeds(server: fakeredis.FakeServer, monkeypatch):
    """Transient failures are retried; a later success persists the event (problem N)."""
    import redis.asyncio as redis_async

    b = _make_bridge(server)
    real_pipeline = b._redis.pipeline
    calls = {"n": 0}

    def flaky_pipeline(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise redis_async.ConnectionError("transient")
        return real_pipeline(*args, **kwargs)

    monkeypatch.setattr(b._redis, "pipeline", flaky_pipeline)
    monkeypatch.setattr(asyncio, "sleep", _no_sleep)

    await b.publish(RUN_ID, "evt", {"x": 1})
    assert calls["n"] == 2
    entries = await b._redis.xrange(b._stream_key(RUN_ID))
    assert len(entries) == 1
    await b._redis.aclose()
    await b._blocking_redis.aclose()


@pytest.mark.anyio
async def test_should_refresh_ttl_sampling(bridge: RedisStreamBridge):
    """TTL refresh is sampled at most once per window (problem O)."""
    assert bridge._should_refresh_ttl(RUN_ID, now=1000.0) is True
    assert bridge._should_refresh_ttl(RUN_ID, now=1000.0 + 10) is False  # within window
    assert bridge._should_refresh_ttl(RUN_ID, now=1000.0 + 120) is True  # past window


@pytest.mark.anyio
async def test_ttl_state_evicted_by_lru(bridge: RedisStreamBridge):
    """The sampling state is bounded; oldest entries are evicted (problem O)."""
    from deerflow.runtime.stream_bridge import redis as redis_mod

    original = redis_mod._TTL_STATE_MAXSIZE
    redis_mod._TTL_STATE_MAXSIZE = 3
    try:
        for i in range(5):
            bridge._should_refresh_ttl(f"run-{i}", now=float(i))
        assert len(bridge._ttl_last_refresh) == 3
        assert "run-0" not in bridge._ttl_last_refresh
        assert "run-4" in bridge._ttl_last_refresh
    finally:
        redis_mod._TTL_STATE_MAXSIZE = original


@pytest.mark.anyio
async def test_cleanup_removes_stream_and_sampling_state(bridge: RedisStreamBridge):
    """cleanup() deletes the key and pops the TTL sampling entry (problem O)."""
    await bridge.publish(RUN_ID, "evt", {})
    bridge._ttl_last_refresh[RUN_ID] = 1.0
    assert await bridge._redis.exists(bridge._stream_key(RUN_ID)) == 1

    await bridge.cleanup(RUN_ID)
    assert await bridge._redis.exists(bridge._stream_key(RUN_ID)) == 0
    assert RUN_ID not in bridge._ttl_last_refresh


@pytest.mark.anyio
async def test_refresh_ttl_does_not_recreate_missing_key(bridge: RedisStreamBridge):
    """EXPIRE on a missing key is a no-op (problem L)."""
    await bridge.refresh_ttl(RUN_ID)  # key never created
    assert await bridge._redis.exists(bridge._stream_key(RUN_ID)) == 0


@pytest.mark.anyio
async def test_has_retained_stream(bridge: RedisStreamBridge):
    assert await bridge.has_retained_stream(RUN_ID) is False
    await bridge.publish(RUN_ID, "evt", {})
    assert await bridge.has_retained_stream(RUN_ID) is True


@pytest.mark.anyio
async def test_has_events_after(bridge: RedisStreamBridge):
    await bridge.publish(RUN_ID, "e1", {})
    await bridge.publish(RUN_ID, "e2", {})
    entries = await bridge._redis.xrange(bridge._stream_key(RUN_ID))
    first_id = entries[0][0]
    last_id = entries[-1][0]

    assert await bridge.has_events_after(RUN_ID, None) is True
    assert await bridge.has_events_after(RUN_ID, first_id) is True
    assert await bridge.has_events_after(RUN_ID, last_id) is False


# -- Last-Event-ID resolution (problem) -------------------------------------


@pytest.mark.anyio
async def test_resolve_cursor_none_starts_from_zero(bridge: RedisStreamBridge):
    key = bridge._stream_key(RUN_ID)
    assert await bridge._resolve_cursor(key, None) == "0-0"


@pytest.mark.anyio
async def test_resolve_cursor_invalid_replays_from_earliest(bridge: RedisStreamBridge):
    key = bridge._stream_key(RUN_ID)
    assert await bridge._resolve_cursor(key, "not-an-id") == "0-0"


@pytest.mark.anyio
async def test_resolve_cursor_old_replays_from_earliest(bridge: RedisStreamBridge):
    await bridge.publish(RUN_ID, "e1", {})
    await bridge.publish(RUN_ID, "e2", {})
    key = bridge._stream_key(RUN_ID)
    # "1-0" is older than the earliest retained id.
    assert await bridge._resolve_cursor(key, "1-0") == "0-0"


@pytest.mark.anyio
async def test_resolve_cursor_future_resumes_from_latest(bridge: RedisStreamBridge):
    await bridge.publish(RUN_ID, "e1", {})
    key = bridge._stream_key(RUN_ID)
    entries = await bridge._redis.xrange(key)
    latest_id = entries[-1][0]
    # A far-future id should clamp to the latest retained id.
    resolved = await bridge._resolve_cursor(key, "99999999999999-0")
    assert resolved == latest_id


@pytest.mark.anyio
async def test_resolve_cursor_in_range_passthrough(bridge: RedisStreamBridge):
    await bridge.publish(RUN_ID, "e1", {})
    await bridge.publish(RUN_ID, "e2", {})
    key = bridge._stream_key(RUN_ID)
    entries = await bridge._redis.xrange(key)
    first_id = entries[0][0]
    assert await bridge._resolve_cursor(key, first_id) == first_id


@pytest.mark.anyio
async def test_resolve_cursor_missing_key_starts_from_zero(bridge: RedisStreamBridge):
    key = bridge._stream_key(RUN_ID)  # no events published
    assert await bridge._resolve_cursor(key, "5-0") == "0-0"


@pytest.mark.anyio
async def test_subscribe_replays_after_last_event_id(bridge: RedisStreamBridge):
    await bridge.publish(RUN_ID, "metadata", {})
    await bridge.publish(RUN_ID, "values", {})
    await bridge.publish(RUN_ID, "updates", {})
    await bridge.publish_end(RUN_ID)

    first = await _drain(bridge, RUN_ID)
    resumed = await _drain(bridge, RUN_ID, last_event_id=first[0].id)
    assert [e.event for e in resumed[:-1]] == ["values", "updates"]
    assert resumed[-1] is END_SENTINEL


async def _no_sleep(*_args, **_kwargs):
    return None
