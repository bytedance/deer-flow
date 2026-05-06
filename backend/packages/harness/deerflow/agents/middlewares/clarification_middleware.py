"""Middleware for intercepting clarification requests and presenting them to the user.

When ``clarification_enabled`` is *True* (the default, matching interactive UI
sessions), the middleware interrupts execution so the frontend can display the
question and collect a user response.

When ``clarification_enabled`` is *False* (headless / API-driven runs), the
middleware auto-responds with a ToolMessage that instructs the agent to proceed
using its best judgment, keeping the run alive without human intervention.

The flag is read from ``config.configurable["clarification_enabled"]`` at
construction time and can be set per-run, just like ``thinking_enabled`` or
``subagent_enabled``.
"""

import json
import logging
from collections.abc import Callable
from hashlib import sha256
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.graph import END
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

logger = logging.getLogger(__name__)

# Auto-response sent to the agent when clarification is disabled.
_AUTO_RESPONSE = "The user is not available for interactive clarification. Proceed with your best judgment using the information already provided in the conversation. Use web_search or other available tools to find any missing information."


class ClarificationMiddlewareState(AgentState):
    """Compatible with the ``ThreadState`` schema."""

    pass


class ClarificationMiddleware(AgentMiddleware[ClarificationMiddlewareState]):
    """Intercepts ``ask_clarification`` tool calls.

    Behaviour depends on the ``enabled`` flag:

    * **enabled=True** (default) — interrupts the run via ``Command(goto=END)``
      so the frontend can present the question and resume later.
    * **enabled=False** — returns a ``ToolMessage`` that auto-answers the
      clarification, allowing the run to continue without human input.

    Args:
        enabled: Whether to actually interrupt for clarification.  When *False*
            the middleware auto-responds and the agent continues autonomously.
    """

    state_schema = ClarificationMiddlewareState

    def __init__(self, *, enabled: bool = True) -> None:
        self.enabled = enabled
        
    def _stable_message_id(self, tool_call_id: str, formatted_message: str) -> str:
        """Build a deterministic message ID so retried clarification calls replace, not append."""
        if tool_call_id:
            return f"clarification:{tool_call_id}"
        digest = sha256(formatted_message.encode("utf-8")).hexdigest()[:16]
        return f"clarification:{digest}"

    def _is_chinese(self, text: str) -> bool:
        """Check if text contains Chinese characters.

    # ── Helpers ──────────────────────────────────────────────────────────

    def _is_chinese(self, text: str) -> bool:
        """Check if text contains Chinese characters."""
        return any("\u4e00" <= char <= "\u9fff" for char in text)

    def _format_clarification_message(self, args: dict) -> str:
        """Format the clarification arguments into a user-friendly message."""
        question = args.get("question", "")
        clarification_type = args.get("clarification_type", "missing_info")
        context = args.get("context")
        options = args.get("options", [])

        # Some models (e.g. Qwen3-Max) serialize array parameters as JSON strings
        # instead of native arrays. Deserialize and normalize so `options`
        # is always a list for the rendering logic below.
        if isinstance(options, str):
            try:
                options = json.loads(options)
            except (json.JSONDecodeError, TypeError):
                options = [options]

        if options is None:
            options = []
        elif not isinstance(options, list):
            options = [options]

        # Type-specific icons
        type_icons = {
            "missing_info": "❓",
            "ambiguous_requirement": "🤔",
            "approach_choice": "🔀",
            "risk_confirmation": "⚠️",
            "suggestion": "💡",
        }

        icon = type_icons.get(clarification_type, "❓")

        message_parts = []

        if context:
            message_parts.append(f"{icon} {context}")
            message_parts.append(f"\n{question}")
        else:
            message_parts.append(f"{icon} {question}")

        if options and len(options) > 0:
            message_parts.append("")
            for i, option in enumerate(options, 1):
                message_parts.append(f"  {i}. {option}")

        return "\n".join(message_parts)

    # ── Core logic ───────────────────────────────────────────────────────

    def _handle_clarification(self, request: ToolCallRequest) -> Command | ToolMessage:
        """Handle a clarification request.

        Returns a ``Command`` (interrupt) when enabled, or a ``ToolMessage``
        (auto-answer) when disabled.
        """
        args = request.tool_call.get("args", {})
        question = args.get("question", "")
        tool_call_id = request.tool_call.get("id", "")

        logger.info("Intercepted clarification request (enabled=%s)", self.enabled)
        logger.debug("Clarification question: %s", question)

        if not self.enabled:
            # Headless / API mode — auto-respond so the agent continues.
            logger.info("Clarification disabled — auto-responding")
            return ToolMessage(
                content=_AUTO_RESPONSE,
                tool_call_id=tool_call_id,
                name="ask_clarification",
            )

        # Interactive mode — interrupt and present the question to the user.
        formatted_message = self._format_clarification_message(args)

        tool_message = ToolMessage(
            id=self._stable_message_id(tool_call_id, formatted_message),
            content=formatted_message,
            tool_call_id=tool_call_id,
            name="ask_clarification",
        )

        return Command(
            update={"messages": [tool_message]},
            goto=END,
        )

    # ── Middleware interface ──────────────────────────────────────────────

    @override
    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        """Intercept ``ask_clarification`` tool calls (sync version)."""
        if request.tool_call.get("name") != "ask_clarification":
            return handler(request)
        return self._handle_clarification(request)

    @override
    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        """Intercept ``ask_clarification`` tool calls (async version)."""
        if request.tool_call.get("name") != "ask_clarification":
            return await handler(request)
        return self._handle_clarification(request)
