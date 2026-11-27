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
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import replace
from typing import Any, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from deerflow.agents.middlewares.tool_output_budget_middleware import restore_tool_artifact_blobs
from deerflow.agents.middlewares.tool_result_meta import normalize_tool_result
from deerflow.agents.middlewares.tool_transform_meta import TOOL_OUTPUT_BLOB_KEY
from deerflow.agents.task_continuity.state import RESOLVED_TOOL_CALL_ARGS_KEY
from deerflow.config.tool_artifact_config import ToolArtifactConfig
from deerflow.sandbox.lease import run_sync_lifecycle_operation

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
        resolved, blobs = self._resolve_request(request)
        if isinstance(resolved, ToolMessage):
            return resolved
        if blobs:
            restore_tool_artifact_blobs(resolved, blobs)
        return handler(resolved)

    @override
    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        if not (self._config.enabled and self._config.resolve_handles_in_args):
            return await handler(request)
        resolved, blobs = self._resolve_request(request)
        if isinstance(resolved, ToolMessage):
            return resolved
        if blobs:
            await run_sync_lifecycle_operation(restore_tool_artifact_blobs, resolved, blobs)
        return await handler(resolved)

    def _resolve_request(self, request: ToolCallRequest) -> tuple[ToolCallRequest | ToolMessage, list[Mapping[str, Any]]]:
        args = request.tool_call.get("args")
        if not isinstance(args, dict):
            return request, []

        state = request.state or {}
        entries = {str(entry["handle"]): entry for entry in state.get("tool_artifacts") or [] if isinstance(entry, dict) and entry.get("handle") and isinstance(entry.get("real_ref"), str) and entry["real_ref"]}
        handle_map = {handle: entry["real_ref"] for handle, entry in entries.items()}

        referenced = self._referenced_handles(args)
        unknown = referenced - handle_map.keys()
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
            return normalize_tool_result(message, tool_call_id=message.tool_call_id), []

        # Share resolved batch arguments for note admission only in this runtime; preserve message history.
        if request.tool_call.get("name") == "task_note" and request.runtime is not None:
            runtime = request.runtime
            message = next((message for message in reversed(runtime.state.get("messages", [])) if isinstance(message, AIMessage)), None)
            if message is not None:
                resolved_calls = {call["id"]: self._resolve_value(call["args"], handle_map) for call in message.tool_calls if call["name"] == "task_note"}
                request = replace(request, runtime=replace(runtime, state={**runtime.state, RESOLVED_TOOL_CALL_ARGS_KEY: resolved_calls}))

        resolved_args = self._resolve_value(args, handle_map)
        if resolved_args == args:
            return request, []
        blobs = [blob for handle in referenced if isinstance(blob := entries[handle].get(TOOL_OUTPUT_BLOB_KEY), Mapping) and blob.get("virtual_path") == handle_map[handle]]
        return request.override(tool_call={**request.tool_call, "args": resolved_args}), blobs

    def _referenced_handles(self, value) -> set[str]:
        if isinstance(value, str):
            return {match.group(1) or match.group(2) for match in self._handle_re.finditer(value)}
        if isinstance(value, dict):
            value = list(value.values())
        if isinstance(value, list):
            return set().union(*(self._referenced_handles(item) for item in value))
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
