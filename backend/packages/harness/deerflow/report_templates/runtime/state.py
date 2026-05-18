"""Runtime state machine — backed by ``status.json`` per ReportRun.

Phase 4 §3.4: the runtime is **LLM-driven** — there is no background worker.
Each ``report_template_*`` tool is a stateless function that reads the
ReportRun's ``status.json`` to know where it is in the pipeline, makes one
transition, and writes the result back atomically.

State machine:

    pending
       │  prepare_run()
       ▼
    awaiting_step:<step_id>
       │  submit_step()              (when there are more form_steps)
       ▼
    awaiting_step:<next_step_id>
       │  submit_step()              (when next == "generate")
       ▼
    ready_for_data
       │  run_data_steps()
       ▼
    data_complete
       │  assemble_payload()
       ▼
    payload_ready
       │  render_report()
       ▼
    rendered
       │  export()
       ▼
    exported (terminal — also success)

    failed (terminal) — set by any tool that hits an unrecoverable error
    canceled (terminal) — reserved for Phase 4+; not yet emitted

The state file lives at::

    {run_output_dir}/status.json

The run_output_dir resolves to ``{thread_output_dir}/report-runs/{rr_id}/``
(§7.2). All runtime helpers receive the resolved path so this module stays
free of path-resolution policy.

Concurrency:
    Same-process atomicity is enforced by a per-path lock; cross-process
    safety relies on ``os.replace()`` being atomic on POSIX/NTFS. Each
    LLM-driven step is single-writer per ReportRun.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Status values
# ---------------------------------------------------------------------------

RunStatus = Literal[
    "pending",
    "awaiting_step",
    "ready_for_data",
    "data_complete",
    "payload_ready",
    "rendered",
    "exported",
    "failed",
    "canceled",
]

STATUS_FILE_NAME = "status.json"
STATUS_SCHEMA_VERSION = "1"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class RuntimeStateError(Exception):
    """Base error for state-machine misuse."""


class StateNotFoundError(RuntimeStateError):
    """Raised when the status.json file is missing."""


class StateTransitionError(RuntimeStateError):
    """Raised when the caller's expected state does not match the actual state."""

    def __init__(self, *, expected: str | list[str], actual: str) -> None:
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"state transition failed: expected {expected}, but found {actual!r}"
        )


# ---------------------------------------------------------------------------
# RuntimeState dataclass
# ---------------------------------------------------------------------------


@dataclass
class RuntimeState:
    """The full content of ``status.json``.

    ``form_state`` mirrors ``$.form.<step_id>.<field>`` — every submitted
    form step adds an entry here. ``step_outputs`` mirrors ``$.steps.<step_id>``
    — every executed data step / before_step appends its parsed JSON output
    keyed by ``output_id``.
    """

    schema_version: str = STATUS_SCHEMA_VERSION
    report_run_id: str = ""
    thread_id: str = ""
    template_id: str = ""
    template_version: int | None = None  # None for builtin
    template_version_ref: str | None = None
    status: RunStatus = "pending"
    nonce: str = ""
    expected_step: str | None = None  # step_id awaiting submission
    completed_steps: list[str] = field(default_factory=list)
    form_state: dict[str, dict[str, Any]] = field(default_factory=dict)
    step_outputs: dict[str, dict[str, Any]] = field(default_factory=dict)
    parameters_summary: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "report_run_id": self.report_run_id,
            "thread_id": self.thread_id,
            "template_id": self.template_id,
            "template_version": self.template_version,
            "template_version_ref": self.template_version_ref,
            "status": self.status,
            "nonce": self.nonce,
            "expected_step": self.expected_step,
            "completed_steps": list(self.completed_steps),
            "form_state": dict(self.form_state),
            "step_outputs": dict(self.step_outputs),
            "parameters_summary": dict(self.parameters_summary),
            "error_code": self.error_code,
            "error_message": self.error_message,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RuntimeState":
        return cls(
            schema_version=data.get("schema_version", STATUS_SCHEMA_VERSION),
            report_run_id=data["report_run_id"],
            thread_id=data["thread_id"],
            template_id=data["template_id"],
            template_version=data.get("template_version"),
            template_version_ref=data.get("template_version_ref"),
            status=data.get("status", "pending"),
            nonce=data.get("nonce", ""),
            expected_step=data.get("expected_step"),
            completed_steps=list(data.get("completed_steps", [])),
            form_state=dict(data.get("form_state", {})),
            step_outputs=dict(data.get("step_outputs", {})),
            parameters_summary=dict(data.get("parameters_summary", {})),
            error_code=data.get("error_code"),
            error_message=data.get("error_message"),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )


# ---------------------------------------------------------------------------
# Atomic file I/O — shared across all runtime helpers
# ---------------------------------------------------------------------------

_locks_lock = threading.Lock()
_locks: dict[str, threading.Lock] = {}


