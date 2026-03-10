"""Middleware for logging a chronological timeline of thread messages.

Supports two storage backends:
- **Database mode** (when DATABASE_URL is set): append-only INSERTs into
  the ``timeline_events`` table — no locking required.
- **File mode** (fallback): atomic JSON file writes under the thread's
  outputs directory, guarded by a module-level threading lock.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
from datetime import UTC, datetime
from typing import Any, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langgraph.runtime import Runtime

from src.config.paths import get_paths

logger = logging.getLogger(__name__)

# Set to "1"/"true"/"yes" to force file-mode timeline logging (dev-only).
_FORCE_FILE_MODE = os.getenv("THINKTANK_TIMELINE_FILE_MODE", "").strip().lower() in {"1", "true", "yes"}

# ---------------------------------------------------------------------------
# File-mode helpers (kept for backward-compatibility when no DB is configured)
# ---------------------------------------------------------------------------

_WRITE_LOCK = threading.Lock()


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _resolve_outputs_path(state: AgentState, thread_id: str) -> str:
    thread_data = state.get("thread_data") or {}
    outputs_path = thread_data.get("outputs_path")
    if outputs_path:
        os.makedirs(outputs_path, exist_ok=True)
        return outputs_path
    fallback_path = get_paths().sandbox_outputs_dir(thread_id)
    fallback_path.mkdir(parents=True, exist_ok=True)
    return str(fallback_path)


def _serialize_message(message: Any) -> dict:
    if hasattr(message, "model_dump"):
        return message.model_dump()
    if hasattr(message, "dict"):
        return message.dict()
    return {
        "type": getattr(message, "type", None),
        "content": getattr(message, "content", None),
        "additional_kwargs": getattr(message, "additional_kwargs", None),
    }


def _load_timeline(file_path: str, thread_id: str) -> dict:
    if os.path.exists(file_path):
        try:
            with open(file_path, encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict) and "events" in data:
                return data
        except Exception:
            pass
    return {
        "schema_version": 1,
        "thread_id": thread_id,
        "created_at": _utc_now(),
        "updated_at": _utc_now(),
        "last_message_index": 0,
        "last_subagent_signatures": {},
        "events": [],
    }


def _write_timeline(file_path: str, data: dict) -> None:
    temp_path = f"{file_path}.tmp"
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=True)
    os.replace(temp_path, file_path)


# ---------------------------------------------------------------------------
# Database-mode helpers
# ---------------------------------------------------------------------------

# Per-thread in-memory cache so we don't query the DB on every middleware call.
# Initialised lazily from the latest DB row on first access per thread.
_db_last_index: dict[str, int] = {}
_db_last_index_lock = threading.Lock()
_db_subagent_signatures: dict[str, dict[str, str]] = {}
_db_subagent_signatures_lock = threading.Lock()


def _db_get_last_message_index(session: Any, thread_id: str) -> int:
    """Return the effective ``last_message_index`` for *thread_id*.

    The value is cached in-memory after the first DB query.  On process
    restart the cache is cold so we derive the value from the most recent
    ``timeline_events`` row for the thread.
    """
    with _db_last_index_lock:
        cached = _db_last_index.get(thread_id)
    if cached is not None:
        return cached

    from src.db.models import TimelineEventModel

    latest = (
        session.query(TimelineEventModel)
        .filter(
            TimelineEventModel.thread_id == thread_id,
            TimelineEventModel.event_type.in_(["message", "history_truncated"]),
        )
        .order_by(TimelineEventModel.id.desc())
        .first()
    )

    if latest is None:
        idx = 0
    elif latest.event_type == "history_truncated":
        # After truncation the effective index resets to current_length.
        data = latest.message_data or {}
        idx = data.get("current_length", 0)
    else:
        # For message events, last_message_index == message_index + 1.
        idx = (latest.message_index or 0) + 1

    with _db_last_index_lock:
        _db_last_index[thread_id] = idx
    return idx


def _db_set_last_message_index(thread_id: str, value: int) -> None:
    with _db_last_index_lock:
        _db_last_index[thread_id] = value


def _json_signature(payload: Any) -> str:
    try:
        return json.dumps(payload, sort_keys=True, ensure_ascii=True)
    except Exception:
        return repr(payload)


def _db_get_subagent_signatures(session: Any, thread_id: str) -> dict[str, str]:
    with _db_subagent_signatures_lock:
        cached = _db_subagent_signatures.get(thread_id)
    if cached is not None:
        return cached

    from src.db.models import TimelineEventModel

    signatures: dict[str, str] = {}
    rows = (
        session.query(TimelineEventModel)
        .filter(TimelineEventModel.thread_id == thread_id, TimelineEventModel.event_type == "subagent_trajectory")
        .order_by(TimelineEventModel.id.asc())
        .all()
    )
    for row in rows:
        if row.message_id and row.message_data is not None:
            signatures[row.message_id] = _json_signature(row.message_data)

    with _db_subagent_signatures_lock:
        _db_subagent_signatures[thread_id] = signatures
    return signatures


def _db_record_messages(
    thread_id: str,
    messages: list,
    stage: str,
) -> None:
    """Persist new timeline events to the database via append-only INSERTs."""
    from src.db.engine import get_db_session
    from src.db.models import TimelineEventModel

    with get_db_session() as session:
        last_index = _db_get_last_message_index(session, thread_id)
        current_len = len(messages)

        if current_len < last_index:
            # History was truncated — record the event.
            session.add(
                TimelineEventModel(
                    thread_id=thread_id,
                    event_type="history_truncated",
                    stage=stage,
                    message_data={
                        "previous_last_index": last_index,
                        "current_length": current_len,
                    },
                )
            )
            _db_set_last_message_index(thread_id, current_len)
            last_index = current_len

        if current_len > last_index:
            for idx in range(last_index, current_len):
                msg = messages[idx]
                session.add(
                    TimelineEventModel(
                        thread_id=thread_id,
                        event_type="message",
                        stage=stage,
                        message_index=idx,
                        role=getattr(msg, "type", None),
                        message_id=getattr(msg, "id", None),
                        message_data=_serialize_message(msg),
                    )
                )
            _db_set_last_message_index(thread_id, current_len)

        # session.commit() is handled by the get_db_session context manager.


def _db_record_subagent_trajectories(
    thread_id: str,
    trajectories: dict[str, Any],
    stage: str,
) -> None:
    """Persist changed subagent trajectory snapshots to the database."""
    from src.db.engine import get_db_session
    from src.db.models import TimelineEventModel

    if not isinstance(trajectories, dict) or not trajectories:
        return

    with get_db_session() as session:
        signatures = _db_get_subagent_signatures(session, thread_id)
        changed = False

        for task_id, trajectory in trajectories.items():
            signature = _json_signature(trajectory)
            if signatures.get(task_id) == signature:
                continue

            session.add(
                TimelineEventModel(
                    thread_id=thread_id,
                    event_type="subagent_trajectory",
                    stage=stage,
                    role="subagent",
                    message_id=task_id,
                    message_data=trajectory if isinstance(trajectory, dict) else {"value": trajectory},
                )
            )
            signatures[task_id] = signature
            changed = True

        if changed:
            with _db_subagent_signatures_lock:
                _db_subagent_signatures[thread_id] = signatures


# ---------------------------------------------------------------------------
# File-mode recording (original implementation)
# ---------------------------------------------------------------------------


def _file_record_messages(
    state: AgentState,
    thread_id: str,
    messages: list,
    stage: str,
) -> None:
    """Persist new timeline events to a JSON file (legacy file-based mode)."""
    outputs_path = _resolve_outputs_path(state, thread_id)
    timeline_path = os.path.join(outputs_path, "agent_timeline.json")

    with _WRITE_LOCK:
        timeline = _load_timeline(timeline_path, thread_id)
        last_index = int(timeline.get("last_message_index", 0) or 0)
        current_len = len(messages)

        if current_len < last_index:
            timeline["events"].append(
                {
                    "event": "history_truncated",
                    "timestamp": _utc_now(),
                    "stage": stage,
                    "previous_last_index": last_index,
                    "current_length": current_len,
                }
            )
            last_index = current_len

        if current_len > last_index:
            for idx in range(last_index, current_len):
                msg = messages[idx]
                timeline["events"].append(
                    {
                        "event": "message",
                        "timestamp": _utc_now(),
                        "stage": stage,
                        "message_index": idx,
                        "role": getattr(msg, "type", None),
                        "message_id": getattr(msg, "id", None),
                        "message": _serialize_message(msg),
                    }
                )
            timeline["last_message_index"] = current_len
            timeline["updated_at"] = _utc_now()

        _write_timeline(timeline_path, timeline)


def _file_record_subagent_trajectories(
    state: AgentState,
    thread_id: str,
    trajectories: dict[str, Any],
    stage: str,
) -> None:
    """Persist changed subagent trajectory snapshots to timeline JSON."""
    if not isinstance(trajectories, dict) or not trajectories:
        return

    outputs_path = _resolve_outputs_path(state, thread_id)
    timeline_path = os.path.join(outputs_path, "agent_timeline.json")

    with _WRITE_LOCK:
        timeline = _load_timeline(timeline_path, thread_id)
        signatures = timeline.get("last_subagent_signatures", {})
        if not isinstance(signatures, dict):
            signatures = {}

        changed = False
        for task_id, trajectory in trajectories.items():
            signature = _json_signature(trajectory)
            if signatures.get(task_id) == signature:
                continue

            timeline["events"].append(
                {
                    "event": "subagent_trajectory",
                    "timestamp": _utc_now(),
                    "stage": stage,
                    "task_id": task_id,
                    "trajectory": trajectory,
                }
            )
            signatures[task_id] = signature
            changed = True

        if changed:
            timeline["last_subagent_signatures"] = signatures
            timeline["updated_at"] = _utc_now()
            _write_timeline(timeline_path, timeline)


# ---------------------------------------------------------------------------
# Middleware class
# ---------------------------------------------------------------------------


class TimelineLoggingMiddleware(AgentMiddleware[AgentState]):
    """Logs thread messages (human/ai/tool) as an ordered timeline.

    When ``DATABASE_URL`` is configured, events are persisted as
    append-only rows in the ``timeline_events`` table (no locking).
    Otherwise falls back to atomic JSON file writes.
    """

    def _record_messages(self, state: AgentState, runtime: Runtime, stage: str) -> None:
        thread_id = runtime.context.get("thread_id")
        if not thread_id:
            return

        messages = state.get("messages", [])
        if not isinstance(messages, list):
            return

        try:
            from src.db.engine import is_db_enabled

            if not _FORCE_FILE_MODE and is_db_enabled():
                _db_record_messages(thread_id, messages, stage)
                _db_record_subagent_trajectories(thread_id, state.get("subagent_trajectories", {}), stage)
            else:
                _file_record_messages(state, thread_id, messages, stage)
                _file_record_subagent_trajectories(state, thread_id, state.get("subagent_trajectories", {}), stage)
        except Exception:
            # Timeline logging should never break the agent loop.
            logger.exception("Timeline recording failed for thread %s", thread_id)

    @override
    def before_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        self._record_messages(state, runtime, "before_model")
        return None

    @override
    def after_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        self._record_messages(state, runtime, "after_model")
        return None

    @override
    def after_agent(self, state: AgentState, runtime: Runtime) -> dict | None:
        self._record_messages(state, runtime, "after_agent")
        return None

    @override
    async def abefore_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        await asyncio.to_thread(self._record_messages, state, runtime, "before_model")
        return None

    @override
    async def aafter_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        await asyncio.to_thread(self._record_messages, state, runtime, "after_model")
        return None

    @override
    async def aafter_agent(self, state: AgentState, runtime: Runtime) -> dict | None:
        await asyncio.to_thread(self._record_messages, state, runtime, "after_agent")
        return None
