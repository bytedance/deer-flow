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
from typing import Any, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage
from langgraph.runtime import Runtime

logger = logging.getLogger(__name__)

_TOOL_NAME_ALIASES = {
    "todo_write": "write_todos",
}


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


def _normalize_tool_name(name: Any) -> Any:
    """Normalize known provider/tool aliases to the runtime tool name."""
    if not isinstance(name, str):
        return name
    return _TOOL_NAME_ALIASES.get(name, name)


def _normalize_tool_call_name(call: Any) -> tuple[Any, bool]:
    """Return a tool-call dict with a normalized name when possible."""
    if not isinstance(call, dict):
        return call, False

    normalized_name = _normalize_tool_name(call.get("name"))
    if normalized_name == call.get("name"):
        return call, False

    return {**call, "name": normalized_name}, True


def _build_fixed_tool_call(call: dict[str, Any], parsed_args: dict[str, Any]) -> dict[str, Any]:
    """Convert an invalid_tool_call payload into a valid tool_call payload."""
    return {
        "name": call.get("name"),
        "args": parsed_args,
        "id": call.get("id", ""),
        "type": "tool_call",
    }


def _fix_invalid_tool_calls(message: AIMessage) -> AIMessage:
    """Fix invalid tool calls and normalize known tool-name aliases."""
    changes_made = False
    existing_tool_calls = list(getattr(message, "tool_calls", []) or [])
    normalized_tool_calls = []

    for call in existing_tool_calls:
        normalized_call, changed = _normalize_tool_call_name(call)
        normalized_tool_calls.append(normalized_call)
        changes_made = changes_made or changed

    invalid_calls = getattr(message, "invalid_tool_calls", None) or []
    if not invalid_calls:
        if not changes_made:
            return message

        return AIMessage(
            content=message.content,
            name=message.name,
            id=message.id,
            response_metadata=message.response_metadata,
            usage_metadata=message.usage_metadata,
            additional_kwargs=message.additional_kwargs,
            tool_calls=normalized_tool_calls,
            invalid_tool_calls=[],
        )

    fixed_calls = []
    still_invalid = []

    for call in invalid_calls:
        normalized_call, changed = _normalize_tool_call_name(call)
        changes_made = changes_made or changed

        if not isinstance(normalized_call, dict):
            still_invalid.append(normalized_call)
            continue

        args = normalized_call.get("args")
        parsed_args = _try_parse_args(args)

        if parsed_args is not None:
            # Successfully parsed, move to tool_calls
            fixed_call = _build_fixed_tool_call(normalized_call, parsed_args)
            fixed_calls.append(fixed_call)
            changes_made = True
            logger.debug(
                f"Fixed invalid tool call: name={normalized_call.get('name')}, "
                f"parsed args from string to dict"
            )
        else:
            still_invalid.append(normalized_call)

    if not fixed_calls and not changes_made:
        return message

    # Build new message with fixed calls
    normalized_tool_calls.extend(fixed_calls)

    # Create new message with fixed tool_calls
    return AIMessage(
        content=message.content,
        name=message.name,
        id=message.id,
        response_metadata=message.response_metadata,
        usage_metadata=message.usage_metadata,
        additional_kwargs=message.additional_kwargs,
        tool_calls=normalized_tool_calls,
        invalid_tool_calls=still_invalid,
    )


class InvalidToolCallFixMiddleware(AgentMiddleware[AgentState]):
    """Repairs malformed tool calls and normalizes known tool-name aliases.

    Some LLM providers return tool_calls with args as JSON strings instead of
    dicts. This causes LangChain to mark them as invalid. This middleware
    attempts to parse those strings and moves successfully parsed calls to
    tool_calls so they can be executed. It also normalizes a small set of
    known provider aliases, such as ``todo_write`` -> ``write_todos``.
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

        fixed_message = _fix_invalid_tool_calls(last_message)
        if fixed_message is last_message:
            # No changes made
            return None

        # Replace the last message with the fixed version
        new_messages = list(messages[:-1]) + [fixed_message]
        original_invalid_calls = getattr(last_message, "invalid_tool_calls", None) or []
        repaired_count = len(original_invalid_calls) - len(fixed_message.invalid_tool_calls)
        renamed_count = sum(
            1
            for before, after in zip(getattr(last_message, "tool_calls", []) or [], fixed_message.tool_calls)
            if isinstance(before, dict) and isinstance(after, dict) and before.get("name") != after.get("name")
        )
        logger.info(
            "Normalized tool calls in model response: repaired_invalid=%s renamed=%s",
            repaired_count,
            renamed_count,
        )
        return {"messages": new_messages}

    @override
    async def aafter_model(self, state: AgentState, runtime: Runtime) -> AgentState | None:
        """Async version of after_model."""
        return self.after_model(state, runtime)
