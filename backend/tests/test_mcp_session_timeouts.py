"""Timeout coverage for MCP server bring-up.

``tool_call_timeout`` only bounds ``session.call_tool()``. Discovery
(subprocess spawn + initialize + tools/list) and persistent-session
initialization have no bound on their own, so a hung stdio server would block
agent construction forever. These tests pin the ``session_init_timeout`` bound
on both stages and the per-server independence of the discovery timeout.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import FastAPI
from langchain_core.tools import StructuredTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from pydantic import BaseModel, Field, ValidationError

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


@pytest.mark.parametrize("field_name", ["session_init_timeout", "tool_call_timeout"])
@pytest.mark.parametrize("invalid_timeout", [0, -1, float("inf"), float("-inf"), float("nan")])
def test_runtime_mcp_timeout_must_be_finite_and_positive(field_name: str, invalid_timeout: float) -> None:
    with pytest.raises(ValidationError):
        McpServerConfig.model_validate({field_name: invalid_timeout})


@pytest.mark.parametrize("field_name", ["session_init_timeout", "tool_call_timeout"])
def test_runtime_mcp_timeout_accepts_none_and_coerces_positive_numeric_strings(field_name: str) -> None:
    assert getattr(McpServerConfig.model_validate({field_name: None}), field_name) is None
    assert getattr(McpServerConfig.model_validate({field_name: "0.25"}), field_name) == 0.25


@pytest.mark.asyncio
@pytest.mark.parametrize("field_name", ["session_init_timeout", "tool_call_timeout"])
async def test_invalid_timeout_cannot_reach_mcp_tool_assembly(tmp_path, monkeypatch, field_name: str) -> None:
    config_path = tmp_path / "extensions_config.json"
    config_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "healthy": {
                        "type": "http",
                        "url": "https://example.invalid/mcp",
                        field_name: 0,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(config_path))
    responsive_discovery = AsyncMock(return_value=[_tool("healthy_healthy_search")])
    monkeypatch.setattr(MultiServerMCPClient, "get_tools", responsive_discovery)

    with pytest.raises(RuntimeError, match=field_name):
        await get_mcp_tools()

    responsive_discovery.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("session_init_timeout", [0.01, None])
async def test_valid_session_timeout_preserves_real_mcp_tool_assembly(tmp_path, monkeypatch, session_init_timeout: float | None) -> None:
    config_path = tmp_path / "extensions_config.json"
    config_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "healthy": {
                        "type": "http",
                        "url": "https://example.invalid/mcp",
                        "session_init_timeout": session_init_timeout,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(config_path))
    responsive_discovery = AsyncMock(return_value=[_tool("healthy_healthy_search")])
    monkeypatch.setattr(MultiServerMCPClient, "get_tools", responsive_discovery)

    tools = await get_mcp_tools()

    assert [tool.name for tool in tools] == ["healthy_healthy_search"]
    responsive_discovery.assert_awaited_once_with(server_name="healthy")


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


@pytest.mark.parametrize("field_name", ["session_init_timeout", "tool_call_timeout"])
@pytest.mark.parametrize("invalid_timeout", [0, -1, float("inf"), float("-inf"), float("nan")])
def test_gateway_mcp_timeout_must_be_finite_and_positive(field_name: str, invalid_timeout: float) -> None:
    from app.gateway.routers.mcp import McpServerConfigResponse

    with pytest.raises(ValidationError):
        McpServerConfigResponse.model_validate({field_name: invalid_timeout})


@pytest.mark.parametrize("field_name", ["session_init_timeout", "tool_call_timeout"])
def test_gateway_mcp_timeout_accepts_none_and_coerces_positive_numeric_strings(field_name: str) -> None:
    from app.gateway.routers.mcp import McpServerConfigResponse

    assert getattr(McpServerConfigResponse.model_validate({field_name: None}), field_name) is None
    assert getattr(McpServerConfigResponse.model_validate({field_name: "0.25"}), field_name) == 0.25


@pytest.mark.parametrize("field_name", ["session_init_timeout", "tool_call_timeout"])
@pytest.mark.parametrize("invalid_timeout", [0, -1])
@pytest.mark.asyncio
async def test_put_mcp_config_rejects_invalid_timeout_without_persisting(tmp_path, monkeypatch, field_name: str, invalid_timeout: int) -> None:
    from app.gateway.routers import mcp as mcp_router

    config_path = tmp_path / "extensions_config.json"
    original = b'{"mcpServers":{"sentinel":{"type":"http","url":"https://example.invalid/old"}},"skills":{}}\n'
    config_path.write_bytes(original)
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(config_path))

    app = FastAPI()
    app.include_router(mcp_router.router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.put(
            "/api/mcp/config",
            json={
                "mcp_servers": {
                    "healthy": {
                        "type": "http",
                        "url": "https://example.invalid/mcp",
                        field_name: invalid_timeout,
                    }
                }
            },
        )

    assert response.status_code == 422
    assert config_path.read_bytes() == original


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


@pytest.mark.asyncio
async def test_positive_tool_call_timeout_reaches_stdio_call(tmp_path) -> None:
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
            tool_call_timeout=0.25,
            session_init_timeout=5.0,
            tool_name_prefix=False,
        )
        await wrapped.coroutine(query="repositories")

    mock_session.call_tool.assert_awaited_once_with(
        "github_search",
        {"query": "repositories"},
        read_timeout_seconds=timedelta(seconds=0.25),
    )
