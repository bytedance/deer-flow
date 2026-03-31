"""Helpers for safe MCP configuration management."""

from __future__ import annotations

import json
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from deerflow.config.extensions_config import ExtensionsConfig, get_extensions_config, reload_extensions_config


def summarize_mcp_servers(config: ExtensionsConfig | None = None) -> dict[str, dict[str, bool | str]]:
    """Return the public MCP server view exposed by the API/UI.

    The HTTP management surface only needs the enabled state plus the human
    description. Connection details and secrets stay file-only to avoid
    accidental disclosure or remote transport rewrites.
    """
    extensions_config = config or get_extensions_config()
    return {
        name: {
            "enabled": server.enabled,
            "description": server.description,
        }
        for name, server in extensions_config.mcp_servers.items()
    }


def _load_raw_extensions_config(config_path: str | None = None) -> tuple[Path | None, dict[str, Any]]:
    """Load the raw extensions config without resolving env placeholders."""
    resolved_path = ExtensionsConfig.resolve_config_path(config_path)
    if resolved_path is None:
        return None, {"mcpServers": {}, "skills": {}}

    try:
        with open(resolved_path, encoding="utf-8") as f:
            config_data = json.load(f)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Extensions config file at {resolved_path} is not valid JSON: {exc}") from exc

    if not isinstance(config_data, dict):
        raise ValueError(f"Extensions config file at {resolved_path} must contain a JSON object")

    mcp_servers = config_data.setdefault("mcpServers", {})
    skills = config_data.setdefault("skills", {})

    if not isinstance(mcp_servers, dict):
        raise ValueError("Extensions config field 'mcpServers' must be a JSON object")
    if not isinstance(skills, dict):
        raise ValueError("Extensions config field 'skills' must be a JSON object")

    return resolved_path, config_data


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    """Write JSON atomically to avoid partial config writes."""
    fd = tempfile.NamedTemporaryFile(
        mode="w",
        dir=path.parent,
        suffix=".tmp",
        delete=False,
        encoding="utf-8",
    )
    try:
        json.dump(data, fd, indent=2)
        fd.write("\n")
        fd.close()
        Path(fd.name).replace(path)
    except BaseException:
        fd.close()
        Path(fd.name).unlink(missing_ok=True)
        raise


def update_mcp_server_enabled_states(
    enabled_updates: Mapping[str, bool],
    *,
    config_path: str | None = None,
) -> ExtensionsConfig:
    """Persist enabled-state toggles for existing MCP servers only.

    Transport details are preserved from the raw JSON file so env placeholders
    and other unmanaged fields are not rewritten or exposed.
    """
    resolved_path, config_data = _load_raw_extensions_config(config_path)
    if resolved_path is None:
        raise FileNotFoundError("Cannot locate extensions_config.json. Set DEER_FLOW_EXTENSIONS_CONFIG_PATH or ensure it exists in the project root.")

    raw_servers = config_data["mcpServers"]
    unknown_servers = sorted(set(enabled_updates) - set(raw_servers))
    if unknown_servers:
        joined = ", ".join(unknown_servers)
        raise KeyError(f"Unknown MCP server(s): {joined}")

    for server_name, enabled in enabled_updates.items():
        raw_server = raw_servers.get(server_name)
        if not isinstance(raw_server, dict):
            raise ValueError(f"MCP server '{server_name}' must be a JSON object")
        raw_server["enabled"] = bool(enabled)

    _atomic_write_json(resolved_path, config_data)
    return reload_extensions_config(str(resolved_path))
