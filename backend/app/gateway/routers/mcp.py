import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from deerflow.config.extensions_config import (
    ExtensionsConfig,
    get_extensions_config,
    reload_extensions_config,
)
from deerflow.mcp.cache import get_mcp_cache_status
from deerflow.mcp.tools import discover_mcp_tools_by_server

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["mcp"])


class McpOAuthConfigResponse(BaseModel):
    """OAuth configuration for an MCP server."""

    enabled: bool = Field(default=True, description="Whether OAuth token injection is enabled")
    token_url: str = Field(default="", description="OAuth token endpoint URL")
    grant_type: Literal["client_credentials", "refresh_token"] = Field(default="client_credentials", description="OAuth grant type")
    client_id: str | None = Field(default=None, description="OAuth client ID")
    client_secret: str | None = Field(default=None, description="OAuth client secret")
    refresh_token: str | None = Field(default=None, description="OAuth refresh token")
    scope: str | None = Field(default=None, description="OAuth scope")
    audience: str | None = Field(default=None, description="OAuth audience")
    token_field: str = Field(default="access_token", description="Token response field containing access token")
    token_type_field: str = Field(default="token_type", description="Token response field containing token type")
    expires_in_field: str = Field(default="expires_in", description="Token response field containing expires-in seconds")
    default_token_type: str = Field(default="Bearer", description="Default token type when response omits token_type")
    refresh_skew_seconds: int = Field(default=60, description="Refresh this many seconds before expiry")
    extra_token_params: dict[str, str] = Field(default_factory=dict, description="Additional form params sent to token endpoint")


class McpServerConfigResponse(BaseModel):
    """Response model for MCP server configuration."""

    enabled: bool = Field(default=True, description="Whether this MCP server is enabled")
    type: str = Field(default="stdio", description="Transport type: 'stdio', 'sse', or 'http'")
    command: str | None = Field(default=None, description="Command to execute to start the MCP server (for stdio type)")
    args: list[str] = Field(default_factory=list, description="Arguments to pass to the command (for stdio type)")
    env: dict[str, str] = Field(default_factory=dict, description="Environment variables for the MCP server")
    url: str | None = Field(default=None, description="URL of the MCP server (for sse or http type)")
    headers: dict[str, str] = Field(default_factory=dict, description="HTTP headers to send (for sse or http type)")
    oauth: McpOAuthConfigResponse | None = Field(default=None, description="OAuth configuration for MCP HTTP/SSE servers")
    description: str = Field(default="", description="Human-readable description of what this MCP server provides")
    tools: dict[str, "McpToolConfigResponse"] = Field(
        default_factory=dict,
        description="Tool-level enablement states under this MCP server",
    )


class McpToolConfigResponse(BaseModel):
    """Response model for a tool exposed by an MCP server."""

    enabled: bool = Field(default=True, description="Whether this MCP tool is enabled")
    discovered: bool = Field(
        default=False,
        description="Whether this tool was discovered from the live MCP server",
    )
    description: str = Field(
        default="",
        description="Best-effort description discovered from the MCP tool metadata",
    )


class McpToolConfigUpdateRequest(BaseModel):
    """Request model for updating a single MCP tool's state."""

    enabled: bool = Field(default=True, description="Whether this MCP tool is enabled")


class McpConfigResponse(BaseModel):
    """Response model for MCP configuration."""

    mcp_servers: dict[str, McpServerConfigResponse] = Field(
        default_factory=dict,
        description="Map of MCP server name to configuration",
    )
    runtime: "McpRuntimeStatusResponse" = Field(
        default_factory=lambda: McpRuntimeStatusResponse(),
        description="Hot-reload and runtime cache status for MCP tools in the current process",
    )


class McpConfigUpdateRequest(BaseModel):
    """Request model for updating MCP configuration."""

    mcp_servers: dict[str, "McpServerConfigUpdateRequest"] = Field(
        ...,
        description="Map of MCP server name to configuration",
    )


class McpServerConfigUpdateRequest(BaseModel):
    """Request model for a single MCP server configuration update."""

    enabled: bool = Field(default=True, description="Whether this MCP server is enabled")
    type: str = Field(default="stdio", description="Transport type: 'stdio', 'sse', or 'http'")
    command: str | None = Field(default=None, description="Command to execute to start the MCP server (for stdio type)")
    args: list[str] = Field(default_factory=list, description="Arguments to pass to the command (for stdio type)")
    env: dict[str, str] = Field(default_factory=dict, description="Environment variables for the MCP server")
    url: str | None = Field(default=None, description="URL of the MCP server (for sse or http type)")
    headers: dict[str, str] = Field(default_factory=dict, description="HTTP headers to send (for sse or http type)")
    oauth: McpOAuthConfigResponse | None = Field(default=None, description="OAuth configuration for MCP HTTP/SSE servers")
    description: str = Field(default="", description="Human-readable description of what this MCP server provides")
    tools: dict[str, McpToolConfigUpdateRequest] = Field(
        default_factory=dict,
        description="Tool-level enablement states under this MCP server",
    )


