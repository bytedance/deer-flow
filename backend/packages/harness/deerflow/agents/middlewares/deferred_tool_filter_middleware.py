"""Middleware to filter deferred tool schemas from model binding.

When tool_search is enabled, MCP tools are still passed to ToolNode for
execution, but their schemas must NOT be sent to the LLM via bind_tools until
the model has discovered them via tool_search. This middleware removes the
still-deferred tools from request.tools before model binding, and blocks tool
calls to tools that have not been promoted yet.

The deferred name set and the catalog hash are injected at construction time
(no ContextVar). Promotion state is read from graph state (``state["promoted"]``),
scoped by catalog hash and genuine user-message ID so a stale promotion cannot
expose a renamed tool or remain active in a later user turn.
"""

import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.runtime import Runtime
from langgraph.types import Command

from deerflow.agents.middlewares.message_utils import genuine_user_turn_id, has_ai_response_after_latest_user_message

logger = logging.getLogger(__name__)


class DeferredToolFilterMiddleware(AgentMiddleware[AgentState]):
    """Hide deferred tool schemas from the bound model until promoted.

    ToolNode still holds all tools (including deferred) for execution routing,
    but the LLM only sees active tool schemas plus tools that have already been
    promoted under the current catalog hash and genuine user turn.
    """

    def __init__(self, deferred_names: frozenset[str], catalog_hash: str | None):
        super().__init__()
        self._deferred = deferred_names
        self._catalog_hash = catalog_hash

    def release_policy_parameters(self) -> dict[str, object]:
        return {
            "deferred_names": sorted(self._deferred),
            "catalog_hash": self._catalog_hash,
            "promotion_scope": "graph_state_catalog_hash_user_turn",
        }

    def _promotion_is_current(self, state: Mapping[str, Any] | None, promoted: Mapping[str, Any]) -> bool:
        if promoted.get("catalog_hash") != self._catalog_hash:
            return False
        promoted_turn_id = promoted.get("turn_id")
        if promoted_turn_id is None:
            return has_ai_response_after_latest_user_message(list((state or {}).get("messages") or []))
        current_turn_id = genuine_user_turn_id(list((state or {}).get("messages") or []))
        return current_turn_id is not None and promoted_turn_id == current_turn_id

    def _promoted(self, state: Mapping[str, Any] | None) -> set[str]:
        promoted = (state or {}).get("promoted")
        if not isinstance(promoted, Mapping) or not self._promotion_is_current(state, promoted):
            return set()
        names = promoted.get("names")
        if isinstance(names, Sequence) and not isinstance(names, (str, bytes)):
            return {name for name in names if isinstance(name, str)}
        return set()

    def _turn_state_update(self, state: Mapping[str, Any] | None) -> dict[str, Any] | None:
        turn_id = genuine_user_turn_id(list((state or {}).get("messages") or []))
        if not self._deferred or not self._catalog_hash or turn_id is None:
            return None
        promoted = (state or {}).get("promoted")
        if isinstance(promoted, Mapping) and self._promotion_is_current(state, promoted):
            if promoted.get("turn_id") == turn_id:
                return None
            names = promoted.get("names")
            migrated_names = [name for name in names if isinstance(name, str)] if isinstance(names, Sequence) and not isinstance(names, (str, bytes)) else []
        else:
            migrated_names = []
        return {
            "promoted": {
                "catalog_hash": self._catalog_hash,
                "names": migrated_names,
                "turn_id": turn_id,
            }
        }

    def _hidden(self, state: Mapping[str, Any] | None) -> set[str]:
        return set(self._deferred) - self._promoted(state)

    def _filter_tools(self, request: ModelRequest) -> ModelRequest:
        if not self._deferred:
            return request
        hide = self._hidden(request.state)
        if not hide:
            return request
        active = [t for t in request.tools if getattr(t, "name", None) not in hide]
        if len(active) < len(request.tools):
            logger.debug("Filtered %d deferred tool schema(s) from model binding", len(request.tools) - len(active))
        return request.override(tools=active)

    def _blocked_tool_message(self, request: ToolCallRequest) -> ToolMessage | None:
        if not self._deferred:
            return None
        name = str(request.tool_call.get("name") or "")
        if not name or name not in self._hidden(request.state):
            return None
        tool_call_id = str(request.tool_call.get("id") or "missing_tool_call_id")
        return ToolMessage(
            content=(f"Error: Tool '{name}' is deferred and has not been promoted yet. Call tool_search first to expose and promote this tool's schema, then retry."),
            tool_call_id=tool_call_id,
            name=name,
            status="error",
        )

    @override
    def before_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        return self._turn_state_update(state)

    @override
    async def abefore_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        return self._turn_state_update(state)

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        return handler(self._filter_tools(request))

    @override
    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        blocked = self._blocked_tool_message(request)
        if blocked is not None:
            return blocked
        return handler(request)

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        return await handler(self._filter_tools(request))

    @override
    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        blocked = self._blocked_tool_message(request)
        if blocked is not None:
            return blocked
        return await handler(request)
