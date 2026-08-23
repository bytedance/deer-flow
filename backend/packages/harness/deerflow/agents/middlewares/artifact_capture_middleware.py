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
        # Bounded memos (FIFO-evicted) so steady-state cost stays on the new
        # message tail instead of a full-history rescan per model call:
        # - _processed_results: extraction ran for this tool result, whatever it
        #   yielded. Recording successes too is what makes sliding-window
        #   evictions final — without it an evicted entry whose ToolMessage is
        #   still in context would resurrect (re-extract -> re-register) every
        #   round forever.
        # - _quiet_calls: args scan for this tool call fully resolved (nothing
        #   new to consume); settled calls are skipped entirely afterwards.
        self._processed_results: dict[tuple[str, str, bool], None] = {}
        self._quiet_calls: dict[tuple[str, str], None] = {}
        self._MEMO_LIMIT = 4096

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
        # Handles are deterministic per (thread_id, tool_call_id), so a message
        # that already contributed entries can never yield anything new on a
        # rescan — skip it before paying for extraction. Consumption updates
        # preserve `tool_call_id`, so this stays accurate across rounds.
        seen_call_ids = {entry.get("tool_call_id") for entry in existing if isinstance(entry, dict)}

        new_entries: list[ArtifactEntry] = []
        for message in messages:
            if not isinstance(message, ToolMessage):
                continue
            tool_call_id = message.tool_call_id or ""
            if tool_call_id and tool_call_id in seen_call_ids:
                continue
            memo_key = (thread_id, tool_call_id, self._config.detect_refs_in_text) if tool_call_id else None
            if memo_key is not None and memo_key in self._processed_results:
                continue
            entries = extract_artifacts_from_result(message, thread_id=thread_id, detect_refs_in_text=self._config.detect_refs_in_text)
            # Record the extraction itself, whatever it yielded: eviction plus a
            # still-present ToolMessage must not resurrect the entry next round.
            if memo_key is not None:
                self._remember_bounded(self._processed_results, memo_key)
            if not entries:
                continue
            for entry in entries:
                if entry["handle"] in existing_handles:
                    continue
                existing_handles.add(entry["handle"])
                new_entries.append(entry)

        if not new_entries:
            return None
        # Configured cap as a sliding window: when the projection exceeds it,
        # a trailing trim directive makes the reducer evict the oldest entries
        # (latest-wins merge keeps everything else intact). Fresh captures —
        # typically the artifacts that post-date compaction and matter most —
        # are always registered; nothing freezes at the cap.
        projected = len(existing) + len(new_entries)
        if projected > self._config.max_entries:
            return {"tool_artifacts": [*new_entries, {"op": "trim_to", "keep": self._config.max_entries}]}
        return {"tool_artifacts": new_entries}

    def _remember_bounded(self, memo: dict, key) -> None:  # noqa: ANN001
        while len(memo) >= self._MEMO_LIMIT:
            memo.pop(next(iter(memo)))
        memo[key] = None

    def _remember_quiet(self, quiet_key: tuple[str, str]) -> None:
        self._remember_bounded(self._quiet_calls, quiet_key)

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
        for message in messages:
            if not isinstance(message, AIMessage):
                continue
            for tool_call in message.tool_calls or []:
                tool_call_id = tool_call.get("id")
                args = tool_call.get("args")
                if not tool_call_id or not isinstance(args, dict):
                    continue
                # Args are immutable once in state. Settle the call only when
                # every referenced handle resolved against the effective
                # registry; a transient miss retries next round.
                quiet_key = (thread_id, tool_call_id)
                if quiet_key in self._quiet_calls:
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
                    self._remember_quiet(quiet_key)

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
