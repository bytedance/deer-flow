"""Middleware for dynamic tool discovery via tool search.

Controls which tools are visible to the LLM per-request by filtering the
ModelRequest.tools list. All tools remain registered in ToolNode for execution;
this middleware only controls which tool *definitions* are sent to bind_tools().

Uses the same patterns as:
- LLMToolSelectorMiddleware: request.override(tools=...) in wrap_model_call
- ClarificationMiddleware: Command return from wrap_tool_call
"""

import logging
from collections.abc import Awaitable, Callable
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import (
    ModelCallResult,
    ModelRequest,
    ModelResponse,
)
from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from src.tools.catalog import ToolCatalog

logger = logging.getLogger(__name__)


class ToolSearchMiddlewareState(AgentState):
    """Compatible with ThreadState schema — declares discovered_tools field."""

    discovered_tools: list[str]


class ToolSearchMiddleware(AgentMiddleware[ToolSearchMiddlewareState]):
    """Dynamically controls which tools are visible to the LLM per-request.

    When the total tool count exceeds the activation threshold, this middleware:
    1. Defers non-core tools (primarily MCP tools) from the LLM context
    2. Provides a ``tool_search`` tool for the LLM to discover deferred tools
    3. Tracks discovered tools in ThreadState so they persist across turns
    4. On each model call, only binds core + discovered + tool_search to the LLM

    All tools remain registered in ToolNode and can be executed — this middleware
    only controls which tool *definitions* are sent to the LLM's bind_tools().

    Args:
        catalog: Pre-built ToolCatalog indexing all available tools.
        tool_search_tool: The tool_search BaseTool instance.
        activation_threshold: Minimum total tool count to activate deferral.
            Below this threshold, all tools are sent to the LLM as usual.
        core_tool_names: Set of tool names that should always be loaded.
    """

    state_schema = ToolSearchMiddlewareState

    def __init__(
        self,
        catalog: ToolCatalog,
        tool_search_tool: BaseTool,
        activation_threshold: int = 20,
        core_tool_names: set[str] | None = None,
    ):
        super().__init__()
        self.catalog = catalog
        self.tool_search_tool = tool_search_tool
        self.activation_threshold = activation_threshold
        self.core_tool_names = core_tool_names or set()
        self._is_active = len(catalog.entries) > activation_threshold

    def _is_core_tool(self, tool: BaseTool | dict) -> bool:
        """Check if a tool is a core tool that should always be loaded."""
        if isinstance(tool, dict):
            return True  # provider-specific dict tools are always core
        return tool.name in self.core_tool_names

    def _filter_tools(
        self,
        all_tools: list[BaseTool | dict],
        discovered_names: set[str],
    ) -> list[BaseTool | dict]:
        """Filter tools to core + discovered + tool_search.

        Args:
            all_tools: All tools from the ModelRequest.
            discovered_names: Set of tool names the LLM has discovered.

        Returns:
            Filtered tool list for binding to the LLM.
        """
        filtered = []
        seen_names: set[str] = set()

        for tool in all_tools:
            if isinstance(tool, dict):
                filtered.append(tool)
                continue

            if self._is_core_tool(tool) or tool.name in discovered_names:
                if tool.name not in seen_names:
                    filtered.append(tool)
                    seen_names.add(tool.name)

        # Ensure tool_search is included
        if self.tool_search_tool.name not in seen_names:
            filtered.append(self.tool_search_tool)

        return filtered

    def _execute_search(self, args: dict) -> tuple[str, list[str]]:
        """Run the catalog search and format results.

        Args:
            args: Tool call arguments (query, mode, max_results).

        Returns:
            Tuple of (formatted result string, list of discovered tool names).
        """
        query = args.get("query", "")
        mode = args.get("mode", "auto")
        max_results = min(args.get("max_results", 5), 10)

        if not query.strip():
            return "Please provide a search query.", []

        results = self.catalog.search(query, mode=mode, max_results=max_results)

        if not results:
            return "No matching tools found. Try a different query or broader search terms.", []

        discovered_names: list[str] = []
        lines = [f"Found {len(results)} tool(s):\n"]
        for entry in results:
            lines.append(f"- **{entry.name}**: {entry.description}")
            if entry.parameter_names:
                lines.append(f"  Parameters: {', '.join(entry.parameter_names)}")
            if entry.server_name:
                lines.append(f"  (from: {entry.server_name})")
            discovered_names.append(entry.name)

        lines.append("\nThese tools are now activated and available for your next action.")

        return "\n".join(lines), discovered_names

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        """Filter tool list before model invocation."""
        if not self._is_active:
            return handler(request)

        discovered = set(request.state.get("discovered_tools") or [])
        filtered_tools = self._filter_tools(request.tools, discovered)

        total = len(request.tools)
        active = len(filtered_tools)
        deferred = total - active
        if deferred > 0:
            logger.info(
                "Tool search: %d/%d tools active (%d deferred, %d discovered)",
                active,
                total,
                deferred,
                len(discovered),
            )

        modified_request = request.override(tools=filtered_tools)
        return handler(modified_request)

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        """Async version of wrap_model_call."""
        if not self._is_active:
            return await handler(request)

        discovered = set(request.state.get("discovered_tools") or [])
        filtered_tools = self._filter_tools(request.tools, discovered)
        modified_request = request.override(tools=filtered_tools)
        return await handler(modified_request)

    @override
    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        """Intercept tool_search calls and run catalog search."""
        if request.tool_call.get("name") != "tool_search":
            return handler(request)

        args = request.tool_call.get("args", {})
        tool_call_id = request.tool_call.get("id", "")

        result_text, discovered_names = self._execute_search(args)
        logger.info(
            "Tool search query=%r discovered %d tool(s): %s",
            args.get("query"),
            len(discovered_names),
            discovered_names,
        )

        tool_message = ToolMessage(
            content=result_text,
            tool_call_id=tool_call_id,
            name="tool_search",
        )

        if discovered_names:
            return Command(
                update={
                    "messages": [tool_message],
                    "discovered_tools": discovered_names,
                },
            )

        return tool_message

    @override
    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        """Async version of wrap_tool_call."""
        if request.tool_call.get("name") != "tool_search":
            return await handler(request)

        # Search is CPU-bound and fast, no need for async
        args = request.tool_call.get("args", {})
        tool_call_id = request.tool_call.get("id", "")

        result_text, discovered_names = self._execute_search(args)
        logger.info(
            "Tool search query=%r discovered %d tool(s): %s",
            args.get("query"),
            len(discovered_names),
            discovered_names,
        )

        tool_message = ToolMessage(
            content=result_text,
            tool_call_id=tool_call_id,
            name="tool_search",
        )

        if discovered_names:
            return Command(
                update={
                    "messages": [tool_message],
                    "discovered_tools": discovered_names,
                },
            )

        return tool_message
