"""Redis-backed stream bridge."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from .base import END_SENTINEL, HEARTBEAT_SENTINEL, _END_EVENT, StreamBridge, StreamEvent

logger = logging.getLogger(__name__)


def _json_dumps(data: Any) -> str:
    return json.dumps(data, default=str, ensure_ascii=False)


class RedisStreamBridge(StreamBridge):
    """Stream bridge using Redis Streams (``XADD`` / ``XRANGE`` / ``XREAD``)."""

    def __init__(
        self,
        *,
        redis_url: str,
        queue_maxsize: int = 256,
        key_prefix: str = "deerflow:sse",
    ) -> None:
        self._redis_url = redis_url
        self._maxlen = max(1, queue_maxsize)
        self._key_prefix = key_prefix.rstrip(":")
        self._redis: Any = None

    def _key(self, run_id: str) -> str:
        return f"{self._key_prefix}:{run_id}"

    async def _client(self) -> Any:
        if self._redis is None:
            try:
                import redis.asyncio as redis_async
            except ImportError as exc:
                raise ImportError(
                    "Redis stream bridge requires the 'redis' package. Install with: uv add redis"
                ) from exc
            self._redis = redis_async.from_url(self._redis_url, decode_responses=True)
        return self._redis

    @staticmethod
    def _parse_message(msg_id: str, fields: dict[str, str]) -> StreamEvent | None:
        event = fields.get("event", "")
        if event == _END_EVENT:
            return None
        raw = fields.get("data", "{}")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = {"_raw": raw}
        return StreamEvent(id=msg_id, event=event, data=data)

    async def publish(self, run_id: str, event: str, data: Any) -> None:
        r = await self._client()
        await r.xadd(
            self._key(run_id),
            {"event": event, "data": _json_dumps(data)},
            maxlen=self._maxlen,
            approximate=True,
        )

    async def publish_end(self, run_id: str) -> None:
        r = await self._client()
        await r.xadd(
            self._key(run_id),
            {"event": _END_EVENT, "data": "{}"},
            maxlen=self._maxlen,
            approximate=True,
        )

    async def subscribe(
        self,
        run_id: str,
        *,
        last_event_id: str | None = None,
        heartbeat_interval: float = 15.0,
    ) -> AsyncIterator[StreamEvent]:
        r = await self._client()
        key = self._key(run_id)
        block_ms = max(1, int(heartbeat_interval * 1000))

        min_id = f"({last_event_id}" if last_event_id else "-"
        try:
            batch = await r.xrange(key, min=min_id, max="+")
        except Exception:
            logger.exception("Redis XRANGE failed for run %s", run_id)
            batch = []

        cursor = last_event_id or "0-0"
        for msg_id, fields in batch:
            cursor = msg_id
            if fields.get("event") == _END_EVENT:
                yield END_SENTINEL
                return
            ev = self._parse_message(msg_id, fields)
            if ev is not None:
                yield ev

        while True:
            try:
                result = await r.xread(streams={key: cursor}, block=block_ms, count=100)
            except Exception:
                logger.exception("Redis XREAD failed for run %s", run_id)
                yield HEARTBEAT_SENTINEL
                await asyncio.sleep(0)
                continue

            if not result:
                yield HEARTBEAT_SENTINEL
                continue

            for _sname, messages in result:
                for msg_id, fields in messages:
                    cursor = msg_id
                    if fields.get("event") == _END_EVENT:
                        yield END_SENTINEL
                        return
                    ev = self._parse_message(msg_id, fields)
                    if ev is not None:
                        yield ev

    async def cleanup(self, run_id: str, *, delay: float = 0) -> None:
        if delay > 0:
            await asyncio.sleep(delay)
        if self._redis is None:
            return
        try:
            await self._redis.delete(self._key(run_id))
        except Exception:
            logger.debug("Redis delete stream key failed for run %s (non-fatal)", run_id, exc_info=True)

    async def close(self) -> None:
        if self._redis is not None:
            try:
                await self._redis.aclose()
            except Exception:
                logger.debug("Redis close failed (non-fatal)", exc_info=True)
            self._redis = None
