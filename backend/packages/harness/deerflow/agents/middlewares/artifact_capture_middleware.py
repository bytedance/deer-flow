"""Middleware that captures tool-result artifacts into ``ThreadState.tool_artifacts``.

Runs as a ``before_model`` hook (not ``wrap_tool_call``) so it never wraps a
``ToolMessage`` in a ``Command``. It scans the message tail for tool messages
whose artifacts have not been captured yet, extracts ``ArtifactEntry`` records,
and returns a state update. It also tracks which handles were consumed by later
tool calls so the model-context projection can mark them ``[consumed]``.
"""

from __future__ import annotations

import re
from typing import Any, cast, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.runtime import Runtime

from deerflow.agents.thread_state import ArtifactEntry
from deerflow.config.tool_artifact_config import ToolArtifactConfig
from deerflow.tools.artifact_registry import extract_artifacts_from_result

_HANDLE_PATTERN = r"(?:`(art_[0-9a-f]{8})`|(?<!\w)(art_[0-9a-f]{8})(?!\w))"


class ArtifactCaptureMiddleware(AgentMiddleware[AgentState]):
    """Capture tool-result artifact references into durable thread state."""

    def __init__(self, config: ToolArtifactConfig | None = None) -> None:
        super().__init__()
        self._config = config or ToolArtifactConfig()
        self._handle_re = re.compile(_HANDLE_PATTERN)

    @override
    def before_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        return self._merge_updates(self._capture(state, runtime), self._track_consumption(state))

    @override
    async def abefore_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        return self._merge_updates(self._capture(state, runtime), self._track_consumption(state))

    @staticmethod
    def _merge_updates(*updates: dict | None) -> dict | None:
        """Merge state updates without clobbering list channels.

        Both ``_capture`` and ``_track_consumption`` can fire in the same
        ``before_model`` call; a plain ``dict.update`` would replace the shared
        ``tool_artifacts`` value and silently drop one side's entries. List
        values under the same key are concatenated instead — the reducer is
        same-handle latest-wins, so duplicates collapse safely.
        """
        merged: dict[str, Any] = {}
        for update in updates:
            if not update:
                continue
            for key, value in update.items():
                if key in merged and isinstance(merged[key], list) and isinstance(value, list):
                    merged[key] = [*merged[key], *value]
                else:
                    merged[key] = value
        return merged or None

    def _thread_id(self, runtime: Runtime | None) -> str:
        context = getattr(runtime, "context", None)
        tid = context.get("thread_id") if isinstance(context, dict) else None
        return str(tid) if tid else ""

    def _capture(self, state: AgentState, runtime: Runtime | None) -> dict | None:
        if not self._config.enabled:
            return None
        thread_id = self._thread_id(runtime)
        if not thread_id:
            return None

        messages = state.get("messages") or []
        existing = state.get("tool_artifacts") or []
        existing_handles = {entry.get("handle") for entry in existing if isinstance(entry, dict)}

        new_entries: list[ArtifactEntry] = []
        for message in messages:
            if not isinstance(message, ToolMessage):
                continue
            entries = extract_artifacts_from_result(message, thread_id=thread_id, detect_refs_in_text=self._config.detect_refs_in_text)
            for entry in entries:
                if entry["handle"] in existing_handles:
                    continue
                existing_handles.add(entry["handle"])
                new_entries.append(entry)

        if new_entries:
            return {"tool_artifacts": new_entries}
        return None

    def _track_consumption(self, state: AgentState) -> dict | None:
        existing = state.get("tool_artifacts") or []
        if not existing:
            return None
        handle_map: dict[str, ArtifactEntry] = {
            entry["handle"]: cast(ArtifactEntry, entry) for entry in existing if isinstance(entry, dict)
        }
        if not handle_map:
            return None

        messages = state.get("messages") or []
        consumed_updates: list[ArtifactEntry] = []
        for message in messages:
            if not isinstance(message, AIMessage):
                continue
            for tool_call in message.tool_calls or []:
                tool_call_id = tool_call.get("id")
                args = tool_call.get("args")
                if not tool_call_id or not isinstance(args, dict):
                    continue
                for handle in self._find_handles(args):
                    entry = handle_map.get(handle)
                    if entry is None:
                        continue
                    consumed = list(entry.get("consumed_by") or [])
                    if tool_call_id in consumed:
                        continue
                    updated: dict[str, Any] = {**entry, "consumed_by": [*consumed, tool_call_id]}
                    consumed_updates.append(cast(ArtifactEntry, updated))
                    handle_map[handle] = consumed_updates[-1]

        if consumed_updates:
            return {"tool_artifacts": consumed_updates}
        return None

    def _find_handles(self, value: Any) -> set[str]:
        """Recursively find artifact handles in tool-call args."""
        handles: set[str] = set()
        if isinstance(value, str):
            for match in self._handle_re.finditer(value):
                handles.add(match.group(1) or match.group(2))
        elif isinstance(value, dict):
            for item in value.values():
                handles.update(self._find_handles(item))
        elif isinstance(value, list):
            for item in value:
                handles.update(self._find_handles(item))
        return handles