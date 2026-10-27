"""Single source of truth for the MCP-tool metadata tag.

A tool is "MCP-sourced" when it carries the ``deerflow_mcp`` metadata flag.
The tag is *written* where MCP tools are loaded (``tools.py``) and *read* by
deferred-tool assembly (``tool_search.py``) and the agent build site
(``agent.py``). Keeping the key, the tagger, and the predicate here means the
magic string lives in exactly one place, and readers import a public predicate
instead of a private cross-module helper.

This is a leaf module by design: it depends only on ``BaseTool`` so that any
module (including the tool loader) can import it without an import cycle.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from langchain.tools import BaseTool

MCP_TOOL_METADATA_KEY = "deerflow_mcp"
MCP_TOOL_ROUTING_METADATA_KEY = "deerflow_mcp_routing"
MCP_TOOL_SOURCE_METADATA_KEY = "deerflow_mcp_source"


def tag_mcp_tool(
    tool: BaseTool,
    *,
    server_name: str | None = None,
    transport: str | None = None,
) -> BaseTool:
    """Mark ``tool`` as MCP-sourced. Mutates in place and returns it for chaining."""
    metadata: dict[str, Any] = {**(tool.metadata or {}), MCP_TOOL_METADATA_KEY: True}
    if server_name:
        metadata[MCP_TOOL_SOURCE_METADATA_KEY] = {
            "server_name": server_name,
            "transport": transport or "unknown",
        }
    tool.metadata = metadata
    return tool


def is_mcp_tool(tool: BaseTool) -> bool:
    """True when ``tool`` carries the MCP-source tag written by :func:`tag_mcp_tool`."""
    return (getattr(tool, "metadata", None) or {}).get(MCP_TOOL_METADATA_KEY) is True


def get_mcp_source(tool: BaseTool) -> dict[str, str] | None:
    """Return only the credential-free logical MCP source metadata."""

    source = (getattr(tool, "metadata", None) or {}).get(MCP_TOOL_SOURCE_METADATA_KEY)
    if not isinstance(source, Mapping):
        return None
    server_name = source.get("server_name")
    transport = source.get("transport")
    if not isinstance(server_name, str) or not server_name:
        return None
    return {
        "server_name": server_name,
        "transport": transport if isinstance(transport, str) and transport else "unknown",
    }


def tag_mcp_routing(tool: BaseTool, routing: Mapping[str, Any]) -> BaseTool:
    """Attach serialized MCP routing metadata to ``tool``."""
    tool.metadata = {
        **(tool.metadata or {}),
        MCP_TOOL_ROUTING_METADATA_KEY: dict(routing),
    }
    return tool


def get_mcp_routing(tool: BaseTool) -> dict[str, Any] | None:
    """Return routing metadata only for MCP tools whose routing mode is active."""
    if not is_mcp_tool(tool):
        return None
    routing = (getattr(tool, "metadata", None) or {}).get(MCP_TOOL_ROUTING_METADATA_KEY)
    if not isinstance(routing, dict) or routing.get("mode") == "off":
        return None
    return routing
