"""Compatibility middleware for advisory MCP capability metadata."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, TypedDict, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langgraph.runtime import Runtime

from deerflow.config.tool_search_config import clamp_auto_promote_top_k


class McpRoutingIndexEntry(TypedDict):
    priority: int
    keywords: list[str]


McpRoutingIndex = Mapping[str, McpRoutingIndexEntry]


class McpRoutingMiddleware(AgentMiddleware[AgentState]):
    """Keep configuration compatible without inferring intent from text.

    Capability hints remain in the prompt. Only explicit tool_search selection
    promotes deferred schemas; DeferredToolFilterMiddleware enforces scope and
    blocks calls to tools that have not been selected.
    """

    def __init__(
        self,
        routing_index: McpRoutingIndex,
        catalog_hash: str | None,
        top_k: int,
    ) -> None:
        super().__init__()
        self._catalog_hash = catalog_hash
        self._top_k = clamp_auto_promote_top_k(top_k)
        self._routing_index = self._normalize_index(routing_index)

    @staticmethod
    def _normalize_index(routing_index: McpRoutingIndex) -> dict[str, tuple[int, tuple[str, ...]]]:
        # Defensive re-normalization: this middleware is built to accept arbitrary
        # serialized routing data, not only the output of
        # tool_search._routing_priority / _routing_keywords. In practice it is a
        # no-op over the builder's output; keep the coercion rules aligned with
        # those two helpers if either side changes.
        normalized: dict[str, tuple[int, tuple[str, ...]]] = {}
        for raw_name, raw_entry in routing_index.items():
            name = str(raw_name)
            if not name:
                continue
            # A serialized index is untrusted shape: anything that is not a
            # mapping carries no priority or keywords, so skip it instead of
            # failing on ``.get``. Middleware construction happens per run, and
            # one malformed entry would take every model call down with it.
            if not isinstance(raw_entry, Mapping):
                continue
            try:
                priority = int(raw_entry.get("priority", 0))
            except (TypeError, ValueError, OverflowError):
                # OverflowError: int() refuses inf, which JSON accepts.
                priority = 0
            raw_keywords = raw_entry.get("keywords") or []
            if not isinstance(raw_keywords, Sequence) or isinstance(raw_keywords, (str, bytes)):
                raw_keywords = []
            keywords = tuple(keyword for keyword in (str(item).strip() for item in raw_keywords) if keyword)
            if not keywords:
                continue
            normalized[name] = (priority, keywords)
        return normalized

    def _matched_names(self, state: Mapping[str, Any] | None) -> list[str]:
        """Compatibility no-op: discovery requires explicit tool_search selection.

        Configured keywords describe capabilities; a substring in user prose
        cannot establish intent, even when it occurs in the latest user turn.
        """
        return []

    @override
    def before_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        return None

    @override
    async def abefore_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        return None


def assert_mcp_routing_before_deferred_filter(middlewares: Sequence[AgentMiddleware]) -> None:
    """Preserve the legacy ordering contract for configured stacks."""
    from deerflow.agents.middlewares.deferred_tool_filter_middleware import DeferredToolFilterMiddleware

    routing_idx = next((idx for idx, middleware in enumerate(middlewares) if isinstance(middleware, McpRoutingMiddleware)), None)
    filter_idx = next((idx for idx, middleware in enumerate(middlewares) if isinstance(middleware, DeferredToolFilterMiddleware)), None)
    if routing_idx is not None and filter_idx is not None and routing_idx > filter_idx:
        raise RuntimeError(f"McpRoutingMiddleware must be installed before DeferredToolFilterMiddleware (routing index {routing_idx}, deferred filter index {filter_idx})")
