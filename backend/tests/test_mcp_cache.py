"""Tests for MCP tools cache staleness checks."""

from unittest.mock import patch

from src.mcp import cache


def _set_cache_state(*, initialized: bool, fingerprint: str | None) -> None:
    cache._cache_initialized = initialized
    cache._config_fingerprint = fingerprint
    cache._last_stale_check = 0.0


def test_cache_stale_when_config_appears_after_missing() -> None:
    _set_cache_state(initialized=True, fingerprint=None)

    with patch.object(cache, "_get_config_fingerprint", return_value="123"), patch("src.mcp.cache.time.monotonic", return_value=999.0):
        assert cache._is_cache_stale() is True


def test_cache_stale_when_config_disappears() -> None:
    _set_cache_state(initialized=True, fingerprint="123")

    with patch.object(cache, "_get_config_fingerprint", return_value=None), patch("src.mcp.cache.time.monotonic", return_value=999.0):
        assert cache._is_cache_stale() is True
