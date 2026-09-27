"""Middleware that captures tool-result artifacts into ``ThreadState.tool_artifacts``.

Runs as a ``before_model`` hook (not ``wrap_tool_call``) so it never wraps a
``ToolMessage`` in a ``Command``. It scans the message tail for tool messages
whose artifacts have not been captured yet, extracts ``ArtifactEntry`` records,
and returns a state update. It also tracks which handles were consumed by later
tool calls so the model-context projection can mark them ``[consumed]``.
"""

from __future__ import annotations

import hashlib
import json
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
        if not self._config.enabled:
            return None
        thread_id = self._thread_id(runtime)
        capture_update = self._capture(state, runtime)
        pending: list[ArtifactEntry] = []
        if capture_update:
            pending = [cast(ArtifactEntry, item) for item in capture_update.get("tool_artifacts", []) if isinstance(item, dict) and "handle" in item]
        consumption_update = self._track_consumption(state, thread_id, pending)
        return self._merge_updates(capture_update, consumption_update)

    @override
    async def abefore_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        if not self._config.enabled:
            return None
        thread_id = self._thread_id(runtime)
        capture_update = self._capture(state, runtime)
        pending: list[ArtifactEntry] = []
        if capture_update:
            pending = [cast(ArtifactEntry, item) for item in capture_update.get("tool_artifacts", []) if isinstance(item, dict) and "handle" in item]
        consumption_update = self._track_consumption(state, thread_id, pending)
        return self._merge_updates(capture_update, consumption_update)

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
        processed = set(state.get("tool_artifact_processed") or [])
        newly_processed: list[str] = []
        occurrences: dict[str, int] = {}
        new_entries: list[ArtifactEntry] = []
        for message in messages:
            if not isinstance(message, ToolMessage):
                continue
            tool_call_id = message.tool_call_id or ""
            call_index = occurrences.get(tool_call_id, 0)
            occurrences[tool_call_id] = call_index + 1
            identity = self._occurrence_key("result", thread_id, message.id, tool_call_id, call_index)
            if identity in processed:
                continue
            entries = extract_artifacts_from_result(message, thread_id=thread_id, call_index=0 if message.id is not None else call_index, detect_refs_in_text=self._config.detect_refs_in_text)
            processed.add(identity)
            newly_processed.append(identity)
            if not entries:
                continue
            for entry in entries:
                if entry["handle"] in existing_handles:
                    continue
                existing_handles.add(entry["handle"])
                new_entries.append(entry)

        update: dict[str, Any] = {}
        if newly_processed:
            update["tool_artifact_processed"] = newly_processed
        if new_entries:
            update["tool_artifacts"] = new_entries
            if len(existing) + len(new_entries) > self._config.max_entries:
                update["tool_artifacts"].append({"op": "trim_to", "keep": self._config.max_entries})
        return update or None

    @staticmethod
    def _occurrence_key(kind: str, thread_id: str, message_id: str | None, tool_call_id: str, index: int) -> str:
        # Graph message reducers assign durable IDs, including to imported
        # history. The index fallback supports standalone ID-less hook callers.
        seed = [thread_id, message_id, tool_call_id, index if message_id is None or kind == "call" else 0]
        return kind + ":" + hashlib.sha256(json.dumps(seed).encode("utf-8")).hexdigest()

    def _track_consumption(self, state: AgentState, thread_id: str = "", pending_entries: list[ArtifactEntry] | None = None) -> dict | None:
        # The effective registry includes entries being captured in this very
        # before_model call: an AIMessage may already reference a handle whose
        # registration rides along in the same update, and settling the scan as
        # "quiet" on a transient miss would lose the consumption mark forever.
        registry_items: list[Any] = [*(state.get("tool_artifacts") or []), *(pending_entries or [])]
        if not registry_items:
            return None
        handle_map: dict[str, ArtifactEntry] = {entry["handle"]: cast(ArtifactEntry, entry) for entry in registry_items if isinstance(entry, dict)}
        if not handle_map:
            return None

        messages = state.get("messages") or []
        consumed_updates: list[ArtifactEntry] = []
        processed = set(state.get("tool_artifact_processed") or [])
        newly_processed: list[str] = []
        occurrences: dict[str, int] = {}
        for message in messages:
            if not isinstance(message, AIMessage):
                continue
            for tool_index, tool_call in enumerate(message.tool_calls or []):
                tool_call_id = tool_call.get("id")
                args = tool_call.get("args")
                if not tool_call_id or not isinstance(args, dict):
                    continue
                # Args are immutable once in state. Settle the call only when
                # every referenced handle resolved against the effective
                # registry; a transient miss retries next round.
                fallback_index = occurrences.get(tool_call_id, 0)
                occurrences[tool_call_id] = fallback_index + 1
                quiet_key = self._occurrence_key("call", thread_id, message.id, tool_call_id, tool_index if message.id is not None else fallback_index)
                if quiet_key in processed:
                    continue
                had_unresolved = False
                for handle in self._find_handles(args):
                    entry = handle_map.get(handle)
                    if entry is None:
                        had_unresolved = True
                        continue
                    consumed = list(entry.get("consumed_by") or [])
                    if tool_call_id in consumed:
                        continue
                    updated: dict[str, Any] = {**entry, "consumed_by": [*consumed, tool_call_id]}
                    consumed_updates.append(cast(ArtifactEntry, updated))
                    handle_map[handle] = consumed_updates[-1]
                if not had_unresolved:
                    processed.add(quiet_key)
                    newly_processed.append(quiet_key)

        update: dict[str, Any] = {}
        if consumed_updates:
            update["tool_artifacts"] = consumed_updates
        if newly_processed:
            update["tool_artifact_processed"] = newly_processed
        return update or None

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
