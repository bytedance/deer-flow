"""Timeout coverage for MCP server bring-up.

``tool_call_timeout`` only bounds ``session.call_tool()``. Discovery
(subprocess spawn + initialize + tools/list) and persistent-session
initialization have no bound on their own, so a hung stdio server would block
agent construction forever. These tests pin the ``session_init_timeout`` bound
on both stages and the per-server independence of the discovery timeout.
"""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from deerflow.config.extensions_config import ExtensionsConfig, McpServerConfig
from deerflow.constants import DEFAULT_MCP_SESSION_INIT_TIMEOUT
from deerflow.mcp.tools import _make_session_pool_tool, get_mcp_tools


class _Args(BaseModel):
    query: str = Field(..., description="query")


def _tool(name: str) -> StructuredTool:
    async def _call(query: str) -> str:
        return query

    return StructuredTool(
        name=name,
        description="Search",
        args_schema=_Args,
        coroutine=_call,
    )


def test_session_init_timeout_defaults_to_shared_constant() -> None:
    assert McpServerConfig().session_init_timeout == DEFAULT_MCP_SESSION_INIT_TIMEOUT
    assert McpServerConfig(session_init_timeout=None).session_init_timeout is None


@pytest.mark.asyncio
async def test_discovery_timeout_skips_hung_server_without_blocking_healthy_server() -> None:
    """A server whose discovery hangs must time out and be skipped, while a
    healthy server still contributes its tools."""
    extensions_config = ExtensionsConfig.model_validate(
        {
            "mcpServers": {
                "slow_server": {
                    "type": "stdio",
                    "command": "uvx",
                    "args": ["slow-mcp"],
                    "session_init_timeout": 0.05,
                },
                "fast_server": {
                    "type": "stdio",
                    "command": "uvx",
                    "args": ["fast-mcp"],
                    "session_init_timeout": 1.0,
                },
            }
        }
    )
    servers_config = {
        "slow_server": {"transport": "stdio", "command": "uvx", "args": ["slow-mcp"]},
        "fast_server": {"transport": "stdio", "command": "uvx", "args": ["fast-mcp"]},
    }

    class FakeClient:
        def __init__(
            self,
            connections,
            *,
            callbacks=None,
            tool_interceptors=None,
            tool_name_prefix=False,
        ) -> None:
            self.connections = connections
            self.callbacks = callbacks
            self.tool_interceptors = tool_interceptors or []
            self.tool_name_prefix = tool_name_prefix

        async def get_tools(self, *, server_name=None):
            if server_name == "slow_server":
                await asyncio.sleep(60)  # hung discovery
            # The real adapter returns server-prefixed tool names when
            # tool_name_prefix=True.
            return [_tool("fast_server_fast_search")]

    with (
        patch("deerflow.mcp.tools.ExtensionsConfig.from_file", return_value=extensions_config),
        patch("deerflow.mcp.tools.build_servers_config", return_value=servers_config),
        patch("deerflow.mcp.tools.get_initial_oauth_headers", new_callable=AsyncMock, return_value={}),
        patch("deerflow.mcp.tools.build_oauth_tool_interceptor", return_value=None),
        patch("langchain_mcp_adapters.client.MultiServerMCPClient", FakeClient),
        patch("langchain_mcp_adapters.tools.load_mcp_tools", new_callable=AsyncMock),
        patch("deerflow.mcp.tools._make_session_pool_tool", side_effect=lambda tool, *_args, **_kwargs: tool),
    ):
        # Without the discovery timeout the slow server would hang the call past
        # the 5s bound and this test would fail with TimeoutError.
        tools = await asyncio.wait_for(get_mcp_tools(), timeout=5)

    assert [tool.name for tool in tools] == ["fast_server_fast_search"]


@pytest.mark.asyncio
async def test_session_init_timeout_raises_when_session_creation_hangs(tmp_path, caplog) -> None:
    """A server that never finishes initialize() must not block the tool call,
    and the timeout must be visible in logs at the same level as discovery
    timeouts so operators can diagnose hung MCP sessions."""
    mock_pool = MagicMock()

    async def hanging_get_session(*_args, **_kwargs) -> None:
        await asyncio.sleep(60)

    mock_pool.get_session = hanging_get_session

    with (
        patch("deerflow.mcp.tools.get_session_pool", return_value=mock_pool),
        patch("deerflow.mcp.tools.get_paths", return_value=MagicMock()),
        patch(
            "deerflow.mcp.tools._prepare_stdio_workspace",
            return_value=(tmp_path, tmp_path / "tmp", {}),
        ),
        caplog.at_level(logging.WARNING, logger="deerflow.mcp.tools"),
    ):
        wrapped = _make_session_pool_tool(
            _tool("github_search"),
            "github",
            {"transport": "stdio", "command": "mcp-server", "args": []},
            session_init_timeout=0.05,
            tool_name_prefix=False,
        )
        loop = asyncio.get_running_loop()
        start = loop.time()
        with pytest.raises(TimeoutError):
            await wrapped.coroutine(query="repositories")
        # Bounds the regression: the timeout must fire promptly, not wait on the
        # hung session.
        assert loop.time() - start < 1.0

    timeout_warnings = [record for record in caplog.records if record.levelno == logging.WARNING and "timed out" in record.getMessage()]
    assert timeout_warnings, "session-init timeout must be logged like discovery timeouts"
    assert "github" in timeout_warnings[0].getMessage()


