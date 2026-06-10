"""Redis Streams-backed stream bridge."""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
from collections.abc import AsyncIterator, Mapping
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import ResponseError

from .base import END_SENTINEL, HEARTBEAT_SENTINEL, StreamBridge, StreamEvent

logger = logging.getLogger(__name__)

_KIND_EVENT = "event"
_KIND_END = "end"


class RedisStreamBridge(StreamBridge):
    """Per-run stream bridge backed by Redis Streams.

    Each run is stored in one Redis Stream and subscribers read directly with
    ``XREAD``.  This keeps the SSE bridge usable across multiple gateway
    worker processes while preserving ``Last-Event-ID`` replay semantics.
    """

    supports_cross_process = True

    def __init__(
        self,
        *,
        redis_url: str,
        queue_maxsize: int = 256,
        key_prefix: str = "deerflow:stream_bridge",
        client: Redis | None = None,
    ) -> None:
        self._redis_url = redis_url
        self._maxsize = max(1, queue_maxsize)
        self._key_prefix = key_prefix.rstrip(":")
        self._redis = client if client is not None else Redis.from_url(redis_url, decode_responses=True)
        self._owns_client = client is None

    def _stream_key(self, run_id: str) -> str:
        return f"{self._key_prefix}:{run_id}"

    @staticmethod
    def _decode(value: Any) -> str:
        if isinstance(value, bytes):
            return value.decode("utf-8")
        return str(value)

    @classmethod
    def _normalise_fields(cls, fields: Mapping[Any, Any]) -> dict[str, str]:
        return {cls._decode(key): cls._decode(value) for key, value in fields.items()}

    @staticmethod
    def _encode_data(data: Any) -> str:
        return json.dumps(data, default=str, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _decode_data(raw: str | None) -> Any:
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Redis stream bridge received non-JSON event data")
            return raw

    def _entry_from_redis(self, event_id: str, fields: Mapping[Any, Any]) -> StreamEvent:
        payload = self._normalise_fields(fields)
        kind = payload.get("kind", _KIND_EVENT)
        if kind == _KIND_END:
            return END_SENTINEL
        return StreamEvent(
            id=event_id,
            event=payload.get("event", "message"),
            data=self._decode_data(payload.get("data")),
        )

    async def publish(self, run_id: str, event: str, data: Any) -> None:
        await self._redis.xadd(
            self._stream_key(run_id),
            {
                "kind": _KIND_EVENT,
                "event": event,
                "data": self._encode_data(data),
            },
            maxlen=self._maxsize,
            approximate=False,
        )

    async def publish_end(self, run_id: str) -> None:
        # Keep the configured number of data events plus the internal end marker.
        await self._redis.xadd(
            self._stream_key(run_id),
            {"kind": _KIND_END},
            maxlen=self._maxsize + 1,
            approximate=False,
        )

    async def subscribe(
        self,
        run_id: str,
        *,
        last_event_id: str | None = None,
        heartbeat_interval: float = 15.0,
    ) -> AsyncIterator[StreamEvent]:
        key = self._stream_key(run_id)
        stream_id = last_event_id or "0-0"
        block_ms = max(1, int(heartbeat_interval * 1000)) if heartbeat_interval > 0 else 1

        while True:
            try:
                response = await self._redis.xread({key: stream_id}, count=1, block=block_ms)
            except ResponseError as exc:
                # Only fall back when Redis rejects the provided stream ID (bad Last-Event-ID).
                message = str(exc)
                if stream_id != "0-0" and (
                    "ID specified" in message
                    or "stream ID" in message
                    or "Invalid" in message
                ):
                    logger.warning(
                        "Invalid Last-Event-ID %r for Redis stream bridge; replaying from earliest retained event",
                        stream_id,
                        exc_info=True,
                    )
                    stream_id = "0-0"
                    continue
                raise

            if not response:
                yield HEARTBEAT_SENTINEL
                continue

            for _stream_name, entries in response:
                for event_id, fields in entries:
                    event_id = self._decode(event_id)
                    stream_id = event_id
                    entry = self._entry_from_redis(event_id, fields)
                    if entry is END_SENTINEL:
                        yield END_SENTINEL
                        return
                    yield entry

    async def cleanup(self, run_id: str, *, delay: float = 0) -> None:
        if delay > 0:
            await asyncio.sleep(delay)
        await self._redis.delete(self._stream_key(run_id))

    async def close(self) -> None:
        if not self._owns_client:
            return
        close = getattr(self._redis, "aclose", None) or getattr(self._redis, "close", None)
        if close is None:
            return
        result = close()
        if inspect.isawaitable(result):
            await result
