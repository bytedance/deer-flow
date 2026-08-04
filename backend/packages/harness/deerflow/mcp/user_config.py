"""Tenant-owned MCP configuration storage.

MCP server credentials and endpoints are user configuration, not platform
configuration.  Keep them in each authenticated user's state directory and
never use a caller supplied path as the ownership authority.
"""

from __future__ import annotations

from pathlib import Path

from deerflow.config.extensions_config import ExtensionsConfig, McpServerConfig, atomic_write_extensions_config
from deerflow.config.paths import get_paths

_USER_MCP_CONFIG_FILE = "mcp_config.json"


def user_mcp_config_path(user_id: str) -> Path:
    """Return the validated, tenant-private MCP configuration path."""
    return get_paths().user_dir(user_id) / _USER_MCP_CONFIG_FILE


def load_user_mcp_config(user_id: str) -> ExtensionsConfig:
    """Load only *user_id*'s MCP servers, with an empty default."""
    path = user_mcp_config_path(user_id)
    if not path.exists():
        return ExtensionsConfig(mcp_servers={}, skills={})
    return ExtensionsConfig.from_file(str(path))


def save_user_mcp_config(user_id: str, servers: dict[str, McpServerConfig]) -> ExtensionsConfig:
    """Atomically replace one tenant's MCP server catalogue."""
    path = user_mcp_config_path(user_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    config = ExtensionsConfig(mcp_servers=servers, skills={})
    atomic_write_extensions_config(path, config.to_file_dict())
    return config
