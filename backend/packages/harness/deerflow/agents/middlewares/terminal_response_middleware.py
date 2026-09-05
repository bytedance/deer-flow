"""Prevent an empty post-tool terminal response from becoming silent success."""

from __future__ import annotations

from typing import Any, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.runtime import Runtime

from deerflow.agents.middlewares.model_response import append_visible_text, has_tool_call_intent, has_visible_content

_FALLBACK_CONTENT = "The model completed the tool run but returned no final response. Please try again or use a different model."


def _tool_result_in_current_turn(messages: list[Any]) -> bool:
    """Return whether a tool result follows the latest real user message."""
    latest_user_index = -1
    for index, message in enumerate(messages):
        if not isinstance(message, HumanMessage):
            continue
        if (message.additional_kwargs or {}).get("hide_from_ui"):
            continue
        latest_user_index = index
    if latest_user_index == -1:
        return False
    return any(isinstance(message, ToolMessage) for message in messages[latest_user_index + 1 :])


class TerminalResponseMiddleware(AgentMiddleware[AgentState]):
    """Last-resort fallback after model-boundary empty-response recovery."""

    def release_policy_parameters(self) -> dict[str, object]:
        from deerflow_extension_api import canonical_hash

        return {
            "post_tool_empty_retry_limit": 0,
            "fallback_content_hash": canonical_hash(_FALLBACK_CONTENT),
        }

    def _apply(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        messages = list(state.get("messages") or [])
        if not messages or not isinstance(messages[-1], AIMessage):
            return None

        last = messages[-1]
        if has_visible_content(last) or has_tool_call_intent(last):
            return None
        if not _tool_result_in_current_turn(messages):
            return None

        additional_kwargs = dict(last.additional_kwargs or {})
        additional_kwargs.update(
            {
                "deerflow_error_fallback": True,
                "error_reason": "Model returned an empty terminal response",
            }
        )
        fallback = last.model_copy(
            update={
                "content": append_visible_text(last, _FALLBACK_CONTENT),
                "additional_kwargs": additional_kwargs,
            }
        )
        return {"messages": [fallback]}

    @override
    def after_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        return self._apply(state, runtime)

    @override
    async def aafter_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        return self._apply(state, runtime)
