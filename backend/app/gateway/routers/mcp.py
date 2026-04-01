import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from deerflow.config.extensions_config import get_extensions_config
from deerflow.mcp.management import summarize_mcp_servers, update_mcp_server_enabled_states

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["mcp"])


class McpServerConfigResponse(BaseModel):
    """Public MCP server info exposed to the settings UI."""

    enabled: bool = Field(default=True, description="Whether this MCP server is enabled")
    description: str = Field(default="", description="Human-readable description of what this MCP server provides")


class McpServerConfigUpdateRequest(BaseModel):
    """HTTP-updatable MCP server state.

    The gateway intentionally allows toggling the enabled bit only. Transport
    details stay file-managed to avoid exposing secrets or remote command
    execution through the HTTP API.
    """

    enabled: bool = Field(..., description="Whether this MCP server is enabled")


class McpConfigResponse(BaseModel):
    """Response model for the public MCP configuration summary."""

    mcp_servers: dict[str, McpServerConfigResponse] = Field(
        default_factory=dict,
        description="Map of MCP server name to public enabled-state summary",
    )


class McpConfigUpdateRequest(BaseModel):
    """Request model for updating MCP enabled states."""

    mcp_servers: dict[str, McpServerConfigUpdateRequest] = Field(
        ...,
        description="Map of MCP server name to enabled-state updates",
    )


@router.get(
    "/mcp/config",
    response_model=McpConfigResponse,
    summary="Get MCP Configuration Summary",
    description="Retrieve the current public Model Context Protocol (MCP) server summary, including enabled state and description only.",
)
async def get_mcp_configuration() -> McpConfigResponse:
    """Get the current MCP configuration summary.

    Returns:
        The current MCP configuration summary with all servers.

    Example:
        ```json
        {
            "mcp_servers": {
                "github": {
                    "enabled": true,
                    "description": "GitHub MCP server for repository operations"
                }
            }
        }
        ```
    """
    config = get_extensions_config()

    return McpConfigResponse(mcp_servers=summarize_mcp_servers(config))


@router.put(
    "/mcp/config",
    response_model=McpConfigResponse,
    summary="Update MCP Enabled States",
    description="Update Model Context Protocol (MCP) server enabled states and save those toggles to file.",
)
async def update_mcp_configuration(request: McpConfigUpdateRequest) -> McpConfigResponse:
    """Update MCP enabled states for existing servers.

    This will:
    1. Persist `enabled` changes for existing MCP servers
    2. Preserve the raw JSON transport definitions and env placeholders
    3. Reload the configuration cache

    Args:
        request: The MCP enabled-state changes to save.

    Returns:
        The updated MCP configuration summary.

    Raises:
        HTTPException: 404 if an MCP server is unknown.
        HTTPException: 500 if the configuration file cannot be written.

    Example Request:
        ```json
        {
            "mcp_servers": {
                "github": {
                    "enabled": true
                }
            }
        }
        ```
    """
    try:
        enabled_updates = {name: server.enabled for name, server in request.mcp_servers.items()}
        reloaded_config = update_mcp_server_enabled_states(enabled_updates)
        logger.info("MCP enabled states updated for server(s): %s", ", ".join(sorted(enabled_updates)))
        return McpConfigResponse(mcp_servers=summarize_mcp_servers(reloaded_config))
    except KeyError as e:
        detail = e.args[0] if e.args else str(e)
        raise HTTPException(status_code=404, detail=detail) from e
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.error(f"Failed to update MCP configuration: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update MCP configuration: {str(e)}")
