"""中间件 to filter deferred 工具 schemas from 模型 binding.

When tool_search is 已启用, MCP tools are registered in the DeferredToolRegistry
and passed to ToolNode for execution, but their schemas should NOT be sent to the
LLM via bind_tools (that's the whole point of deferral — saving context tokens).

This 中间件 intercepts wrap_model_call and removes deferred tools from
请求.tools so that 模型.bind_tools only receives 活跃 工具 schemas.
The 代理 discovers deferred tools at runtime via the tool_search 工具.
"""

import logging
from collections.abc import Awaitable, Callable
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse

logger = logging.getLogger(__name__)


class DeferredToolFilterMiddleware(AgentMiddleware[AgentState]):
    """Remove deferred tools from 请求.tools before 模型 binding.

    ToolNode still holds all tools (including deferred) for execution routing,
    but the LLM only sees 活跃 工具 schemas — deferred tools are discoverable
    via tool_search at runtime.
    """

    def _filter_tools(self, request: ModelRequest) -> ModelRequest:
        from deerflow.tools.builtins.tool_search import get_deferred_registry

        registry = get_deferred_registry()
        if not registry:
            return request

        deferred_names = {e.name for e in registry.entries}
        active_tools = [t for t in request.tools if getattr(t, "name", None) not in deferred_names]

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
