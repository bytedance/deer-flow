# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class MCPServerMetadataRequest(BaseModel):
    """Request model for MCP server metadata."""

    transport: str = Field(
        ...,
        description=(
            "The type of MCP server connection (stdio or sse or streamable_http)"
        ),
    )
    command: Optional[str] = Field(
        None, description="The command to execute (for stdio type)"
    )
    args: Optional[List[str]] = Field(
        None, description="Command arguments (for stdio type)"
    )
    url: Optional[str] = Field(
        None, description="The URL of the SSE server (for sse type)"
    )
    env: Optional[Dict[str, str]] = Field(
        None, description="Environment variables (for stdio type)"
    )
    headers: Optional[Dict[str, str]] = Field(
        None, description="HTTP headers (for sse/streamable_http type)"
    )
    timeout_seconds: Optional[int] = Field(        
        None, 
        ge=1,
        le=3600,
        description="Optional custom timeout in seconds for the operation (default: 60, range: 1-3600)"
    )
    sse_read_timeout: Optional[int] = Field(
        None,
        ge=1,
        le=3600, 
        description="Optional SSE read timeout in seconds (for sse type, default: 30, range: 1-3600)"
    )


class MCPServerMetadataResponse(BaseModel):
    """Response model for MCP server metadata."""

    transport: str = Field(
        ...,
        description=(
            "The type of MCP server connection (stdio or sse or streamable_http)"
        ),
    )
    command: Optional[str] = Field(
        None, description="The command to execute (for stdio type)"
    )
    args: Optional[List[str]] = Field(
        None, description="Command arguments (for stdio type)"
    )
    url: Optional[str] = Field(
        None, description="The URL of the SSE server (for sse type)"
    )
    env: Optional[Dict[str, str]] = Field(
        None, description="Environment variables (for stdio type)"
    )
    headers: Optional[Dict[str, str]] = Field(
        None, description="HTTP headers (for sse/streamable_http type)"
    )
    tools: List = Field(
        default_factory=list, description="Available tools from the MCP server"
    )
