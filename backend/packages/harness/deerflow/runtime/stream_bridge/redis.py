"""Redis Streams-backed stream bridge."""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import re
from collections.abc import AsyncIterator, Mapping
from typing import Any

try:
    from redis.asyncio import Redis
    from redis.exceptions import RedisError, ResponseError
except ImportError:  # pragma: no cover - only hit when the optional extra is missing
    # ``redis`` is an optional extra (mirrors the ``postgres``/asyncpg path in
    # persistence/engine.py). This module is imported lazily from
    # ``make_stream_bridge`` only when ``stream_bridge.type == "redis"``, so the
    # hint surfaces exactly when a Redis bridge is requested without the package.
    raise ImportError(
        "stream_bridge.type is set to 'redis' but the redis package is not installed.\n"
        "Install it with:\n"
        "    cd backend && uv sync --all-packages --extra redis\n"
        "On the next `make dev` the redis extra is auto-detected from config.yaml\n"
        "(stream_bridge.type: redis) and reinstalled, so it will not be wiped again.\n"
        "Or switch to stream_bridge.type: memory in config.yaml for single-process deployment."
    ) from None

from .base import END_SENTINEL, HEARTBEAT_SENTINEL, StreamBridge, StreamEvent, StreamGap, StreamItem

logger = logging.getLogger(__name__)

_KIND_EVENT = "event"
_KIND_END = "end"
_REDIS_STREAM_ID_RE = re.compile(r"\d+(-\d+)?")

# Batch size for ``XREAD``. Reading more than one entry per round-trip collapses
# a large ``Last-Event-ID`` replay into far fewer calls; live tailing still
# yields each event as it arrives because the consume loop returns mid-batch on
# the end marker.
_XREAD_COUNT = 64

