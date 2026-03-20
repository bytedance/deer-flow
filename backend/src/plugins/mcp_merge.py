"""MCP server merging utilities for plugins."""

import logging

logger = logging.getLogger(__name__)


def namespace_server_name(plugin_name: str, server_name: str) -> str:
    """Create a namespaced MCP server name.

    Args:
        plugin_name: Name of the plugin.
        server_name: Original server name from the plugin's .mcp.json.

    Returns:
        Namespaced name in the format 'plugin_name:server_name'.
    """
    return f"{plugin_name}:{server_name}"


def merge_plugin_mcp_servers(plugin_name: str, plugin_mcp: dict, existing: dict) -> dict:
    """Merge a plugin's MCP server configs into the existing server dict.

    Server names are namespaced with the plugin name to avoid conflicts.
    Existing servers with the same namespaced name are NOT overwritten.

    Args:
        plugin_name: Name of the plugin providing the servers.
        plugin_mcp: The plugin's .mcp.json content (dict with 'mcpServers' key).
        existing: The existing MCP server config dict to merge into.

    Returns:
        The merged dictionary (also modifies existing in-place).
    """
    servers = plugin_mcp.get("mcpServers", {})

    for server_name, server_config in servers.items():
        namespaced = namespace_server_name(plugin_name, server_name)
        if namespaced in existing:
            logger.debug("Skipping duplicate MCP server %s (already exists)", namespaced)
            continue
        existing[namespaced] = server_config

    return existing
