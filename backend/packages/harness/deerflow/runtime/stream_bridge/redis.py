"""Redis Streams stream bridge.

Implements :class:`StreamBridge` on top of Redis Streams so that any
gateway worker / replica can subscribe to a run's stream regardless of
which worker produced the events.

Design notes (see docs/superpowers/specs/2026-06-10-redis-stream-bridge-design.md):

- Data-event ``publish`` is **best-effort with bounded retry**: transient
  connection/timeout errors are retried a few times with short backoff;
  if still failing the frame is dropped (logged) rather than raised, so
  Redis availability does not couple to run success rate.
- Subscriptions use a **dedicated blocking connection pool**, isolated from
  the command pool so a flood of SSE subscribers cannot starve publishes.
- END is written as a normal stream entry (``event=__end__``) so ordering
  and late-join replay are preserved.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections import OrderedDict
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from .base import END_SENTINEL, HEARTBEAT_SENTINEL, StreamBridge, StreamEvent

if TYPE_CHECKING:
    from deerflow.config.stream_bridge_config import StreamBridgeConfig

logger = logging.getLogger(__name__)

END_EVENT_NAME = "__end__"

# Accept either ``0`` / ``0-0`` or ``<digits>-<digits>`` Redis stream IDs.
_STREAM_ID_RE = re.compile(r"^(?:0|\d+-\d+)$")
# run_id must be a UUID (the only producer of run ids today).
_RUN_ID_RE = re.compile(r"^[0-9a-fA-F-]{36}$")

# TTL refresh sampling window: only refresh at most once per this interval on
# the publish hot path; long-idle runs are kept alive by the worker TTL keeper.
_TTL_REFRESH_WINDOW_SECONDS = 60.0
# Upper bound for the per-run TTL sampling state to guard against leaks when
# cleanup is missed (process restart etc.).
_TTL_STATE_MAXSIZE = 100_000

_PUBLISH_RETRY_BACKOFFS = (0.05, 0.15, 0.3)
_SUBSCRIBE_MAX_RETRIES = 5


def mask_redis_url(url: str | None) -> str:
    """Redact credentials from a redis URL for safe logging."""
    if not url:
        return "<none>"
    # redis://[:password@]host:port/db -> redis://***@host:port/db
    return re.sub(r"://[^@/]*@", "://***@", url)


class RedisStreamBridge(StreamBridge):
    """Redis Streams-backed :class:`StreamBridge`."""

    def __init__(
        self,
        *,
        redis_url: str,
        queue_maxsize: int = 256,
        max_command_connections: int = 64,
        max_blocking_connections: int = 1024,
        pool_timeout: float = 1.0,
        socket_timeout: float = 30.0,
        ttl_seconds: int = 86400,
        max_payload_bytes: int = 524288,
        key_prefix: str = "df:sb",
        read_batch_size: int = 100,
    ) -> None:
        try:
            import redis.asyncio as redis_async
        except ImportError as exc:  # pragma: no cover - exercised via factory
            raise ImportError(
                "Install deerflow-harness[redis] to use stream_bridge.type=redis"
            ) from exc

        # redis-py raises its own ConnectionError / TimeoutError which do NOT
        # inherit from the builtin OSError hierarchy, so they must be caught
        # explicitly for the best-effort retry paths to work (problems N/D).
        self._retryable_errors = (
            redis_async.ConnectionError,
            redis_async.TimeoutError,
            OSError,
        )

        self._redis_url = redis_url
        self._maxsize = queue_maxsize
        self._ttl_seconds = ttl_seconds
        self._max_payload_bytes = max_payload_bytes
        self._key_prefix = key_prefix
        self._read_batch_size = read_batch_size
        self._pool_timeout = pool_timeout

        # Command pool: short commands (publish / cleanup / refresh_ttl / probes).
        self._command_pool = redis_async.BlockingConnectionPool.from_url(
            redis_url,
            max_connections=max_command_connections,
            timeout=pool_timeout,
            socket_timeout=socket_timeout,
            decode_responses=True,
        )
        self._redis = redis_async.Redis(connection_pool=self._command_pool)

        # Blocking subscribe pool: each active XREAD holds a connection while
        # blocking. ``socket_timeout=None`` so long ``block`` durations do not
        # raise spurious TimeoutError; isolated from the command pool.
        self._blocking_pool = redis_async.BlockingConnectionPool.from_url(
            redis_url,
            max_connections=max_blocking_connections,
            timeout=pool_timeout,
            socket_timeout=None,
            decode_responses=True,
        )
        self._blocking_redis = redis_async.Redis(connection_pool=self._blocking_pool)

        # Per-run "last TTL refresh" timestamps (bounded LRU, see problem O).
        self._ttl_last_refresh: OrderedDict[str, float] = OrderedDict()

    # -- construction ----------------------------------------------------------

    @classmethod
    def from_config(cls, config: StreamBridgeConfig) -> RedisStreamBridge:
        assert config.redis_url is not None  # guaranteed by config validator
        return cls(
            redis_url=config.redis_url,
            queue_maxsize=config.queue_maxsize,
            max_command_connections=config.redis_max_command_connections,
            max_blocking_connections=config.redis_max_blocking_connections,
            pool_timeout=config.redis_pool_timeout,
            socket_timeout=config.redis_socket_timeout,
            ttl_seconds=config.redis_ttl_seconds,
            max_payload_bytes=config.redis_max_payload_bytes,
            key_prefix=config.redis_key_prefix,
        )

    @property
    def supports_cross_process_subscribe(self) -> bool:
        return True

    @property
    def ttl_seconds(self) -> int:
        return self._ttl_seconds

    # -- helpers ---------------------------------------------------------------

    def _stream_key(self, run_id: str) -> str:
        if not _RUN_ID_RE.match(run_id):
            raise ValueError(f"Invalid run_id for redis stream key: {run_id!r}")
        return f"{self._key_prefix}:{run_id}:stream"

    def _encode_payload(self, run_id: str, event: str, data: Any) -> tuple[str | None, bool]:
        """Serialize *data* to JSON with ``default=str`` fallback.

        Returns ``(payload_json, used_fallback)``.  Returns ``(None, _)`` when
        the payload is rejected (too large or unserializable) — the caller
        treats that as a dropped data event.
        """
        used_fallback = False
        try:
            payload_json = json.dumps(data, ensure_ascii=False)
        except (TypeError, ValueError):
            try:
                payload_json = json.dumps(data, default=str, ensure_ascii=False)
                used_fallback = True
            except (TypeError, ValueError):
                logger.warning(
                    "Redis stream payload not serializable; dropping run=%s event=%s type=%s",
                    run_id,
                    event,
                    type(data).__name__,
                )
                return None, used_fallback

        payload_bytes = len(payload_json.encode("utf-8"))
        if payload_bytes > self._max_payload_bytes:
            logger.warning(
                "Redis stream payload too large (%d > %d); dropping run=%s event=%s",
                payload_bytes,
                self._max_payload_bytes,
                run_id,
                event,
            )
            return None, used_fallback

        return payload_json, used_fallback

    def _should_refresh_ttl(self, run_id: str, now: float) -> bool:
        last = self._ttl_last_refresh.get(run_id)
        if last is not None and (now - last) < _TTL_REFRESH_WINDOW_SECONDS:
            return False
        self._ttl_last_refresh[run_id] = now
        self._ttl_last_refresh.move_to_end(run_id)
        while len(self._ttl_last_refresh) > _TTL_STATE_MAXSIZE:
            self._ttl_last_refresh.popitem(last=False)
        return True

    # -- StreamBridge API ------------------------------------------------------

    async def publish(self, run_id: str, event: str, data: Any) -> None:
        key = self._stream_key(run_id)
        payload_json, used_fallback = self._encode_payload(run_id, event, data)
        if payload_json is None:
            # Oversized / unserializable: best-effort drop, do not raise.
            return

        if used_fallback:
            logger.warning(
                "Redis stream payload used default=str fallback for run %s event %s (type=%s)",
                run_id,
                event,
                type(data).__name__,
            )

        payload = {"event": event, "data": payload_json}
        refresh = self._should_refresh_ttl(run_id, time.monotonic())

        last_exc: Exception | None = None
        for attempt in range(len(_PUBLISH_RETRY_BACKOFFS) + 1):
            try:
                async with self._redis.pipeline(transaction=False) as pipe:
                    pipe.xadd(key, payload, maxlen=self._maxsize, approximate=True)
                    if refresh:
                        pipe.expire(key, self._ttl_seconds)
                    await pipe.execute()
                return
            except self._retryable_errors as exc:
                last_exc = exc
                if attempt < len(_PUBLISH_RETRY_BACKOFFS):
                    await asyncio.sleep(_PUBLISH_RETRY_BACKOFFS[attempt])
                    continue

        # Bounded retry exhausted: best-effort drop (problem N).
        logger.warning(
            "Redis stream publish dropped after retries for run %s event %s: %s",
            run_id,
            event,
            last_exc,
        )

    async def publish_end(self, run_id: str) -> None:
        key = self._stream_key(run_id)
        payload = {"event": END_EVENT_NAME, "data": "null"}
        try:
            await self._redis.xadd(key, payload, maxlen=self._maxsize, approximate=True)
        except Exception:
            logger.warning("Failed to publish stream end for run %s", run_id, exc_info=True)

    async def subscribe(
        self,
        run_id: str,
        *,
        last_event_id: str | None = None,
        heartbeat_interval: float = 15.0,
    ) -> AsyncIterator[StreamEvent]:
        key = self._stream_key(run_id)
        cursor = await self._resolve_cursor(key, last_event_id)
        block_ms = max(1, int(heartbeat_interval * 1000))
        retries = 0

        while True:
            try:
                response = await self._blocking_redis.xread(
                    {key: cursor},
                    block=block_ms,
                    count=self._read_batch_size,
                )
                retries = 0
            except asyncio.CancelledError:
                raise
            except self._retryable_errors as exc:
                retries += 1
                if retries > _SUBSCRIBE_MAX_RETRIES:
                    logger.error(
                        "Redis stream subscribe exceeded retries for run %s cursor=%s: %s",
                        run_id,
                        cursor,
                        exc,
                    )
                    raise
                await asyncio.sleep(min(2.0, 0.1 * (2**retries)))
                continue

            if not response:
                yield HEARTBEAT_SENTINEL
                continue

            _key, entries = response[0]
            for raw_id, fields in entries:
                cursor = raw_id
                event_name = fields.get("event")
                if event_name == END_EVENT_NAME:
                    yield END_SENTINEL
                    return
                raw_data = fields.get("data")
                try:
                    parsed = json.loads(raw_data) if raw_data is not None else None
                except (TypeError, ValueError):
                    parsed = raw_data
                yield StreamEvent(id=raw_id, event=event_name, data=parsed)

    async def _resolve_cursor(self, key: str, last_event_id: str | None) -> str:
        """Resolve the XREAD cursor from a client-provided Last-Event-ID."""
        if last_event_id is None:
            return "0-0"

        if not _STREAM_ID_RE.match(last_event_id):
            logger.warning("Invalid Last-Event-ID %r; replaying from earliest", last_event_id)
            return "0-0"

        try:
            earliest = await self._redis.xrange(key, min="-", max="+", count=1)
            latest = await self._redis.xrevrange(key, max="+", min="-", count=1)
        except Exception:
            # Boundary probe failed: fall back to the provided id (best-effort).
            return last_event_id

        if not earliest or not latest:
            # Key missing / empty: start from beginning, block for new events.
            return "0-0"

        earliest_id = earliest[0][0]
        latest_id = latest[0][0]

        if _compare_stream_ids(last_event_id, earliest_id) < 0:
            logger.warning(
                "Last-Event-ID %s older than earliest retained %s; replaying from earliest",
                last_event_id,
                earliest_id,
            )
            return "0-0"
        if _compare_stream_ids(last_event_id, latest_id) > 0:
            logger.warning(
                "Last-Event-ID %s ahead of latest %s; resuming from latest",
                last_event_id,
                latest_id,
            )
            return latest_id
        return last_event_id

    async def refresh_ttl(self, run_id: str) -> None:
        key = self._stream_key(run_id)
        try:
            # EXPIRE on a missing key is a no-op (returns 0); never recreates it.
            await self._redis.expire(key, self._ttl_seconds)
        except Exception:
            logger.warning("Failed to refresh TTL for run %s", run_id, exc_info=True)

    async def has_retained_stream(self, run_id: str) -> bool:
        key = self._stream_key(run_id)
        return bool(await self._redis.exists(key))

    async def has_events_after(self, run_id: str, last_event_id: str | None) -> bool:
        key = self._stream_key(run_id)
        start = f"({last_event_id}" if last_event_id else "-"
        try:
            entries = await self._redis.xrange(key, min=start, max="+", count=1)
        except Exception:
            # Probe failed: conservative — assume events may exist.
            return True
        return bool(entries)

    async def cleanup(self, run_id: str, *, delay: float = 0) -> None:
        if delay > 0:
            await asyncio.sleep(delay)
        self._ttl_last_refresh.pop(run_id, None)
        try:
            await self._redis.delete(self._stream_key(run_id))
        except Exception:
            logger.warning("Failed to cleanup Redis stream for run %s", run_id, exc_info=True)

    async def ping(self) -> None:
        await self._redis.ping()

    async def close(self) -> None:
        try:
            await self._redis.aclose()
        finally:
            await self._blocking_redis.aclose()


def _compare_stream_ids(a: str, b: str) -> int:
    """Compare two Redis stream IDs. Returns -1 / 0 / 1."""
    ta = _id_tuple(a)
    tb = _id_tuple(b)
    return (ta > tb) - (ta < tb)


def _id_tuple(stream_id: str) -> tuple[int, int]:
    if "-" in stream_id:
        ms, _, seq = stream_id.partition("-")
        return int(ms), int(seq)
    return int(stream_id), 0
