"""MCP client using langchain-mcp-adapters."""

import logging
from typing import Any

from deerflow.config.extensions_config import ExtensionsConfig, McpServerConfig
from deerflow.mcp.credentials import McpUserCredentials, resolve_server_credentials_sync

logger = logging.getLogger(__name__)


def build_server_params(
    server_name: str,
    config: McpServerConfig,
    *,
    credentials: McpUserCredentials | None = None,
    include_global_secrets: bool = True,
) -> dict[str, Any]:
    """Build server parameters for MultiServerMCPClient.

    Args:
        server_name: Name of the MCP server.
        config: Configuration for the MCP server.

    Returns:
        Dictionary of server parameters for langchain-mcp-adapters.
    """
    transport_type = config.type or "stdio"
    params: dict[str, Any] = {"transport": transport_type}

    if transport_type == "stdio":
        if not config.command:
            raise ValueError(f"MCP server '{server_name}' with stdio transport requires 'command' field")
        params["command"] = config.command
        params["args"] = config.args
        # Add environment variables if present
        env = credentials.env if credentials is not None else (config.env if include_global_secrets else {})
        if env:
            params["env"] = env
    elif transport_type in ("sse", "http"):
        if not config.url:
            raise ValueError(f"MCP server '{server_name}' with {transport_type} transport requires 'url' field")
        params["url"] = config.url
        # Add headers if present
        headers = credentials.headers if credentials is not None else (config.headers if include_global_secrets else {})
        if headers:
            params["headers"] = headers
    else:
        raise ValueError(f"MCP server '{server_name}' has unsupported transport type: {transport_type}")

    return params


def build_servers_config(
    extensions_config: ExtensionsConfig,
    *,
    user_id: str | None = None,
    include_global_secrets: bool = True,
) -> dict[str, dict[str, Any]]:
    """Build servers configuration for MultiServerMCPClient.

    Args:
        extensions_config: Extensions configuration containing all MCP servers.

    Returns:
        Dictionary mapping server names to their parameters.
    """
    enabled_servers = extensions_config.get_enabled_mcp_servers()

    if not enabled_servers:
        logger.info("No enabled MCP servers found")
        return {}

    servers_config = {}
    for server_name, server_config in enabled_servers.items():
        try:
            credentials = None
            if user_id is not None:
                credentials = resolve_server_credentials_sync(
                    server_name,
                    server_config,
                    user_id=user_id,
                    include_global_secrets=include_global_secrets,
                )
            servers_config[server_name] = build_server_params(
                server_name,
                server_config,
                credentials=credentials,
                include_global_secrets=include_global_secrets,
            )
            logger.info(f"Configured MCP server: {server_name}")
        except Exception as e:
            logger.error(f"Failed to configure MCP server '{server_name}': {e}")

    return servers_config