@pytest.mark.asyncio
async def test_discovery_timeout_from_sdk_with_opt_out_is_reported_without_logging_error(caplog) -> None:
    """With session_init_timeout opted out (None), a TimeoutError raised by
    discovery itself (e.g. an internal timeout inside the MCP SDK) must still
    be reported gracefully. The skip must go through the generic failure path —
    never through the "timed out (%.1fs)" format with a None value, which
    would raise inside the logging module and silently drop the warning."""
    extensions_config = ExtensionsConfig.model_validate(
        {
            "mcpServers": {
                "flaky_server": {
                    "type": "stdio",
                    "command": "uvx",
                    "args": ["flaky-mcp"],
                    "session_init_timeout": None,
                },
            }
        }
    )
    servers_config = {
        "flaky_server": {"transport": "stdio", "command": "uvx", "args": ["flaky-mcp"]},
    }

    class FakeClient:
        def __init__(
            self,
            connections,
            *,
            callbacks=None,
            tool_interceptors=None,
            tool_name_prefix=False,
        ) -> None:
            self.callbacks = callbacks
            self.tool_interceptors = tool_interceptors or []
            self.tool_name_prefix = tool_name_prefix

        async def get_tools(self, *, server_name=None):
            raise TimeoutError("internal SDK timeout")

    with (
        patch("deerflow.mcp.tools.ExtensionsConfig.from_file", return_value=extensions_config),
        patch("deerflow.mcp.tools.build_servers_config", return_value=servers_config),
        patch("deerflow.mcp.tools.get_initial_oauth_headers", new_callable=AsyncMock, return_value={}),
        patch("deerflow.mcp.tools.build_oauth_tool_interceptor", return_value=None),
        patch("langchain_mcp_adapters.client.MultiServerMCPClient", FakeClient),
        patch("langchain_mcp_adapters.tools.load_mcp_tools", new_callable=AsyncMock),
        caplog.at_level(logging.WARNING, logger="deerflow.mcp.tools"),
    ):
        tools = await get_mcp_tools()

    assert tools == []
    # getMessage() on every captured record must not raise: pre-fix, the only
    # record for this server was the broken "timed out (%.1fs)" % None format.
    assert any("tool discovery failed" in record.getMessage() for record in caplog.records)
    assert not any("timed out" in record.getMessage() for record in caplog.records)


def test_gateway_response_model_session_init_timeout_default_matches_runtime_config() -> None:
    """A server created via PUT /api/mcp/config without session_init_timeout
    must get the same bring-up timeout as one created in the config file —
    the response model's default feeds model_dump() into the persisted config."""
    from app.gateway.routers.mcp import McpServerConfigResponse

    assert McpServerConfigResponse.model_validate({}).session_init_timeout == DEFAULT_MCP_SESSION_INIT_TIMEOUT
    # An explicit null stays an explicit opt-out (no timeout).
    assert McpServerConfigResponse.model_validate({"session_init_timeout": None}).session_init_timeout is None


@pytest.mark.asyncio
async def test_session_init_timeout_does_not_block_fast_session(tmp_path) -> None:
    """A promptly-initialized session still completes the tool call."""
    mock_session = AsyncMock()
    mock_session.call_tool = AsyncMock(return_value=MagicMock(content=[], isError=False, structuredContent=None))
    mock_pool = MagicMock()
    mock_pool.get_session = AsyncMock(return_value=mock_session)

    with (
        patch("deerflow.mcp.tools.get_session_pool", return_value=mock_pool),
        patch("deerflow.mcp.tools.get_paths", return_value=MagicMock()),
        patch(
            "deerflow.mcp.tools._prepare_stdio_workspace",
            return_value=(tmp_path, tmp_path / "tmp", {}),
        ),
    ):
        wrapped = _make_session_pool_tool(
            _tool("github_search"),
            "github",
            {"transport": "stdio", "command": "mcp-server", "args": []},
            session_init_timeout=5.0,
            tool_name_prefix=False,
        )
        await wrapped.coroutine(query="repositories")

    mock_session.call_tool.assert_awaited_once_with("github_search", {"query": "repositories"})
