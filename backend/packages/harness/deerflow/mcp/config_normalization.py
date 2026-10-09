"""Shared normalization of MCP configuration values.

The MCP tools cache, the custom-interceptor builder and the durable-task
configuration snapshot must all agree on when two configs are equivalent.
Keeping the rules here stops those three call sites from drifting apart.
"""

from __future__ import annotations

from typing import Any

# Server fields that only affect how tools are presented or routed to the
# model, never how a durable-task server is contacted or driven.
TASK_PRESENTATION_FIELDS = ("description", "routing", "tools", "tool_name_prefix")


def normalize_mcp_interceptor_paths(raw: Any) -> list[Any]:
    """Return the custom interceptor paths a raw ``mcpInterceptors`` value selects.

    Mirrors what ``build_mcp_tool_interceptors`` consumes: a bare string is one
    path, a list is used verbatim (order and duplicates preserved), and any
    other value — including a missing key and ``None`` — selects no custom
    interceptors.
    """
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, list):
        return list(raw)
    return []


def normalize_mcp_server_config(server: Any, *, task_runtime: bool = False) -> dict[str, Any]:
    """Return a parsed server config with alias-only fields normalized away.

    ``transport`` is an MCP-spec alias for ``type``: the model validator copies
    it onto ``type`` but keeps the raw extra key (``extra="allow"``), so dropping
    it makes equivalent ``type``/``transport`` spellings compare equal. With
    ``task_runtime=True`` the presentation-only fields are dropped too, matching
    what the durable-task runtime actually depends on.
    """
    dumped = server.model_dump(mode="json")
    dumped.pop("transport", None)
    if task_runtime:
        for field in TASK_PRESENTATION_FIELDS:
            dumped.pop(field, None)
    return dumped
