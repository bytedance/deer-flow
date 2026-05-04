"""Tests for RateLimitConfig — defaults, loading, and singleton lifecycle."""

import pytest

from deerflow.config.rate_limit_config import (
    RateLimitConfig,
    get_rate_limit_config,
    load_rate_limit_config_from_dict,
    reset_rate_limit_config,
)


class TestRateLimitConfigDefaults:
    def test_default_disabled(self):
        reset_rate_limit_config()
        config = get_rate_limit_config()
        assert config.enabled is False
        assert config.backend == "memory"
        assert config.global_per_minute == 1000
        assert config.tenant_per_minute == 100
        assert config.user_per_minute == 60
        assert config.llm_calls_per_minute == 50
        assert config.tokens_per_minute == 100000
        assert config.endpoints == []

    def test_default_redis_url_empty(self):
        reset_rate_limit_config()
        config = get_rate_limit_config()
        assert config.redis_url == ""


class TestRateLimitConfigLoading:
    def test_load_from_dict(self):
        data = {
            "enabled": True,
            "backend": "redis",
            "redis_url": "redis://localhost:6379",
            "global_per_minute": 500,
            "tenant_per_minute": 50,
            "user_per_minute": 30,
            "llm_calls_per_minute": 25,
            "tokens_per_minute": 50000,
            "endpoints": [{"path": "/api/rag/search", "limit": "30/minute"}],
        }
        config = load_rate_limit_config_from_dict(data)
        assert config.enabled is True
        assert config.backend == "redis"
        assert config.redis_url == "redis://localhost:6379"
        assert config.global_per_minute == 500
        assert config.tenant_per_minute == 50
        assert len(config.endpoints) == 1
        assert config.endpoints[0].path == "/api/rag/search"
        assert config.endpoints[0].limit == "30/minute"

    def test_load_partial_dict_fills_defaults(self):
        config = load_rate_limit_config_from_dict({"enabled": True})
        assert config.enabled is True
        assert config.backend == "memory"

    def test_get_returns_loaded_config(self):
        load_rate_limit_config_from_dict({"enabled": True, "global_per_minute": 99})
        config = get_rate_limit_config()
        assert config.enabled is True
        assert config.global_per_minute == 99


class TestRateLimitConfigSingleton:
    def test_reset_clears_cache(self):
        load_rate_limit_config_from_dict({"enabled": True})
        reset_rate_limit_config()
        config = get_rate_limit_config()
        assert config.enabled is False

    def test_get_creates_default_when_none_loaded(self):
        reset_rate_limit_config()
        config = get_rate_limit_config()
        assert isinstance(config, RateLimitConfig)
        assert config.enabled is False
