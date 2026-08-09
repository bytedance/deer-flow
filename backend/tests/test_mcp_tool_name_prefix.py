from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from app.gateway.routers.mcp import McpServerConfigResponse
from deerflow.config.extensions_config import ExtensionsConfig, McpServerConfig, McpToolOverride
from deerflow.mcp.tools import _make_session_pool_tool, get_mcp_tools
from deerflow.tools.mcp_metadata import get_mcp_routing


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


async def _load_openviking_tools(
    tool_overrides: dict[str, dict[str, object]],
    *,
    discovered_names: tuple[str, ...] = ("find", "forget"),
) -> tuple[list[StructuredTool], ExtensionsConfig]:
    extensions_config = ExtensionsConfig.model_validate(
        {
            "mcpServers": {
                "openviking": {
                    "type": "http",
                    "url": "http://127.0.0.1:1933/mcp",
                    "tools": tool_overrides,
                }
            }
        }
    )
    servers_config = {
        "openviking": {
            "transport": "http",
            "url": "http://127.0.0.1:1933/mcp",
        }
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
            assert server_name == "openviking"
            assert self.tool_name_prefix is True
            return [_tool(f"openviking_{name}") for name in discovered_names]

    with (
        patch("deerflow.mcp.tools.ExtensionsConfig.from_file", return_value=extensions_config),
        patch("deerflow.mcp.tools.build_servers_config", return_value=servers_config),
        patch("deerflow.mcp.tools.get_initial_oauth_headers", new_callable=AsyncMock, return_value={}),
        patch("deerflow.mcp.tools.build_oauth_tool_interceptor", return_value=None),
        patch("langchain_mcp_adapters.client.MultiServerMCPClient", FakeClient),
    ):
        tools = await get_mcp_tools()

    return tools, extensions_config


def test_mcp_tool_name_prefix_is_an_explicit_default_true_field() -> None:
    assert "tool_name_prefix" in McpServerConfig.model_fields
    assert McpServerConfig().tool_name_prefix is True
    assert McpServerConfig(tool_name_prefix=False).model_dump()["tool_name_prefix"] is False


def test_mcp_tool_override_enabled_is_an_explicit_default_true_field() -> None:
    assert "enabled" in McpToolOverride.model_fields
    assert McpToolOverride().enabled is True
    assert McpToolOverride(enabled=False).model_dump()["enabled"] is False


def test_gateway_mcp_config_preserves_tool_name_prefix() -> None:
    response = McpServerConfigResponse.model_validate(McpServerConfig(tool_name_prefix=False).model_dump())

    assert response.tool_name_prefix is False


@pytest.mark.asyncio
async def test_mcp_tool_name_prefix_can_be_disabled_per_server_without_disabling_stdio_pooling() -> None:
    extensions_config = ExtensionsConfig.model_validate(
        {
            "mcpServers": {
                "semantic_scholar": {
                    "type": "stdio",
                    "command": "uvx",
                    "args": ["s2-mcp-server"],
                    "tool_name_prefix": False,
                    "routing": {"mode": "prefer", "priority": 10},
                    "tools": {
                        "semantic_scholar_search_papers": {
                            "routing": {"priority": 99},
                        }
                    },
                },
                "github": {
                    "type": "http",
                    "url": "https://example.test/mcp",
                },
            }
        }
    )
    servers_config = {
        "semantic_scholar": {
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
        "semantic_scholar": _tool("semantic_scholar_search_papers"),
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
    semantic_scholar_tool = next(tool for tool in tools if tool.name == "semantic_scholar_search_papers")
    routing = get_mcp_routing(semantic_scholar_tool)
    assert routing is not None
    assert routing["priority"] == 99
    wrap_tool.assert_called_once()
    assert wrap_tool.call_args.args[1] == "semantic_scholar"
    assert wrap_tool.call_args.kwargs["tool_name_prefix"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_overrides", "expected_names"),
    [
        pytest.param({}, {"openviking_find", "openviking_forget"}, id="default_allows_discovered_tools"),
        pytest.param(
            {"forget": {"enabled": False}},
            {"openviking_find"},
            id="disabled_original_name_is_not_exposed",
        ),
    ],
)
async def test_mcp_tool_enabled_override_uses_original_name_before_prefixing(
    tool_overrides: dict[str, dict[str, bool]],
    expected_names: set[str],
) -> None:
    tools, _ = await _load_openviking_tools(tool_overrides)

    assert {tool.name for tool in tools} == expected_names


@pytest.mark.asyncio
async def test_mcp_tool_override_warns_when_original_name_is_not_discovered(caplog: pytest.LogCaptureFixture) -> None:
    tools, _ = await _load_openviking_tools({"forgot": {"enabled": False}})

    assert {tool.name for tool in tools} == {"openviking_find", "openviking_forget"}
    assert ("MCP server 'openviking' configured tool override 'forgot' did not match any discovered tool; offered original tool names: 'find', 'forget'") in caplog.messages


@pytest.mark.asyncio
async def test_mcp_tool_override_warning_escapes_discovered_names(caplog: pytest.LogCaptureFixture) -> None:
    tools, _ = await _load_openviking_tools(
        {"forgot": {"enabled": False}},
        discovered_names=("find\nforged-log-line",),
    )

    assert tools == []
    warning = next(message for message in caplog.messages if "did not match any discovered tool" in message)
    assert "offered original tool names: 'find\\nforged-log-line'" in warning
    assert "\n" not in warning


@pytest.mark.asyncio
async def test_mcp_tool_override_does_not_warn_for_discovered_original_name(caplog: pytest.LogCaptureFixture) -> None:
    tools, _ = await _load_openviking_tools({"forget": {"enabled": False}})

    assert {tool.name for tool in tools} == {"openviking_find"}
    assert not any("did not match any discovered tool" in message for message in caplog.messages)


@pytest.mark.asyncio
async def test_mcp_tool_override_does_not_warn_for_empty_discovery(caplog: pytest.LogCaptureFixture) -> None:
    tools, _ = await _load_openviking_tools(
        {"forgot": {"enabled": False}},
        discovered_names=(),
    )

    assert tools == []
    assert not any("did not match any discovered tool" in message for message in caplog.messages)


@pytest.mark.asyncio
async def test_mcp_tool_override_warns_for_unknown_field_without_disabling_tool(caplog: pytest.LogCaptureFixture) -> None:
    tools, extensions_config = await _load_openviking_tools({"forget": {"enable": False}})

    override = extensions_config.mcp_servers["openviking"].tools["forget"]
    assert override.enabled is True
    assert {tool.name for tool in tools} == {"openviking_find", "openviking_forget"}
    assert "MCP server 'openviking' tool override 'forget' has unknown field(s): enable" in caplog.messages


@pytest.mark.asyncio
async def test_unprefixed_stdio_tool_keeps_server_like_original_name(tmp_path: Path) -> None:
    """Pooling must not strip a prefix that belongs to the MCP tool itself."""
    original_tool = _tool("github_search")
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
            original_tool,
            "github",
            {"transport": "stdio", "command": "mcp-server", "args": []},
            tool_name_prefix=False,
        )
        await wrapped.coroutine(query="repositories")

    mock_session.call_tool.assert_awaited_once_with("github_search", {"query": "repositories"})
