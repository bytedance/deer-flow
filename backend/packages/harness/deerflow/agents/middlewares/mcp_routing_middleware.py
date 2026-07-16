"""Auto-promote deferred MCP tools from routing metadata before model calls."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any, TypedDict, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage
from langgraph.runtime import Runtime

from deerflow.config.tool_search_config import clamp_auto_promote_top_k
from deerflow.utils.messages import get_original_user_content_text, is_real_user_message

logger = logging.getLogger(__name__)


class McpRoutingIndexEntry(TypedDict):
    priority: int
    keywords: list[str]


McpRoutingIndex = Mapping[str, McpRoutingIndexEntry]


class McpRoutingMiddleware(AgentMiddleware[AgentState]):
    """Write minimal deferred-tool promotion state from latest user text.

    The middleware intentionally receives only serialized routing data. It does
    not hold ``BaseTool`` objects, does not execute tools, and does not filter
    tool calls. ``DeferredToolFilterMiddleware`` remains responsible for hiding
    unpromoted schemas and blocking unpromoted deferred tool calls.
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
            try:
                priority = int(raw_entry.get("priority", 0))
            except (TypeError, ValueError):
                priority = 0
            raw_keywords = raw_entry.get("keywords") or []
            if not isinstance(raw_keywords, Sequence) or isinstance(raw_keywords, (str, bytes)):
                raw_keywords = []
            keywords = tuple(keyword for keyword in (str(item).strip() for item in raw_keywords) if keyword)
            if not keywords:
                continue
            normalized[name] = (priority, keywords)
        return normalized

    @staticmethod
    def _latest_user_message(messages: list[Any]) -> HumanMessage | None:
        for message in reversed(messages):
            if is_real_user_message(message):
                return message
        return None

    def _matched_names(self, state: Mapping[str, Any] | None) -> list[str]:
        if not self._catalog_hash or not self._routing_index:
            return []
        messages = list((state or {}).get("messages") or [])
        target = self._latest_user_message(messages)
        if target is None:
            return []

        text = get_original_user_content_text(target.content, target.additional_kwargs)
        if not text:
            return []

        haystack = text.casefold()
        matched: list[tuple[int, str]] = []
        for name, (priority, keywords) in self._routing_index.items():
            if any(keyword.casefold() in haystack for keyword in keywords):
                matched.append((priority, name))

        if not matched:
            return []

        matched.sort(key=lambda item: (-item[0], item[1]))
        return [name for _, name in matched[: self._top_k]]

    def _state_update(self, state: Mapping[str, Any] | None) -> dict[str, Any] | None:
        names = self._matched_names(state)
        if not names:
            return None
        logger.debug(
            "McpRoutingMiddleware auto-promoted %d deferred tool schema(s) catalog=%s names=%s",
            len(names),
            (self._catalog_hash or "")[:8],
            names,
        )
        return {
            "promoted": {
                "catalog_hash": self._catalog_hash,
                "names": names,
            }
        }

    @override
    def before_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        return self._state_update(state)

    @override
    async def abefore_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        return self._state_update(state)


def assert_mcp_routing_before_deferred_filter(middlewares: Sequence[AgentMiddleware]) -> None:
    """Fail fast if auto-promote would run after deferred schema filtering."""
    from deerflow.agents.middlewares.deferred_tool_filter_middleware import DeferredToolFilterMiddleware

    routing_idx = next((idx for idx, middleware in enumerate(middlewares) if isinstance(middleware, McpRoutingMiddleware)), None)
    filter_idx = next((idx for idx, middleware in enumerate(middlewares) if isinstance(middleware, DeferredToolFilterMiddleware)), None)
    if routing_idx is not None and filter_idx is not None and routing_idx > filter_idx:
        raise RuntimeError(f"McpRoutingMiddleware must be installed before DeferredToolFilterMiddleware (routing index {routing_idx}, deferred filter index {filter_idx})")
