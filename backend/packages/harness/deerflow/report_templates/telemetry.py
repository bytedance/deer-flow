"""Telemetry collector for the Report Template Platform (Phase 7).

Pattern: in-memory thread-safe counters + on-disk JSONL audit log. Mirrors the
existing ``deerflow.tools.render_ui_metrics`` collector — Prometheus / OTel are
deliberately out of scope for this phase (see
``docs/plans/2026-05-18-phase7-charter.md`` §3).

Six event categories cover the design's monitoring needs:

  - ``report_run_outcome``        : ReportRun success/failure with error_code
  - ``fallback_triggered``        : ai-report--daily falling back to legacy SOUL
  - ``validator_outcome``         : DSL validate() pass/fail + error_code
  - ``storage_snapshot``          : per-(owner_type, owner_id) byte counts
  - ``version_count_snapshot``    : per-template version count
  - ``skill_unavailable``         : skill disabled / registry load failure

Counters are exposed via ``summary()`` (used by HTTP route + admin tools).
Events are also appended to ``{DEER_FLOW_HOME}/report-templates/.telemetry.log``
so a 30-day fallback report (charter §4.2) can be reconstructed offline. The
JSONL sink is optional — disable by setting ``DEER_FLOW_REPORT_TELEMETRY_LOG=0``.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Event payload
# ---------------------------------------------------------------------------


@dataclass
class TelemetryEvent:
    """A single telemetry record. Kept flat for JSONL serialization."""

    type: str
    timestamp: float = field(default_factory=time.time)
    # Common labels (any may be None depending on the event type)
    template_id: str | None = None
    template_version_ref: str | None = None
    visibility: str | None = None
    report_run_id: str | None = None
    status: str | None = None  # succeeded / failed / canceled
    error_code: str | None = None
    duration_seconds: float | None = None
    # Fallback-specific
    agent_name: str | None = None
    reason: str | None = None
    # Validator-specific
    outcome: str | None = None  # valid / invalid
    # Storage / version-count snapshots
    owner_type: str | None = None  # users / tenants
    owner_id: str | None = None
    bytes_used: int | None = None
    version_count: int | None = None
    # Skill-specific
    skill_name: str | None = None
    script_qualified_name: str | None = None
    action: str | None = None  # disabled_after_publish / registry_load_failed


# ---------------------------------------------------------------------------
# Collector
# ---------------------------------------------------------------------------


_TELEMETRY_LOG_ENV = "DEER_FLOW_REPORT_TELEMETRY_LOG"
_HOME_ENV = "DEER_FLOW_HOME"


def _is_jsonl_enabled() -> bool:
    return os.environ.get(_TELEMETRY_LOG_ENV, "1") not in ("0", "false", "False", "")


def _default_jsonl_path() -> Path:
    home = os.environ.get(_HOME_ENV)
    if home:
        base = Path(home) / "report-templates"
    else:
        base = Path.cwd() / ".deer-flow" / "report-templates"
    base.mkdir(parents=True, exist_ok=True)
    return base / ".telemetry.log"


class ReportTemplateTelemetry:
    """Thread-safe in-memory counters + optional JSONL sink."""

    def __init__(self, *, jsonl_path: Path | None = None) -> None:
        self._lock = threading.Lock()
        self._jsonl_path = jsonl_path
        # P0: ReportRun outcomes
        self._runs_total: dict[tuple[str, str, str], int] = defaultdict(int)
        # key: (template_id, status, error_code)
        self._run_duration_sum_by_template: dict[str, float] = defaultdict(float)
        self._run_duration_count_by_template: dict[str, int] = defaultdict(int)
        # P0: fallback
        self._fallback_total: dict[tuple[str, str], int] = defaultdict(int)
        # key: (agent_name, reason)
        # P1: validator
        self._validator_total: dict[tuple[str, str], int] = defaultdict(int)
        # key: (outcome, error_code)
        # P1: storage / version snapshots — keep last value per key
        self._storage_bytes: dict[tuple[str, str], int] = {}
        self._version_counts: dict[str, int] = {}
        # P2: skill unavailable
        self._skill_unavailable_total: dict[tuple[str, str], int] = defaultdict(int)
        # key: (skill_name, action)

    # -- Recording -------------------------------------------------------------

    def record_report_run(
        self,
        *,
        template_id: str,
        template_version_ref: str | None,
        visibility: str | None,
        report_run_id: str,
        status: str,
        error_code: str | None,
        duration_seconds: float | None,
    ) -> None:
        ec = error_code or ""
        with self._lock:
            self._runs_total[(template_id, status, ec)] += 1
            if duration_seconds is not None and duration_seconds >= 0:
                self._run_duration_sum_by_template[template_id] += duration_seconds
                self._run_duration_count_by_template[template_id] += 1
        self._emit(
            TelemetryEvent(
                type="report_run_outcome",
                template_id=template_id,
                template_version_ref=template_version_ref,
                visibility=visibility,
                report_run_id=report_run_id,
                status=status,
                error_code=error_code,
                duration_seconds=duration_seconds,
            )
        )

    def record_fallback(self, *, agent_name: str, reason: str) -> None:
        with self._lock:
            self._fallback_total[(agent_name, reason)] += 1
        self._emit(TelemetryEvent(type="fallback_triggered", agent_name=agent_name, reason=reason))

    def record_validator(self, *, outcome: str, error_code: str | None) -> None:
        ec = error_code or ""
        with self._lock:
            self._validator_total[(outcome, ec)] += 1
        self._emit(TelemetryEvent(type="validator_outcome", outcome=outcome, error_code=error_code))

    def record_storage_snapshot(self, *, owner_type: str, owner_id: str, bytes_used: int) -> None:
        with self._lock:
            self._storage_bytes[(owner_type, owner_id)] = bytes_used
        self._emit(
            TelemetryEvent(
                type="storage_snapshot",
                owner_type=owner_type,
                owner_id=owner_id,
                bytes_used=bytes_used,
            )
        )

    def record_version_count(self, *, template_id: str, version_count: int) -> None:
        with self._lock:
            self._version_counts[template_id] = version_count
        self._emit(
            TelemetryEvent(
                type="version_count_snapshot",
                template_id=template_id,
                version_count=version_count,
            )
        )

    def record_skill_unavailable(
        self, *, skill_name: str, action: str, script_qualified_name: str | None = None
    ) -> None:
        with self._lock:
            self._skill_unavailable_total[(skill_name, action)] += 1
        self._emit(
            TelemetryEvent(
                type="skill_unavailable",
                skill_name=skill_name,
                action=action,
                script_qualified_name=script_qualified_name,
            )
        )

    # -- Querying --------------------------------------------------------------

    def summary(self) -> dict[str, Any]:
        """Snapshot of current counters. Cheap to call from HTTP routes."""
        with self._lock:
            runs_total = sum(self._runs_total.values())
            failures = sum(c for (_, st, _), c in self._runs_total.items() if st == "failed")
            success_rate = (runs_total - failures) / runs_total if runs_total else 0.0
            avg_duration_by_template = {
                tid: round(self._run_duration_sum_by_template[tid] / self._run_duration_count_by_template[tid], 3)
                for tid in self._run_duration_count_by_template
            }
            return {
                "report_runs": {
                    "total": runs_total,
                    "success_rate": round(success_rate, 4),
                    "by_template_status_error": [
                        {"template_id": k[0], "status": k[1], "error_code": k[2] or None, "count": v}
                        for k, v in sorted(self._runs_total.items())
                    ],
                    "avg_duration_seconds_by_template": avg_duration_by_template,
                },
                "fallback_triggered": {
                    "total": sum(self._fallback_total.values()),
                    "by_agent_reason": [
                        {"agent_name": k[0], "reason": k[1], "count": v}
                        for k, v in sorted(self._fallback_total.items())
                    ],
                },
                "validator": {
                    "total": sum(self._validator_total.values()),
                    "by_outcome_error": [
                        {"outcome": k[0], "error_code": k[1] or None, "count": v}
                        for k, v in sorted(self._validator_total.items())
                    ],
                },
                "storage": {
                    "by_owner": [
                        {"owner_type": k[0], "owner_id": k[1], "bytes_used": v}
                        for k, v in sorted(self._storage_bytes.items())
                    ],
                    "total_bytes": sum(self._storage_bytes.values()),
                },
                "version_counts": [
                    {"template_id": tid, "version_count": cnt}
                    for tid, cnt in sorted(self._version_counts.items())
                ],
                "skill_unavailable": {
                    "total": sum(self._skill_unavailable_total.values()),
                    "by_skill_action": [
                        {"skill_name": k[0], "action": k[1], "count": v}
                        for k, v in sorted(self._skill_unavailable_total.items())
                    ],
                },
            }

    def reset(self) -> None:
        """Clear all counters. Intended for tests."""
        with self._lock:
            self._runs_total.clear()
            self._run_duration_sum_by_template.clear()
            self._run_duration_count_by_template.clear()
            self._fallback_total.clear()
            self._validator_total.clear()
            self._storage_bytes.clear()
            self._version_counts.clear()
            self._skill_unavailable_total.clear()

    # -- JSONL sink ------------------------------------------------------------

    def _emit(self, event: TelemetryEvent) -> None:
        if not _is_jsonl_enabled():
            return
        path = self._jsonl_path or _default_jsonl_path()
        try:
            payload = {k: v for k, v in asdict(event).items() if v is not None}
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except OSError as e:
            # Telemetry must never break the caller. Log once and move on.
            logger.debug("telemetry JSONL write failed: %s", e)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_singleton: ReportTemplateTelemetry | None = None
_singleton_lock = threading.Lock()


def get_telemetry() -> ReportTemplateTelemetry:
    """Return the process-wide telemetry collector."""
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = ReportTemplateTelemetry()
    return _singleton


def reset_telemetry() -> None:
    """Drop the singleton — tests use this between cases."""
    global _singleton
    with _singleton_lock:
        _singleton = None
