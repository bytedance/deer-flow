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
from collections.abc import Awaitable, Callable, Iterator, Mapping
from dataclasses import dataclass, replace
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
from deerflow.sandbox.tools import literal_shell_file_operands
from deerflow.utils.bash_exit import BASH_TOOL_NAMES

_HANDLE_PATTERN = r"(?:`(art_[0-9a-f]{8})`|(?<!\w)(art_[0-9a-f]{8})(?!\w))"
_PENDING_DIAGNOSTIC_BLOBS = "__deerflow_pending_diagnostic_blobs"
_ArgumentPosition = tuple[str | int, ...]
_ArgumentField = tuple[str | int | None, ...]


@dataclass(frozen=True, slots=True)
class _DiagnosticUse:
    payload: Mapping[str, Any]
    field: _ArgumentField
    resolved_argument: str


@dataclass(frozen=True, slots=True)
class _PendingDiagnosticBlobs:
    uses: list[_DiagnosticUse]


def _argument_strings(value: Any, position: _ArgumentPosition = ()) -> Iterator[tuple[_ArgumentPosition, str]]:
    if isinstance(value, str):
        yield position, value
    elif isinstance(value, dict):
        for key, child in value.items():
            yield from _argument_strings(child, (*position, key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _argument_strings(child, (*position, index))


def _argument_field(position: _ArgumentPosition) -> _ArgumentField:
    """Group string items within the same list while keeping sibling fields distinct."""
    if position and isinstance(position[-1], int):
        return (*position[:-1], None)
    return position


def _retains_path(path: str, original: str, approved: str) -> bool:
    if approved in (original, path):
        return True
    # Preserve paths embedded in compound arguments, such as shell commands.
    # A literal path argument cannot turn into an embedded match after editing.
    if original == path:
        return False
    pattern = re.compile(rf"""(?:^|[\s"'`=|&;<>()\[\]{{}}]){re.escape(path)}(?=$|[\s"'`|&;<>()\[\]{{}}])""")
    return pattern.search(approved) is not None


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
        entries = {str(entry["handle"]): entry for entry in state.get("tool_artifacts") or [] if isinstance(entry, dict) and entry.get("handle") and isinstance(entry.get("real_ref"), str) and entry["real_ref"]}
        handle_map = {handle: entry["real_ref"] for handle, entry in entries.items()}

        uses_by_position = {}
        for position, text in _argument_strings(args):
            if handles := {match.group(1) or match.group(2) for match in self._handle_re.finditer(text)}:
                uses_by_position[position] = handles
        referenced = set().union(*uses_by_position.values())
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
        blobs = {handle: blob for handle in referenced if isinstance(blob := entries[handle].get(TOOL_OUTPUT_BLOB_KEY), Mapping) and blob.get("virtual_path") == handle_map[handle]}
        if blobs:
            uses = [
                _DiagnosticUse(blobs[handle], _argument_field(position), text)
                for position, text in _argument_strings(resolved_args)
                if "description" not in position  # Display text never requests file I/O.
                for handle in uses_by_position.get(position, ())
                if handle in blobs
            ]
            # Keep the restore plan on this request copy. Policies see the
            # resolved arguments and the checkpoint retains the original state.
            if uses:
                request = request.override(state={**state, _PENDING_DIAGNOSTIC_BLOBS: _PendingDiagnosticBlobs(uses)})
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


class ArtifactBlobRestoreMiddleware(AgentMiddleware[AgentState]):
    """Materialize diagnostics only for tool calls that passed the policy gates."""

    @staticmethod
    def _approved_payloads(request: ToolCallRequest) -> list[Mapping[str, Any]]:
        state = request.state
        pending = state.get(_PENDING_DIAGNOSTIC_BLOBS) if isinstance(state, Mapping) else None
        if not isinstance(pending, _PendingDiagnosticBlobs):
            return []
        approved: dict[_ArgumentField, list[str]] = {}
        for position, argument in _argument_strings(request.tool_call.get("args")):
            approved.setdefault(_argument_field(position), []).append(argument)
        command_operands = None
        if request.tool_call.get("name") in BASH_TOOL_NAMES:
            command_operands = {path for command in approved.get(("command",), ()) for path in literal_shell_file_operands(command)}
        payloads = {}
        for use in pending.uses:
            path = use.payload["virtual_path"]
            if use.field == ("command",) and command_operands is not None:
                retained = path in command_operands
            else:
                retained = any(_retains_path(path, use.resolved_argument, argument) for argument in approved.get(use.field, ()))
            if retained:
                payloads[path] = use.payload
        return list(payloads.values())

    @override
    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        if payloads := self._approved_payloads(request):
            restore_tool_artifact_blobs(request, payloads)
        return handler(request)

    @override
    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        if payloads := self._approved_payloads(request):
            await run_sync_lifecycle_operation(restore_tool_artifact_blobs, request, payloads)
        return await handler(request)
