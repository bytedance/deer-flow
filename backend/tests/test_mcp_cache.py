"""Tests for MCP tools cache: mtime tracking, staleness detection, lazy initialization, and reset."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.mcp.cache import (
    _get_config_mtime,
    _is_cache_stale,
    get_cached_mcp_tools,
    initialize_mcp_tools,
    reset_mcp_tools_cache,
)


@pytest.fixture(autouse=True)
def _reset_cache():
    """Reset MCP cache before and after each test."""
    reset_mcp_tools_cache()
    yield
    reset_mcp_tools_cache()


# ---------------------------------------------------------------------------
# _get_config_mtime
# ---------------------------------------------------------------------------
class TestGetConfigMtime:
    """Tests for _get_config_mtime()."""

    @patch("src.mcp.cache.ExtensionsConfig", create=True)
    def test_returns_mtime_when_file_exists(self, mock_ext_cls, tmp_path: Path) -> None:
        config_file = tmp_path / "extensions.yaml"
        config_file.write_text("mcp_servers: []")
        mock_ext_cls.resolve_config_path.return_value = config_file

        with patch.dict("sys.modules", {"src.config.extensions_config": MagicMock(ExtensionsConfig=mock_ext_cls)}):
            result = _get_config_mtime()

        assert isinstance(result, float)
        assert result > 0

    @patch("src.mcp.cache.ExtensionsConfig", create=True)
    def test_returns_none_when_no_file(self, mock_ext_cls) -> None:
        mock_ext_cls.resolve_config_path.return_value = None

        with patch.dict("sys.modules", {"src.config.extensions_config": MagicMock(ExtensionsConfig=mock_ext_cls)}):
            result = _get_config_mtime()

        assert result is None

    @patch("src.mcp.cache.ExtensionsConfig", create=True)
    def test_returns_none_when_path_not_exists(self, mock_ext_cls, tmp_path: Path) -> None:
        mock_ext_cls.resolve_config_path.return_value = tmp_path / "nonexistent.yaml"

        with patch.dict("sys.modules", {"src.config.extensions_config": MagicMock(ExtensionsConfig=mock_ext_cls)}):
            result = _get_config_mtime()

        assert result is None


# ---------------------------------------------------------------------------
# _is_cache_stale
# ---------------------------------------------------------------------------
class TestIsCacheStale:
    """Tests for _is_cache_stale()."""

    def test_not_stale_when_not_initialized(self) -> None:
        """Cache is not stale when it hasn't been initialized yet."""
        assert _is_cache_stale() is False

    @patch("src.mcp.cache._get_config_mtime")
    def test_not_stale_when_mtime_unchanged(self, mock_mtime) -> None:
        import src.mcp.cache as cache_mod

        cache_mod._cache_initialized = True
        cache_mod._config_mtime = 1000.0
        mock_mtime.return_value = 1000.0

        assert _is_cache_stale() is False

    @patch("src.mcp.cache._get_config_mtime")
    def test_stale_when_mtime_increased(self, mock_mtime) -> None:
        import src.mcp.cache as cache_mod

        cache_mod._cache_initialized = True
        cache_mod._config_mtime = 1000.0
        mock_mtime.return_value = 2000.0

        assert _is_cache_stale() is True

    @patch("src.mcp.cache._get_config_mtime")
    def test_not_stale_when_original_mtime_none(self, mock_mtime) -> None:
        import src.mcp.cache as cache_mod

        cache_mod._cache_initialized = True
        cache_mod._config_mtime = None
        mock_mtime.return_value = 1000.0

        assert _is_cache_stale() is False

    @patch("src.mcp.cache._get_config_mtime")
    def test_not_stale_when_current_mtime_none(self, mock_mtime) -> None:
        import src.mcp.cache as cache_mod

        cache_mod._cache_initialized = True
        cache_mod._config_mtime = 1000.0
        mock_mtime.return_value = None

        assert _is_cache_stale() is False


