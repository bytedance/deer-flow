"""Compact oversized historical tool-call args before the next model request."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, ToolMessage

from deerflow.agents.middlewares.dangling_tool_call_middleware import SYNTHETIC_DANGLING_TOOL_RESULT_KEY
from deerflow.agents.middlewares.tool_call_metadata import clone_ai_message_with_updated_tool_calls

_DEFAULT_WRITE_FILE_CONTEXT_MAX_CHARS = 2000


def _omitted_write_file_content_marker(length: int) -> str:
    return f"[write_file content omitted in model context: {length} chars]"


def _is_synthetic_dangling_tool_result(message: ToolMessage) -> bool:
    return bool((getattr(message, "additional_kwargs", None) or {}).get(SYNTHETIC_DANGLING_TOOL_RESULT_KEY))


class ToolArgsCompactionMiddleware(AgentMiddleware[AgentState]):
    """Compacts oversized historical write_file args in the model-bound request view."""

    def __init__(self, *, write_file_max_chars: int = _DEFAULT_WRITE_FILE_CONTEXT_MAX_CHARS) -> None:
        self._write_file_max_chars = max(0, write_file_max_chars)

    def _build_compacted_messages(self, messages: list[Any]) -> list[Any] | None:
        if self._write_file_max_chars <= 0:
            return None

        completed_tool_call_ids = {msg.tool_call_id for msg in messages if isinstance(msg, ToolMessage) and isinstance(msg.tool_call_id, str) and msg.tool_call_id and not _is_synthetic_dangling_tool_result(msg)}
        if not completed_tool_call_ids:
            return None

        patched: list[Any] = []
        changed = False
        for msg in messages:
            if not isinstance(msg, AIMessage) or not msg.tool_calls:
                patched.append(msg)
                continue

            new_tool_calls: list[dict[str, Any]] = []
            message_changed = False
            for tool_call in msg.tool_calls:
                updated_tool_call, tool_call_changed = self._compact_tool_call(tool_call, completed_tool_call_ids)
                new_tool_calls.append(updated_tool_call)
                message_changed = message_changed or tool_call_changed

            if message_changed:
                patched.append(clone_ai_message_with_updated_tool_calls(msg, new_tool_calls))
                changed = True
            else:
                patched.append(msg)

        return patched if changed else None

    def _compact_tool_call(
        self,
        tool_call: dict[str, Any],
        completed_tool_call_ids: set[str],
    ) -> tuple[dict[str, Any], bool]:
        tool_call_id = tool_call.get("id")
        if not isinstance(tool_call_id, str) or tool_call_id not in completed_tool_call_ids:
            return tool_call, False
        if tool_call.get("name") != "write_file":
            return tool_call, False

        args = tool_call.get("args")
        if not isinstance(args, dict):
            return tool_call, False
        content = args.get("content")
        if not isinstance(content, str) or len(content) <= self._write_file_max_chars:
            return tool_call, False

        new_args = dict(args)
        new_args["content"] = _omitted_write_file_content_marker(len(content))
        new_tool_call = dict(tool_call)
        new_tool_call["args"] = new_args
        return new_tool_call, True

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        patched = self._build_compacted_messages(request.messages)
        if patched is not None:
            request = request.override(messages=patched)
        return handler(request)

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        patched = self._build_compacted_messages(request.messages)
        if patched is not None:
            request = request.override(messages=patched)
        return await handler(request)
