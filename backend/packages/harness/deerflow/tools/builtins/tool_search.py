"""Tool search — deferred tool discovery at runtime.

Contains:
- DeferredToolCatalog: immutable, searchable catalog of deferred tools.
- build_tool_search_tool: builds the `tool_search` tool as a closure over a
  catalog; it records promotions into graph state via ``Command``.
- build_deferred_tool_setup: assembles the catalog + tool from the tools
  configured for this agent build.
- build_mcp_routing_middleware: builds the PR2 auto-promote middleware from
  serialized routing metadata on deferred tools available to the caller.

The agent sees deferred tool names in <available-deferred-tools> but cannot
call them until it fetches their full schema via the tool_search tool. The
deferred set rides on a build-time closure and promotion lives in per-thread
graph state — there is no ContextVar. Source-agnostic: a tool is "deferred"
when it carries the ``deerflow_mcp`` metadata tag.
"""

import hashlib
import html
import json
import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass
from functools import cached_property
from typing import TYPE_CHECKING, Annotated, Any

from langchain.tools import BaseTool
from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langchain_core.utils.function_calling import convert_to_openai_function
from langgraph.types import Command

from deerflow.tools.mcp_metadata import get_mcp_routing, is_mcp_tool

if TYPE_CHECKING:
    from langchain.agents.middleware import AgentMiddleware

logger = logging.getLogger(__name__)

MAX_RESULTS = 5  # Max tools returned per search


def _compile_catalog_regex(pattern: str) -> re.Pattern[str]:
    """Compile ``pattern`` case-insensitively, falling back to a literal match.

    Search queries come from the model, so an invalid regex (e.g. an unbalanced
    paren) must degrade to a literal substring match rather than raise.
    """
    try:
        return re.compile(pattern, re.IGNORECASE)
    except re.error:
        return re.compile(re.escape(pattern), re.IGNORECASE)


# ── Catalog ──


# NOTE: frozen=True without slots=True keeps __dict__, which is what lets the
# @cached_property fields below cache (they write to instance.__dict__, bypassing
# the frozen __setattr__). Do NOT add slots=True or hash/names break at runtime.
@dataclass(frozen=True)
class DeferredToolCatalog:
    """Immutable catalog of deferred tools. Pure search, no mutation."""

    tools: tuple[BaseTool, ...]

    @cached_property
    def names(self) -> frozenset[str]:
        return frozenset(t.name for t in self.tools)

    @cached_property
    def hash(self) -> str:
        canon = [{"name": t.name, "schema": convert_to_openai_function(t)} for t in sorted(self.tools, key=lambda t: t.name)]
        blob = json.dumps(canon, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]

    def search(self, query: str) -> list[BaseTool]:
        query = query.strip()
        if not query:
            return []

        if query.startswith("select:"):
            # No cap: ``select:`` names the tools explicitly, so returning a
            # subset silently drops schemas the model asked for by name. Mirrors
            # ``SkillCatalog.search`` (``skills/catalog.py``); the ranked modes
            # below stay capped at ``MAX_RESULTS``.
            wanted = {n.strip() for n in query[7:].split(",")}
            return [t for t in self.tools if t.name in wanted]

        if query.startswith("+"):
            parts = query[1:].split(None, 1)
            if not parts:
                return []  # bare "+" with no required token — nothing to require
            required = parts[0].lower()
            candidates = [t for t in self.tools if required in t.name.lower()]
            if len(parts) > 1:
                candidates.sort(key=lambda t: _catalog_regex_score(parts[1], t), reverse=True)
            return candidates[:MAX_RESULTS]

        regex = _compile_catalog_regex(query)
        scored: list[tuple[int, BaseTool]] = []
        for t in self.tools:
            searchable = f"{t.name} {t.description or ''}"
            if regex.search(searchable):
                scored.append((2 if regex.search(t.name) else 1, t))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [t for _, t in scored][:MAX_RESULTS]


def _catalog_regex_score(pattern: str, t: BaseTool) -> int:
    regex = _compile_catalog_regex(pattern)
    return len(regex.findall(f"{t.name} {t.description or ''}"))


# ── Setup / tool ──