# ---------------------------------------------------------------------------
# initialize_mcp_tools
# ---------------------------------------------------------------------------
class TestInitializeMcpTools:
    """Tests for initialize_mcp_tools()."""

    @pytest.mark.asyncio
    @patch("src.mcp.cache._get_config_mtime", return_value=1234.0)
    async def test_initializes_and_caches(self, mock_mtime) -> None:
        import src.mcp.cache as cache_mod

        fake_tools = [MagicMock(name="tool1"), MagicMock(name="tool2")]

        async def mock_by_server():
            return {"server_a": fake_tools}

        mock_get_by_server = AsyncMock(side_effect=mock_by_server)
        # Need to patch the lazy import
        with patch.dict("sys.modules", {"src.mcp.tools": MagicMock(get_mcp_tools_by_server=mock_get_by_server)}):
            # Reset the lock for this test
            cache_mod._initialization_lock = asyncio.Lock()

            result = await initialize_mcp_tools()

        assert len(result) == 2
        assert cache_mod._cache_initialized is True
        assert cache_mod._config_mtime == 1234.0

    @pytest.mark.asyncio
    async def test_returns_cached_on_second_call(self) -> None:
        import src.mcp.cache as cache_mod

        fake_tools = [MagicMock(name="cached")]
        cache_mod._mcp_tools_cache = fake_tools
        cache_mod._cache_initialized = True
        cache_mod._initialization_lock = asyncio.Lock()

        result = await initialize_mcp_tools()
        assert result is fake_tools


# ---------------------------------------------------------------------------
# reset_mcp_tools_cache
# ---------------------------------------------------------------------------
class TestResetMcpToolsCache:
    """Tests for reset_mcp_tools_cache()."""

    def test_reset_clears_state(self) -> None:
        import src.mcp.cache as cache_mod

        cache_mod._mcp_tools_cache = [MagicMock()]
        cache_mod._cache_initialized = True
        cache_mod._config_mtime = 999.0

        reset_mcp_tools_cache()

        assert cache_mod._mcp_tools_cache is None
        assert cache_mod._cache_initialized is False
        assert cache_mod._config_mtime is None


# ---------------------------------------------------------------------------
# get_cached_mcp_tools
# ---------------------------------------------------------------------------
class TestGetCachedMcpTools:
    """Tests for get_cached_mcp_tools()."""

    def test_returns_cached_tools_when_initialized(self) -> None:
        import src.mcp.cache as cache_mod

        fake_tools = [MagicMock(name="t1")]
        cache_mod._mcp_tools_cache = fake_tools
        cache_mod._cache_initialized = True

        result = get_cached_mcp_tools()
        assert result is fake_tools

    def test_returns_empty_list_when_none_cached(self) -> None:
        import src.mcp.cache as cache_mod

        cache_mod._mcp_tools_cache = None
        cache_mod._cache_initialized = True

        result = get_cached_mcp_tools()
        assert result == []

    @patch("src.mcp.cache._is_cache_stale", return_value=True)
    @patch("src.mcp.cache._background_refresh")
    def test_serves_stale_and_triggers_background_refresh(self, mock_refresh, mock_stale) -> None:
        """When cache is stale, returns cached tools and triggers background refresh."""
        import src.mcp.cache as cache_mod

        fake_tools = [MagicMock(name="stale_tool")]
        cache_mod._cache_initialized = True
        cache_mod._mcp_tools_cache = fake_tools

        # Patch threading.Thread to avoid actually spawning a thread
        with patch("src.mcp.cache.threading") as mock_threading:
            result = get_cached_mcp_tools()

        # Should return stale cache immediately
        assert result is fake_tools
        # Should have started a background thread
        mock_threading.Thread.assert_called_once()
        mock_threading.Thread.return_value.start.assert_called_once()

    @patch("src.mcp.cache.initialize_mcp_tools", new_callable=AsyncMock)
    def test_returns_empty_on_init_failure(self, mock_init) -> None:
        """When lazy initialization fails, returns empty list."""
        import src.mcp.cache as cache_mod

        cache_mod._cache_initialized = False
        mock_init.side_effect = Exception("init failed")

        result = get_cached_mcp_tools()
        assert result == []