class McpRuntimeStatusResponse(BaseModel):
    """Runtime status for MCP tool hot reload visibility."""

    status: Literal["not_initialized", "pending_reload", "in_sync"] = Field(
        default="not_initialized",
        description="Whether the current process has loaded MCP tools and if its cache is stale",
    )
    reload_mode: Literal["next_tool_load"] = Field(
        default="next_tool_load",
        description="How persisted MCP config changes are applied",
    )
    restart_required: bool = Field(
        default=False,
        description="Whether a full application restart is required to pick up saved MCP config changes",
    )
    will_apply_on_next_load: bool = Field(
        default=True,
        description="Whether the latest saved config will be picked up automatically on the next MCP tool load",
    )
    cache_initialized: bool = Field(
        default=False,
        description="Whether the current process has initialized its MCP tools cache",
    )
    cache_stale: bool = Field(
        default=False,
        description="Whether the current process cache is behind the latest config file mtime",
    )
    config_last_modified_at: datetime | None = Field(
        default=None,
        description="Timestamp of the latest saved extensions config on disk",
    )
    runtime_config_last_loaded_at: datetime | None = Field(
        default=None,
        description="Timestamp of the config file that the current process cache last loaded",
    )
    active_server_count: int = Field(
        default=0,
        description="Number of enabled MCP servers loaded into the current process cache",
    )
    active_tool_count: int = Field(
        default=0,
        description="Number of MCP tools currently loaded into the current process cache",
    )


McpServerConfigResponse.model_rebuild()
McpConfigResponse.model_rebuild()
McpConfigUpdateRequest.model_rebuild()


def _timestamp_to_datetime(timestamp: float | None) -> datetime | None:
    if timestamp is None:
        return None
    return datetime.fromtimestamp(timestamp, tz=UTC)


def _build_mcp_runtime_status_response() -> McpRuntimeStatusResponse:
    status = get_mcp_cache_status()
    return McpRuntimeStatusResponse(
        **{
            **status,
            "config_last_modified_at": _timestamp_to_datetime(status.get("config_last_modified_at")),
            "runtime_config_last_loaded_at": _timestamp_to_datetime(status.get("runtime_config_last_loaded_at")),
        }
    )


async def _build_mcp_config_response(config: ExtensionsConfig) -> McpConfigResponse:
    discovered_tools = await discover_mcp_tools_by_server(config)
    servers: dict[str, McpServerConfigResponse] = {}

    for server_name, server in config.mcp_servers.items():
        configured_tools = {
            tool_name: McpToolConfigResponse(
                enabled=tool_config.enabled,
                discovered=False,
                description="",
            )
            for tool_name, tool_config in server.tools.items()
        }

        for tool_name, description in discovered_tools.get(server_name, {}).items():
            configured_tools[tool_name] = McpToolConfigResponse(
                enabled=config.is_mcp_tool_enabled(server_name, tool_name),
                discovered=True,
                description=description,
            )

        servers[server_name] = McpServerConfigResponse(
            **server.model_dump(exclude={"tools"}),
            tools=dict(sorted(configured_tools.items())),
        )

    return McpConfigResponse(
        mcp_servers=servers,
        runtime=_build_mcp_runtime_status_response(),
    )


@router.get(
    "/mcp/config",
    response_model=McpConfigResponse,
    summary="Get MCP Configuration",
    description="Retrieve the current Model Context Protocol (MCP) server configurations.",
)
async def get_mcp_configuration() -> McpConfigResponse:
    """Get the current MCP configuration.

    Returns:
        The current MCP configuration with all servers.

    Example:
        ```json
        {
            "mcp_servers": {
                "github": {
                    "enabled": true,
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-github"],
                    "env": {"GITHUB_TOKEN": "ghp_xxx"},
                    "description": "GitHub MCP server for repository operations"
                }
            }
        }
        ```
    """
    config = get_extensions_config()
    return await _build_mcp_config_response(config)


@router.put(
    "/mcp/config",
    response_model=McpConfigResponse,
    summary="Update MCP Configuration",
    description="Update Model Context Protocol (MCP) server configurations and save to file.",
)
async def update_mcp_configuration(request: McpConfigUpdateRequest) -> McpConfigResponse:
    """Update the MCP configuration.

    This will:
    1. Save the new configuration to the mcp_config.json file
    2. Reload the configuration cache
    3. Reset MCP tools cache to trigger reinitialization

    Args:
        request: The new MCP configuration to save.

    Returns:
        The updated MCP configuration.

    Raises:
        HTTPException: 500 if the configuration file cannot be written.

    Example Request:
        ```json
        {
            "mcp_servers": {
                "github": {
                    "enabled": true,
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-github"],
                    "env": {"GITHUB_TOKEN": "$GITHUB_TOKEN"},
                    "description": "GitHub MCP server for repository operations"
                }
            }
        }
        ```
    """
    try:
        # Get the current config path (or determine where to save it)
        config_path = ExtensionsConfig.resolve_config_path()

        # If no config file exists, create one in the parent directory (project root)
        if config_path is None:
            config_path = Path.cwd().parent / "extensions_config.json"
            logger.info(f"No existing extensions config found. Creating new config at: {config_path}")

        # Load current config to preserve skills configuration
        current_config = get_extensions_config()

        # Convert request to dict format for JSON serialization
        config_data = {
            "mcpServers": {name: server.model_dump() for name, server in request.mcp_servers.items()},
            "skills": {name: {"enabled": skill.enabled} for name, skill in current_config.skills.items()},
        }

        # Write the configuration to file
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=2)

        logger.info(f"MCP configuration updated and saved to: {config_path}")

        # NOTE: No need to reload/reset cache here - LangGraph Server (separate process)
        # will detect config file changes via mtime and reinitialize MCP tools automatically

        # Reload the configuration and update the global cache
        reloaded_config = reload_extensions_config()
        return await _build_mcp_config_response(reloaded_config)

    except Exception as e:
        logger.error(f"Failed to update MCP configuration: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update MCP configuration: {str(e)}")
