"""Continuous online regression tracking for academic eval metrics.

This module compares current benchmark metrics against:
- previous run on the same branch (commit-level regression),
- latest run from previous ISO week (weekly drift),
and emits structured alerts plus markdown summaries.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

ONLINE_REGRESSION_SCHEMA_VERSION = "deerflow.academic_online_regression.v1"


class OnlineDriftThresholds(BaseModel):
    """Thresholds for drift alerts."""

    max_claim_grounding_drop: float = 0.0
    max_citation_fidelity_drop: float = 0.0
    max_ece_increase: float = 0.0
    max_safety_valve_rate_increase: float = 0.0
    allow_safety_valve_increase: bool = False
    max_auc_drop: float = 1.0
    max_brier_increase: float = 1.0
    max_score_gap_drop: float = 1.0
    max_overall_drop: float = 1.0
    fail_on_status_drop: bool = True


class OnlineLayerSnapshot(BaseModel):
    """One layer metrics snapshot for one run."""

    layer: str
    status: str = "pass"
    case_count: int = 0
    accepted_case_count: int = 0
    rejected_case_count: int = 0
    average_overall_score: float = 0.0
    average_claim_grounding: float = 0.0
    average_citation_fidelity: float = 0.0
    auc_accept_reject: float = 0.0
    ece: float = 0.0
    brier_score: float = 0.0
    safety_valve_triggered_count: int = 0
    safety_valve_triggered_rate: float = 0.0
    accept_reject_score_gap: float = 0.0


class OnlineRegressionRun(BaseModel):
    """One online regression run snapshot."""

    run_id: str
    created_at: str
    week: str
    branch: str
    commit_sha: str
    source: str = "academic-online-regression"
    status: str = "pass"
    layers: dict[str, OnlineLayerSnapshot] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class OnlineRegressionHistory(BaseModel):
    """History store for online regression."""

    schema_version: str = ONLINE_REGRESSION_SCHEMA_VERSION
    updated_at: str
    runs: list[OnlineRegressionRun] = Field(default_factory=list)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _iso_week_key(now: datetime | None = None) -> str:
    current = now or datetime.now(UTC)
    iso = current.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _parse_iso_datetime(value: str) -> datetime:
    token = str(value or "").strip()
    if token.endswith("Z"):
        token = f"{token[:-1]}+00:00"
    return datetime.fromisoformat(token)


def _week_rank(week_key: str) -> tuple[int, int]:
    token = str(week_key or "").strip().upper()
    if "-W" not in token:
        return (0, 0)
    year, week = token.split("-W", 1)
    try:
        return (int(year), int(week))
    except Exception:
        return (0, 0)


def _ordered_runs(runs: list[OnlineRegressionRun]) -> list[OnlineRegressionRun]:
    return sorted(
        runs,
        key=lambda row: (row.created_at, row.run_id),
    )


def load_online_regression_history(path: Path) -> OnlineRegressionHistory:
    """Load existing online regression history, or return empty history."""
    if not path.exists():
        return OnlineRegressionHistory(updated_at=_now_iso(), runs=[])
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Online regression history must be a JSON object.")
    return OnlineRegressionHistory.model_validate(payload)


def dump_online_regression_history(path: Path, history: OnlineRegressionHistory, *, overwrite: bool = True) -> None:
    """Persist online regression history."""
    if path.exists() and not overwrite:
        raise FileExistsError(f"Refusing to overwrite existing file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(history.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8")


def build_online_run_from_offline_report(
    *,
    offline_report: dict[str, Any],
    branch: str,
    commit_sha: str,
    run_label: str = "online-regression",
    created_at: str | None = None,
) -> OnlineRegressionRun:
    """Build online snapshot from offline regression report payload."""
    now_iso = created_at or _now_iso()
    week_key = _iso_week_key(_parse_iso_datetime(now_iso))
    layers_payload = offline_report.get("layers")
    layers: dict[str, OnlineLayerSnapshot] = {}
    if isinstance(layers_payload, dict):
        for layer_name, layer_value in layers_payload.items():
            if not isinstance(layer_value, dict):
                continue
            layers[str(layer_name)] = OnlineLayerSnapshot(
                layer=str(layer_name),
                status=str(layer_value.get("status") or "pass"),
                case_count=int(layer_value.get("case_count") or 0),
                accepted_case_count=int(layer_value.get("accepted_case_count") or 0),
                rejected_case_count=int(layer_value.get("rejected_case_count") or 0),
                average_overall_score=float(layer_value.get("average_overall_score") or 0.0),
                average_claim_grounding=float(layer_value.get("average_claim_grounding") or 0.0),
                average_citation_fidelity=float(layer_value.get("average_citation_fidelity") or 0.0),
                auc_accept_reject=float(layer_value.get("auc_accept_reject") or 0.0),
                ece=float(layer_value.get("ece") or 0.0),
                brier_score=float(layer_value.get("brier_score") or 0.0),
                safety_valve_triggered_count=int(layer_value.get("safety_valve_triggered_count") or 0),
                safety_valve_triggered_rate=float(layer_value.get("safety_valve_triggered_rate") or 0.0),
                accept_reject_score_gap=float(layer_value.get("accept_reject_score_gap") or 0.0),
            )
    run_id = f"{run_label}-{now_iso.replace(':', '').replace('-', '').replace('.', '')}-{commit_sha[:8] or 'local'}"
    return OnlineRegressionRun(
        run_id=run_id,
        created_at=now_iso,
        week=week_key,
        branch=str(branch or "unknown"),
        commit_sha=str(commit_sha or "unknown"),
        status=str(offline_report.get("status") or "pass"),
        layers=layers,
        metadata={
            "offline_report_status": str(offline_report.get("status") or "pass"),
        },
    )


def build_online_run_from_eval_summary(
    *,
    eval_summary: dict[str, Any],
    branch: str,
    commit_sha: str,
    run_label: str = "online-regression",
    created_at: str | None = None,
    layer_name: str = "academic_eval",
) -> OnlineRegressionRun:
    """Build online snapshot directly from evaluate_academic_and_persist summary payload."""
    now_iso = created_at or _now_iso()
    week_key = _iso_week_key(_parse_iso_datetime(now_iso))
    layer = OnlineLayerSnapshot(
        layer=str(layer_name),
        status=str(eval_summary.get("status") or "pass"),
        case_count=int(eval_summary.get("case_count") or 0),
        accepted_case_count=int(eval_summary.get("accepted_case_count") or 0),
        rejected_case_count=int(eval_summary.get("rejected_case_count") or 0),
        average_overall_score=float(eval_summary.get("average_overall_score") or 0.0),
        average_claim_grounding=float(eval_summary.get("average_claim_grounding") or 0.0),
        average_citation_fidelity=float(eval_summary.get("average_citation_fidelity") or 0.0),
        auc_accept_reject=float(eval_summary.get("auc_accept_reject") or 0.0),
        ece=float(eval_summary.get("ece") or 0.0),
        brier_score=float(eval_summary.get("brier_score") or 0.0),
        safety_valve_triggered_count=int(eval_summary.get("safety_valve_triggered_count") or 0),
        safety_valve_triggered_rate=float(eval_summary.get("safety_valve_triggered_rate") or 0.0),
        accept_reject_score_gap=float(eval_summary.get("accept_reject_score_gap") or 0.0),
    )
    run_id = f"{run_label}-{now_iso.replace(':', '').replace('-', '').replace('.', '')}-{commit_sha[:8] or 'local'}"
    return OnlineRegressionRun(
        run_id=run_id,
        created_at=now_iso,
        week=week_key,
        branch=str(branch or "unknown"),
        commit_sha=str(commit_sha or "unknown"),
        status=str(eval_summary.get("status") or "pass"),
        layers={str(layer_name): layer},
        metadata={
            "artifact_path": str(eval_summary.get("artifact_path") or ""),
            "leaderboard_artifact_path": str(eval_summary.get("leaderboard_artifact_path") or ""),
        },
    )


def append_online_run(
    history: OnlineRegressionHistory,
    run: OnlineRegressionRun,
    *,
    max_runs: int = 300,
) -> OnlineRegressionHistory:
    """Append one run and keep bounded history."""
    runs = [*history.runs, run]
    runs = _ordered_runs(runs)
    if max_runs > 0 and len(runs) > max_runs:
        runs = runs[-max_runs:]
    return OnlineRegressionHistory(
        schema_version=ONLINE_REGRESSION_SCHEMA_VERSION,
        updated_at=_now_iso(),
        runs=runs,
    )


def find_previous_commit_run(history: OnlineRegressionHistory, current: OnlineRegressionRun) -> OnlineRegressionRun | None:
    """Find previous run (same branch) before current run."""
    ordered = _ordered_runs(history.runs)
    before = [
        row
        for row in ordered
        if row.branch == current.branch and row.created_at < current.created_at
    ]
    if not before:
        return None
    return before[-1]


def find_previous_week_run(history: OnlineRegressionHistory, current: OnlineRegressionRun) -> OnlineRegressionRun | None:
    """Find latest run from previous week (same branch)."""
    current_rank = _week_rank(current.week)
    candidates = [
        row
        for row in history.runs
        if row.branch == current.branch and _week_rank(row.week) < current_rank
    ]
    if not candidates:
        return None
    return _ordered_runs(candidates)[-1]


def _comparison_alert(name: str, *, severity: str, layer: str, message: str, delta: float | None = None, current: float | None = None, previous: float | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": name,
        "severity": severity,
        "layer": layer,
        "message": message,
    }
    if delta is not None:
        payload["delta"] = round(float(delta), 6)
    if current is not None:
        payload["current"] = round(float(current), 6)
    if previous is not None:
        payload["previous"] = round(float(previous), 6)
    return payload


def _compare_layer(current: OnlineLayerSnapshot, previous: OnlineLayerSnapshot, *, thresholds: OnlineDriftThresholds) -> dict[str, Any]:
    alerts: list[dict[str, Any]] = []
    deltas = {
        "average_overall_score": float(current.average_overall_score) - float(previous.average_overall_score),
        "average_claim_grounding": float(current.average_claim_grounding) - float(previous.average_claim_grounding),
        "average_citation_fidelity": float(current.average_citation_fidelity) - float(previous.average_citation_fidelity),
        "auc_accept_reject": float(current.auc_accept_reject) - float(previous.auc_accept_reject),
        "ece": float(current.ece) - float(previous.ece),
        "brier_score": float(current.brier_score) - float(previous.brier_score),
        "safety_valve_triggered_rate": float(current.safety_valve_triggered_rate) - float(previous.safety_valve_triggered_rate),
        "accept_reject_score_gap": float(current.accept_reject_score_gap) - float(previous.accept_reject_score_gap),
    }
    layer = current.layer

    if thresholds.fail_on_status_drop and previous.status == "pass" and current.status != "pass":
        alerts.append(
            _comparison_alert(
                "status_drop",
                severity="critical",
                layer=layer,
                message=f"Layer status dropped from {previous.status} to {current.status}.",
            )
        )
    if deltas["average_overall_score"] < -float(thresholds.max_overall_drop):
        alerts.append(
            _comparison_alert(
                "overall_score_drop",
                severity="warning",
                layer=layer,
                message="Average overall score dropped beyond threshold.",
                delta=deltas["average_overall_score"],
                current=current.average_overall_score,
                previous=previous.average_overall_score,
            )
        )
    if deltas["average_claim_grounding"] < -float(thresholds.max_claim_grounding_drop):
        alerts.append(
            _comparison_alert(
                "claim_grounding_drop",
                severity="critical",
                layer=layer,
                message="Average claim grounding dropped beyond threshold.",
                delta=deltas["average_claim_grounding"],
                current=current.average_claim_grounding,
                previous=previous.average_claim_grounding,
            )
        )
    if deltas["average_citation_fidelity"] < -float(thresholds.max_citation_fidelity_drop):
        alerts.append(
            _comparison_alert(
                "citation_fidelity_drop",
                severity="critical",
                layer=layer,
                message="Average citation fidelity dropped beyond threshold.",
                delta=deltas["average_citation_fidelity"],
                current=current.average_citation_fidelity,
                previous=previous.average_citation_fidelity,
            )
        )
    if deltas["auc_accept_reject"] < -float(thresholds.max_auc_drop):
        alerts.append(
            _comparison_alert(
                "auc_drop",
                severity="critical",
                layer=layer,
                message="AUC dropped beyond threshold.",
                delta=deltas["auc_accept_reject"],
                current=current.auc_accept_reject,
                previous=previous.auc_accept_reject,
            )
        )
    if deltas["ece"] > float(thresholds.max_ece_increase):
        alerts.append(
            _comparison_alert(
                "ece_increase",
                severity="warning",
                layer=layer,
                message="ECE increased beyond threshold.",
                delta=deltas["ece"],
                current=current.ece,
                previous=previous.ece,
            )
        )
    if deltas["brier_score"] > float(thresholds.max_brier_increase):
        alerts.append(
            _comparison_alert(
                "brier_increase",
                severity="warning",
                layer=layer,
                message="Brier score increased beyond threshold.",
                delta=deltas["brier_score"],
                current=current.brier_score,
                previous=previous.brier_score,
            )
        )
    if (not thresholds.allow_safety_valve_increase) and deltas["safety_valve_triggered_rate"] > float(thresholds.max_safety_valve_rate_increase):
        alerts.append(
            _comparison_alert(
                "safety_valve_triggered_increase",
                severity="warning",
                layer=layer,
                message="Safety-valve trigger rate increased beyond threshold.",
                delta=deltas["safety_valve_triggered_rate"],
                current=current.safety_valve_triggered_rate,
                previous=previous.safety_valve_triggered_rate,
            )
        )
    if deltas["accept_reject_score_gap"] < -float(thresholds.max_score_gap_drop):
        alerts.append(
            _comparison_alert(
                "score_gap_drop",
                severity="warning",
                layer=layer,
                message="Accept/reject score gap dropped beyond threshold.",
                delta=deltas["accept_reject_score_gap"],
                current=current.accept_reject_score_gap,
                previous=previous.accept_reject_score_gap,
            )
        )
    return {
        "layer": layer,
        "current": current.model_dump(),
        "previous": previous.model_dump(),
        "deltas": {key: round(value, 6) for key, value in deltas.items()},
        "alerts": alerts,
    }


def compare_online_runs(current: OnlineRegressionRun, previous: OnlineRegressionRun | None, *, thresholds: OnlineDriftThresholds) -> dict[str, Any]:
    """Compare one run to previous run snapshot."""
    if previous is None:
        return {
            "status": "insufficient_history",
            "current_run_id": current.run_id,
            "previous_run_id": None,
            "comparisons": [],
            "alerts": [],
        }

    comparisons: list[dict[str, Any]] = []
    alerts: list[dict[str, Any]] = []
    for layer_name, current_layer in current.layers.items():
        previous_layer = previous.layers.get(layer_name)
        if previous_layer is None:
            continue
        layer_cmp = _compare_layer(current_layer, previous_layer, thresholds=thresholds)
        comparisons.append(layer_cmp)
        for alert in layer_cmp["alerts"]:
            alerts.append(alert)
    status = "pass" if not alerts else "has_alerts"
    return {
        "status": status,
        "current_run_id": current.run_id,
        "previous_run_id": previous.run_id,
        "comparisons": comparisons,
        "alerts": alerts,
    }


def build_online_drift_report(
    *,
    current: OnlineRegressionRun,
    previous_commit: OnlineRegressionRun | None,
    previous_week: OnlineRegressionRun | None,
    thresholds: OnlineDriftThresholds,
) -> dict[str, Any]:
    """Build commit-level and week-level drift report."""
    commit_cmp = compare_online_runs(current, previous_commit, thresholds=thresholds)
    week_cmp = compare_online_runs(current, previous_week, thresholds=thresholds)
    commit_alerts = commit_cmp.get("alerts", [])
    week_alerts = week_cmp.get("alerts", [])
    has_alerts = bool(commit_alerts or week_alerts)
    return {
        "schema_version": ONLINE_REGRESSION_SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "status": "has_alerts" if has_alerts else "pass",
        "current_run": current.model_dump(),
        "thresholds": thresholds.model_dump(),
        "comparisons": {
            "commit_to_previous": commit_cmp,
            "week_to_previous": week_cmp,
        },
        "alert_count": len(commit_alerts) + len(week_alerts),
    }


def render_online_drift_markdown(report: dict[str, Any]) -> str:
    """Render online drift report markdown."""
    lines: list[str] = []
    lines.append("# Academic Online Regression Drift Report")
    lines.append("")
    lines.append(f"- Status: `{report.get('status', 'unknown')}`")
    lines.append(f"- Generated At: `{report.get('generated_at', '')}`")
    lines.append(f"- Alert Count: `{int(report.get('alert_count') or 0)}`")
    lines.append("")
    comparisons = report.get("comparisons", {})
    if not isinstance(comparisons, dict):
        comparisons = {}
    for section_name in ("commit_to_previous", "week_to_previous"):
        section = comparisons.get(section_name)
        lines.append(f"## `{section_name}`")
        if not isinstance(section, dict):
            lines.append("- No data.")
            lines.append("")
            continue
        lines.append(f"- Status: `{section.get('status', 'unknown')}`")
        lines.append(f"- Current Run: `{section.get('current_run_id', '')}`")
        lines.append(f"- Previous Run: `{section.get('previous_run_id', '')}`")
        alerts = section.get("alerts", [])
        if isinstance(alerts, list) and alerts:
            lines.append("- Alerts:")
            for item in alerts:
                if not isinstance(item, dict):
                    continue
                lines.append(
                    f"  - [{item.get('severity', 'warning')}] `{item.get('layer', 'unknown')}` `{item.get('name', '')}`: {item.get('message', '')}"
                )
        else:
            lines.append("- Alerts: none")
        lines.append("")
    return "\n".join(lines)

