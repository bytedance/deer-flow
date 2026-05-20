"""Tool search — deferred tool discovery at runtime.

Contains:
- DeferredToolRegistry: stores deferred tools and handles regex search
- tool_search: the LangChain tool the agent calls to discover deferred tools

The agent sees deferred tool names in <available-deferred-tools> but cannot
call them until it fetches their full schema via the tool_search tool.
Source-agnostic: no mention of MCP or tool origin.
"""

import contextvars
import json
import logging
import re
from dataclasses import dataclass

from langchain.tools import BaseTool
from langchain_core.tools import tool
from langchain_core.utils.function_calling import convert_to_openai_function

logger = logging.getLogger(__name__)

MAX_RESULTS = 5  # Max tools returned per search


# ── Registry ──


@dataclass
class DeferredToolEntry:
    """Lightweight metadata for a deferred tool (no full schema in context)."""

    name: str
    description: str
    tool: BaseTool  # Full tool object, returned only on search match


class DeferredToolRegistry:
    """Registry of deferred tools, searchable by regex pattern.

    Tools that have been promoted (via tool_search) are moved from
    ``_entries`` to ``_promoted`` so that the middleware stops filtering
    them from model binding.  ``reset_promoted()`` moves all promoted
    tools back to deferred — called by the middleware after each model
    turn so that unused promoted tools don't stay visible forever
    (issue #2968).
    """

    def __init__(self):
        self._entries: list[DeferredToolEntry] = []
        self._promoted: list[DeferredToolEntry] = []

    def register(self, tool: BaseTool) -> None:
        self._entries.append(
            DeferredToolEntry(
                name=tool.name,
                description=tool.description or "",
                tool=tool,
            )
        )

    def promote(self, names: set[str]) -> None:
        """Move tools from deferred to promoted so they pass through the filter.

        Called after tool_search returns a tool's schema — the LLM now knows
        the full definition, so the DeferredToolFilterMiddleware should stop
        stripping it from bind_tools on subsequent model calls.

        Promoted tools are tracked in ``_promoted`` (not discarded) so that
        ``reset_promoted()`` can move them back to deferred after the model
        turn that uses them.
        """
        if not names:
            return
        promoted_entries: list[DeferredToolEntry] = []
        remaining: list[DeferredToolEntry] = []
        for e in self._entries:
            (promoted_entries if e.name in names else remaining).append(e)
        self._entries = remaining
        self._promoted.extend(promoted_entries)
        if promoted_entries:
            logger.debug(f"Promoted {len(promoted_entries)} tool(s) from deferred to active: {names}")

    def search(self, query: str) -> list[BaseTool]:
        """Search deferred tools by regex pattern against name + description.

        Supports three query forms (aligned with Claude Code):
          - "select:name1,name2" — exact name match
          - "+keyword rest" — name must contain keyword, rank by rest
          - "keyword query" — regex match against name + description

        Returns:
            List of matched BaseTool objects (up to MAX_RESULTS).
        """
        if query.startswith("select:"):
            names = {n.strip() for n in query[7:].split(",")}
            return [e.tool for e in self._entries if e.name in names][:MAX_RESULTS]

        if query.startswith("+"):
            parts = query[1:].split(None, 1)
            required = parts[0].lower()
            candidates = [e for e in self._entries if required in e.name.lower()]
            if len(parts) > 1:
                candidates.sort(
                    key=lambda e: _regex_score(parts[1], e),
                    reverse=True,
                )
            return [e.tool for e in candidates][:MAX_RESULTS]

        # General regex search
        try:
            regex = re.compile(query, re.IGNORECASE)
        except re.error:
            regex = re.compile(re.escape(query), re.IGNORECASE)

        scored = []
        for entry in self._entries:
            searchable = f"{entry.name} {entry.description}"
            if regex.search(searchable):
                score = 2 if regex.search(entry.name) else 1
                scored.append((score, entry))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [entry.tool for _, entry in scored][:MAX_RESULTS]

    def reset_promoted(self) -> None:
        """Move all promoted tools back to deferred.

        Called by ``DeferredToolFilterMiddleware`` after each model call so
        that promoted tools are only visible for one turn.  If the agent
        needs them again it must call ``tool_search`` once more.
        """
        if not self._promoted:
            return
        count = len(self._promoted)
        self._entries.extend(self._promoted)
        self._promoted.clear()
        logger.debug(f"Re-deferred {count} previously promoted tool(s)")

    @property
    def promoted_names(self) -> set[str]:
        """Names of tools that have been promoted (not deferred, not hidden)."""
        return {e.name for e in self._promoted}

    @property
    def entries(self) -> list[DeferredToolEntry]:
        return list(self._entries)

    @property
    def deferred_names(self) -> set[str]:
        """Names of tools that are still hidden from model binding."""
        return {entry.name for entry in self._entries}

    def contains(self, name: str) -> bool:
        """Return whether *name* is still deferred."""
        return any(entry.name == name for entry in self._entries)

    def __len__(self) -> int:
        return len(self._entries)


def _regex_score(pattern: str, entry: DeferredToolEntry) -> int:
    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except re.error:
        regex = re.compile(re.escape(pattern), re.IGNORECASE)
    return len(regex.findall(f"{entry.name} {entry.description}"))


# ── Per-request registry (ContextVar) ──
#
# Using a ContextVar instead of a module-level global prevents concurrent
# requests from clobbering each other's registry.  In asyncio-based LangGraph
# each graph run executes in its own async context, so each request gets an
# independent registry value.  For synchronous tools run via
# loop.run_in_executor, Python copies the current context to the worker thread,
# so the ContextVar value is correctly inherited there too.

_registry_var: contextvars.ContextVar[DeferredToolRegistry | None] = contextvars.ContextVar("deferred_tool_registry", default=None)


def get_deferred_registry() -> DeferredToolRegistry | None:
    return _registry_var.get()


def set_deferred_registry(registry: DeferredToolRegistry) -> None:
    _registry_var.set(registry)


def reset_deferred_registry() -> None:
    """Reset the deferred registry for the current async context."""
    _registry_var.set(None)


# ── Tool ──


@tool
def tool_search(query: str) -> str:
    """Fetches full schema definitions for deferred tools so they can be called.

    Deferred tools appear by name in <available-deferred-tools> in the system
    prompt. Until fetched, only the name is known — there is no parameter
    schema, so the tool cannot be invoked. This tool takes a query, matches
    it against the deferred tool list, and returns the matched tools' complete
    definitions. Once a tool's schema appears in that result, it is callable.

    Query forms:
      - "select:Read,Edit,Grep" — fetch these exact tools by name
      - "notebook jupyter" — keyword search, up to max_results best matches
      - "+slack send" — require "slack" in the name, rank by remaining terms

    Args:
        query: Query to find deferred tools. Use "select:<tool_name>" for
               direct selection, or keywords to search.

    Returns:
        Matched tool definitions as JSON array.
    """
    registry = get_deferred_registry()
    if not registry:
        return "No deferred tools available."

    matched_tools = registry.search(query)
    if not matched_tools:
        return f"No tools found matching: {query}"

    # Use LangChain's built-in serialization to produce OpenAI function format.
    # This is model-agnostic: all LLMs understand this standard schema.
    tool_defs = [convert_to_openai_function(t) for t in matched_tools[:MAX_RESULTS]]

    # Promote matched tools so the DeferredToolFilterMiddleware stops filtering
    # them from bind_tools — the LLM now has the full schema and can invoke them.
    registry.promote({t.name for t in matched_tools[:MAX_RESULTS]})

    return json.dumps(tool_defs, indent=2, ensure_ascii=False)