# Maximum consecutive transient Redis errors (``ConnectionError``,
# ``TimeoutError``, etc.) tolerated during ``subscribe`` before the error
# propagates to the caller.  Brief blips are retried with exponential backoff
# capped at ``heartbeat_interval``.
_MAX_SUBSCRIBE_RETRIES = 3


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
        max_connections: int | None = None,
        stream_ttl_seconds: int | None = 86400,
        client: Redis | None = None,
    ) -> None:
        self._redis_url = redis_url
        self._maxsize = max(1, queue_maxsize)
        self._key_prefix = key_prefix.rstrip(":")
        if stream_ttl_seconds is not None and stream_ttl_seconds > 0:
            self._stream_ttl_seconds = stream_ttl_seconds
        else:
            self._stream_ttl_seconds = None
        # Each live SSE subscriber holds one pooled connection blocked in
        # ``XREAD ... BLOCK`` for up to ``heartbeat_interval``. ``max_connections``
        # caps that pool; ``None`` keeps redis-py's effectively-unbounded default.
        self._redis = client if client is not None else Redis.from_url(redis_url, decode_responses=True, max_connections=max_connections)
        self._owns_client = client is None

    def _stream_key(self, run_id: str) -> str:
        return f"{self._key_prefix}:{run_id}"

    async def _xadd_retained(self, key: str, fields: dict[str, str], *, maxlen: int) -> None:
        if self._stream_ttl_seconds is None:
            await self._redis.xadd(
                key,
                fields,
                maxlen=maxlen,
                approximate=False,
            )
            return

        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.xadd(
                key,
                fields,
                maxlen=maxlen,
                approximate=False,
            )
            pipe.expire(key, self._stream_ttl_seconds)
            await pipe.execute()

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

    @classmethod
    def _is_end_entry(cls, fields: Mapping[Any, Any]) -> bool:
        return cls._normalise_fields(fields).get("kind") == _KIND_END

    @staticmethod
    def _parse_stream_id(event_id: str) -> tuple[int, int] | None:
        if _REDIS_STREAM_ID_RE.fullmatch(event_id) is None:
            return None
        milliseconds, separator, sequence = event_id.partition("-")
        return int(milliseconds), int(sequence) if separator else 0

    @classmethod
    def _stream_id_lt(cls, left: str, right: str) -> bool:
        left_parts = cls._parse_stream_id(left)
        right_parts = cls._parse_stream_id(right)
        return left_parts is not None and right_parts is not None and left_parts < right_parts

    async def publish(self, run_id: str, event: str, data: Any) -> None:
        key = self._stream_key(run_id)
        await self._xadd_retained(
            key,
            {
                "kind": _KIND_EVENT,
                "event": event,
                "data": self._encode_data(data),
            },
            maxlen=self._maxsize,
        )

    async def publish_end(self, run_id: str) -> None:
        # Keep the configured number of data events plus the internal end marker.
        key = self._stream_key(run_id)
        await self._xadd_retained(
            key,
            {"kind": _KIND_END},
            maxlen=self._maxsize + 1,
        )

    async def stream_exists(self, run_id: str) -> bool:
        """Return whether Redis still has retained stream data for *run_id*."""
        return bool(await self._redis.exists(self._stream_key(run_id)))

    async def _resolve_start_stream_id(self, key: str, last_event_id: str | None) -> str:
        if last_event_id is None:
            return "0-0"
        if _REDIS_STREAM_ID_RE.fullmatch(last_event_id):
            return last_event_id
        entries = await self._redis.xrevrange(key, count=1)
        if not entries:
            return "0-0"
        event_id, fields = entries[0]
        payload = self._normalise_fields(fields)
        if payload.get("kind") == _KIND_END:
            return "0-0"
        return self._decode(event_id)

    async def _read_retained_snapshot(
        self,
        key: str,
        stream_id: str,
    ) -> tuple[list[Any], list[Any], list[Any]]:
        """Atomically read retained bounds and entries after ``stream_id``.

        A blocking ``XREAD`` cannot participate in a Redis transaction. Live
        subscribers therefore use this non-blocking atomic snapshot for
        correctness, and a separate blocking read only as a wake-up signal.
        """
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.xrange(key, count=1)
            pipe.xrevrange(key, count=1)
            pipe.xread({key: stream_id}, count=_XREAD_COUNT)
            earliest, latest, response = await pipe.execute()
        return earliest, latest, response

    async def subscribe(
        self,
        run_id: str,
        *,
        last_event_id: str | None = None,
        heartbeat_interval: float = 15.0,
    ) -> AsyncIterator[StreamItem]:
        key = self._stream_key(run_id)
        stream_id = await self._resolve_start_stream_id(key, last_event_id)
        gap_detection_enabled = last_event_id is not None and self._parse_stream_id(last_event_id) is not None
        block_ms = max(1, int(heartbeat_interval * 1000)) if heartbeat_interval > 0 else 1
        consecutive_errors = 0

        while True:
            try:
                earliest_entries, latest_entries, response = await self._read_retained_snapshot(key, stream_id)
            except ResponseError:
                # Last-Event-ID is client-controlled and validated before XREAD.
                # If Redis still rejects the id, fail instead of resetting to
                # 0-0, which would replay the whole retained buffer on reconnect.
                logger.warning(
                    "Redis rejected stream id %r for stream bridge subscription",
                    stream_id,
                    exc_info=True,
                )
                raise
            except RedisError:
                consecutive_errors += 1
                if consecutive_errors > _MAX_SUBSCRIBE_RETRIES:
                    raise
                delay = min(2**consecutive_errors, heartbeat_interval)
                logger.warning(
                    "Transient Redis error in stream bridge subscriber (retry %d/%d); backing off %.1fs",
                    consecutive_errors,
                    _MAX_SUBSCRIBE_RETRIES,
                    delay,
                    exc_info=True,
                )
                await asyncio.sleep(delay)
                continue
            else:
                # A non-empty snapshot is forward progress. For an empty
                # snapshot, keep any preceding wake-up failure count until the
                # blocking XREAD itself succeeds; otherwise a permanently
                # failing blocking read could retry forever because the
                # non-blocking transaction succeeds between attempts.
                if response:
                    consecutive_errors = 0

            if earliest_entries and gap_detection_enabled:
                earliest_id = self._decode(earliest_entries[0][0])
                if self._stream_id_lt(stream_id, earliest_id):
                    latest_id = self._decode(latest_entries[0][0])
                    logger.warning(
                        "subscriber for Redis stream %s fell behind retained history at %s",
                        key,
                        stream_id,
                    )
                    yield StreamGap(
                        requested_event_id=stream_id,
                        earliest_available_event_id=earliest_id,
                        latest_available_event_id=latest_id,
                    )
                    return

            if not response:
                if latest_entries and self._decode(latest_entries[0][0]) == stream_id and self._is_end_entry(latest_entries[0][1]):
                    yield END_SENTINEL
                    return

                try:
                    wake_response = await self._redis.xread(
                        {key: stream_id},
                        count=_XREAD_COUNT,
                        block=block_ms,
                    )
                except ResponseError:
                    logger.warning(
                        "Redis rejected stream id %r for stream bridge subscription",
                        stream_id,
                        exc_info=True,
                    )
                    raise
                except RedisError:
                    consecutive_errors += 1
                    if consecutive_errors > _MAX_SUBSCRIBE_RETRIES:
                        raise
                    delay = min(2**consecutive_errors, heartbeat_interval)
                    logger.warning(
                        "Transient Redis error in stream bridge subscriber (retry %d/%d); backing off %.1fs",
                        consecutive_errors,
                        _MAX_SUBSCRIBE_RETRIES,
                        delay,
                        exc_info=True,
                    )
                    await asyncio.sleep(delay)
                    continue
                else:
                    consecutive_errors = 0

                if not wake_response:
                    yield HEARTBEAT_SENTINEL
                continue

            for _stream_name, entries in response:
                for event_id, fields in entries:
                    event_id = self._decode(event_id)
                    stream_id = event_id
                    gap_detection_enabled = True
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
