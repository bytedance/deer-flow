#!/usr/bin/env python
"""Pro-tier KPI health assessment: health score trend, peer percentile, weighted composite score.

Consumes ``daily_data.json`` (from query_daily.py) and produces ``pro_kpi_result.json``.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

from _stub_helpers import base_parser, emit_error, read_json, write_json

SCHEMA_VERSION = "2"

# Target ranges per KPI
TARGETS = {
    "runtime_rate": {"min": 95, "max": 100, "unit": "%", "better": "higher", "weight": 0.15},
    "alarm_count": {"min": 0, "max": 5, "unit": "条", "better": "lower", "weight": 0.15},
    "vibration_level": {"min": 0, "max": 7.1, "unit": "mm/s", "better": "lower", "weight": 0.25},
    "temperature": {"min": 0, "max": 85, "unit": "°C", "better": "lower", "weight": 0.15},
    "pressure": {"min": 0.5, "max": 2.5, "unit": "MPa", "better": "in_range", "weight": 0.10},
    "corrosion_rate": {"min": 0, "max": 0.5, "unit": "mm/a", "better": "lower", "weight": 0.10},
    "flow_rate": {"min": 50, "max": 200, "unit": "m³/h", "better": "in_range", "weight": 0.05},
    "motor_current": {"min": 0, "max": 150, "unit": "A", "better": "lower", "weight": 0.05},
}

DISPLAY_NAMES = {
    "runtime_rate": "运行率",
    "alarm_count": "告警数量",
    "vibration_level": "振动烈度",
    "temperature": "温度",
    "pressure": "压力",
    "flow_rate": "流量",
    "corrosion_rate": "腐蚀速率",
    "motor_current": "电机电流",
}


def _single_kpi_score(value: float, target: dict) -> float:
    """Score a single KPI value 0-100 against target ranges."""
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
    """Weighted health score from multiple KPI values."""
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


def _peer_percentile(
    equipment_scores: list[dict],
) -> dict[str, dict]:
    """Compute percentile rankings among peer equipment."""
    if len(equipment_scores) < 2:
        return {}

    scores = [eq["health_score"] for eq in equipment_scores]
    n = len(scores)
    sorted_scores = sorted(scores)

    percentiles: dict[str, dict] = {}
    for eq in equipment_scores:
        eq_id = eq.get("equipment_id", "")
        rank = sorted_scores.index(eq["health_score"]) + 1
        pct = round((rank / n) * 100, 1)
        percentiles[eq_id] = {
            "percentile": pct,
            "total_peers": n,
            "rank": rank,
            "better_than_pct": round(100 - pct, 1),
        }
    return percentiles


def analyze_kpi_pro(data: dict) -> dict:
    """Pro-tier KPI health analysis."""
    equipment_list = data.get("equipment", [])
    kpi_summary: list[dict] = []
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

            target = TARGETS.get(kpi_key, {})
            t_min = target.get("min", 0)
            t_max = target.get("max", 100)
            compliant = t_min <= current <= t_max

            kpi_summary.append({
                "equipment_id": eq_id,
                "equipment_name": eq_name,
                "metric_key": kpi_key,
                "metric_name": DISPLAY_NAMES.get(kpi_key, kpi_key),
                "value": current,
                "unit": kpi_val.get("unit", target.get("unit", "")),
                "target_min": t_min,
                "target_max": t_max,
                "compliant": compliant,
            })

        score, per_kpi = _health_score(kpi_values)
        equipment_scores.append({
            "equipment_id": eq_id,
            "equipment_name": eq_name,
            "health_score": score,
            "per_kpi_scores": per_kpi,
        })

    percentiles = _peer_percentile(equipment_scores)

    # Attach percentile info
    for eq in equipment_scores:
        eq_id = eq["equipment_id"]
        if eq_id in percentiles:
            eq["peer_percentile"] = percentiles[eq_id]

    total_pairs = len(kpi_summary)
    compliant_pairs = sum(1 for k in kpi_summary if k["compliant"])
    compliance_pct = round(compliant_pairs / max(total_pairs, 1) * 100, 1)

    return {
        "schema_version": SCHEMA_VERSION,
        "kpi_summary": kpi_summary,
        "total_pairs": total_pairs,
        "compliant_pairs": compliant_pairs,
        "compliance_pct": compliance_pct,
        "equipment_scores": equipment_scores,
        "peer_percentiles": percentiles,
    }


def main() -> int:
    parser = base_parser(description="Pro-tier KPI health assessment")
    parser.add_argument("--input", required=True, help="Path to daily_data.json")
    args = parser.parse_args()

    data = read_json(Path(args.input))
    if data is None:
        emit_error("BAD_INPUT", f"Failed to read {args.input}")
        return 0
    if "error" in data:
        emit_error("UPSTREAM_ERROR", data["error"])
        return 0

    result = analyze_kpi_pro(data)

    out_path = write_json(Path(args.output_dir), "pro_kpi_result", result)

    print(json.dumps({
        "ok": True,
        "compliance_pct": result["compliance_pct"],
        "equipment_count": len(result["equipment_scores"]),
        "output": str(out_path),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
