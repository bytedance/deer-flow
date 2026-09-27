"""Persistent personal MCP connections, separate from deployment configuration."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from deerflow.config.extensions_config import ExtensionsConfig, read_raw_extensions_config
from deerflow.config.paths import get_paths

PERSONAL_SERVER_PREFIX = "personal_"


def user_mcp_config_path(user_id: str) -> Path:
    """Use the same validated user root as skills and account integrations."""
    return get_paths().user_dir(user_id) / "integrations" / "mcp.json"


def read_user_mcp_config(user_id: str) -> dict[str, Any]:
    path = user_mcp_config_path(user_id)
    if not path.exists():
        return {"mcpServers": {}}
    return read_raw_extensions_config(path)


def personal_server_name(user_id: str, name: str, configuration: dict[str, Any]) -> str:
    """Bind runtime sessions and durable tasks to one owner and config revision.

    Display names remain local to each user's file. Never let a same-named
    personal connection replace a deployment connection or another user's tools.
    """
    identity = json.dumps([user_id, name, configuration], sort_keys=True)
    return PERSONAL_SERVER_PREFIX + hashlib.sha256(identity.encode()).hexdigest()[:32]


def load_user_mcp_config(user_id: str) -> ExtensionsConfig:
    """Read literal user values; personal files cannot resolve host $ENV secrets."""
    raw = read_user_mcp_config(user_id)
    servers = {}
    for name, definition in raw.get("mcpServers", {}).items():
        runtime_name = personal_server_name(user_id, name, definition)
        servers[runtime_name] = {**definition, "tool_name_prefix": True}
    return ExtensionsConfig.model_validate({"mcpServers": servers})
