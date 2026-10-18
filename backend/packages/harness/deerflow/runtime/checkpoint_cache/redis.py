"""Shared Redis backend. Entries are immutable, so a multi-worker shared
cache needs no invalidation; the TTL is a leak safety net only.

Thread-scoped purge (``adelete_thread``) exists for data lifecycle: when a
thread's checkpoints are deleted, its cached history payloads are removed
immediately instead of lingering until TTL expiry.

The redis import is lazy (module is importable without the optional
``redis`` extra), mirroring runtime/stream_bridge/redis.py.
"""

from __future__ import annotations

import logging
from typing import Any

from deerflow.runtime.checkpoint_cache.base import CheckpointCacheStats, thread_key_stem

logger = logging.getLogger(__name__)

REDIS_INSTALL = "redis is required for the redis checkpoint cache backend. Install it with: uv sync --extra redis"

_TAG_SEPARATOR = b"\x00"


def _create_client(redis_url: str, *, max_connections: int | None) -> Any:
    try:
        import redis.asyncio as redis_async
    except ImportError as exc:
        raise ImportError(REDIS_INSTALL) from exc
    kwargs: dict[str, Any] = {"decode_responses": False}
    if max_connections is not None:
        kwargs["max_connections"] = max_connections
    return redis_async.from_url(redis_url, **kwargs)


def _redis_error() -> type[Exception]:
    """Lazy RedisError import, mirroring the lazy client creation above."""
    try:
        from redis.exceptions import RedisError
    except ImportError as exc:
        raise ImportError(REDIS_INSTALL) from exc
    return RedisError


class RedisCheckpointHistoryCache:
    def __init__(
        self,
        redis_url: str,
        *,
        serde: Any,
        ttl_seconds: int,
        max_connections: int | None = None,
    ) -> None:
        self._client = _create_client(redis_url, max_connections=max_connections)
        self._serde = serde
        # ttl_seconds=0 is an explicit opt-out of expiry (no SETEX) — not the
        # default, and leaked/orphaned keys then rely on redis maxmemory only.
        self._ttl = ttl_seconds if ttl_seconds > 0 else None
        self._hits = 0
        self._misses = 0
        self._write_serialization_failures = 0

    async def aget_many(self, keys: list[str]) -> dict[str, dict[str, Any]]:
        if not keys:
            return {}
        try:
            raws = await self._client.mget(keys)
        except _redis_error() as exc:
            # Performance-only bypass: a redis outage costs hits, never availability.
            logger.warning("checkpoint history cache mget failed; treating as all-miss: %s", exc)
            self._misses += len(keys)
            return {}
        found: dict[str, dict[str, Any]] = {}
        for key, raw in zip(keys, raws, strict=True):
            if raw is None:
                self._misses += 1
                continue
            try:
                tag, payload = raw.split(_TAG_SEPARATOR, 1)
                entry = self._serde.loads_typed((tag.decode(), payload))
                if not isinstance(entry, dict) or not isinstance(entry.get("writes"), list):
                    raise ValueError("invalid checkpoint history entry shape")
            except Exception as exc:
                # Cached history is optional. A malformed entry must not prevent
                # rebuilding history from authoritative checkpoints.
                logger.warning(
                    "checkpoint history cache decode failed; treating as miss (key=%s): %s",
                    key,
                    type(exc).__name__,
                )
                self._misses += 1
                continue
            self._hits += 1
            found[key] = entry
        return found

    async def aset_many(self, entries: dict[str, dict[str, Any]]) -> None:
        if not entries:
            return
        try:
            pipe = self._client.pipeline(transaction=False)
            for key, entry in entries.items():
                try:
                    tag, data = self._serde.dumps_typed(entry)
                except Exception as exc:
                    self._write_serialization_failures += 1
                    # Cache writes are optional; one unserializable entry must not
                    # abort authoritative history reads or discard other entries.
                    logger.warning(
                        "checkpoint history cache serialization failed; skipping (key=%s): %s",
                        key,
                        type(exc).__name__,
                    )
                    continue
                pipe.set(key, tag.encode() + _TAG_SEPARATOR + data, ex=self._ttl)
            await pipe.execute()
        except _redis_error() as exc:
            # Writes are optional; the next read simply recomputes the history.
            logger.warning("checkpoint history cache write failed; skipping: %s", exc)

    async def adelete_thread(self, key_prefix: str, thread_id: str) -> None:
        """SCAN+UNLINK every entry of one thread. Failure degrades to
        TTL-bounded residual retention; the source-of-truth delete already
        happened, so this never raises."""
        stem = thread_key_stem(key_prefix, thread_id)
        # The configured namespace is a literal key prefix, not a Redis glob.
        pattern = "".join("\\" + char if char in "\\*?[]" else char for char in stem) + "*"
        # redis-py encodes SCAN results with the configured connection encoder.
        # A fixed UTF-8 fence silently skips owned keys for other encodings.
        encoded_stem = self._client.connection_pool.get_encoder().encode(stem)
        try:
            cursor = 0
            while True:
                cursor, keys = await self._client.scan(cursor=cursor, match=pattern, count=500)
                keys = [key for key in keys if key.startswith(encoded_stem if isinstance(key, bytes) else stem)]
                if keys:
                    await self._client.unlink(*keys)
                if cursor == 0:
                    break
        except _redis_error() as exc:
            logger.warning("checkpoint history cache thread purge failed; residual entries expire via TTL: %s", exc)

    def stats(self) -> CheckpointCacheStats:
        return CheckpointCacheStats(
            hits=self._hits,
            misses=self._misses,
            write_serialization_failures=self._write_serialization_failures,
        )

    async def aclose(self) -> None:
        await self._client.aclose()
