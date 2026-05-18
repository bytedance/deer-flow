"""Tool-name → :class:`AuditEventType` routing table (plan M2-5b).

Split out as its own module so adding a new community tool, MCP server,
or skill never requires editing :class:`AuditMiddleware`. The map is
consulted via :func:`map_tool_to_event_type` which encodes five rules
(plan §4.1 M2-5b):

1. **Sandbox-write tools** (``bash`` / ``write_file`` / ``str_replace``)
   → ``SANDBOX_COMMAND_EXECUTED``. These are the high-blast-radius
   verbs we always want in the audit log.
2. **MCP tools** (``mcp:{server}:{tool}`` naming convention) →
   ``TOOL_INVOKED``, with ``server`` recorded in ``details`` so
   per-server slicing is possible without parsing the name again.
3. **Community search/fetch tools** (``tavily_*`` / ``jina_*`` /
   ``firecrawl_*``) → ``DATA_EXPORTED``. The "export" framing matches
   RFC §5.1's compliance taxonomy — data flows out of our boundary.
4. **Read-only whitelist** (``ls`` / ``read_file`` / ``view_image`` /
   ``present_files``) → returns ``None``, signalling the middleware
   should not emit an event. Without the whitelist a ``ls /`` run
   would flood the audit table with low-signal rows.
5. **Default** for any tool not matched above →
   ``AGENT_TASK_COMPLETED``. We pick a known enum (not "UNKNOWN") so
   forward-compat callers don't have to handle a sentinel everywhere.

The exported :data:`RECORDED_TOOLS` set is the inverse of (4) and is
useful for tests / dashboards that want "which built-in tools generate
audit rows?" without re-running the dispatch logic.
"""

from __future__ import annotations

from deerflow.enterprise.audit.events import AuditEventType


# Rule 1 ── sandbox-write verbs we always audit.
_SANDBOX_WRITE_TOOLS: frozenset[str] = frozenset({"bash", "write_file", "str_replace"})

# Rule 2 ── MCP tools share a common prefix.
_MCP_TOOL_PREFIX = "mcp:"

# Rule 3 ── community fetch/search tools tagged as DATA_EXPORTED.
_COMMUNITY_DATA_PREFIXES: tuple[str, ...] = ("tavily_", "jina_", "firecrawl_")

# Rule 4 ── never-audit whitelist. Adding a tool here is a deliberate
# choice that this verb is too noisy or too read-only to be worth a
# row. The middleware skips it entirely.
_READ_ONLY_WHITELIST: frozenset[str] = frozenset(
    {
        "ls",
        "read_file",
        "view_image",
        "present_files",
        "ask_clarification",  # produces an interrupt; recorded elsewhere
        "write_todos",
    }
)


def map_tool_to_event_type(tool_name: str) -> AuditEventType | None:
    """Resolve a tool name to its audit event type.

    Returns ``None`` for whitelisted read-only tools — the middleware
    treats that as "do not emit an event". For every other tool the
    function returns a non-None :class:`AuditEventType` so callers
    never have to branch on "did the map have an entry?".
    """
    if tool_name in _READ_ONLY_WHITELIST:
        return None
    if tool_name in _SANDBOX_WRITE_TOOLS:
        return AuditEventType.SANDBOX_COMMAND_EXECUTED
    if tool_name.startswith(_MCP_TOOL_PREFIX):
        return AuditEventType.TOOL_INVOKED
    for prefix in _COMMUNITY_DATA_PREFIXES:
        if tool_name.startswith(prefix):
            return AuditEventType.DATA_EXPORTED
    # Rule 5 ── default: record as a generic agent-task event so the
    # audit table still captures the call. Tests assert this so future
    # refactors don't silently start dropping unknown tools.
    return AuditEventType.AGENT_TASK_COMPLETED


def extract_mcp_server(tool_name: str) -> str | None:
    """Pull the server segment out of an ``mcp:{server}:{tool}`` name.

    Returns ``None`` when the input is not an MCP-prefixed tool, so the
    middleware can branch on truthiness without an extra ``startswith``.
    """
    if not tool_name.startswith(_MCP_TOOL_PREFIX):
        return None
    parts = tool_name.split(":", 2)
    return parts[1] if len(parts) >= 2 else None


# Public symbol used by tests and the audit dashboard route.
RECORDED_TOOLS: frozenset[str] = _SANDBOX_WRITE_TOOLS


__all__ = ["RECORDED_TOOLS", "extract_mcp_server", "map_tool_to_event_type"]
