"""Semantic cache — cosine-similarity-based query/response cache."""

from __future__ import annotations

import hashlib
import json
import logging
import math

from deerflow.cache.redis_client import RedisCache
from deerflow.config.cache_config import get_cache_config

logger = logging.getLogger(__name__)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _hash_query(query: str) -> str:
    return hashlib.sha256(query.encode()).hexdigest()[:16]


class SemanticCache:
    """Caches (query, embedding) → response, using cosine similarity for lookup."""

    def __init__(self, redis_cache: RedisCache | None = None) -> None:
        self._cache = redis_cache or RedisCache()
        self._config = get_cache_config().semantic_cache

    def _key(self, query_hash: str) -> str:
        return f"sem:{query_hash}"

    async def lookup(self, query: str, embedding: list[float]) -> str | None:
        """Try to find a cached response for a semantically similar query."""
        if not self._config.enabled:
            return None

        qh = _hash_query(query)
        try:
            entry = await self._cache.get(self._key(qh))
            if entry is None:
                return None
            cached_embedding = entry.get("embedding")
            if cached_embedding is None:
                return None
            sim = _cosine_similarity(embedding, cached_embedding)
            if sim >= self._config.similarity_threshold:
                logger.debug("Semantic cache hit (similarity=%.3f)", sim)
                return entry["response"]
        except Exception:
            logger.warning("Semantic cache lookup failed")
        return None

    async def store(self, query: str, embedding: list[float], response: str) -> None:
        """Store a query/response pair with its embedding."""
        if not self._config.enabled:
            return
        qh = _hash_query(query)
        try:
            await self._cache.set(
                self._key(qh),
                {"query": query, "embedding": embedding, "response": response},
                ttl=self._config.ttl_seconds,
            )
        except Exception:
            logger.warning("Semantic cache store failed")
