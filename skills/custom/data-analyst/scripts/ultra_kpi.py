#!/usr/bin/env python
"""Ultra-tier KPI health assessment: predictive scoring, risk ranking, risk matrix.

Consumes ``daily_data.json``, produces ``ultra_kpi_result.json``.
Falls back to Pro methods when ONNX model is unavailable.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

from _stub_helpers import base_parser, emit_error, read_json, write_json
from _model_loader import load_model, model_available

SCHEMA_VERSION = "2"

TARGETS = {
    "runtime_rate": {"min": 95, "max": 100, "unit": "%", "better": "higher", "weight": 0.15},
    "alarm_count": {"min": 0, "max": 5, "unit": "条", "better": "lower", "weight": 0.15},
    "vibration_level": {"min": 0, "max": 7.1, "unit": "mm/s", "better": "lower", "weight": 0.25},
    "temperature": {"min": 0, "max": 85, "unit": "°C", "better": "lower", "weight": 0.15},
    "pressure": {"min": 0.5, "max": 2.5, "unit": "MPa", "better": "in_range", "weight": 0.10},
    "corrosion_rate": {"min": 0, "max": 0.5, "unit": "mm/a", "better": "lower", "weight": 0.10},
    "flow_rate": {"min": 50, "max": 200, "unit": "m³/h", "better": "in_range", "weight": 0.05},
}

DISPLAY_NAMES = {
    "runtime_rate": "运行率", "alarm_count": "告警数量", "vibration_level": "振动烈度",
    "temperature": "温度", "pressure": "压力", "flow_rate": "流量",
    "corrosion_rate": "腐蚀速率",
}

RISK_MATRIX_LIKELIHOOD = {
    "rare": {"label": "罕见", "range": (0, 20), "score": 1},
    "unlikely": {"label": "不太可能", "range": (20, 40), "score": 2},
    "possible": {"label": "可能", "range": (40, 60), "score": 3},
    "likely": {"label": "很可能", "range": (60, 80), "score": 4},
    "almost_certain": {"label": "几乎确定", "range": (80, 100), "score": 5},
}

RISK_MATRIX_CONSEQUENCE = {
    "negligible": {"label": "可忽略", "score": 1},
    "minor": {"label": "轻微", "score": 2},
    "moderate": {"label": "中等", "score": 3},
    "major": {"label": "严重", "score": 4},
    "catastrophic": {"label": "灾难性", "score": 5},
}


def _single_kpi_score(value: float, target: dict) -> float:
    t_min = target.get("min", 0)
    t_max = target.get("max", 100)
    better = target.get("better", "in_range")

    if better == "in_range":
        if t_min <= value <= t_max:
            return 100.0
        dist = min(abs(value - t_min), abs(value - t_max))
        tolerance = (t_max - t_min) * 0.5
        return max(0.0, 100.0 - (dist / max(tolerance, 1)) * 100.0)
    elif better == "lower":
        if value <= t_max:
            return 100.0
        return max(0.0, 100.0 - ((value - t_max) / max(t_max, 1)) * 100.0)
    elif better == "higher":
        if value >= t_min:
            return 100.0
        return max(0.0, 100.0 - ((t_min - value) / max(t_min, 1)) * 100.0)
    return 50.0


def _health_score(kpi_values: dict[str, float]) -> tuple[float, dict[str, float]]:
    total_weight = 0.0
    weighted_sum = 0.0
    per_kpi: dict[str, float] = {}
    for key, target in TARGETS.items():
        if key in kpi_values and kpi_values[key] is not None:
            score = _single_kpi_score(kpi_values[key], target)
            weight = target.get("weight", 0.1)
            weighted_sum += score * weight
            total_weight += weight
            per_kpi[key] = round(score, 1)
    if total_weight == 0:
        return 50.0, per_kpi
    return round(weighted_sum / total_weight, 1), per_kpi


def _predict_health(kpi_values: dict[str, float]) -> dict | None:
    """Predict 30-day health score via ONNX model."""
    model = load_model("health_predictor")
    if model is None:
        return None

    import numpy as np

    try:
        session = model["session"]
        input_name = session.get_inputs()[0].name
        output_name = session.get_outputs()[0].name

        features = []
        for key in sorted(TARGETS.keys()):
            features.append(kpi_values.get(key, 0.0))
        X = np.array([features], dtype=np.float32)
        pred = session.run([output_name], {input_name: X})[0]
        predicted_score = float(pred.flatten()[0])
        return {
            "predicted_30day_score": round(max(0.0, min(100.0, predicted_score)), 1),
            "model": "health_predictor_onnx",
            "model_fallback": False,
        }
    except Exception:
        return None


def _trend_trajectory(kpi_values: dict[str, float], targets: dict) -> str:
    """Classify health trajectory based on current KPI values vs targets."""
    deteriorating = 0
    stable = 0
    improving = 0
    for key, target in targets.items():
        if key not in kpi_values or kpi_values[key] is None:
            continue
        v = kpi_values[key]
        t_min = target.get("min", 0)
        t_max = target.get("max", 100)
        better = target.get("better", "in_range")

        if better == "in_range":
            if v < t_min * 0.8 or v > t_max * 1.2:
                deteriorating += 1
            elif t_min <= v <= t_max:
                stable += 1
            else:
                deteriorating += 1
        elif better == "lower":
            if v > t_max * 1.3:
                deteriorating += 1
            elif v <= t_max:
                stable += 1
            else:
                deteriorating += 1
        elif better == "higher":
            if v < t_min * 0.7:
                deteriorating += 1
            elif v >= t_min:
                stable += 1
            else:
                deteriorating += 1

    total = deteriorating + stable + improving
    if total == 0:
        return "stable"
    if deteriorating >= 2:
        return "deteriorating"
    if deteriorating == 1:
        return "watch"
    return "stable"


def _risk_ranking(equipment_scores: list[dict]) -> list[dict]:
    """Rank equipment by risk = trajectory × criticality × non-compliance."""
    ranked = []
    for eq in equipment_scores:
        score = eq.get("health_score", 50)
        per_kpi = eq.get("per_kpi_scores", {})
        non_compliant = sum(1 for s in per_kpi.values() if s < 60)

        trajectory_score = {"deteriorating": 1.0, "watch": 0.6, "stable": 0.2}.get(
            eq.get("trajectory", "stable"), 0.2
        )

        risk = (100 - score) / 100 * trajectory_score * (1 + non_compliant * 0.3)
        ranked.append({
            "equipment_id": eq["equipment_id"],
            "equipment_name": eq["equipment_name"],
            "health_score": score,
            "trajectory": eq.get("trajectory", "stable"),
            "non_compliant_kpis": non_compliant,
            "risk_score": round(risk, 3),
        })

    ranked.sort(key=lambda x: x["risk_score"], reverse=True)
    for i, r in enumerate(ranked):
        r["rank"] = i + 1
        if r["risk_score"] >= 0.5:
            r["risk_level"] = "high"
        elif r["risk_score"] >= 0.25:
            r["risk_level"] = "medium"
        else:
            r["risk_level"] = "low"

    return ranked


def _risk_matrix_data(equipment_scores: list[dict]) -> list[dict]:
    """Generate risk matrix entries (likelihood × consequence)."""
    entries = []
    for eq in equipment_scores:
        score = eq.get("health_score", 50)
        per_kpi = eq.get("per_kpi_scores", {})
        non_compliant = sum(1 for s in per_kpi.values() if s < 60)

        # Likelihood from health score inversion
        if score >= 80:
            likelihood = "rare"
        elif score >= 60:
            likelihood = "unlikely"
        elif score >= 40:
            likelihood = "possible"
        elif score >= 20:
            likelihood = "likely"
        else:
            likelihood = "almost_certain"

        # Consequence from non-compliance count
        if non_compliant == 0:
            consequence = "negligible"
        elif non_compliant == 1:
            consequence = "minor"
        elif non_compliant <= 3:
            consequence = "moderate"
        elif non_compliant <= 5:
            consequence = "major"
        else:
            consequence = "catastrophic"

        entries.append({
            "equipment_id": eq["equipment_id"],
            "equipment_name": eq["equipment_name"],
            "likelihood": likelihood,
            "likelihood_label": RISK_MATRIX_LIKELIHOOD[likelihood]["label"],
            "likelihood_score": RISK_MATRIX_LIKELIHOOD[likelihood]["score"],
            "consequence": consequence,
            "consequence_label": RISK_MATRIX_CONSEQUENCE[consequence]["label"],
            "consequence_score": RISK_MATRIX_CONSEQUENCE[consequence]["score"],
            "risk_level": (
                "critical" if RISK_MATRIX_LIKELIHOOD[likelihood]["score"] >= 4 and
                RISK_MATRIX_CONSEQUENCE[consequence]["score"] >= 4
                else "high" if RISK_MATRIX_LIKELIHOOD[likelihood]["score"] >= 3 and
                RISK_MATRIX_CONSEQUENCE[consequence]["score"] >= 3
                else "medium" if RISK_MATRIX_LIKELIHOOD[likelihood]["score"] >= 2 and
                RISK_MATRIX_CONSEQUENCE[consequence]["score"] >= 2
                else "low"
            ),
        })

    return entries


def analyze_kpi_ultra(data: dict) -> dict:
    """Ultra-tier KPI health analysis."""
    use_onnx = model_available("health_predictor")
    equipment_list = data.get("equipment", [])
    equipment_scores: list[dict] = []

    for eq in equipment_list:
        eq_id = eq.get("id", "")
        eq_name = eq.get("name", eq_id)
        kpis = eq.get("kpis", {})

        kpi_values: dict[str, float] = {}
        for kpi_key, kpi_val in kpis.items():
            current = kpi_val.get("current_value", 0)
            if isinstance(current, (int, float)):
                kpi_values[kpi_key] = float(current)

        score, per_kpi = _health_score(kpi_values)
        trajectory = _trend_trajectory(kpi_values, TARGETS)

        health_prediction = _predict_health(kpi_values) if use_onnx else None

        equipment_scores.append({
            "equipment_id": eq_id,
            "equipment_name": eq_name,
            "health_score": score,
            "per_kpi_scores": per_kpi,
            "trajectory": trajectory,
            "health_prediction": health_prediction,
        })

    # Peer percentile
    if len(equipment_scores) >= 2:
        scores = [eq["health_score"] for eq in equipment_scores]
        sorted_scores = sorted(scores)
        n = len(scores)
        for eq in equipment_scores:
            rank = sorted_scores.index(eq["health_score"]) + 1
            eq["peer_percentile"] = {
                "percentile": round((rank / n) * 100, 1),
                "total_peers": n,
                "rank": rank,
            }

    risk_ranking = _risk_ranking(equipment_scores)
    risk_matrix = _risk_matrix_data(equipment_scores)

    return {
        "schema_version": SCHEMA_VERSION,
        "model_fallback": not use_onnx,
        "onnx_used": use_onnx,
        "equipment_scores": equipment_scores,
        "equipment_count": len(equipment_scores),
        "risk_ranking": risk_ranking,
        "risk_matrix": risk_matrix,
    }


def main() -> int:
    parser = base_parser(description="Ultra-tier KPI health assessment")
    parser.add_argument("--input", required=True, help="Path to daily_data.json")
    args = parser.parse_args()

    data = read_json(Path(args.input))
    if data is None:
        emit_error("BAD_INPUT", f"Failed to read {args.input}")
        return 0
    if "error" in data:
        emit_error("UPSTREAM_ERROR", data["error"])
        return 0

    result = analyze_kpi_ultra(data)

    out_path = write_json(Path(args.output_dir), "ultra_kpi_result", result)

    print(json.dumps({
        "ok": True,
        "equipment_count": result["equipment_count"],
        "onnx_used": result["onnx_used"],
        "high_risk_count": sum(1 for r in result["risk_ranking"] if r["risk_level"] == "high"),
        "output": str(out_path),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
