"""MCP client using langchain-mcp-adapters."""

import logging
import os
from typing import Any
from urllib.parse import urlparse

from src.config.extensions_config import ExtensionsConfig, McpServerConfig

logger = logging.getLogger(__name__)


def _normalize_conninfo(value: str) -> str:
    """Normalize DB conninfo by trimming whitespace and optional wrapping quotes."""
    normalized = value.strip()
    if len(normalized) >= 2 and normalized[0] == normalized[-1] and normalized[0] in {'"', "'"}:
        normalized = normalized[1:-1].strip()
    return normalized


def _is_valid_postgres_conninfo(value: str) -> bool:
    """Return True when value looks like PostgreSQL URI or libpq DSN string."""
    normalized = _normalize_conninfo(value)
    if not normalized:
        return False

    # Accept libpq keyword format: "host=... dbname=..."
    if "://" not in normalized and "=" in normalized:
        return True

    parsed = urlparse(normalized)
    return parsed.scheme.startswith("postgres") and bool(parsed.netloc)


def _is_postgres_mcp_server(server_name: str, config: McpServerConfig) -> bool:
    """Check whether this server config is for postgres-mcp."""
    if server_name.lower() == "postgres":
        return True
    return any("postgres-mcp" in arg for arg in config.args)


def _resolve_postgres_database_uri(config_env: dict[str, str]) -> str:
    """Resolve and validate DATABASE_URI for postgres-mcp.

    Resolution priority:
      1) config env: DATABASE_URI
      2) process env: DATABASE_URI
      3) config env: DATABASE_URL
      4) process env: DATABASE_URL
    """
    candidates = [
        ("config:DATABASE_URI", config_env.get("DATABASE_URI")),
        ("process:DATABASE_URI", os.getenv("DATABASE_URI")),
        ("config:DATABASE_URL", config_env.get("DATABASE_URL")),
        ("process:DATABASE_URL", os.getenv("DATABASE_URL")),
    ]

    invalid_sources: list[str] = []
    for source, candidate in candidates:
        if not candidate:
            continue
        normalized = _normalize_conninfo(candidate)
        if _is_valid_postgres_conninfo(normalized):
            if source != "config:DATABASE_URI":
                logger.warning("Postgres MCP: using %s as DATABASE_URI because configured DATABASE_URI is missing or invalid", source)
            return normalized
        invalid_sources.append(source)

    details = ", ".join(invalid_sources) if invalid_sources else "none"
    raise ValueError(
        "postgres-mcp requires a valid PostgreSQL connection string in DATABASE_URI (or DATABASE_URL fallback). "
        f"Invalid sources checked: {details}"
    )


def build_server_params(server_name: str, config: McpServerConfig) -> dict[str, Any]:
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
        if config.env:
            env = dict(config.env)
            if _is_postgres_mcp_server(server_name, config):
                env["DATABASE_URI"] = _resolve_postgres_database_uri(env)
            params["env"] = env
        elif _is_postgres_mcp_server(server_name, config):
            params["env"] = {"DATABASE_URI": _resolve_postgres_database_uri({})}
    elif transport_type in ("sse", "http"):
        if not config.url:
            raise ValueError(f"MCP server '{server_name}' with {transport_type} transport requires 'url' field")
        params["url"] = config.url
        # Add headers if present
        if config.headers:
            params["headers"] = config.headers
    else:
        raise ValueError(f"MCP server '{server_name}' has unsupported transport type: {transport_type}")

    return params


def build_servers_config(extensions_config: ExtensionsConfig) -> dict[str, dict[str, Any]]:
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
            servers_config[server_name] = build_server_params(server_name, server_config)
            logger.info(f"Configured MCP server: {server_name}")
        except Exception as e:
            logger.error(f"Failed to configure MCP server '{server_name}': {e}")

    return servers_config
