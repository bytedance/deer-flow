"""Middleware that resolves artifact handles in tool arguments to real references.

The model references artifacts by short handles (``art_xxxxxxxx``). Before a
tool executes, this middleware replaces those handles in the tool-call arguments
with the real reference (path, URL, task id) recorded in
``ThreadState.tool_artifacts``. Handles may appear bare, inside backticks, or
embedded in a longer string; unknown handles are left untouched.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

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
        if not self._config.resolve_handles_in_args:
            return handler(request)
        resolved = self._resolve_request(request)
        return handler(resolved)

    @override
    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        if not self._config.resolve_handles_in_args:
            return await handler(request)
        resolved = self._resolve_request(request)
        return await handler(resolved)

    def _resolve_request(self, request: ToolCallRequest) -> ToolCallRequest:
        args = request.tool_call.get("args")
        if not isinstance(args, dict):
            return request

        state = request.state or {}
        artifacts = state.get("tool_artifacts") or []
        handle_map: dict[str, str] = {}
        for entry in artifacts:
            if isinstance(entry, dict) and entry.get("handle"):
                handle_map[str(entry["handle"])] = str(entry.get("real_ref") or "")

        if not handle_map:
            return request

        resolved_args = self._resolve_value(args, handle_map)
        if resolved_args == args:
            return request
        return request.override(tool_call={**request.tool_call, "args": resolved_args})

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