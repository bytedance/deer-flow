"""Middleware to fix dangling tool calls in message history.

A dangling tool call occurs when an AIMessage contains tool_calls but there are
no corresponding ToolMessages in the history (e.g., due to user interruption or
request cancellation). This causes LLM errors due to incomplete message format.

This middleware runs before the model call to detect and patch such gaps by
inserting synthetic ToolMessages with an error indicator.
"""

import logging
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.runtime import Runtime

logger = logging.getLogger(__name__)


class DanglingToolCallMiddleware(AgentMiddleware[AgentState]):
    """Inserts placeholder ToolMessages for dangling tool calls before model invocation.

    Scans the message history for AIMessages whose tool_calls lack corresponding
    ToolMessages, and injects synthetic error responses so the LLM receives a
    well-formed conversation.
    """

    def _fix_dangling_tool_calls(self, state: AgentState) -> dict | None:
        messages = state.get("messages", [])
        if not messages:
            return None

        # Collect IDs of all existing ToolMessages
        existing_tool_msg_ids: set[str] = set()
        for msg in messages:
            if isinstance(msg, ToolMessage):
                existing_tool_msg_ids.add(msg.tool_call_id)

        # Find dangling tool calls and build patch messages
        patches: list[ToolMessage] = []
        for msg in messages:
            if getattr(msg, "type", None) != "ai":
                continue
            tool_calls = getattr(msg, "tool_calls", None)
            if not tool_calls:
                continue
            for tc in tool_calls:
                tc_id = tc.get("id")
                if tc_id and tc_id not in existing_tool_msg_ids:
                    patches.append(
                        ToolMessage(
                            content="[Tool call was interrupted and did not return a result.]",
                            tool_call_id=tc_id,
                            name=tc.get("name", "unknown"),
                            status="error",
                        )
                    )
                    existing_tool_msg_ids.add(tc_id)

        if not patches:
            return None

        logger.warning(f"Injecting {len(patches)} placeholder ToolMessage(s) for dangling tool calls")
        return {"messages": patches}

    @override
    def before_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        return self._fix_dangling_tool_calls(state)

    @override
    async def abefore_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        return self._fix_dangling_tool_calls(state)
