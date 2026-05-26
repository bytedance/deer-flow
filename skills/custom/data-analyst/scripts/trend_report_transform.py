#!/usr/bin/env python
"""Aggregate multi-device trend analysis results into a report-ready payload.

Reads per-device trend analysis JSON (Basic/Pro/Ultra) and optional comparison
data, outputs ``trend_report_features.json`` with structured report sections.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any] | None:
    """Load JSON file, return None if not found."""
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _extract_device_summary(
    analysis: dict[str, Any],
    equipment_id: str,
    equipment_name: str,
    capability_tier: str,
) -> dict[str, Any]:
    """Extract per-device trend summary from analysis result."""
    findings = analysis.get("findings", [])
    evidence = analysis.get("evidence", [])

    # Extract key metrics
    metrics_summary = []
    for finding in findings:
        metric_key = finding.get("metric", "")
        direction = finding.get("direction", "stable")
        slope = finding.get("slope", 0.0)
        volatility = finding.get("volatility", 0.0)
        confidence = finding.get("confidence", 0.0)

        metrics_summary.append({
            "metric_key": metric_key,
            "direction": direction,
            "slope": slope,
            "volatility": volatility,
            "confidence": confidence,
            "severity": finding.get("severity", "info"),
            "description": finding.get("description", ""),
        })

    # Pro/Ultra specific fields
    pro_fields = {}
    if capability_tier in ("pro", "ultra"):
        pro_fields["models"] = analysis.get("models", [])
        pro_fields["stl_decomposition"] = analysis.get("stl_decomposition", {})
        pro_fields["changepoints"] = analysis.get("changepoints", [])
        pro_fields["confidence_band"] = analysis.get("confidence_band", {})

    ultra_fields = {}
    if capability_tier == "ultra":
        ultra_fields["forecast_lstm"] = analysis.get("forecast_lstm", [])
        ultra_fields["confidence_80"] = analysis.get("confidence_80", [])
        ultra_fields["confidence_95"] = analysis.get("confidence_95", [])
        ultra_fields["co_trending_groups"] = analysis.get("co_trending_groups", [])
        ultra_fields["adaptive_threshold"] = analysis.get("adaptive_threshold", {})

    return {
        "equipment_id": equipment_id,
        "equipment_name": equipment_name,
        "capability_tier": capability_tier,
        "metrics_summary": metrics_summary,
        "findings_count": len(findings),
        "evidence_count": len(evidence),
        **pro_fields,
        **ultra_fields,
    }


def _build_cross_device_summary(per_device: list[dict[str, Any]]) -> dict[str, Any]:
    """Build cross-device comparison summary."""
    # Group metrics across devices
    metric_groups: dict[str, list[dict[str, Any]]] = {}
    for device in per_device:
        for metric in device.get("metrics_summary", []):
            key = metric["metric_key"]
            if key not in metric_groups:
                metric_groups[key] = []
            metric_groups[key].append({
                "equipment_id": device["equipment_id"],
                "equipment_name": device["equipment_name"],
                "direction": metric["direction"],
                "slope": metric["slope"],
                "volatility": metric["volatility"],
            })

    # Sort by degradation priority (increasing slope > stable > decreasing)
    degradation_priority = []
    for metric_key, devices in metric_groups.items():
        for d in devices:
            if d["direction"] == "increasing":
                degradation_priority.append({
                    "metric_key": metric_key,
                    "equipment_id": d["equipment_id"],
                    "equipment_name": d["equipment_name"],
                    "slope": d["slope"],
                    "priority": "high" if d["slope"] > 0.1 else "medium",
                })

    degradation_priority.sort(key=lambda x: x["slope"], reverse=True)

    return {
        "metric_groups": metric_groups,
        "degradation_priority": degradation_priority[:10],
        "total_devices": len(per_device),
    }


def _build_comparison_summary(
    current_data: dict[str, Any] | None,
    compare_data: dict[str, Any] | None,
    compare_mode: str,
) -> dict[str, Any]:
    """Build comparison summary (wow/yoy)."""
    if not current_data or not compare_data or compare_mode == "none":
        return {}

    current_series = current_data.get("time_series", [])
    compare_series = compare_data.get("time_series", [])

    # Match metrics by key
    current_map = {s.get("metric_key"): s for s in current_series}
    compare_map = {s.get("metric_key"): s for s in compare_series}

    comparison_metrics = []
    for metric_key in current_map:
        if metric_key not in compare_map:
            continue

        current_vals = current_map[metric_key].get("values", [])
        compare_vals = compare_map[metric_key].get("values", [])

        if not current_vals or not compare_vals:
            continue

        current_avg = sum(current_vals) / len(current_vals)
        compare_avg = sum(compare_vals) / len(compare_vals)

        if compare_avg == 0:
            change_pct = 0.0
        else:
            change_pct = ((current_avg - compare_avg) / compare_avg) * 100

        comparison_metrics.append({
            "metric_key": metric_key,
            "current_avg": round(current_avg, 2),
            "compare_avg": round(compare_avg, 2),
            "change_pct": round(change_pct, 1),
            "trend": "上升" if change_pct > 5 else "下降" if change_pct < -5 else "持平",
        })

    comparison_metrics.sort(key=lambda x: abs(x["change_pct"]), reverse=True)

    mode_label = "环比" if compare_mode == "wow" else "同比"
    return {
        "mode": compare_mode,
        "mode_label": mode_label,
        "metrics": comparison_metrics,
    }


def _build_degradation_alerts(per_device: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract degradation alerts across all devices."""
    alerts = []
    for device in per_device:
        for metric in device.get("metrics_summary", []):
            if metric["direction"] == "increasing" and metric["slope"] > 0.05:
                alerts.append({
                    "equipment_id": device["equipment_id"],
                    "equipment_name": device["equipment_name"],
                    "metric_key": metric["metric_key"],
                    "slope": metric["slope"],
                    "confidence": metric["confidence"],
                    "severity": "warning" if metric["slope"] < 0.1 else "critical",
                })

    alerts.sort(key=lambda x: x["slope"], reverse=True)
    return alerts


