"""Unit tests for MCP tools by-server grouping."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class StubInput(BaseModel):
    query: str = Field(description="Query string")


class StubTool(BaseTool):
    """Minimal tool stub for testing."""

    name: str = "stub"
    description: str = "A stub tool"
    args_schema: type[BaseModel] | None = None

    def _run(self, **kwargs):
        return "ok"


def _make_stub(name: str, description: str = "A tool") -> StubTool:
    return StubTool(name=name, description=description)


# ---------------------------------------------------------------------------
# get_mcp_tools_by_server
# ---------------------------------------------------------------------------


class TestGetMcpToolsByServer:
    @pytest.fixture(autouse=True)
    def _reset_cache(self):
        """Reset MCP tools cache before each test."""
        from src.mcp.cache import reset_mcp_tools_cache

        reset_mcp_tools_cache()
        yield
        reset_mcp_tools_cache()

    @pytest.mark.asyncio
    async def test_returns_per_server_dict(self):
        """Tools should be grouped by their origin server."""
        tools_a = [_make_stub("tool_a1"), _make_stub("tool_a2")]
        tools_b = [_make_stub("tool_b1")]

        async def mock_load(server_name, server_params, interceptors):
            if server_name == "server_a":
                return tools_a
            elif server_name == "server_b":
                return tools_b
            return []

        mock_config = MagicMock()
        mock_servers_config = {
            "server_a": {"transport": "stdio", "command": "echo"},
            "server_b": {"transport": "stdio", "command": "echo"},
        }

        with (
            patch("src.mcp.tools.ExtensionsConfig.from_file", return_value=mock_config),
            patch("src.mcp.tools.build_servers_config", return_value=mock_servers_config),
            patch("src.mcp.tools.get_initial_oauth_headers", new_callable=AsyncMock, return_value={}),
            patch("src.mcp.tools.build_oauth_tool_interceptor", return_value=None),
            patch("src.mcp.tools._load_server_tools", side_effect=mock_load),
        ):
            from src.mcp.tools import get_mcp_tools_by_server

            result = await get_mcp_tools_by_server()

        assert "server_a" in result
        assert len(result["server_a"]) == 2
        assert "server_b" in result
        assert len(result["server_b"]) == 1

    @pytest.mark.asyncio
    async def test_empty_servers_excluded(self):
        """Servers that return no tools should not appear in the result."""

        async def mock_load(server_name, server_params, interceptors):
            if server_name == "good":
                return [_make_stub("tool_1")]
            return []  # empty

        mock_config = MagicMock()
        mock_servers_config = {
            "good": {"transport": "stdio", "command": "echo"},
            "empty": {"transport": "stdio", "command": "echo"},
        }

        with (
            patch("src.mcp.tools.ExtensionsConfig.from_file", return_value=mock_config),
            patch("src.mcp.tools.build_servers_config", return_value=mock_servers_config),
            patch("src.mcp.tools.get_initial_oauth_headers", new_callable=AsyncMock, return_value={}),
            patch("src.mcp.tools.build_oauth_tool_interceptor", return_value=None),
            patch("src.mcp.tools._load_server_tools", side_effect=mock_load),
        ):
            from src.mcp.tools import get_mcp_tools_by_server

            result = await get_mcp_tools_by_server()

        assert "good" in result
        assert "empty" not in result

    @pytest.mark.asyncio
    async def test_no_servers_configured(self):
        """Should return empty dict when no servers are configured."""
        mock_config = MagicMock()

        with (
            patch("src.mcp.tools.ExtensionsConfig.from_file", return_value=mock_config),
            patch("src.mcp.tools.build_servers_config", return_value={}),
        ):
            from src.mcp.tools import get_mcp_tools_by_server

            result = await get_mcp_tools_by_server()

        assert result == {}


# ---------------------------------------------------------------------------
# Cache: get_cached_mcp_tools_by_server
# ---------------------------------------------------------------------------


class TestCachedMcpToolsByServer:
    @pytest.fixture(autouse=True)
    def _reset_cache(self):
        from src.mcp.cache import reset_mcp_tools_cache

        reset_mcp_tools_cache()
        yield
        reset_mcp_tools_cache()

    @pytest.mark.asyncio
    async def test_cache_populated_after_initialization(self):
        """After initialize_mcp_tools, by-server cache should be populated."""
        import src.mcp.cache as cache_mod

        tools_x = [_make_stub("x1"), _make_stub("x2")]

        async def mock_by_server():
            return {"server_x": tools_x}

        cache_mod._initialization_lock = asyncio.Lock()

        with patch("src.mcp.tools.get_mcp_tools_by_server", side_effect=mock_by_server):
            from src.mcp.cache import initialize_mcp_tools

            await initialize_mcp_tools()

        from src.mcp.cache import get_cached_mcp_tools_by_server

        result = get_cached_mcp_tools_by_server()
        assert "server_x" in result
        assert len(result["server_x"]) == 2

    @pytest.mark.asyncio
    async def test_flat_cache_also_populated(self):
        """initialize_mcp_tools should populate both flat and by-server caches."""
        import src.mcp.cache as cache_mod

        tools_y = [_make_stub("y1")]

        async def mock_by_server():
            return {"server_y": tools_y}

        cache_mod._initialization_lock = asyncio.Lock()

        with patch("src.mcp.tools.get_mcp_tools_by_server", side_effect=mock_by_server):
            from src.mcp.cache import initialize_mcp_tools

            await initialize_mcp_tools()

        from src.mcp.cache import get_cached_mcp_tools

        flat = get_cached_mcp_tools()
        assert len(flat) == 1
        assert flat[0].name == "y1"

    def test_empty_when_not_initialized(self):
        """Before initialization, by-server cache should trigger lazy init or return empty."""
        from src.mcp.cache import get_cached_mcp_tools_by_server

        async def mock_by_server():
            return {}

        with patch("src.mcp.tools.get_mcp_tools_by_server", side_effect=mock_by_server):
            result = get_cached_mcp_tools_by_server()
        assert result == {}
