"""Middleware to fix dangling tool calls in message history.

A dangling tool call occurs when an AIMessage contains tool_calls but there are
no corresponding ToolMessages in the history (e.g., due to user interruption or
request cancellation). This causes LLM errors due to incomplete message format.

This middleware intercepts the model call to detect and patch such gaps by
inserting synthetic ToolMessages with an error indicator immediately after the
AIMessage that made the tool calls, ensuring correct message ordering.

It also handles a related issue: when a tool call cycle completes (AIMessage →
ToolMessage(s)) but the conversation continues with a HumanMessage before the
AI has a chance to respond. This orphaned tool result pattern also causes LLM
errors, fixed by injecting a placeholder AIMessage after the last ToolMessage.

Note: Uses wrap_model_call instead of before_model to ensure patches are inserted
at the correct positions (immediately after each dangling AIMessage), not appended
to the end of the message list as before_model + add_messages reducer would do.
"""

import json
import logging
from collections.abc import Awaitable, Callable
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, ToolMessage

logger = logging.getLogger(__name__)


class DanglingToolCallMiddleware(AgentMiddleware[AgentState]):
    """Inserts placeholder messages for incomplete tool call patterns before model invocation.

    Handles two cases:
    1. Dangling tool calls: AIMessage has tool_calls with no corresponding ToolMessages.
       Fix: inject placeholder ToolMessages after the AIMessage.
    2. Orphaned tool results: a tool call cycle (AIMessage → ToolMessages) completes but
       is immediately followed by a HumanMessage with no intervening AI response (e.g.,
       user interrupted before the AI could reply to tool results).
       Fix: inject a placeholder AIMessage after the last ToolMessage in the group.
    """

    @staticmethod
    def _message_tool_calls(msg) -> list[dict]:
        """Return normalized tool calls from structured fields or raw provider payloads."""
        tool_calls = getattr(msg, "tool_calls", None) or []
        if tool_calls:
            return list(tool_calls)

        raw_tool_calls = (getattr(msg, "additional_kwargs", None) or {}).get("tool_calls") or []
        normalized: list[dict] = []
        for raw_tc in raw_tool_calls:
            if not isinstance(raw_tc, dict):
                continue

            function = raw_tc.get("function")
            name = raw_tc.get("name")
            if not name and isinstance(function, dict):
                name = function.get("name")

            args = raw_tc.get("args", {})
            if not args and isinstance(function, dict):
                raw_args = function.get("arguments")
                if isinstance(raw_args, str):
                    try:
                        parsed_args = json.loads(raw_args)
                    except (TypeError, ValueError, json.JSONDecodeError):
                        parsed_args = {}
                    args = parsed_args if isinstance(parsed_args, dict) else {}

            normalized.append(
                {
                    "id": raw_tc.get("id"),
                    "name": name or "unknown",
                    "args": args if isinstance(args, dict) else {},
                }
            )

        return normalized

    def _build_patched_messages(self, messages: list) -> list | None:
        """Return a new message list with patches inserted at the correct positions.

        Phase 1 – dangling tool calls: for each AIMessage whose tool_calls lack a
        corresponding ToolMessage, insert a synthetic ToolMessage immediately after.

        Phase 2 – orphaned tool results: for each ToolMessage that is directly followed
        by a HumanMessage (not another ToolMessage or an AIMessage), insert a synthetic
        AIMessage so the LLM receives a well-formed conversation.

        Returns None if no patches are needed.
        """
        # Collect IDs of all existing ToolMessages
        existing_tool_msg_ids: set[str] = set()
        for msg in messages:
            if isinstance(msg, ToolMessage):
                existing_tool_msg_ids.add(msg.tool_call_id)

        # --- Phase 1: fix dangling tool calls ---
        phase1: list = []
        patched_ids: set[str] = set()
        phase1_count = 0
        for msg in messages:
            phase1.append(msg)
            if getattr(msg, "type", None) != "ai":
                continue
            for tc in self._message_tool_calls(msg):
                tc_id = tc.get("id")
                if tc_id and tc_id not in existing_tool_msg_ids and tc_id not in patched_ids:
                    phase1.append(
                        ToolMessage(
                            content="[Tool call was interrupted and did not return a result.]",
                            tool_call_id=tc_id,
                            name=tc.get("name", "unknown"),
                            status="error",
                        )
                    )
                    patched_ids.add(tc_id)
                    phase1_count += 1

        # --- Phase 2: fix orphaned tool results ---
        # A ToolMessage followed directly by a HumanMessage means the AI never got
        # to reply after the tool results came back. Inject a placeholder AIMessage.
        phase2: list = []
        phase2_count = 0
        for i, msg in enumerate(phase1):
            phase2.append(msg)
            if isinstance(msg, ToolMessage):
                next_msg = phase1[i + 1] if i + 1 < len(phase1) else None
                if next_msg is not None and getattr(next_msg, "type", None) == "human":
                    phase2.append(AIMessage(content="[AI response was interrupted before completing.]"))
                    phase2_count += 1

        total = phase1_count + phase2_count
        if total == 0:
            return None

        logger.warning(f"Injecting {total} placeholder message(s) for dangling/orphaned tool calls ({phase1_count} ToolMessage(s), {phase2_count} AIMessage(s))")
        return phase2

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        patched = self._build_patched_messages(request.messages)
        if patched is not None:
            request = request.override(messages=patched)
        return handler(request)

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        patched = self._build_patched_messages(request.messages)
        if patched is not None:
            request = request.override(messages=patched)
        return await handler(request)
