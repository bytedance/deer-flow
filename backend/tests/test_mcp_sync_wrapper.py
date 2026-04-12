import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from deerflow.config.context_management_config import ContextManagementConfig, ToolResultBudgetConfig, set_context_management_config
from deerflow.mcp.tools import _make_sync_tool_wrapper, get_mcp_tools


class MockArgs(BaseModel):
    x: int = Field(..., description="test param")


@pytest.fixture(autouse=True)
def _reset_context_management_config():
    set_context_management_config(ContextManagementConfig())
    yield
    set_context_management_config(ContextManagementConfig())


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


def test_get_mcp_tools_budgets_oversized_structured_results(tmp_path):
    set_context_management_config(
        ContextManagementConfig(
            tool_result_budget=ToolResultBudgetConfig(
                enabled=True,
                externalize_min_chars=20,
                preview_head_chars=10,
                preview_tail_chars=6,
            )
        )
    )

    async def mock_coro(x: int):
        return {"payload": "x" * 120, "index": x}

    mock_tool = StructuredTool(
        name="x-reader_read_url",
        description="test description",
        args_schema=MockArgs,
        func=None,
        coroutine=mock_coro,
    )
    mock_client_instance = MagicMock()
    mock_client_instance.get_tools = AsyncMock(return_value=[mock_tool])

    with (
        patch("langchain_mcp_adapters.client.MultiServerMCPClient", return_value=mock_client_instance),
        patch("deerflow.config.extensions_config.ExtensionsConfig.from_file"),
        patch("deerflow.mcp.tools.build_servers_config", return_value={"x-reader": {}}),
        patch("deerflow.mcp.tools.get_initial_oauth_headers", new_callable=AsyncMock, return_value={}),
        patch("deerflow.mcp.tools.resolve_thread_data_from_config", return_value={"outputs_path": str(tmp_path / "outputs")}),
    ):
        tools = asyncio.run(get_mcp_tools())
        result = tools[0].func(x=7)

    assert isinstance(result, str)
    assert "Full x-reader_read_url output saved to /mnt/user-data/outputs/.context/tool-results/" in result
    saved_files = list((tmp_path / "outputs" / ".context" / "tool-results").glob("x-reader_read_url-*.txt"))
    assert len(saved_files) == 1


def test_get_mcp_tools_preserves_content_and_artifact_tuple_results(tmp_path):
    set_context_management_config(
        ContextManagementConfig(
            tool_result_budget=ToolResultBudgetConfig(
                enabled=True,
                externalize_min_chars=20,
                preview_head_chars=10,
                preview_tail_chars=6,
            )
        )
    )

    artifact = {"url": "https://example.com", "status": 200}

    async def mock_coro(x: int):
        return ("y" * 120, artifact | {"index": x})

    mock_tool = StructuredTool(
        name="x-reader_read_url",
        description="test description",
        args_schema=MockArgs,
        func=None,
        coroutine=mock_coro,
        response_format="content_and_artifact",
    )
    mock_client_instance = MagicMock()
    mock_client_instance.get_tools = AsyncMock(return_value=[mock_tool])

    with (
        patch("langchain_mcp_adapters.client.MultiServerMCPClient", return_value=mock_client_instance),
        patch("deerflow.config.extensions_config.ExtensionsConfig.from_file"),
        patch("deerflow.mcp.tools.build_servers_config", return_value={"x-reader": {}}),
        patch("deerflow.mcp.tools.get_initial_oauth_headers", new_callable=AsyncMock, return_value={}),
        patch("deerflow.mcp.tools.resolve_thread_data_from_config", return_value={"outputs_path": str(tmp_path / "outputs")}),
    ):
        tools = asyncio.run(get_mcp_tools())
        result = tools[0].func(x=7)

    assert isinstance(result, tuple)
    assert len(result) == 2
    assert isinstance(result[0], str)
    assert "Full x-reader_read_url output saved to /mnt/user-data/outputs/.context/tool-results/" in result[0]
    assert result[1] == {"url": "https://example.com", "status": 200, "index": 7}
    saved_files = list((tmp_path / "outputs" / ".context" / "tool-results").glob("x-reader_read_url-*.txt"))
    assert len(saved_files) == 1
