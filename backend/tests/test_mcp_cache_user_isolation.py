"""Tests for user-scoped MCP tool discovery cache."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from langchain_core.tools import tool

from deerflow.mcp.cache import get_cached_mcp_tools, reset_mcp_tools_cache


@tool
def _tool_a(value: str) -> str:
    """A fake user-a MCP tool."""
    return value


@tool
def _tool_b(value: str) -> str:
    """A fake user-b MCP tool."""
    return value


def test_mcp_tool_cache_is_scoped_by_user_id():
    reset_mcp_tools_cache()
    calls: list[str | None] = []

    async def _fake_get_mcp_tools(user_id: str | None = None):
        calls.append(user_id)
        return [_tool_a] if user_id == "user-a" else [_tool_b]

    try:
        with patch("deerflow.mcp.tools.get_mcp_tools", new=AsyncMock(side_effect=_fake_get_mcp_tools)):
            user_a_first = get_cached_mcp_tools(user_id="user-a")
            user_b_first = get_cached_mcp_tools(user_id="user-b")
            user_a_second = get_cached_mcp_tools(user_id="user-a")

        assert [tool.name for tool in user_a_first] == ["_tool_a"]
        assert [tool.name for tool in user_b_first] == ["_tool_b"]
        assert user_a_second is user_a_first
        assert calls == ["user-a", "user-b"]
    finally:
        reset_mcp_tools_cache()
