# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

from typing import Dict, List, Optional

from pydantic import BaseModel, Field, model_validator

from ..server.mcp_validators import (
    MCPValidationError,
    validate_args_for_local_file_access,
    validate_command,
    validate_command_injection,
    validate_environment_variables,
    validate_headers,
    validate_url,
)


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

    @model_validator(mode="after")
    def validate_security(self) -> "MCPServerMetadataRequest":
        """Validate MCP server configuration for security issues."""
        errors: List[str] = []

        # Validate transport type
        valid_transports = {"stdio", "sse", "streamable_http"}
        if self.transport not in valid_transports:
            errors.append(
                f"Invalid transport type: {self.transport}. Must be one of: {', '.join(valid_transports)}"
            )

        # Validate stdio-specific fields
        if self.transport == "stdio":
            if self.command:
                try:
                    validate_command(self.command)
                except MCPValidationError as e:
                    errors.append(e.message)

            if self.args:
                try:
                    validate_args_for_local_file_access(self.args)
                except MCPValidationError as e:
                    errors.append(e.message)

                try:
                    validate_command_injection(self.args)
                except MCPValidationError as e:
                    errors.append(e.message)

            if self.env:
                try:
                    validate_environment_variables(self.env)
                except MCPValidationError as e:
                    errors.append(e.message)

        # Validate SSE/HTTP-specific fields
        elif self.transport in ("sse", "streamable_http"):
            if self.url:
                try:
                    validate_url(self.url)
                except MCPValidationError as e:
                    errors.append(e.message)

            if self.headers:
                try:
                    validate_headers(self.headers)
                except MCPValidationError as e:
                    errors.append(e.message)

        if errors:
            raise ValueError("; ".join(errors))

        return self


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
