"""Redis client wrapper — async get/set/delete with optional Redis and in-memory fallback."""

from __future__ import annotations

import json
import logging
from typing import Any

from deerflow.config.cache_config import get_cache_config

logger = logging.getLogger(__name__)


class RedisCache:
    """Async key-value cache with optional Redis backend and in-memory fallback."""

    def __init__(self) -> None:
        config = get_cache_config()
        self._redis = None
        self._fallback: dict[str, dict] = {}
        self._available = False

        if config.redis_url:
            try:
                import redis.asyncio as aioredis

                self._redis = aioredis.from_url(config.redis_url, decode_responses=False)
                self._available = True
                logger.info("Redis cache connected: %s", config.redis_url)
            except ImportError:
                logger.warning("redis package not installed; using in-memory fallback")
            except Exception:
                logger.warning("Failed to connect to Redis at %s; using in-memory fallback", config.redis_url)

    def is_available(self) -> bool:
        return self._available and self._redis is not None

    async def get(self, key: str) -> Any | None:
        if self._available and self._redis is not None:
            try:
                raw = await self._redis.get(key)
                if raw is None:
                    return None
                return json.loads(raw)
            except Exception:
                logger.warning("Redis get failed for key %s, falling back", key)
        entry = self._fallback.get(key)
        if entry is None:
            return None
        return entry["value"]

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        if self._available and self._redis is not None:
            try:
                raw = json.dumps(value)
                await self._redis.set(key, raw, ex=ttl)
                return
            except Exception:
                logger.warning("Redis set failed for key %s, falling back", key)
        self._fallback[key] = {"value": value}

    async def delete(self, key: str) -> None:
        if self._available and self._redis is not None:
            try:
                await self._redis.delete(key)
                return
            except Exception:
                logger.warning("Redis delete failed for key %s, falling back", key)
        self._fallback.pop(key, None)

    async def exists(self, key: str) -> bool:
        if self._available and self._redis is not None:
            try:
                return bool(await self._redis.exists(key))
            except Exception:
                logger.warning("Redis exists check failed for key %s, falling back", key)
        return key in self._fallback

    async def close(self) -> None:
        if self._redis is not None:
            try:
                await self._redis.aclose()
            except Exception:
                pass
        self._fallback.clear()
