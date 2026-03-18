"""Middleware to filter deferred tool schemas from model binding.

When tool_search is enabled, MCP tools are registered in the DeferredToolRegistry
and passed to ToolNode for execution, but their schemas should NOT be sent to the
LLM via bind_tools (that's the whole point of deferral — saving context tokens).

This middleware intercepts wrap_model_call and removes deferred tools from
request.tools so that model.bind_tools only receives active tool schemas.
The agent discovers deferred tools at runtime via the tool_search tool.
"""

import logging
from collections.abc import Awaitable, Callable
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse

logger = logging.getLogger(__name__)


class DeferredToolFilterMiddleware(AgentMiddleware[AgentState]):
    """Remove deferred tools from request.tools before model binding.

    ToolNode still holds all tools (including deferred) for execution routing,
    but the LLM only sees active tool schemas — deferred tools are discoverable
    via tool_search at runtime.
    """

    @staticmethod
    def _loaded_tool_names(request: ModelRequest) -> set[str]:
        state = request.state
        if state is None:
            return set()
        if isinstance(state, dict):
            loaded = state.get("loaded_deferred_tools", [])
        else:
            loaded = getattr(state, "loaded_deferred_tools", [])
        return set(loaded or [])

    def _filter_tools(self, request: ModelRequest) -> ModelRequest:
        from deerflow.tools.builtins.tool_search import get_deferred_registry

        registry = get_deferred_registry()
        if not registry:
            return request

        deferred_names = {e.name for e in registry.entries}
        loaded_tool_names = self._loaded_tool_names(request)
        active_tools = [
            t
            for t in request.tools
            if (name := getattr(t, "name", None)) is None
            or name not in deferred_names
            or name in loaded_tool_names
        ]

        if len(active_tools) < len(request.tools):
            logger.debug(f"Filtered {len(request.tools) - len(active_tools)} deferred tool schema(s) from model binding")

        return request.override(tools=active_tools)

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        return handler(self._filter_tools(request))

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        return await handler(self._filter_tools(request))
