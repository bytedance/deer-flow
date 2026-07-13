"""Middleware that emits streaming tool output chunks via LangGraph custom events.

When enabled via ``tool_streaming.enabled``, this middleware wraps async tool
execution to emit ``tool_output_chunk`` events through LangGraph's
``stream_mode="custom"`` channel.  The frontend renders these chunks
incrementally instead of waiting for the full tool result.

Sync tools (``wrap_tool_call``) are passed through unchanged — streaming is
only meaningful for async paths where the event loop can interleave chunk
emission with tool execution.

Architecture:
  ToolStreamingMiddleware (outer)
    └── handler → next middleware → actual tool

Placement:
  Must sit **outer** of ``ToolErrorHandlingMiddleware`` so that downstream
  middlewares see complete ToolMessage results.  The wrapper emits lifecycle
  chunks (start / final) around the handler call; any intermediate chunks
  emitted by the tool itself via ``langgraph.config.get_stream_writer()`` flow
  through the same custom channel and are forwarded to the frontend naturally.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from deerflow.config.tool_streaming_config import ToolStreamingConfig

logger = logging.getLogger(__name__)

# Event type string emitted as a LangGraph custom stream event.
TOOL_OUTPUT_CHUNK_EVENT = "tool_output_chunk"


def _build_start_chunk(tool_call_id: str, tool_name: str) -> dict:
    """Build the start-of-execution lifecycle chunk."""
    return {
        "type": TOOL_OUTPUT_CHUNK_EVENT,
        "tool_call_id": tool_call_id,
        "tool_name": tool_name,
        "chunk": "",
        "is_partial": True,
        "is_final": False,
    }


def _build_final_chunk(tool_call_id: str, tool_name: str, content: str) -> dict:
    """Build the end-of-execution lifecycle chunk with the full output."""
    return {
        "type": TOOL_OUTPUT_CHUNK_EVENT,
        "tool_call_id": tool_call_id,
        "tool_name": tool_name,
        "chunk": content,
        "is_partial": False,
        "is_final": True,
    }


def _build_error_chunk(tool_call_id: str, tool_name: str, error: str) -> dict:
    """Build an error chunk emitted when tool execution fails."""
    return {
        "type": TOOL_OUTPUT_CHUNK_EVENT,
        "tool_call_id": tool_call_id,
        "tool_name": tool_name,
        "chunk": error,
        "is_partial": False,
        "is_final": True,
        "error": True,
    }


def _get_stream_writer():
    """Return ``langgraph.config.get_stream_writer()`` or ``None``.

    The stream writer contextvar is only set during ``graph.astream()`` calls
    that include ``stream_mode="custom"``.  When ``None`` is returned the
    middleware silently degrades to a pass-through — execution is unaffected,
    only the real-time chunks are skipped.
    """
    try:
        from langgraph.config import get_stream_writer

        return get_stream_writer()
    except Exception:
        return None


def _extract_content(result: ToolMessage | Command) -> str:
    """Extract a string representation from a tool result."""
    if isinstance(result, ToolMessage):
        content = result.content
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(
                block.get("text", "") if isinstance(block, dict) else str(block)
                for block in content
            )
        return str(content)
    return ""


class ToolStreamingMiddleware(AgentMiddleware[AgentState]):
    """Emit ``tool_output_chunk`` custom stream events during tool execution.

    Config-driven: ``tool_streaming.enabled`` in config.yaml (default: ``false``).
    When disabled the middleware is a pure pass-through with zero overhead.

    Lifecycle chunks:
      - **start**: emitted before the handler is called (``is_partial=True``,
        ``is_final=False``, empty ``chunk``).  Signals the frontend to show a
        loading indicator for this tool.
      - **intermediate** (optional): emitted by tools that call
        ``langgraph.config.get_stream_writer()`` during execution.  The
        middleware does not produce these — they flow through the custom channel
        natively.
      - **final**: emitted after the handler returns, carrying the complete
        tool output (``is_partial=False``, ``is_final=True``).
      - **error**: emitted when the handler raises an exception.  The exception
        is re-raised so ``ToolErrorHandlingMiddleware`` (inner) can convert it
        to an error ToolMessage.

    Safe fallback: when the stream writer is unavailable (no ``custom`` mode in
    the ``stream_mode`` list, or called outside a graph execution context), the
    middleware silently degrades to a pass-through — tool execution is
    unaffected.
    """

    def __init__(self, *, config: ToolStreamingConfig | None = None) -> None:
        super().__init__()
        self._enabled = config.enabled if config is not None else False
        self._min_chunk_size = config.min_chunk_size if config is not None else 64
        self._max_buffer_seconds = config.max_buffer_seconds if config is not None else 0.1

    @classmethod
    def from_config(cls, config: ToolStreamingConfig) -> ToolStreamingMiddleware:
        """Create from a ``ToolStreamingConfig`` instance."""
        return cls(config=config)

    # ------------------------------------------------------------------
    # Sync path — pass-through (streaming is async-only)
    # ------------------------------------------------------------------

    @override
    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        """Sync tools cannot interleave chunk emission — pass through unchanged."""
        return handler(request)

    # ------------------------------------------------------------------
    # Async path — emit lifecycle chunks around handler
    # ------------------------------------------------------------------

    @override
    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        if not self._enabled:
            return await handler(request)

        tool_call_id = str(request.tool_call.get("id", ""))
        tool_name = str(request.tool_call.get("name", ""))

        writer = _get_stream_writer()
        if writer is None:
            # Custom stream mode not active — silently pass through.
            # This is not an error: the middleware is enabled but the run
            # may not have been configured with stream_mode="custom".
            return await handler(request)

        # Emit start-of-execution chunk so the frontend knows a tool is running.
        try:
            writer((TOOL_OUTPUT_CHUNK_EVENT, _build_start_chunk(tool_call_id, tool_name)))
        except Exception:
            logger.debug("Failed to emit tool start chunk for %s/%s", tool_name, tool_call_id, exc_info=True)

        try:
            result = await handler(request)
        except Exception as exc:
            # Emit an error chunk before re-raising so the frontend can show
            # what went wrong.  ToolErrorHandlingMiddleware (inner) will catch
            # this and convert it to an error ToolMessage.
            error_text = str(exc).strip() or exc.__class__.__name__
            if len(error_text) > 500:
                error_text = error_text[:497] + "..."
            try:
                writer((TOOL_OUTPUT_CHUNK_EVENT, _build_error_chunk(tool_call_id, tool_name, error_text)))
            except Exception:
                logger.debug("Failed to emit tool error chunk for %s/%s", tool_name, tool_call_id, exc_info=True)
            raise

        # Emit final chunk with the complete tool output.
        content = _extract_content(result)
        try:
            writer((TOOL_OUTPUT_CHUNK_EVENT, _build_final_chunk(tool_call_id, tool_name, content)))
        except Exception:
            logger.debug("Failed to emit tool final chunk for %s/%s", tool_name, tool_call_id, exc_info=True)

        return result
