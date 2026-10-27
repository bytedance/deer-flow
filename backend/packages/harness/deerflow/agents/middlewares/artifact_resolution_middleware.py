"""Middleware that resolves artifact handles in tool arguments to real references.

The model references artifacts by short handles (``art_xxxxxxxx``). Before a
tool executes, this middleware replaces those handles in the tool-call arguments
with the real reference (path, URL, task id) recorded in
``ThreadState.tool_artifacts``. Handles may appear bare, inside backticks, or
embedded in a longer string. Unknown or expired handles return a structured
error without executing the tool.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from deerflow.agents.middlewares.tool_result_meta import normalize_tool_result
from deerflow.agents.task_continuity.state import RESOLVED_TOOL_CALL_ARGS_KEY
from deerflow.config.tool_artifact_config import ToolArtifactConfig

_HANDLE_PATTERN = r"(?:`(art_[0-9a-f]{8})`|(?<!\w)(art_[0-9a-f]{8})(?!\w))"


class ArtifactResolutionMiddleware(AgentMiddleware[AgentState]):
    """Resolve artifact handles in tool arguments before execution."""

    def __init__(self, config: ToolArtifactConfig | None = None) -> None:
        super().__init__()
        self._config = config or ToolArtifactConfig()
        self._handle_re = re.compile(_HANDLE_PATTERN)

    @override
    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        if not (self._config.enabled and self._config.resolve_handles_in_args):
            return handler(request)
        resolved = self._resolve_request(request)
        return resolved if isinstance(resolved, ToolMessage) else handler(resolved)

    @override
    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        if not (self._config.enabled and self._config.resolve_handles_in_args):
            return await handler(request)
        resolved = self._resolve_request(request)
        return resolved if isinstance(resolved, ToolMessage) else await handler(resolved)

    def _resolve_request(self, request: ToolCallRequest) -> ToolCallRequest | ToolMessage:
        args = request.tool_call.get("args")
        if not isinstance(args, dict):
            return request

        state = request.state or {}
        artifacts = state.get("tool_artifacts") or []
        handle_map: dict[str, str] = {}
        for entry in artifacts:
            if isinstance(entry, dict) and entry.get("handle") and isinstance(entry.get("real_ref"), str) and entry["real_ref"]:
                handle_map[str(entry["handle"])] = entry["real_ref"]

        unknown = self._unknown_handles(args, handle_map)
        if unknown:
            missing = ", ".join(sorted(unknown)[:10])
            if len(unknown) > 10:
                missing += f" (and {len(unknown) - 10} more)"
            available = [h for h in handle_map if re.fullmatch(r"art_[0-9a-f]{8}", h)]
            current = ", ".join(available[-10:]) or "none"
            message = ToolMessage(
                content=(
                    f"Error: Unknown or expired artifact handle(s): {missing}. Handles are local to this agent. Current handles (up to 10): {current}. Use a current handle or obtain a new concrete reference; do not guess a replacement."
                ),
                name=str(request.tool_call.get("name") or "unknown"),
                tool_call_id=str(request.tool_call.get("id") or "missing_tool_call_id"),
                status="error",
            )
            return normalize_tool_result(message, tool_call_id=message.tool_call_id)

        # Share resolved batch arguments for note admission only in this runtime; preserve message history.
        if request.tool_call.get("name") == "task_note" and request.runtime is not None:
            runtime = request.runtime
            message = next((message for message in reversed(runtime.state.get("messages", [])) if isinstance(message, AIMessage)), None)
            if message is not None:
                resolved_calls = {call["id"]: self._resolve_value(call["args"], handle_map) for call in message.tool_calls if call["name"] == "task_note"}
                request = replace(request, runtime=replace(runtime, state={**runtime.state, RESOLVED_TOOL_CALL_ARGS_KEY: resolved_calls}))

        resolved_args = self._resolve_value(args, handle_map)
        if resolved_args == args:
            return request
        return request.override(tool_call={**request.tool_call, "args": resolved_args})

    def _unknown_handles(self, value, handle_map: dict[str, str]) -> set[str]:
        if isinstance(value, str):
            return {handle for match in self._handle_re.finditer(value) if (handle := match.group(1) or match.group(2)) not in handle_map}
        if isinstance(value, dict):
            value = list(value.values())
        if isinstance(value, list):
            return set().union(*(self._unknown_handles(item, handle_map) for item in value))
        return set()

    def _resolve_value(self, value, handle_map: dict[str, str]):
        if isinstance(value, str):
            return self._resolve_string(value, handle_map)
        if isinstance(value, dict):
            return {key: self._resolve_value(item, handle_map) for key, item in value.items()}
        if isinstance(value, list):
            return [self._resolve_value(item, handle_map) for item in value]
        return value

    def _resolve_string(self, text: str, handle_map: dict[str, str]) -> str:
        def replace_handle(match: re.Match) -> str:
            handle = match.group(1) or match.group(2)
            real_ref = handle_map.get(handle)
            if real_ref:
                return real_ref
            return match.group(0)

        return self._handle_re.sub(replace_handle, text)