@dataclass(frozen=True)
class DeferredToolSetup:
    """Result of assembling deferred-tool support for one agent build.

    The three fields move as a unit, so callers branch on ``tool_search_tool``:

    - **Empty** ``(None, frozenset(), None)``: deferral is disabled, or no MCP
      tool is present in the candidate list. Nothing is deferred — bind tools
      as-is.
    - **Populated**: ``tool_search_tool`` is appended to the agent's tools,
      ``deferred_names`` are withheld from the model until promoted, and
      ``catalog_hash`` scopes those promotions in graph state.

    Invariant: ``tool_search_tool is None`` ⟺ ``deferred_names`` is empty ⟺
    ``catalog_hash is None``.
    """

    tool_search_tool: BaseTool | None
    deferred_names: frozenset[str]
    catalog_hash: str | None


def build_tool_search_tool(catalog: DeferredToolCatalog) -> BaseTool:
    catalog_hash = catalog.hash

    @tool
    def tool_search(query: str, tool_call_id: Annotated[str, InjectedToolCallId]) -> Command:
        """Fetches full schema definitions for deferred tools so they can be called.

        Deferred tools appear by name in <available-deferred-tools> in the system
        prompt. Until fetched, only the name is known. This tool matches a query
        against the deferred tools and returns the matched tools complete schemas;
        once returned, a tool becomes callable.

        Query forms:
          - "select:Read,Edit" -- fetch these exact tools by name
          - "notebook jupyter" -- keyword search, up to max_results best matches
          - "+slack send" -- require "slack" in the name, rank by remaining terms
        """
        matched = catalog.search(query)
        if not matched:
            content, names = f"No tools found matching: {query}", []
        else:
            content = json.dumps([convert_to_openai_function(t) for t in matched], indent=2, ensure_ascii=False)
            names = [t.name for t in matched]
        return Command(
            update={
                "promoted": {"catalog_hash": catalog_hash, "names": names},
                "messages": [ToolMessage(content=content, tool_call_id=tool_call_id, name="tool_search")],
            }
        )

    return tool_search


def build_deferred_tool_setup(candidate_tools: list[BaseTool], *, enabled: bool) -> DeferredToolSetup:
    """Build deferred-tool setup from one agent build's candidate tools.

    Lead agents pass their full configured tool list; ``SkillToolPolicyMiddleware``
    later filters model-visible schemas, execution, and ``tool_search`` results
    for the active skill while keeping the discovery tool itself available.
    Subagents may pass a statically policy-filtered list because their configured
    skills are loaded at startup. The downstream deferred-schema middleware still
    hides unpromoted MCP schemas in either case.

    Returns an empty setup (see :class:`DeferredToolSetup`) in two distinct
    cases: deferral is disabled, or it is enabled but no MCP tool survived
    the caller's build-time selection.
    """
    if not enabled:
        # Deferral disabled: defer nothing; the model binds every tool as before.
        return DeferredToolSetup(None, frozenset(), None)
    deferred = [t for t in candidate_tools if is_mcp_tool(t)]
    if not deferred:
        # Enabled, but no MCP tool to defer: same empty result, different reason.
        return DeferredToolSetup(None, frozenset(), None)
    catalog = DeferredToolCatalog(tuple(deferred))
    return DeferredToolSetup(build_tool_search_tool(catalog), catalog.names, catalog.hash)


def assemble_deferred_tools(candidate_tools: list[BaseTool], *, enabled: bool) -> tuple[list[BaseTool], DeferredToolSetup]:
    """Build the final tool list and deferred setup from candidate tools.

    Fail closed on deferral assembly itself: if tool_search is enabled and MCP
    candidates exist but no deferred set was recovered, raise rather than silently
    binding their full schemas to the model. Lead-agent authorization is enforced
    separately at runtime by ``SkillToolPolicyMiddleware``; subagents may already
    have applied their static skill policy to ``candidate_tools``.

    Shared by every agent-build path (lead, embedded client, subagent) so they
    all get the same fail-closed guarantee from one place.
    """
    deferred_setup = build_deferred_tool_setup(candidate_tools, enabled=enabled)
    if enabled and not deferred_setup.deferred_names and any(is_mcp_tool(t) for t in candidate_tools):
        raise RuntimeError("tool_search enabled and MCP candidates exist, but no deferred set was recovered - refusing to bind MCP schemas (fail-closed).")
    final_tools = list(candidate_tools)
    if deferred_setup.tool_search_tool:
        final_tools.append(deferred_setup.tool_search_tool)
    return final_tools, deferred_setup


