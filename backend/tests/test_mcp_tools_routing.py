"""Regression tests for ``get_mcp_tools`` server routing.

Covers the prefix-collision bug (#3811): when one server name is a prefix of
another (e.g. ``web`` and ``web_scraper``), tools from the longer-named server
must still be pooled under their own server, not the shorter-named one.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.tools import StructuredTool

from deerflow.mcp import tools as mcp_tools


def _make_fake_tool(name: str) -> StructuredTool:
    """Build a minimal LangChain tool with the given (already-prefixed) name."""
    return StructuredTool(
        name=name,
        description=f"fake tool {name}",
        args_schema=None,
        coroutine=AsyncMock(return_value="ok"),
    )


@pytest.mark.asyncio
async def test_prefix_collision_routes_each_tool_to_its_own_server():
    """``web_scraper_*`` tools must pool under ``web_scraper``, not ``web``.

    With the old re-derivation logic (``tool.name.startswith(f"{name}_")`` with
    the first match winning), a ``web_scraper_search`` tool matched ``web_``
    first because ``web`` precedes ``web_scraper`` in insertion order. The tool
    was then wrapped with the wrong server name, so the persistent-session
    wrapper stripped the wrong prefix and the call failed with "tool not found".
    """
    web_tool = _make_fake_tool("web_search")
    scraper_tool = _make_fake_tool("web_scraper_search")

    fake_extensions = MagicMock()
    fake_extensions.model_extra = None

    fake_servers_config = {
        "web": {"transport": "stdio", "command": "echo", "args": ["web"]},
        "web_scraper": {"transport": "stdio", "command": "echo", "args": ["scraper"]},
    }

    captured_calls: list[tuple[str, str]] = []

    def fake_wrap(tool, server_name, connection, interceptors):  # noqa: ANN001
        # Record (tool_name, server_name_passed_to_wrapper) for assertion.
        captured_calls.append((tool.name, server_name))
        # Return the tool unchanged; we only care about routing here.
        return tool

    async def fake_load(server_name):  # noqa: ANN202
        return {"web": [web_tool], "web_scraper": [scraper_tool]}[server_name]

    fake_client = MagicMock()
    fake_client.get_tools = MagicMock(side_effect=fake_load)

    with (
        patch.object(mcp_tools.ExtensionsConfig, "from_file", return_value=fake_extensions),
        patch.object(mcp_tools, "build_servers_config", return_value=fake_servers_config),
        patch.object(mcp_tools, "get_initial_oauth_headers", return_value={}),
        patch.object(mcp_tools, "build_oauth_tool_interceptor", return_value=None),
        patch("langchain_mcp_adapters.client.MultiServerMCPClient", return_value=fake_client),
        patch.object(mcp_tools, "_make_session_pool_tool", side_effect=fake_wrap),
        patch.object(mcp_tools, "make_sync_tool_wrapper", lambda coro, name: coro),
    ):
        result = await mcp_tools.get_mcp_tools()

    # Both tools are returned.
    assert {t.name for t in result} == {"web_search", "web_scraper_search"}

    # Each tool was routed to its authoritative server, not the prefix-matched one.
    assert ("web_search", "web") in captured_calls
    assert ("web_scraper_search", "web_scraper") in captured_calls
    # And the bug-shaped routing is gone.
    assert ("web_scraper_search", "web") not in captured_calls
