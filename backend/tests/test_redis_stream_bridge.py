"""Tests for RedisStreamBridge.

These tests mock the Redis client module to avoid requiring a running Redis server.
"""

import json
import sys
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock

import pytest

from deerflow.runtime.stream_bridge.base import END_SENTINEL, HEARTBEAT_SENTINEL, StreamEvent


def _make_mock_redis_module():
    """Create a mock redis.asyncio module and install it in sys.modules."""
    redis_mod = ModuleType("redis")
    redis_asyncio = ModuleType("redis.asyncio")

    mock_client = AsyncMock()
    mock_client.xadd = AsyncMock(return_value="1234567890-0")
    mock_client.xread = AsyncMock(return_value=[])
    mock_client.delete = AsyncMock(return_value=1)
    mock_client.aclose = AsyncMock()

    redis_asyncio.from_url = MagicMock(return_value=mock_client)
    redis_mod.asyncio = redis_asyncio

    sys.modules["redis"] = redis_mod
    sys.modules["redis.asyncio"] = redis_asyncio

    return mock_client


@pytest.fixture
def mock_redis_client():
    client = _make_mock_redis_module()
    yield client
    sys.modules.pop("redis", None)
    sys.modules.pop("redis.asyncio", None)


@pytest.fixture
def bridge(mock_redis_client):
    from deerflow.runtime.stream_bridge.redis_bridge import RedisStreamBridge

    return RedisStreamBridge(redis_url="redis://localhost:6379/0")


class TestRedisStreamBridgePublish:
    @pytest.mark.anyio
    async def test_publish_calls_xadd(self, bridge, mock_redis_client):
        await bridge.publish("run-1", "values", {"title": "Test"})

        mock_redis_client.xadd.assert_called_once()
        call_args = mock_redis_client.xadd.call_args
        assert call_args[0][0] == "deerflow:stream:run-1"
        fields = call_args[0][1]
        assert fields["event"] == "values"
        assert json.loads(fields["data"]) == {"title": "Test"}
        assert fields["sequence"] == "0"

    @pytest.mark.anyio
    async def test_publish_increments_sequence(self, bridge, mock_redis_client):
        await bridge.publish("run-1", "values", {"a": 1})
        await bridge.publish("run-1", "values", {"a": 2})
        await bridge.publish("run-1", "custom", {"type": "tool_end"})

        calls = mock_redis_client.xadd.call_args_list
        assert calls[0][0][1]["sequence"] == "0"
        assert calls[1][0][1]["sequence"] == "1"
        assert calls[2][0][1]["sequence"] == "2"

    @pytest.mark.anyio
    async def test_publish_end_sends_end_marker(self, bridge, mock_redis_client):
        await bridge.publish_end("run-1")

        mock_redis_client.xadd.assert_called_once()
        fields = mock_redis_client.xadd.call_args[0][1]
        assert fields["event"] == "__end__"

    @pytest.mark.anyio
    async def test_publish_uses_maxlen_approximate(self, bridge, mock_redis_client):
        await bridge.publish("run-1", "values", {"x": 1})

        call_kwargs = mock_redis_client.xadd.call_args[1]
        assert call_kwargs["maxlen"] == 1024
        assert call_kwargs["approximate"] is True


class TestRedisStreamBridgeSubscribe:
    @pytest.mark.anyio
    async def test_subscribe_yields_end_sentinel(self, bridge, mock_redis_client):
        mock_redis_client.xread.return_value = [
            ("deerflow:stream:run-1", [
                ("1234567890-0", {"event": "__end__", "data": "", "sequence": "0"}),
            ])
        ]

        events = []
        async for event in bridge.subscribe("run-1"):
            events.append(event)
            if event is END_SENTINEL:
                break

        assert len(events) == 1
        assert events[0] is END_SENTINEL

    @pytest.mark.anyio
    async def test_subscribe_yields_stream_events(self, bridge, mock_redis_client):
        mock_redis_client.xread.return_value = [
            ("deerflow:stream:run-1", [
                ("1234567890-0", {"event": "values", "data": json.dumps({"title": "Test"}), "sequence": "0"}),
                ("1234567890-1", {"event": "custom", "data": json.dumps({"type": "state_patch"}), "sequence": "1"}),
                ("1234567890-2", {"event": "__end__", "data": "", "sequence": "2"}),
            ])
        ]

        events = []
        async for event in bridge.subscribe("run-1"):
            events.append(event)
            if event is END_SENTINEL:
                break

        assert len(events) == 3
        assert isinstance(events[0], StreamEvent)
        assert events[0].event == "values"
        assert events[0].data == {"title": "Test"}
        assert events[0].sequence == 0
        assert events[0].id == "1234567890-0"
        assert events[1].event == "custom"
        assert events[1].sequence == 1

    @pytest.mark.anyio
    async def test_subscribe_heartbeat_on_empty(self, bridge, mock_redis_client):
        call_count = 0

        async def mock_xread(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return []
            return [("deerflow:stream:run-1", [
                ("1234567890-0", {"event": "__end__", "data": "", "sequence": "0"}),
            ])]

        mock_redis_client.xread.side_effect = mock_xread
        bridge._poll_interval = 0.01

        events = []
        async for event in bridge.subscribe("run-1"):
            events.append(event)
            if event is END_SENTINEL:
                break

        assert events[0] is HEARTBEAT_SENTINEL
        assert events[1] is END_SENTINEL

    @pytest.mark.anyio
    async def test_subscribe_resumes_from_last_event_id(self, bridge, mock_redis_client):
        mock_redis_client.xread.return_value = [
            ("deerflow:stream:run-1", [
                ("1234567890-5", {"event": "__end__", "data": "", "sequence": "5"}),
            ])
        ]

        async for event in bridge.subscribe("run-1", last_event_id="1234567890-4"):
            if event is END_SENTINEL:
                break

        xread_call = mock_redis_client.xread.call_args
        assert xread_call[0][0] == {"deerflow:stream:run-1": "1234567890-4"}


class TestRedisStreamBridgeCleanup:
    @pytest.mark.anyio
    async def test_cleanup_deletes_stream(self, bridge, mock_redis_client):
        await bridge.cleanup("run-1")
        mock_redis_client.delete.assert_called_once_with("deerflow:stream:run-1")

    @pytest.mark.anyio
    async def test_cleanup_with_delay(self, bridge, mock_redis_client):
        await bridge.cleanup("run-1", delay=0.01)
        mock_redis_client.delete.assert_called_once()

    @pytest.mark.anyio
    async def test_close_disconnects(self, bridge, mock_redis_client):
        await bridge.close()
        mock_redis_client.aclose.assert_called_once()


class TestRedisStreamBridgeImport:
    def test_missing_redis_raises_import_error(self):
        """Without redis[hiredis], instantiating RedisStreamBridge raises ImportError."""
        saved = {}
        for mod_name in list(sys.modules.keys()):
            if mod_name == "redis" or mod_name.startswith("redis."):
                saved[mod_name] = sys.modules.pop(mod_name)

        try:
            from deerflow.runtime.stream_bridge.redis_bridge import RedisStreamBridge

            with pytest.raises(ImportError, match="redis\\[hiredis\\]"):
                RedisStreamBridge(redis_url="redis://localhost")
        finally:
            sys.modules.update(saved)
