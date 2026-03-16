import asyncio
import json
import logging
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from deerflow.config.extensions_config import (
    ExtensionsConfig,
    McpServerConfig,
    get_extensions_config,
    reload_extensions_config,
)
from deerflow.mcp.client import build_server_params
from deerflow.mcp.oauth import build_oauth_tool_interceptor, get_initial_oauth_headers
from deerflow.mcp.tools import MCP_SERVER_CONNECT_TIMEOUT

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
    disabled_tools: list[str] = Field(default_factory=list, description="List of tool names that are disabled for this server")


class McpConfigResponse(BaseModel):
    """Response model for MCP configuration."""

    mcp_servers: dict[str, McpServerConfigResponse] = Field(
        default_factory=dict,
        description="Map of MCP server name to configuration",
    )


class McpConfigUpdateRequest(BaseModel):
    """Request model for updating MCP configuration."""

    mcp_servers: dict[str, McpServerConfigResponse] = Field(
        ...,
        description="Map of MCP server name to configuration",
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

    return McpConfigResponse(mcp_servers={name: McpServerConfigResponse(**server.model_dump()) for name, server in config.mcp_servers.items()})


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
        return McpConfigResponse(mcp_servers={name: McpServerConfigResponse(**server.model_dump()) for name, server in reloaded_config.mcp_servers.items()})

    except Exception as e:
        logger.error(f"Failed to update MCP configuration: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update MCP configuration: {str(e)}")


class McpToolInfo(BaseModel):
    """Information about a single MCP tool."""

    name: str = Field(description="Tool name")
    description: str = Field(default="", description="Tool description")


class McpServerToolsResult(BaseModel):
    """Tools result for a single MCP server."""

    tools: list[McpToolInfo] = Field(default_factory=list, description="List of available tools")
    error: str | None = Field(default=None, description="Error message if the server failed to load")


class McpToolsResponse(BaseModel):
    """Response model for MCP tools listing."""

    servers: dict[str, McpServerToolsResult] = Field(default_factory=dict, description="Map of server name to tools result")


async def _fetch_server_tools(
    server_name: str,
    server_config: McpServerConfig,
    initial_auth_header: str | None = None,
    tool_interceptors: list | None = None,
) -> tuple[str, McpServerToolsResult]:
    """Fetch tools from a single MCP server."""
    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient

        server_params = build_server_params(server_name, server_config)

        # Inject initial OAuth header if provided (at connection/discovery time)
        if initial_auth_header and server_params.get("transport") in ("sse", "http"):
            existing_headers = dict(server_params.get("headers", {}))
            existing_headers["Authorization"] = initial_auth_header
            server_params["headers"] = existing_headers

        client = MultiServerMCPClient({server_name: server_params}, tool_interceptors=tool_interceptors)

        # Get tools with a bounded timeout to prevent hanging the API request
        tools = await asyncio.wait_for(client.get_tools(), timeout=MCP_SERVER_CONNECT_TIMEOUT)

        return server_name, McpServerToolsResult(
            tools=[McpToolInfo(name=t.name, description=t.description or "") for t in tools],
        )
    except TimeoutError:
        logger.warning(f"Timeout while fetching tools from MCP server '{server_name}'")
        return server_name, McpServerToolsResult(error=f"Connection timed out after {MCP_SERVER_CONNECT_TIMEOUT}s")
    except Exception as e:
        logger.warning(f"Failed to load tools from MCP server '{server_name}': {e}")
        return server_name, McpServerToolsResult(error=str(e))


@router.get(
    "/mcp/tools",
    response_model=McpToolsResponse,
    summary="Get MCP Server Tools",
    description="Retrieve available tools from each configured MCP server.",
)
async def get_mcp_server_tools() -> McpToolsResponse:
    """Get tools available from each MCP server.

    Returns:
        Tools grouped by server name. Disabled servers return an empty tools list.
        Servers that fail to connect return an error message.
    """
    config = get_extensions_config()
    servers: dict[str, McpServerToolsResult] = {}

    # Separate enabled and disabled servers
    enabled_servers = [(name, cfg) for name, cfg in config.mcp_servers.items() if cfg.enabled]
    disabled_servers = [name for name, cfg in config.mcp_servers.items() if not cfg.enabled]

    # Mark disabled servers with empty tools and no error
    for name in disabled_servers:
        servers[name] = McpServerToolsResult()

    if enabled_servers:
        # Prepare OAuth components once for all server requests
        initial_oauth_headers = await get_initial_oauth_headers(config)
        oauth_interceptor = build_oauth_tool_interceptor(config)
        tool_interceptors = [oauth_interceptor] if oauth_interceptor else []

        # Fetch tools from all enabled servers in parallel
        tasks = [
            _fetch_server_tools(
                name,
                cfg,
                initial_auth_header=initial_oauth_headers.get(name),
                tool_interceptors=tool_interceptors,
            )
            for name, cfg in enabled_servers
        ]
        results = await asyncio.gather(*tasks, return_exceptions=False)
        for server_name, result in results:
            servers[server_name] = result

    return McpToolsResponse(servers=servers)
