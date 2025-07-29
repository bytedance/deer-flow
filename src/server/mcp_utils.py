# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import logging
from datetime import timedelta
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamablehttp_client

logger = logging.getLogger(__name__)


async def _get_tools_from_client_session(
    client_context_manager: Any, timeout_seconds: int = 10
) -> List:
    """
    Helper function to get tools from a client session.

    Args:
        client_context_manager: A context manager that returns (read, write) functions
        timeout_seconds: Timeout in seconds for the read operation

    Returns:
        List of available tools from the MCP server

    Raises:
        Exception: If there's an error during the process
    """
    async with client_context_manager as (read, write, _):
        async with ClientSession(
            read, write, read_timeout_seconds=timedelta(seconds=timeout_seconds)
        ) as session:
            # Initialize the connection
            await session.initialize()
            # List available tools
            listed_tools = await session.list_tools()
            return listed_tools.tools


async def load_mcp_tools(
    server_type: str,
    command: Optional[str] = None,
    args: Optional[List[str]] = None,
    url: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
    timeout_seconds: int = 60,  # Longer default timeout for first-time executions
) -> List:
    """
    Load tools from an MCP server.

    Args:
        server_type: The type of MCP server connection (stdio or sse)
        command: The command to execute (for stdio type)
        args: Command arguments (for stdio type)
        url: The URL of the SSE server (for sse type)
        env: Environment variables
        timeout_seconds: Timeout in seconds (default: 60 for first-time executions)

    Returns:
        List of available tools from the MCP server

    Raises:
        HTTPException: If there's an error loading the tools
    """
    try:
        if server_type == "stdio":
            if not command:
                raise HTTPException(
                    status_code=400, detail="Command is required for stdio type"
                )

            server_params = StdioServerParameters(
                command=command,  # Executable
                args=args,  # Optional command line arguments
                env=env,  # Optional environment variables
            )

            return await _get_tools_from_client_session(
                stdio_client(server_params), timeout_seconds
            )

        elif server_type == "sse":
            if not url:
                raise HTTPException(
                    status_code=400, detail="URL is required for sse type"
                )

            return await _get_tools_from_client_session(
                sse_client(url=url), timeout_seconds
            )

        elif server_type == "streamable_http":
            if not url:
                raise HTTPException(
                    status_code=400, detail="URL is required for streamable_http type"
                )

            return await _get_tools_from_client_session(
                streamablehttp_client(url=url), timeout_seconds
            )

        else:
            raise HTTPException(
                status_code=400, detail=f"Unsupported server type: {server_type}"
            )

    except Exception as e:
        if not isinstance(e, HTTPException):
            logger.exception(f"Error loading MCP tools: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))
        raise
