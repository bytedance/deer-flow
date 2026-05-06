"""Embedding cache — caches embedding vectors keyed by SHA-256 of the input text."""

from __future__ import annotations

import hashlib
import json
import logging

from deerflow.cache.redis_client import RedisCache
from deerflow.config.cache_config import get_cache_config

logger = logging.getLogger(__name__)


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class EmbeddingCache:
    """Caches text → embedding vector mappings to avoid redundant API calls."""

    def __init__(self, redis_cache: RedisCache | None = None) -> None:
        self._cache = redis_cache or RedisCache()
        self._config = get_cache_config().embedding_cache

    def _key(self, text: str) -> str:
        return f"emb:{_hash_text(text)}"

    async def get_embedding(self, text: str) -> list[float] | None:
        if not self._config.enabled:
            return None
        try:
            result = await self._cache.get(self._key(text))
            if result is not None:
                logger.debug("Embedding cache hit for %d chars", len(text))
            return result
        except Exception:
            logger.warning("Embedding cache lookup failed")
            return None

    async def set_embedding(self, text: str, embedding: list[float]) -> None:
        if not self._config.enabled:
            return
        try:
            await self._cache.set(self._key(text), embedding, ttl=self._config.ttl_seconds)
        except Exception:
            logger.warning("Embedding cache store failed")
