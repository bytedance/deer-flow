"""Cache configuration — Redis, embedding cache, and semantic cache settings."""

from __future__ import annotations

from pydantic import BaseModel, Field


class EmbeddingCacheSettings(BaseModel):
    enabled: bool = Field(default=True, description="Enable embedding cache")
    ttl_seconds: int = Field(default=86400, description="TTL for cached embeddings in seconds")


class SemanticCacheSettings(BaseModel):
    enabled: bool = Field(default=False, description="Enable semantic (query) cache")
    similarity_threshold: float = Field(default=0.92, description="Cosine similarity threshold for cache hit")
    ttl_seconds: int = Field(default=3600, description="TTL for cached responses in seconds")


class CacheConfig(BaseModel):
    enabled: bool = Field(default=False, description="Enable caching layer")
    redis_url: str = Field(default="", description="Redis connection URL (optional; falls back to in-memory)")
    embedding_cache: EmbeddingCacheSettings = Field(default_factory=EmbeddingCacheSettings)
    semantic_cache: SemanticCacheSettings = Field(default_factory=SemanticCacheSettings)


_cache_config: CacheConfig | None = None


def get_cache_config() -> CacheConfig:
    global _cache_config
    if _cache_config is None:
        _cache_config = CacheConfig()
    return _cache_config


def load_cache_config_from_dict(data: dict) -> CacheConfig:
    global _cache_config
    _cache_config = CacheConfig.model_validate(data)
    return _cache_config


def reset_cache_config() -> None:
    global _cache_config
    _cache_config = None
