"""Compact oversized historical tool-call args before the next model request."""

from __future__ import annotations

from collections import defaultdict, deque
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

        completed_tool_call_positions = self._completed_tool_call_positions(messages)
        if not completed_tool_call_positions:
            return None

        patched: list[Any] = []
        changed = False
        for message_index, msg in enumerate(messages):
            if not isinstance(msg, AIMessage) or not msg.tool_calls:
                patched.append(msg)
                continue

            new_tool_calls: list[dict[str, Any]] = []
            message_changed = False
            for tool_call_index, tool_call in enumerate(msg.tool_calls):
                updated_tool_call, tool_call_changed = self._compact_tool_call(tool_call, (message_index, tool_call_index) in completed_tool_call_positions)
                new_tool_calls.append(updated_tool_call)
                message_changed = message_changed or tool_call_changed

            if message_changed:
                patched.append(clone_ai_message_with_updated_tool_calls(msg, new_tool_calls))
                changed = True
            else:
                patched.append(msg)

        return patched if changed else None

    def _completed_tool_call_positions(self, messages: list[Any]) -> set[tuple[int, int]]:
        pending_tool_calls_by_id: dict[str, deque[tuple[int, int]]] = defaultdict(deque)
        completed_positions: set[tuple[int, int]] = set()

        for message_index, msg in enumerate(messages):
            if isinstance(msg, AIMessage) and msg.tool_calls:
                for tool_call_index, tool_call in enumerate(msg.tool_calls):
                    tool_call_id = tool_call.get("id")
                    if isinstance(tool_call_id, str) and tool_call_id:
                        pending_tool_calls_by_id[tool_call_id].append((message_index, tool_call_index))
                continue

            if not isinstance(msg, ToolMessage) or _is_synthetic_dangling_tool_result(msg):
                continue
            tool_call_id = msg.tool_call_id
            if not isinstance(tool_call_id, str) or not tool_call_id:
                continue

            pending_positions = pending_tool_calls_by_id.get(tool_call_id)
            if pending_positions:
                completed_positions.add(pending_positions.popleft())

        return completed_positions

    def _compact_tool_call(
        self,
        tool_call: dict[str, Any],
        is_completed: bool,
    ) -> tuple[dict[str, Any], bool]:
        if not is_completed:
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
