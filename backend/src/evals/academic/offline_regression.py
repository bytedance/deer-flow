"""Offline benchmark regression runner for layered academic eval datasets."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from .evaluator import evaluate_dataset
from .failure_modes import evaluate_failure_mode_library
from .importer import import_accept_reject_payload
from .offline_benchmark_suite import LAYER_FILE_NAMES
from .schemas import AcademicEvalCase


class OfflineRegressionThresholds(BaseModel):
    """Quality gates for offline layered regression."""

    core_min_auc: float = 0.9
    core_max_ece: float = 0.25
    core_max_brier: float = 0.1
    domain_min_accept_reject_gap: float = 0.1
    failure_mode_min_targeted_case_count: int = 5
    failure_mode_required_status: str = "pass"


class OfflineRegressionDriftThresholds(BaseModel):
    """Drift gates between current and baseline offline reports."""

    max_hallucination_rate_increase: float = 0.0
    max_ece_increase: float = 0.0
    max_brier_increase: float = 0.0
    max_auc_drop: float = 1.0
    fail_on_status_drop: bool = True


def load_offline_layer_payloads(input_dir: Path) -> dict[str, dict[str, Any]]:
    """Load expected layered raw payloads from directory."""
    payloads: dict[str, dict[str, Any]] = {}
    for layer_key, file_name in LAYER_FILE_NAMES.items():
        path = input_dir / file_name
        if not path.exists():
            raise FileNotFoundError(f"Missing layer file: {path}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"Layer payload must be JSON object: {path}")
        payloads[layer_key] = payload
    return payloads


def _check(name: str, *, value: float | int | str, pass_if: bool, expected: str) -> dict[str, Any]:
    return {
        "name": name,
        "value": value,
        "expected": expected,
        "status": "pass" if pass_if else "fail",
    }


def _hallucination_rate_from_summary(summary: Any) -> float:
    case_count = int(getattr(summary, "case_count", 0) or 0)
    if case_count <= 0:
        return 0.0
    fidelity = float(getattr(summary, "average_citation_fidelity", 0.0) or 0.0)
    return max(0.0, min(1.0, 1.0 - fidelity))


def evaluate_offline_regression_layers(
    layer_payloads: dict[str, dict[str, Any]],
    *,
    dataset_version: str = "v1",
    thresholds: OfflineRegressionThresholds | None = None,
) -> dict[str, Any]:
    """Evaluate layered payloads and return gate summary."""
    cfg = thresholds or OfflineRegressionThresholds()
    layer_reports: dict[str, dict[str, Any]] = {}
    failed_checks: list[dict[str, Any]] = []

    for layer_key, raw_payload in layer_payloads.items():
        imported = import_accept_reject_payload(
            raw_payload=raw_payload,
            source_path_label=f"offline-layer:{layer_key}",
            dataset_name=f"offline_{layer_key}",
            dataset_version=dataset_version,
            benchmark_split=layer_key,
            source_name=f"offline-regression-{layer_key}",
            anonymize=False,
            strict=True,
        )
        cases = [AcademicEvalCase.model_validate(item) for item in imported["dataset_payload"]["cases"]]
        summary = evaluate_dataset(cases)

        checks: list[dict[str, Any]] = []
        if layer_key == "core":
            checks.append(
                _check(
                    "core_auc_accept_reject",
                    value=round(float(summary.auc_accept_reject), 6),
                    pass_if=float(summary.auc_accept_reject) >= float(cfg.core_min_auc),
                    expected=f">= {cfg.core_min_auc}",
                )
            )
            checks.append(
                _check(
                    "core_ece",
                    value=round(float(summary.ece), 6),
                    pass_if=float(summary.ece) <= float(cfg.core_max_ece),
                    expected=f"<= {cfg.core_max_ece}",
                )
            )
            checks.append(
                _check(
                    "core_brier_score",
                    value=round(float(summary.brier_score), 6),
                    pass_if=float(summary.brier_score) <= float(cfg.core_max_brier),
                    expected=f"<= {cfg.core_max_brier}",
                )
            )
        elif layer_key == "failure_mode":
            gate = evaluate_failure_mode_library(cases)
            status = str(gate.get("status") or "unknown")
            targeted_case_count = int(gate.get("targeted_case_count") or 0)
            checks.append(
                _check(
                    "failure_mode_gate_status",
                    value=status,
                    pass_if=status == str(cfg.failure_mode_required_status),
                    expected=f"== {cfg.failure_mode_required_status}",
                )
            )
            checks.append(
                _check(
                    "failure_mode_targeted_case_count",
                    value=targeted_case_count,
                    pass_if=targeted_case_count >= int(cfg.failure_mode_min_targeted_case_count),
                    expected=f">= {cfg.failure_mode_min_targeted_case_count}",
                )
            )
        else:
            checks.append(
                _check(
                    "domain_accept_reject_score_gap",
                    value=round(float(summary.accept_reject_score_gap), 6),
                    pass_if=float(summary.accept_reject_score_gap) >= float(cfg.domain_min_accept_reject_gap),
                    expected=f">= {cfg.domain_min_accept_reject_gap}",
                )
            )
            checks.append(
                _check(
                    "domain_has_accepted_cases",
                    value=int(summary.accepted_case_count),
                    pass_if=int(summary.accepted_case_count) > 0,
                    expected="> 0",
                )
            )
            checks.append(
                _check(
                    "domain_has_rejected_cases",
                    value=int(summary.rejected_case_count),
                    pass_if=int(summary.rejected_case_count) > 0,
                    expected="> 0",
                )
            )

        layer_status = "pass" if all(item["status"] == "pass" for item in checks) else "fail"
        for item in checks:
            if item["status"] == "fail":
                failed_checks.append({"layer": layer_key, **item})

        layer_reports[layer_key] = {
            "status": layer_status,
            "case_count": int(summary.case_count),
            "accepted_case_count": int(summary.accepted_case_count),
            "rejected_case_count": int(summary.rejected_case_count),
            "average_overall_score": float(summary.average_overall_score),
            "average_claim_grounding": float(summary.average_claim_grounding),
            "average_citation_fidelity": float(summary.average_citation_fidelity),
            "citation_hallucination_rate": _hallucination_rate_from_summary(summary),
            "auc_accept_reject": float(summary.auc_accept_reject),
            "ece": float(summary.ece),
            "brier_score": float(summary.brier_score),
            "accept_reject_score_gap": float(summary.accept_reject_score_gap),
            "checks": checks,
        }

    return {
        "status": "pass" if not failed_checks else "fail",
        "thresholds": cfg.model_dump(),
        "layers": layer_reports,
        "failed_checks": failed_checks,
    }


def _drift_alert(
    name: str,
    *,
    layer: str,
    severity: str,
    message: str,
    delta: float | None = None,
    current: float | None = None,
    baseline: float | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": name,
        "layer": layer,
        "severity": severity,
        "message": message,
    }
    if delta is not None:
        payload["delta"] = round(float(delta), 6)
    if current is not None:
        payload["current"] = round(float(current), 6)
    if baseline is not None:
        payload["baseline"] = round(float(baseline), 6)
    return payload


def _as_layer_dict(report: dict[str, Any], layer_name: str) -> dict[str, Any]:
    layers = report.get("layers")
    if not isinstance(layers, dict):
        return {}
    layer = layers.get(layer_name)
    return layer if isinstance(layer, dict) else {}


def build_offline_regression_drift_report(
    *,
    current_report: dict[str, Any],
    baseline_report: dict[str, Any] | None,
    thresholds: OfflineRegressionDriftThresholds | None = None,
) -> dict[str, Any]:
    """Compare current offline regression report with baseline and emit drift alerts."""
    cfg = thresholds or OfflineRegressionDriftThresholds()
    if not isinstance(baseline_report, dict) or not baseline_report:
        return {
            "status": "insufficient_baseline",
            "thresholds": cfg.model_dump(),
            "comparisons": [],
            "alerts": [],
            "alert_count": 0,
            "prompt_pack_hash_changed": None,
            "prompt_layer_hash_changed": None,
        }

    current_layers = current_report.get("layers")
    baseline_layers = baseline_report.get("layers")
    if not isinstance(current_layers, dict) or not isinstance(baseline_layers, dict):
        return {
            "status": "insufficient_baseline",
            "thresholds": cfg.model_dump(),
            "comparisons": [],
            "alerts": [],
            "alert_count": 0,
            "prompt_pack_hash_changed": None,
            "prompt_layer_hash_changed": None,
        }

    comparisons: list[dict[str, Any]] = []
    alerts: list[dict[str, Any]] = []
    shared_layers = sorted(set(current_layers.keys()) & set(baseline_layers.keys()))
    for layer_name in shared_layers:
        current_layer = _as_layer_dict(current_report, layer_name)
        baseline_layer = _as_layer_dict(baseline_report, layer_name)
        if not current_layer or not baseline_layer:
            continue

        deltas = {
            "citation_hallucination_rate": float(current_layer.get("citation_hallucination_rate") or 0.0)
            - float(baseline_layer.get("citation_hallucination_rate") or 0.0),
            "ece": float(current_layer.get("ece") or 0.0) - float(baseline_layer.get("ece") or 0.0),
            "brier_score": float(current_layer.get("brier_score") or 0.0) - float(baseline_layer.get("brier_score") or 0.0),
            "auc_accept_reject": float(current_layer.get("auc_accept_reject") or 0.0)
            - float(baseline_layer.get("auc_accept_reject") or 0.0),
        }
        layer_alerts: list[dict[str, Any]] = []
        current_status = str(current_layer.get("status") or "unknown")
        baseline_status = str(baseline_layer.get("status") or "unknown")
        if cfg.fail_on_status_drop and baseline_status == "pass" and current_status != "pass":
            layer_alerts.append(
                _drift_alert(
                    "status_drop",
                    layer=layer_name,
                    severity="critical",
                    message=f"Layer status dropped from {baseline_status} to {current_status}.",
                )
            )
        if deltas["citation_hallucination_rate"] > float(cfg.max_hallucination_rate_increase):
            layer_alerts.append(
                _drift_alert(
                    "citation_hallucination_rate_increase",
                    layer=layer_name,
                    severity="critical",
                    message="Citation hallucination rate increased beyond threshold.",
                    delta=deltas["citation_hallucination_rate"],
                    current=float(current_layer.get("citation_hallucination_rate") or 0.0),
                    baseline=float(baseline_layer.get("citation_hallucination_rate") or 0.0),
                )
            )
        if deltas["ece"] > float(cfg.max_ece_increase):
            layer_alerts.append(
                _drift_alert(
                    "ece_increase",
                    layer=layer_name,
                    severity="critical",
                    message="ECE increased beyond threshold.",
                    delta=deltas["ece"],
                    current=float(current_layer.get("ece") or 0.0),
                    baseline=float(baseline_layer.get("ece") or 0.0),
                )
            )
        if deltas["brier_score"] > float(cfg.max_brier_increase):
            layer_alerts.append(
                _drift_alert(
                    "brier_score_increase",
                    layer=layer_name,
                    severity="critical",
                    message="Brier score increased beyond threshold.",
                    delta=deltas["brier_score"],
                    current=float(current_layer.get("brier_score") or 0.0),
                    baseline=float(baseline_layer.get("brier_score") or 0.0),
                )
            )
        if deltas["auc_accept_reject"] < -float(cfg.max_auc_drop):
            layer_alerts.append(
                _drift_alert(
                    "auc_drop",
                    layer=layer_name,
                    severity="warning",
                    message="AUC dropped beyond threshold.",
                    delta=deltas["auc_accept_reject"],
                    current=float(current_layer.get("auc_accept_reject") or 0.0),
                    baseline=float(baseline_layer.get("auc_accept_reject") or 0.0),
                )
            )

        comparisons.append(
            {
                "layer": layer_name,
                "current": current_layer,
                "baseline": baseline_layer,
                "deltas": {key: round(value, 6) for key, value in deltas.items()},
                "alerts": layer_alerts,
            }
        )
        alerts.extend(layer_alerts)

    current_pack_hash = str(current_report.get("prompt_pack_hash") or "").strip()
    baseline_pack_hash = str(baseline_report.get("prompt_pack_hash") or "").strip()
    current_layer_hashes = current_report.get("prompt_layer_signatures")
    baseline_layer_hashes = baseline_report.get("prompt_layer_signatures")
    prompt_pack_hash_changed = bool(current_pack_hash and baseline_pack_hash and current_pack_hash != baseline_pack_hash)
    prompt_layer_hash_changed = (
        isinstance(current_layer_hashes, dict)
        and isinstance(baseline_layer_hashes, dict)
        and current_layer_hashes != baseline_layer_hashes
    )

    return {
        "status": "has_alerts" if alerts else "pass",
        "thresholds": cfg.model_dump(),
        "comparisons": comparisons,
        "alerts": alerts,
        "alert_count": len(alerts),
        "prompt_pack_hash_changed": prompt_pack_hash_changed,
        "prompt_layer_hash_changed": prompt_layer_hash_changed,
        "current_prompt_pack_hash": current_pack_hash or None,
        "baseline_prompt_pack_hash": baseline_pack_hash or None,
    }


def render_offline_regression_markdown(report: dict[str, Any]) -> str:
    """Render regression report markdown."""
    lines: list[str] = []
    lines.append("# Offline Benchmark Regression Report")
    lines.append("")
    lines.append(f"- Status: `{report.get('status', 'unknown')}`")
    lines.append("")
    lines.append("## Layers")
    lines.append("")
    layers = report.get("layers", {})
    if not isinstance(layers, dict) or not layers:
        lines.append("- No layer reports.")
        return "\n".join(lines)
    for layer_name in sorted(layers.keys()):
        layer = layers[layer_name]
        if not isinstance(layer, dict):
            continue
        lines.append(f"### `{layer_name}`")
        lines.append(f"- Status: `{layer.get('status', 'unknown')}`")
        lines.append(f"- Cases: `{layer.get('case_count', 0)}`")
        lines.append(f"- Citation Hallucination Rate: `{layer.get('citation_hallucination_rate', 0.0):.4f}`")
        lines.append(f"- AUC: `{layer.get('auc_accept_reject', 0.0):.4f}`")
        lines.append(f"- ECE: `{layer.get('ece', 0.0):.4f}`")
        lines.append(f"- Brier: `{layer.get('brier_score', 0.0):.4f}`")
        lines.append(f"- Score Gap: `{layer.get('accept_reject_score_gap', 0.0):.4f}`")
        checks = layer.get("checks", [])
        if isinstance(checks, list) and checks:
            lines.append("- Checks:")
            for check in checks:
                if not isinstance(check, dict):
                    continue
                lines.append(f"  - `{check.get('name', 'unknown')}`: `{check.get('status', 'unknown')}` (value={check.get('value')}, expected {check.get('expected')})")
        lines.append("")
    return "\n".join(lines)


def render_offline_regression_drift_markdown(report: dict[str, Any]) -> str:
    """Render offline drift comparison as markdown."""
    lines: list[str] = []
    lines.append("# Offline Benchmark Drift Report")
    lines.append("")
    lines.append(f"- Status: `{report.get('status', 'unknown')}`")
    lines.append(f"- Alert Count: `{int(report.get('alert_count') or 0)}`")
    if report.get("prompt_pack_hash_changed") is not None:
        lines.append(f"- Prompt Pack Hash Changed: `{bool(report.get('prompt_pack_hash_changed'))}`")
    if report.get("prompt_layer_hash_changed") is not None:
        lines.append(f"- Prompt Layer Hash Changed: `{bool(report.get('prompt_layer_hash_changed'))}`")
    lines.append("")
    comparisons = report.get("comparisons")
    if not isinstance(comparisons, list) or not comparisons:
        lines.append("- No baseline comparisons available.")
        return "\n".join(lines)
    lines.append("## Layers")
    lines.append("")
    for row in comparisons:
        if not isinstance(row, dict):
            continue
        layer_name = str(row.get("layer") or "unknown")
        deltas = row.get("deltas") if isinstance(row.get("deltas"), dict) else {}
        alerts = row.get("alerts") if isinstance(row.get("alerts"), list) else []
        lines.append(f"### `{layer_name}`")
        lines.append(f"- Hallucination Δ: `{float(deltas.get('citation_hallucination_rate') or 0.0):.4f}`")
        lines.append(f"- ECE Δ: `{float(deltas.get('ece') or 0.0):.4f}`")
        lines.append(f"- Brier Δ: `{float(deltas.get('brier_score') or 0.0):.4f}`")
        lines.append(f"- AUC Δ: `{float(deltas.get('auc_accept_reject') or 0.0):.4f}`")
        if alerts:
            lines.append("- Alerts:")
            for alert in alerts:
                if not isinstance(alert, dict):
                    continue
                lines.append(
                    f"  - [{alert.get('severity', 'warning')}] `{alert.get('name', 'unknown')}`: {alert.get('message', '')}"
                )
        else:
            lines.append("- Alerts: none")
        lines.append("")
    return "\n".join(lines)