def _build_forecasts(per_device: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract forecast data across all devices."""
    forecasts = []
    for device in per_device:
        # Basic/Pro forecasts are in evidence or findings
        # Ultra has forecast_lstm
        if "forecast_lstm" in device and device["forecast_lstm"]:
            forecasts.append({
                "equipment_id": device["equipment_id"],
                "equipment_name": device["equipment_name"],
                "type": "lstm",
                "values": device["forecast_lstm"][:14],  # 14-day horizon
            })

    return forecasts


def _build_recommendations(
    degradation_alerts: list[dict[str, Any]],
    capability_tier: str,
) -> list[dict[str, Any]]:
    """Generate maintenance recommendations based on degradation alerts."""
    recommendations = []

    # Rule-based recommendations
    for alert in degradation_alerts[:5]:
        metric_key = alert["metric_key"]
        severity = alert["severity"]

        if metric_key == "vibration_level":
            recommendations.append({
                "priority": "urgent" if severity == "critical" else "important",
                "action": f"对 {alert['equipment_name']} 进行振动频谱分析，检查轴承和联轴器状态",
                "equipment_id": alert["equipment_id"],
                "metric_key": metric_key,
            })
        elif metric_key == "temperature":
            recommendations.append({
                "priority": "urgent" if severity == "critical" else "important",
                "action": f"检查 {alert['equipment_name']} 的润滑系统和冷却系统，安排停机检修",
                "equipment_id": alert["equipment_id"],
                "metric_key": metric_key,
            })
        elif metric_key == "pressure":
            recommendations.append({
                "priority": "important",
                "action": f"检查 {alert['equipment_name']} 的阀门和管路，排除堵塞或泄漏",
                "equipment_id": alert["equipment_id"],
                "metric_key": metric_key,
            })
        elif metric_key == "corrosion_rate":
            recommendations.append({
                "priority": "important",
                "action": f"检查 {alert['equipment_name']} 的防腐层，安排壁厚检测",
                "equipment_id": alert["equipment_id"],
                "metric_key": metric_key,
            })

    return recommendations


def main() -> int:
    parser = argparse.ArgumentParser(description="Aggregate trend analysis results")
    parser.add_argument("--input", required=True, help="Path to trend analysis JSON")
    parser.add_argument("--trend-data", help="Path to trend_data.json")
    parser.add_argument("--compare-data", help="Path to comparison trend_data.json")
    parser.add_argument(
        "--capability-tier",
        choices=["basic", "pro", "ultra"],
        default="pro",
        help="Capability tier",
    )
    parser.add_argument("--equipment-ids", required=True, help="Comma-separated equipment IDs")
    parser.add_argument("--equipment-names", help="Comma-separated equipment names")
    parser.add_argument(
        "--compare-mode",
        choices=["none", "wow", "yoy"],
        default="none",
        help="Comparison mode",
    )
    parser.add_argument("--output-dir", default="/mnt/user-data/outputs/", help="Output directory")

    args = parser.parse_args()

    input_path = Path(args.input)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load analysis result
    analysis = _load_json(input_path)
    if not analysis:
        print(json.dumps({"error": f"Analysis file not found: {input_path}"}))
        return 1

    # Parse equipment lists
    equipment_ids = [eid.strip() for eid in args.equipment_ids.split(",")]
    equipment_names = (
        [name.strip() for name in args.equipment_names.split(",")]
        if args.equipment_names
        else equipment_ids
    )

    if len(equipment_names) < len(equipment_ids):
        equipment_names.extend(equipment_ids[len(equipment_names):])

    # Build per-device summary (single device in current implementation)
    per_device = []
    for eid, ename in zip(equipment_ids, equipment_names):
        device_summary = _extract_device_summary(analysis, eid, ename, args.capability_tier)
        per_device.append(device_summary)

    # Build cross-device summary
    cross_device_summary = _build_cross_device_summary(per_device)

    # Build comparison summary
    trend_data = _load_json(Path(args.trend_data)) if args.trend_data else None
    compare_data = _load_json(Path(args.compare_data)) if args.compare_data else None
    comparison_summary = _build_comparison_summary(trend_data, compare_data, args.compare_mode)

    # Build degradation alerts
    degradation_alerts = _build_degradation_alerts(per_device)

    # Build forecasts
    forecasts = _build_forecasts(per_device)

    # Build recommendations
    recommendations = _build_recommendations(degradation_alerts, args.capability_tier)

    # Assemble final payload
    payload = {
        "analysis_type": "trend",
        "capability_tier": args.capability_tier,
        "per_device": per_device,
        "cross_device_summary": cross_device_summary,
        "comparison_summary": comparison_summary,
        "degradation_alerts": degradation_alerts,
        "forecasts": forecasts,
        "recommendations": recommendations,
        "data_quality": [],  # Populated by data_quality.py if available
    }

    # Check for model fallback
    if analysis.get("model_fallback"):
        payload["model_fallback"] = True

    output_path = output_dir / "trend_report_features.json"
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(json.dumps({
        "ok": True,
        "output": str(output_path),
        "devices": len(per_device),
        "alerts": len(degradation_alerts),
        "recommendations": len(recommendations),
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
