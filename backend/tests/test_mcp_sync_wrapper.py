import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from deerflow.config.extensions_config import ExtensionsConfig, McpServerConfig, McpToolStateConfig
from deerflow.mcp.tools import (
    _filter_tools_for_extensions_config,
    _make_sync_tool_wrapper,
    discover_mcp_tools_by_server,
    get_mcp_tools,
    split_prefixed_mcp_tool_name,
)


class MockArgs(BaseModel):
    x: int = Field(..., description="test param")


def test_mcp_tool_sync_wrapper_generation():
    """Test that get_mcp_tools correctly adds a sync func to async-only tools."""

    async def mock_coro(x: int):
        return f"result: {x}"

    mock_tool = StructuredTool(
        name="test_tool",
        description="test description",
        args_schema=MockArgs,
        func=None,  # Sync func is missing
        coroutine=mock_coro,
    )

    mock_client_instance = MagicMock()
    # Use AsyncMock for get_tools as it's awaited (Fix for Comment 5)
    mock_client_instance.get_tools = AsyncMock(return_value=[mock_tool])

    with (
        patch("langchain_mcp_adapters.client.MultiServerMCPClient", return_value=mock_client_instance),
        patch("deerflow.config.extensions_config.ExtensionsConfig.from_file"),
        patch("deerflow.mcp.tools.build_servers_config", return_value={"test-server": {}}),
        patch("deerflow.mcp.tools.get_initial_oauth_headers", new_callable=AsyncMock, return_value={}),
    ):
        # Run the async function manually with asyncio.run
        tools = asyncio.run(get_mcp_tools())

        assert len(tools) == 1
        patched_tool = tools[0]

        # Verify func is now populated
        assert patched_tool.func is not None

        # Verify it works (sync call)
        result = patched_tool.func(x=42)
        assert result == "result: 42"


def test_mcp_tool_sync_wrapper_in_running_loop():
    """Test the actual helper function from production code (Fix for Comment 1 & 3)."""

    async def mock_coro(x: int):
        await asyncio.sleep(0.01)
        return f"async_result: {x}"

    # Test the real helper function exported from deerflow.mcp.tools
    sync_func = _make_sync_tool_wrapper(mock_coro, "test_tool")

    async def run_in_loop():
        # This call should succeed due to ThreadPoolExecutor in the real helper
        return sync_func(x=100)

    # We run the async function that calls the sync func
    result = asyncio.run(run_in_loop())
    assert result == "async_result: 100"


def test_mcp_tool_sync_wrapper_exception_logging():
    """Test the actual helper's error logging (Fix for Comment 3)."""

    async def error_coro():
        raise ValueError("Tool failure")

    sync_func = _make_sync_tool_wrapper(error_coro, "error_tool")

    with patch("deerflow.mcp.tools.logger.error") as mock_log_error:
        with pytest.raises(ValueError, match="Tool failure"):
            sync_func()
        mock_log_error.assert_called_once()
        # Verify the tool name is in the log message
        assert "error_tool" in mock_log_error.call_args[0][0]


def test_split_prefixed_mcp_tool_name_prefers_longest_server_name():
    assert split_prefixed_mcp_tool_name(
        "github_enterprise_search_repositories",
        ["github", "github_enterprise"],
    ) == ("github_enterprise", "search_repositories")


def test_filter_tools_for_extensions_config_skips_disabled_tools():
    extensions = ExtensionsConfig(
        mcp_servers={
            "github": McpServerConfig(
                enabled=True,
                type="stdio",
                command="npx",
                tools={
                    "search_repositories": McpToolStateConfig(enabled=False),
                },
            ),
        },
        skills={},
    )
    tools = [
        SimpleNamespace(name="github_search_repositories", description="repo search"),
        SimpleNamespace(name="github_get_issue", description="issue lookup"),
    ]

    filtered = _filter_tools_for_extensions_config(tools, extensions)

    assert [tool.name for tool in filtered] == ["github_get_issue"]


@pytest.mark.asyncio
async def test_discover_mcp_tools_by_server_returns_raw_tool_names():
    extensions = ExtensionsConfig(
        mcp_servers={
            "github": McpServerConfig(enabled=True, type="stdio", command="npx"),
            "feishu": McpServerConfig(enabled=True, type="stdio", command="uvx"),
        },
        skills={},
    )

    with patch(
        "deerflow.mcp.tools._load_mcp_tools",
        new=AsyncMock(
            return_value=[
                SimpleNamespace(
                    name="github_search_repositories",
                    description="Search repositories",
                ),
                SimpleNamespace(
                    name="feishu_import_document",
                    description="Import a document",
                ),
            ],
        ),
    ):
        discovered = await discover_mcp_tools_by_server(extensions)

    assert discovered == {
        "feishu": {"import_document": "Import a document"},
        "github": {"search_repositories": "Search repositories"},
    }
