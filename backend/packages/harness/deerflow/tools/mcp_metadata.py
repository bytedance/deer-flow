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

from langchain.tools import BaseTool

MCP_TOOL_METADATA_KEY = "deerflow_mcp"


def tag_mcp_tool(tool: BaseTool) -> BaseTool:
    """Mark ``tool`` as MCP-sourced. Mutates in place and returns it for chaining."""
    tool.metadata = {**(tool.metadata or {}), MCP_TOOL_METADATA_KEY: True}
    return tool


def is_mcp_tool(tool: BaseTool) -> bool:
    """True when ``tool`` carries the MCP-source tag written by :func:`tag_mcp_tool`."""
    return (getattr(tool, "metadata", None) or {}).get(MCP_TOOL_METADATA_KEY) is True
