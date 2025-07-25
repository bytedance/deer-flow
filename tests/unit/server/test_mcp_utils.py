# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi import HTTPException

import src.server.mcp_utils as mcp_utils


@pytest.mark.asyncio
@patch("src.server.mcp_utils.ClientSession")
async def test__get_tools_from_client_session_success(mock_ClientSession):
    mock_read = AsyncMock()
    mock_write = AsyncMock()
    mock_callback = AsyncMock()
    mock_context_manager = AsyncMock()
    mock_context_manager.__aenter__.return_value = (
        mock_read,
        mock_write,
        mock_callback,
    )
    mock_context_manager.__aexit__.return_value = None

    mock_session = AsyncMock()
    mock_session.__aenter__.return_value = mock_session
    mock_session.__aexit__.return_value = None
    mock_session.initialize = AsyncMock()
    mock_tools_obj = MagicMock()
    mock_tools_obj.tools = ["tool1", "tool2"]
    mock_session.list_tools = AsyncMock(return_value=mock_tools_obj)
    mock_ClientSession.return_value = mock_session

    result = await mcp_utils._get_tools_from_client_session(
        mock_context_manager, timeout_seconds=5
    )
    assert result == ["tool1", "tool2"]
    mock_session.initialize.assert_awaited_once()
    mock_session.list_tools.assert_awaited_once()


@pytest.mark.asyncio
@patch("src.server.mcp_utils._get_tools_from_client_session", new_callable=AsyncMock)
@patch("src.server.mcp_utils.StdioServerParameters")
@patch("src.server.mcp_utils.stdio_client")
async def test_load_mcp_tools_stdio_success(
    mock_stdio_client, mock_StdioServerParameters, mock_get_tools
):
    mock_get_tools.return_value = ["toolA"]
    params = MagicMock()
    mock_StdioServerParameters.return_value = params
    mock_client = MagicMock()
    mock_stdio_client.return_value = mock_client

    result = await mcp_utils.load_mcp_tools(
        server_type="stdio",
        command="echo",
        args=["foo"],
        env={"FOO": "BAR"},
        timeout_seconds=3,
    )
    assert result == ["toolA"]
    mock_StdioServerParameters.assert_called_once_with(
        command="echo", args=["foo"], env={"FOO": "BAR"}
    )
    mock_stdio_client.assert_called_once_with(params)
    mock_get_tools.assert_awaited_once_with(mock_client, 3)


@pytest.mark.asyncio
async def test_load_mcp_tools_stdio_missing_command():
    with pytest.raises(HTTPException) as exc:
        await mcp_utils.load_mcp_tools(server_type="stdio")
    assert exc.value.status_code == 400
    assert "Command is required" in exc.value.detail


@pytest.mark.asyncio
@patch("src.server.mcp_utils._get_tools_from_client_session", new_callable=AsyncMock)
@patch("src.server.mcp_utils.sse_client")
async def test_load_mcp_tools_sse_success(mock_sse_client, mock_get_tools):
    mock_get_tools.return_value = ["toolB"]
    mock_client = MagicMock()
    mock_sse_client.return_value = mock_client

    result = await mcp_utils.load_mcp_tools(
        server_type="sse",
        url="http://localhost:1234",
        timeout_seconds=7,
    )
    assert result == ["toolB"]
    mock_sse_client.assert_called_once_with(url="http://localhost:1234")
    mock_get_tools.assert_awaited_once_with(mock_client, 7)


@pytest.mark.asyncio
async def test_load_mcp_tools_sse_missing_url():
    with pytest.raises(HTTPException) as exc:
        await mcp_utils.load_mcp_tools(server_type="sse")
    assert exc.value.status_code == 400
    assert "URL is required" in exc.value.detail


@pytest.mark.asyncio
async def test_load_mcp_tools_unsupported_type():
    with pytest.raises(HTTPException) as exc:
        await mcp_utils.load_mcp_tools(server_type="unknown")
    assert exc.value.status_code == 400
    assert "Unsupported server type" in exc.value.detail


@pytest.mark.asyncio
@patch("src.server.mcp_utils._get_tools_from_client_session", new_callable=AsyncMock)
@patch("src.server.mcp_utils.StdioServerParameters")
@patch("src.server.mcp_utils.stdio_client")
async def test_load_mcp_tools_exception_handling(
    mock_stdio_client, mock_StdioServerParameters, mock_get_tools
):
    mock_get_tools.side_effect = Exception("unexpected error")
    mock_StdioServerParameters.return_value = MagicMock()
    mock_stdio_client.return_value = MagicMock()

    with pytest.raises(HTTPException) as exc:
        await mcp_utils.load_mcp_tools(server_type="stdio", command="foo")
    assert exc.value.status_code == 500
    assert "unexpected error" in exc.value.detail