def _get_lock(path: Path) -> threading.Lock:
    key = str(path.resolve())
    with _locks_lock:
        return _locks.setdefault(key, threading.Lock())


def read_state(run_dir: Path) -> RuntimeState:
    """Read ``status.json`` from a run-scoped directory."""
    status_path = run_dir / STATUS_FILE_NAME
    if not status_path.exists():
        raise StateNotFoundError(f"status file not found at {status_path}")
    raw = json.loads(status_path.read_text(encoding="utf-8"))
    return RuntimeState.from_dict(raw)


def write_state(run_dir: Path, state: RuntimeState) -> None:
    """Write ``status.json`` atomically (tmp file + rename)."""
    status_path = run_dir / STATUS_FILE_NAME
    status_path.parent.mkdir(parents=True, exist_ok=True)
    lock = _get_lock(status_path)
    with lock:
        from deerflow.report_templates.records import now_iso

        state.updated_at = now_iso()
        tmp = status_path.with_suffix(status_path.suffix + f".tmp.{os.getpid()}.{uuid.uuid4().hex[:8]}")
        try:
            tmp.write_text(
                json.dumps(state.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(tmp, status_path)
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass


# ---------------------------------------------------------------------------
# Transitions
# ---------------------------------------------------------------------------


_ALLOWED_TRANSITIONS: dict[RunStatus, set[RunStatus]] = {
    "pending": {"awaiting_step", "ready_for_data", "failed"},
    "awaiting_step": {"awaiting_step", "ready_for_data", "failed", "canceled"},
    "ready_for_data": {"data_complete", "failed"},
    "data_complete": {"payload_ready", "failed"},
    "payload_ready": {"rendered", "failed"},
    "rendered": {"exported", "failed"},
    "exported": set(),
    "failed": set(),
    "canceled": set(),
}


def expect_status(state: RuntimeState, *allowed: RunStatus) -> None:
    """Raise ``StateTransitionError`` if ``state.status`` is not in ``allowed``.

    Used by every tool entry point to fail fast before any side-effect.
    """
    if state.status not in allowed:
        raise StateTransitionError(expected=list(allowed), actual=state.status)


def transition(state: RuntimeState, new_status: RunStatus) -> None:
    """Mutate ``state.status`` if the transition is in the allowed graph."""
    if new_status not in _ALLOWED_TRANSITIONS.get(state.status, set()):
        raise StateTransitionError(
            expected=sorted(_ALLOWED_TRANSITIONS.get(state.status, set())),
            actual=f"{state.status!r} → {new_status!r}",
        )
    state.status = new_status
    _record_terminal_outcome(state)


def mark_failed(state: RuntimeState, *, code: str, message: str) -> None:
    """Set the state to ``failed`` regardless of current status (terminal)."""
    state.error_code = code
    state.error_message = message
    state.status = "failed"
    _record_terminal_outcome(state)


def mark_succeeded(state: RuntimeState) -> None:
    """Helper used by tests / runtime end-of-pipeline to emit success telemetry.

    Production code typically calls ``transition(state, "exported")`` directly
    — call this **after** that transition (or when the run reaches any other
    successful terminal status) to ensure the outcome is recorded.
    """
    _record_terminal_outcome(state)


def _record_terminal_outcome(state: RuntimeState) -> None:
    """Emit a Phase 7 ``report_run_outcome`` event if status is terminal.

    Idempotent: callers can invoke after every transition without worrying
    about double-counting — only the first call per (report_run_id, status)
    transition writes a telemetry event. Tracking is in-process only; the
    JSONL sink is what gives us cross-process audit (charter §4.1).
    """
    if state.status not in {"exported", "failed", "canceled"}:
        return
    key = (state.report_run_id, state.status)
    with _emitted_lock:
        if key in _emitted_terminal:
            return
        _emitted_terminal.add(key)
    try:
        from deerflow.report_templates.records import iso_to_epoch
        from deerflow.report_templates.telemetry import get_telemetry

        duration: float | None = None
        if state.created_at:
            try:
                duration = max(0.0, time.time() - iso_to_epoch(state.created_at))
            except (ValueError, TypeError):
                duration = None
        get_telemetry().record_report_run(
            template_id=state.template_id,
            template_version_ref=state.template_version_ref,
            visibility=None,  # state.json doesn't carry visibility; route layer can enrich later
            report_run_id=state.report_run_id,
            status=state.status,
            error_code=state.error_code,
            duration_seconds=duration,
        )
    except Exception:  # noqa: BLE001
        # Telemetry must never break the caller (charter §3 — zero-intrusion).
        logger.debug("telemetry record_report_run failed", exc_info=True)


# Tracks emitted terminal outcomes for the lifetime of the process so we don't
# double-count when ``transition()`` runs again on the same state object.
_emitted_terminal: set[tuple[str, str]] = set()
_emitted_lock = threading.Lock()
