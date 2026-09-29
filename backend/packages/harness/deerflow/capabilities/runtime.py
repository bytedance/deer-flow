"""Stable installation references and agent tool selection, not an authorization system."""

from collections.abc import Mapping
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from deerflow.config.extensions_config import ExtensionsConfig
from deerflow.tools.mcp_metadata import get_mcp_source, is_mcp_tool


def installation_id(server_name: str, server: Mapping[str, Any]) -> str:
    metadata = server.get("capability")
    if isinstance(metadata, dict) and isinstance(metadata.get("id"), str) and metadata["id"]:
        return metadata["id"]
    # Existing configs are adopted without rewriting them during a GET. Names
    # are existing immutable runtime keys; future saves retain this identity.
    return str(uuid5(NAMESPACE_URL, f"deerflow:mcp:{server_name}"))


def ambiguous_installation_ids(servers: Mapping[str, Mapping[str, Any]]) -> set[str]:
    """Count disabled entries too: enabling one must never widen another selection."""
    seen: set[str] = set()
    ambiguous: set[str] = set()
    for name, server in servers.items():
        identity = installation_id(name, server)
        if identity in seen:
            ambiguous.add(identity)
        seen.add(identity)
    return ambiguous


def filter_mcp_plugins(tools: list[Any], selected: list[str] | None, config: ExtensionsConfig) -> list[Any]:
    if selected is None:
        return tools
    ambiguous = ambiguous_installation_ids({name: server.model_dump() for name, server in config.mcp_servers.items()})
    wanted = set(selected) - ambiguous
    servers = {name for name, server in config.get_enabled_mcp_servers().items() if installation_id(name, server.model_dump()) in wanted}
    return [tool for tool in tools if not is_mcp_tool(tool) or (get_mcp_source(tool) or {}).get("server_name") in servers]
