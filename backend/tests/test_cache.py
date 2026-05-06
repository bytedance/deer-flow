"""Tests for cache layer — Redis client, embedding cache, and semantic cache."""

from __future__ import annotations

import pytest

from deerflow.cache.embedding_cache import EmbeddingCache
from deerflow.cache.redis_client import RedisCache
from deerflow.cache.semantic_cache import SemanticCache, _cosine_similarity
from deerflow.config.cache_config import (
    get_cache_config,
    load_cache_config_from_dict,
    reset_cache_config,
)


class TestCacheConfig:
    def test_default_config(self):
        reset_cache_config()
        config = get_cache_config()
        assert config.enabled is False
        assert config.redis_url == ""
        assert config.embedding_cache.enabled is True
        assert config.embedding_cache.ttl_seconds == 86400
        assert config.semantic_cache.enabled is False
        assert config.semantic_cache.similarity_threshold == 0.92

    def test_load_from_dict(self):
        load_cache_config_from_dict({
            "enabled": True,
            "redis_url": "redis://localhost:6379",
            "embedding_cache": {"enabled": True, "ttl_seconds": 3600},
            "semantic_cache": {"enabled": True, "similarity_threshold": 0.85, "ttl_seconds": 7200},
        })
        config = get_cache_config()
        assert config.enabled is True
        assert config.redis_url == "redis://localhost:6379"
        assert config.embedding_cache.ttl_seconds == 3600
        assert config.semantic_cache.similarity_threshold == 0.85

    def test_reset(self):
        load_cache_config_from_dict({"enabled": True})
        reset_cache_config()
        assert get_cache_config().enabled is False


class TestRedisCache:
    @pytest.fixture(autouse=True)
    def _reset(self):
        reset_cache_config()
        yield
        reset_cache_config()

    @pytest.mark.anyio
    async def test_in_memory_get_set(self):
        load_cache_config_from_dict({"redis_url": ""})
        cache = RedisCache()
        assert not cache.is_available()

        await cache.set("key1", {"data": "hello"})
        result = await cache.get("key1")
        assert result == {"data": "hello"}

    @pytest.mark.anyio
    async def test_in_memory_miss(self):
        load_cache_config_from_dict({"redis_url": ""})
        cache = RedisCache()
        assert await cache.get("nonexistent") is None

    @pytest.mark.anyio
    async def test_in_memory_delete(self):
        load_cache_config_from_dict({"redis_url": ""})
        cache = RedisCache()
        await cache.set("key1", "value")
        await cache.delete("key1")
        assert await cache.get("key1") is None

    @pytest.mark.anyio
    async def test_in_memory_exists(self):
        load_cache_config_from_dict({"redis_url": ""})
        cache = RedisCache()
        await cache.set("key1", "value")
        assert await cache.exists("key1") is True
        assert await cache.exists("key2") is False

    @pytest.mark.anyio
    async def test_close(self):
        load_cache_config_from_dict({"redis_url": ""})
        cache = RedisCache()
        await cache.set("key1", "value")
        await cache.close()
        assert await cache.get("key1") is None


class TestEmbeddingCache:
    @pytest.fixture(autouse=True)
    def _reset(self):
        reset_cache_config()
        yield
        reset_cache_config()

    @pytest.mark.anyio
    async def test_cache_hit(self):
        load_cache_config_from_dict({"embedding_cache": {"enabled": True, "ttl_seconds": 3600}})
        ec = EmbeddingCache()
        emb = [0.1, 0.2, 0.3]
        await ec.set_embedding("hello world", emb)
        result = await ec.get_embedding("hello world")
        assert result == emb

    @pytest.mark.anyio
    async def test_cache_miss(self):
        load_cache_config_from_dict({"embedding_cache": {"enabled": True}})
        ec = EmbeddingCache()
        assert await ec.get_embedding("unknown text") is None

    @pytest.mark.anyio
    async def test_disabled(self):
        load_cache_config_from_dict({"embedding_cache": {"enabled": False}})
        ec = EmbeddingCache()
        await ec.set_embedding("text", [0.1])
        assert await ec.get_embedding("text") is None

    @pytest.mark.anyio
    async def test_different_texts_different_keys(self):
        load_cache_config_from_dict({"embedding_cache": {"enabled": True}})
        ec = EmbeddingCache()
        await ec.set_embedding("text A", [1.0, 0.0])
        await ec.set_embedding("text B", [0.0, 1.0])
        assert await ec.get_embedding("text A") == [1.0, 0.0]
        assert await ec.get_embedding("text B") == [0.0, 1.0]


class TestSemanticCache:
    @pytest.fixture(autouse=True)
    def _reset(self):
        reset_cache_config()
        yield
        reset_cache_config()

    def test_cosine_similarity_identical(self):
        assert _cosine_similarity([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == pytest.approx(1.0)

    def test_cosine_similarity_orthogonal(self):
        assert _cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)

    def test_cosine_similarity_different_lengths(self):
        assert _cosine_similarity([1.0], [1.0, 2.0]) == 0.0

    def test_cosine_similarity_zero_vector(self):
        assert _cosine_similarity([0.0, 0.0], [1.0, 2.0]) == 0.0

    @pytest.mark.anyio
    async def test_store_and_lookup_hit(self):
        load_cache_config_from_dict({
            "semantic_cache": {"enabled": True, "similarity_threshold": 0.9, "ttl_seconds": 3600},
        })
        sc = SemanticCache()
        emb = [0.5, 0.5, 0.5, 0.5]
        await sc.store("What is DeerFlow?", emb, "DeerFlow is an AI agent system.")

        result = await sc.lookup("What is DeerFlow?", emb)
        assert result == "DeerFlow is an AI agent system."

    @pytest.mark.anyio
    async def test_lookup_miss_different_embedding(self):
        load_cache_config_from_dict({
            "semantic_cache": {"enabled": True, "similarity_threshold": 0.9, "ttl_seconds": 3600},
        })
        sc = SemanticCache()
        await sc.store("query", [1.0, 0.0, 0.0], "response")

        result = await sc.lookup("query", [0.0, 1.0, 0.0])
        assert result is None

    @pytest.mark.anyio
    async def test_lookup_miss_no_entry(self):
        load_cache_config_from_dict({
            "semantic_cache": {"enabled": True, "similarity_threshold": 0.9},
        })
        sc = SemanticCache()
        assert await sc.lookup("unknown", [0.1, 0.2]) is None

    @pytest.mark.anyio
    async def test_disabled(self):
        load_cache_config_from_dict({"semantic_cache": {"enabled": False}})
        sc = SemanticCache()
        await sc.store("q", [0.1], "response")
        assert await sc.lookup("q", [0.1]) is None