def _routing_priority(value: Any) -> int:
    # Produces the typed priority stored in the routing index. McpRoutingMiddleware
    # ._normalize_index re-parses this defensively (it is built to accept arbitrary
    # serialized data), so keep the two coercion rules in sync if either changes.
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _routing_keywords(value: Any) -> list[str]:
    # See _routing_priority: McpRoutingMiddleware._normalize_index re-normalizes
    # keywords defensively; keep both coercion rules aligned.
    if not isinstance(value, list):
        return []
    return [keyword for keyword in (str(item).strip() for item in value) if keyword]


def build_mcp_routing_middleware(
    tools: Iterable[BaseTool],
    deferred_setup: DeferredToolSetup,
    *,
    top_k: int,
) -> "AgentMiddleware | None":
    """Build PR2 auto-promotion middleware from the caller's deferred tools.

    The builder may inspect ``BaseTool.metadata`` at construction time, but the
    returned middleware receives only a flat serializable routing index.
    """
    if deferred_setup.catalog_hash is None or not deferred_setup.deferred_names:
        return None

    routing_index: dict[str, dict[str, Any]] = {}
    for candidate in tools:
        tool_name = getattr(candidate, "name", "")
        if tool_name not in deferred_setup.deferred_names:
            continue
        routing = get_mcp_routing(candidate)
        if routing is None or routing.get("mode") != "prefer":
            continue
        keywords = _routing_keywords(routing.get("keywords"))
        if not keywords:
            continue
        if routing.get("auto_promote_top_k") is not None:
            logger.debug("Ignoring per-tool MCP routing auto_promote_top_k for %s in PR2", tool_name)
        routing_index[str(tool_name)] = {
            "priority": _routing_priority(routing.get("priority", 0)),
            "keywords": keywords,
        }

    if not routing_index:
        return None

    from deerflow.agents.middlewares.mcp_routing_middleware import McpRoutingMiddleware

    return McpRoutingMiddleware(routing_index, deferred_setup.catalog_hash, top_k)


# Prompt rendering


def get_deferred_tools_prompt_section(*, deferred_names: frozenset[str] = frozenset()) -> str:
    """Generate <available-deferred-tools> from an explicit deferred-name set.

    Lists only names so the agent knows what exists and can use tool_search to
    load them. Returns empty string when there are no deferred tools. The set is
    computed at agent build time (after tool-policy filtering) and passed in.

    Lives here, next to the assembly that produces ``deferred_names``, so every
    agent-build path (lead, embedded client, subagent) renders the section the
    same way without coupling back to ``lead_agent.prompt``.
    """
    if not deferred_names:
        return ""
    # Names come verbatim from external MCP servers; escape so a crafted tool
    # name cannot close this block and forge a framework tag. Mirrors
    # get_skill_index_prompt_section.
    names = "\n".join(html.escape(name, quote=False) for name in sorted(deferred_names))
    return f"<available-deferred-tools>\n{names}\n</available-deferred-tools>"


def _format_keyword_list(keywords: list[str]) -> str:
    if len(keywords) == 1:
        return keywords[0]
    return f"{', '.join(keywords[:-1])}, or {keywords[-1]}"


def get_mcp_routing_hints_prompt_section(tools: Iterable[BaseTool], *, deferred_names: frozenset[str] = frozenset()) -> str:
    """Render <mcp_routing_hints> from MCP tools carrying routing metadata.

    When tool_search has deferred an MCP tool, the hint must point the model at
    promotion first; otherwise it may try to call a schema that is hidden from
    the bound model request.
    """
    hints: list[tuple[int, str, list[str]]] = []
    for candidate in tools:
        routing = get_mcp_routing(candidate)
        if routing is None or routing.get("mode") != "prefer":
            continue
        keywords = routing.get("keywords") or []
        if not keywords:
            continue
        hints.append((int(routing.get("priority", 0)), candidate.name, [html.escape(str(keyword), quote=False) for keyword in keywords]))

    if not hints:
        return ""

    lines = ["<mcp_routing_hints>"]
    for priority, tool_name, keywords in sorted(hints, key=lambda item: (-item[0], item[1])):
        # tool_name comes verbatim from the external MCP server; escape at render
        # (keep the raw name for the deferred_names membership check above).
        esc_name = html.escape(tool_name, quote=False)
        lines.append(f"When the user's request involves {_format_keyword_list(keywords)}:")
        if tool_name in deferred_names:
            lines.append(f"  use `tool_search` to fetch `{esc_name}`, then prefer that MCP tool.")
        else:
            lines.append(f"  prefer the `{esc_name}` tool.")
    lines.append("</mcp_routing_hints>")
    return "\n".join(lines)
