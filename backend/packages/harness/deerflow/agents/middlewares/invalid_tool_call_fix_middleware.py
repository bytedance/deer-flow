"""Middleware to fix invalid tool calls from LLM providers.

Some LLM providers (e.g., DeepSeek) return tool_calls where ``args`` is a JSON
string instead of a dict. LangChain marks these as ``invalid_tool_calls`` rather
than ``tool_calls``, causing the tool to not be executed.

This middleware intercepts the model response and attempts to parse string args
into dicts, moving successfully parsed calls from ``invalid_tool_calls`` to
``tool_calls``.
"""

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse
from langchain_core.messages import AIMessage
from langgraph.runtime import Runtime

logger = logging.getLogger(__name__)


def _try_parse_args(args: Any) -> dict | None:
    """Try to parse args into a dict. Returns None if parsing fails."""
    if isinstance(args, dict):
        return args

    if isinstance(args, str):
        try:
            parsed = json.loads(args)
            if isinstance(parsed, dict):
                return parsed
        except (TypeError, ValueError, json.JSONDecodeError):
            pass

    return None


def _fix_invalid_tool_calls(message: AIMessage) -> AIMessage:
    """Fix invalid_tool_calls by parsing string args and moving to tool_calls."""
    invalid_calls = getattr(message, "invalid_tool_calls", None) or []
    if not invalid_calls:
        return message

    fixed_calls = []
    still_invalid = []

    for call in invalid_calls:
        if not isinstance(call, dict):
            still_invalid.append(call)
            continue

        args = call.get("args")
        parsed_args = _try_parse_args(args)

        if parsed_args is not None:
            # Successfully parsed, move to tool_calls
            fixed_call = {**call, "args": parsed_args}
            fixed_calls.append(fixed_call)
            logger.debug(
                f"Fixed invalid tool call: name={call.get('name')}, "
                f"parsed args from string to dict"
            )
        else:
            still_invalid.append(call)

    if not fixed_calls:
        return message

    # Build new message with fixed calls
    existing_tool_calls = list(getattr(message, "tool_calls", []) or [])
    existing_tool_calls.extend(fixed_calls)

    # Create new message with fixed tool_calls
    return AIMessage(
        content=message.content,
        name=message.name,
        id=message.id,
        response_metadata=message.response_metadata,
        usage_metadata=message.usage_metadata,
        additional_kwargs=message.additional_kwargs,
        tool_calls=existing_tool_calls,
        invalid_tool_calls=still_invalid,
    )


class InvalidToolCallFixMiddleware(AgentMiddleware[AgentState]):
    """Fixes invalid_tool_calls by parsing string args into dicts.

    Some LLM providers return tool_calls with args as JSON strings instead of
    dicts. This causes LangChain to mark them as invalid. This middleware
    attempts to parse those strings and moves successfully parsed calls to
    tool_calls so they can be executed.
    """

    @override
    def after_model(self, state: AgentState, runtime: Runtime) -> AgentState | None:
        """Fix invalid tool calls in the model response."""
        messages = state.get("messages") or []
        if not messages:
            return None

        last_message = messages[-1]
        if not isinstance(last_message, AIMessage):
            return None

        # Check if there are invalid tool calls to fix
        invalid_calls = getattr(last_message, "invalid_tool_calls", None) or []
        if not invalid_calls:
            return None

        fixed_message = _fix_invalid_tool_calls(last_message)
        if fixed_message is last_message:
            # No changes made
            return None

        # Replace the last message with the fixed version
        new_messages = list(messages[:-1]) + [fixed_message]
        logger.info(
            f"Fixed {len(invalid_calls) - len(fixed_message.invalid_tool_calls)} "
            f"invalid tool call(s) by parsing string args"
        )
        return {"messages": new_messages}

    @override
    async def aafter_model(self, state: AgentState, runtime: Runtime) -> AgentState | None:
        """Async version of after_model."""
        return self.after_model(state, runtime)
