"""Middleware that emits ``tool_end`` custom events after each tool execution.

After every tool call completes (success or error), this middleware emits a
``tool_end`` event via ``get_stream_writer()`` with the tool name, execution
status, and a truncated summary. The frontend's ``onCustomEvent`` handler
consumes these events for real-time tool execution tracking.

Event format::

    {"type": "tool_end", "name": "<tool_name>", "data": {"status": "success|error", "summary": "..."}}

Summary is truncated to 500 bytes max.
"""

import logging
from collections.abc import Awaitable, Callable

from langchain.agents.middleware import AgentMiddleware, AgentState
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

logger = logging.getLogger(__name__)

_MAX_SUMMARY_BYTES = 500


def _truncate_summary(text: str, max_bytes: int = _MAX_SUMMARY_BYTES) -> str:
    """Truncate *text* to at most *max_bytes* UTF-8 bytes."""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    return encoded[: max_bytes - 3].decode("utf-8", errors="ignore") + "..."


def _extract_summary(result: ToolMessage | Command) -> str:
    """Build a short summary from a tool result.

    ``wrap_tool_call`` handlers may return either a ``ToolMessage`` or a
    ``Command`` (e.g. ``GenUIInterruptMiddleware`` returns ``Command(goto=END)``
    for interactive ``render_ui`` calls). ``Command`` has no ``content``
    attribute, so we pull the inner ``ToolMessage`` out of ``update["messages"]``
    when present and fall back to a generic label otherwise.
    """
    if isinstance(result, Command):
        messages = (result.update or {}).get("messages") if result.update else None
        if messages:
            inner = messages[0]
            if isinstance(inner, ToolMessage):
                content = inner.content if isinstance(inner.content, str) else str(inner.content)
                status_prefix = "Error: " if getattr(inner, "status", None) == "error" else ""
                return _truncate_summary(f"{status_prefix}{content[:200]}")
        goto = getattr(result, "goto", None)
        return _truncate_summary(f"Command(goto={goto})" if goto else "Command")

    content = result.content if isinstance(result.content, str) else str(result.content)
    if result.status == "error":
        return _truncate_summary(f"Error: {content[:200]}")
    return _truncate_summary(content[:200])


class ToolEndEmitMiddleware(AgentMiddleware[AgentState]):
    """Emit ``tool_end`` custom events after each tool execution.

    This is implemented as a middleware with ``wrap_tool_call`` / ``awrap_tool_call``
    hooks, not as a state-modifying middleware. It delegates to the handler and
    emits the event based on the result.
    """

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        result = handler(request)
        self._emit_tool_end(request, result)
        return result

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        result = await handler(request)
        self._emit_tool_end(request, result)
        return result

    def _emit_tool_end(self, request: ToolCallRequest, result: ToolMessage | Command) -> None:
        try:
            from langgraph.config import get_stream_writer

            writer = get_stream_writer()
        except Exception:
            return

        tool_name = str(request.tool_call.get("name") or "unknown_tool")
        if isinstance(result, Command):
            status = "success"
        else:
            status = "error" if getattr(result, "status", None) == "error" else "success"
        summary = _extract_summary(result)

        try:
            writer({
                "type": "tool_end",
                "name": tool_name,
                "data": {"status": status, "summary": summary},
            })
        except Exception:
            logger.debug("Failed to emit tool_end for %s", tool_name, exc_info=True)
