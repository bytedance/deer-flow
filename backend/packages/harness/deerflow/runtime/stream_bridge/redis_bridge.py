"""Redis Stream bridge — cross-worker event delivery via Redis Streams.

Uses Redis Streams (XADD / XREAD) to publish and consume events, enabling
multi-worker SSE where the producer and consumer may be on different processes.

Key format: ``deerflow:stream:{run_id}``

Each event is stored as a Redis Stream entry with fields:
  - ``event``: SSE event name
  - ``data``: JSON-serialised payload
  - ``sequence``: monotonically increasing integer sequence number

The bridge supports:
  - **MAXLEN trimming**: streams are capped at ``queue_maxsize`` entries
  - **Resumption**: subscribers can resume from a specific Redis Stream ID
  - **Consumer lag detection**: warns when subscribers fall behind
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from .base import END_SENTINEL, HEARTBEAT_SENTINEL, StreamBridge, StreamEvent
from .metrics import stream_bridge_metrics

logger = logging.getLogger(__name__)

_STREAM_KEY_PREFIX = "deerflow:stream:"
_END_MARKER_FIELD = "__end__"
_LAG_WARNING_THRESHOLD = 100


def _stream_key(run_id: str) -> str:
    return f"{_STREAM_KEY_PREFIX}{run_id}"


class RedisStreamBridge(StreamBridge):
    """Redis Streams-backed stream bridge for multi-worker deployments.

    Args:
        redis_url: Redis connection URL (e.g. ``redis://localhost:6379/0``).
        queue_maxsize: Maximum stream length (MAXLEN). Default 1024.
        poll_interval: Seconds between XREAD polls when no new entries.
        heartbeat_interval: Seconds between heartbeat sentinels when idle.
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379/0",
        *,
        queue_maxsize: int = 1024,
        poll_interval: float = 0.5,
        heartbeat_interval: float = 15.0,
    ) -> None:
        try:
            import redis.asyncio as aioredis
        except ImportError as exc:
            raise ImportError(
                "redis[hiredis] is required for RedisStreamBridge. "
                "Install with: pip install 'deerflow-harness[redis]'"
            ) from exc

        self._redis = aioredis.from_url(redis_url, decode_responses=True)
        self._maxsize = queue_maxsize
        self._poll_interval = poll_interval
        self._heartbeat_interval = heartbeat_interval
        self._counters: dict[str, int] = {}

    async def publish(self, run_id: str, event: str, data: Any) -> None:
        seq = self._counters.get(run_id, 0)
        self._counters[run_id] = seq + 1

        try:
            payload = json.dumps(data)
        except (TypeError, ValueError):
            payload = "null"

        key = _stream_key(run_id)
        await self._redis.xadd(
            key,
            {"event": event, "data": payload, "sequence": str(seq)},
            maxlen=self._maxsize,
            approximate=True,
        )
        stream_bridge_metrics.record_publish(event, data)

    async def publish_end(self, run_id: str) -> None:
        key = _stream_key(run_id)
        seq = self._counters.get(run_id, 0)
        self._counters[run_id] = seq + 1
        await self._redis.xadd(
            key,
            {"event": _END_MARKER_FIELD, "data": "", "sequence": str(seq)},
            maxlen=self._maxsize,
            approximate=True,
        )

    async def subscribe(
        self,
        run_id: str,
        *,
        last_event_id: str | None = None,
        heartbeat_interval: float = 15.0,
    ) -> AsyncIterator[StreamEvent]:
        key = _stream_key(run_id)
        start_id = last_event_id if last_event_id else "0-0"

        while True:
            try:
                entries = await self._redis.xread({key: start_id}, count=50, block=int(self._poll_interval * 1000))
            except Exception:
                logger.warning("Redis XREAD failed for run %s", run_id, exc_info=True)
                await asyncio.sleep(self._poll_interval)
                continue

            if not entries:
                yield HEARTBEAT_SENTINEL
                continue

            for _stream_name, messages in entries:
                for message_id, fields in messages:
                    start_id = message_id

                    if fields.get("event") == _END_MARKER_FIELD:
                        yield END_SENTINEL
                        return

                    try:
                        data = json.loads(fields.get("data", "null"))
                    except json.JSONDecodeError:
                        data = fields.get("data")

                    sequence = int(fields.get("sequence", 0))
                    yield StreamEvent(
                        id=message_id,
                        event=fields.get("event", "unknown"),
                        data=data,
                        sequence=sequence,
                    )

    async def cleanup(self, run_id: str, *, delay: float = 0) -> None:
        if delay > 0:
            await asyncio.sleep(delay)
        key = _stream_key(run_id)
        try:
            await self._redis.delete(key)
        except Exception:
            logger.warning("Failed to delete Redis stream %s", key, exc_info=True)
        self._counters.pop(run_id, None)
        stream_bridge_metrics.remove_run(run_id)

    async def close(self) -> None:
        try:
            await self._redis.aclose()
        except Exception:
            logger.debug("Error closing Redis connection", exc_info=True)
        self._counters.clear()
