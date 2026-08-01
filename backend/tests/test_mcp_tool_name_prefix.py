from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from app.gateway.routers.mcp import McpServerConfigResponse
from deerflow.config.extensions_config import ExtensionsConfig, McpServerConfig
from deerflow.mcp.tools import get_mcp_tools


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


def test_mcp_tool_name_prefix_is_an_explicit_default_true_field() -> None:
    assert "tool_name_prefix" in McpServerConfig.model_fields
    assert McpServerConfig().tool_name_prefix is True
    assert McpServerConfig(tool_name_prefix=False).model_dump()["tool_name_prefix"] is False


def test_gateway_mcp_config_preserves_tool_name_prefix() -> None:
    response = McpServerConfigResponse.model_validate(McpServerConfig(tool_name_prefix=False).model_dump())

    assert response.tool_name_prefix is False


@pytest.mark.asyncio
async def test_mcp_tool_name_prefix_can_be_disabled_per_server_without_disabling_stdio_pooling() -> None:
    extensions_config = ExtensionsConfig.model_validate(
        {
            "mcpServers": {
                "semantic-scholar": {
                    "type": "stdio",
                    "command": "uvx",
                    "args": ["s2-mcp-server"],
                    "tool_name_prefix": False,
                },
                "github": {
                    "type": "http",
                    "url": "https://example.test/mcp",
                },
            }
        }
    )
    servers_config = {
        "semantic-scholar": {
            "transport": "stdio",
            "command": "uvx",
            "args": ["s2-mcp-server"],
        },
        "github": {
            "transport": "http",
            "url": "https://example.test/mcp",
        },
    }
    raw_tools = {
        "semantic-scholar": _tool("semantic_scholar_search_papers"),
        "github": _tool("search_repositories"),
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
            tool = raw_tools[server_name]
            name = f"{server_name}_{tool.name}" if self.tool_name_prefix else tool.name
            return [_tool(name)]

    async def fake_load_mcp_tools(
        session,
        *,
        connection,
        callbacks=None,
        tool_interceptors=None,
        server_name=None,
        tool_name_prefix=False,
    ):
        assert session is None
        assert connection is servers_config[server_name]
        tool = raw_tools[server_name]
        name = f"{server_name}_{tool.name}" if tool_name_prefix else tool.name
        return [_tool(name)]

    with (
        patch("deerflow.mcp.tools.ExtensionsConfig.from_file", return_value=extensions_config),
        patch("deerflow.mcp.tools.build_servers_config", return_value=servers_config),
        patch("deerflow.mcp.tools.get_initial_oauth_headers", new_callable=AsyncMock, return_value={}),
        patch("deerflow.mcp.tools.build_oauth_tool_interceptor", return_value=None),
        patch("langchain_mcp_adapters.client.MultiServerMCPClient", FakeClient),
        patch("langchain_mcp_adapters.tools.load_mcp_tools", side_effect=fake_load_mcp_tools),
        patch("deerflow.mcp.tools._make_session_pool_tool", side_effect=lambda tool, *_args, **_kwargs: tool) as wrap_tool,
    ):
        tools = await get_mcp_tools()

    assert {tool.name for tool in tools} == {
        "semantic_scholar_search_papers",
        "github_search_repositories",
    }
    wrap_tool.assert_called_once()
    assert wrap_tool.call_args.args[1] == "semantic-scholar"
