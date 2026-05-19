#!/usr/bin/env python
"""Compute KPI summary, trend chart, alarm table from query_daily output.

Reads ``$DAILY_REPORT_OUTPUT_DIR/daily_data.json`` and writes
``$DAILY_REPORT_OUTPUT_DIR/daily_kpi.json`` matching design doc §6.2.

Supports two modes:
- **detail** (≤20 devices): per-device KPI cards and trends (original behavior)
- **grouped** (>20 devices): aggregated KPIs (mean/min/max) + top_anomalies
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

DEFAULT_OUTPUT_DIR = "/mnt/user-data/outputs"
INPUT_FILENAME = "daily_data.json"
OUTPUT_FILENAME = "daily_kpi.json"

KPI_DISPLAY_NAMES = {
    "runtime_rate": "运行率",
    "downtime_count": "停机次数",
    "alarm_count": "告警数量",
    "output": "产量",
    "energy_consumption": "能耗",
    "corrosion_rate": "腐蚀速率",
    "thickness_loss": "壁厚减薄量",
    "vibration_level": "振动水平",
    "bearing_temp": "轴承温度",
    "flow_rate": "流量",
    "outlet_pressure": "出口压力",
    "valve_temp": "阀温",
}

KPI_BETTER_WHEN_HIGHER = {"runtime_rate", "output", "flow_rate", "outlet_pressure"}

KPI_THRESHOLDS: dict[str, tuple[str, float]] = {
    "runtime_rate": ("below", 0.85),
    "corrosion_rate": ("above", 0.3),
    "thickness_loss": ("above", 1.5),
    "vibration_level": ("above", 10.0),
    "bearing_temp": ("above", 75.0),
    "valve_temp": ("above", 100.0),
    "downtime_count": ("above", 5),
}


def _output_dir() -> Path:
    return Path(os.environ.get("DAILY_REPORT_OUTPUT_DIR", DEFAULT_OUTPUT_DIR))


def _delta(current, previous):
    if previous is None or current is None:
        return None
    try:
        return round(current - previous, 4)
    except TypeError:
        return None


def _direction(delta) -> str | None:
    if delta is None or delta == 0:
        return "flat" if delta == 0 else None
    return "up" if delta > 0 else "down"


def _build_kpi_summary(current_kpis: dict, previous_kpis: dict | None, units: dict) -> list[dict]:
    summary = []
    for key, value in current_kpis.items():
        previous = previous_kpis.get(key) if previous_kpis else None
        delta = _delta(value, previous)
        summary.append(
            {
                "key": key,
                "name": KPI_DISPLAY_NAMES.get(key, key),
                "current": value,
                "previous": previous,
                "delta": delta,
                "unit": units.get(key, ""),
                "direction": _direction(delta),
                "better_when_higher": key in KPI_BETTER_WHEN_HIGHER,
            }
        )
    return summary


def _build_aggregated_kpi_summary(
    per_equipment: dict,
    previous_kpis: dict | None,
    units: dict,
    kpi_keys: list[str],
) -> list[dict]:
    """Build KPI summary with min/max/mean from per-equipment data."""
    summary = []
    for key in kpi_keys:
        values = []
        for eq_data in per_equipment.values():
            v = eq_data.get("kpis", {}).get(key)
            if v is not None and isinstance(v, (int, float)):
                values.append(v)
        if not values:
            continue
        mean_val = round(sum(values) / len(values), 4)
        min_val = round(min(values), 4)
        max_val = round(max(values), 4)
        previous = previous_kpis.get(key) if previous_kpis else None
        delta = _delta(mean_val, previous)
        summary.append({
            "key": key,
            "name": KPI_DISPLAY_NAMES.get(key, key),
            "current": mean_val,
            "current_note": "均值",
            "min": min_val,
            "max": max_val,
            "previous": previous,
            "delta": delta,
            "unit": units.get(key, ""),
            "direction": _direction(delta),
            "better_when_higher": key in KPI_BETTER_WHEN_HIGHER,
        })
    return summary


def _build_trend_chart(
    current_hourly: list[float],
    compare_hourly: list[float] | None,
    report_date: str,
    compare_date: str | None,
    equipment_count: int | None = None,
    per_equipment: dict | None = None,
) -> dict:
    """Return a ready-to-render ECharts option object (see EChartBlock contract).

    When ``per_equipment`` is provided (grouped mode), builds per-area
    series showing the average hourly runtime rate for each area,
    replacing the single fleet-level line.
    """
    title_suffix = f"（{equipment_count}台均值）" if equipment_count else ""
    x_axis = [f"{h:02d}:00" for h in range(24)]

    if per_equipment and equipment_count:
        series, legend = _build_area_trend_series(per_equipment, report_date)
        if compare_hourly and compare_date:
            compare_label = f"{compare_date} 整体均值"
            series.append({"name": compare_label, "type": "line", "smooth": True, "lineStyle": {"type": "dashed"}, "data": list(compare_hourly)})
            legend.append(compare_label)
    else:
        current_label = f"{report_date} 均值" if equipment_count else report_date
        series = [{"name": current_label, "type": "line", "smooth": True, "data": list(current_hourly or [])}]
        legend = [current_label]
        if compare_hourly and compare_date:
            compare_label = f"{compare_date} 均值" if equipment_count else compare_date
            series.append({"name": compare_label, "type": "line", "smooth": True, "data": list(compare_hourly)})
            legend.append(compare_label)

    return {
        "title": {"text": f"24 小时运行率趋势{title_suffix}"},
        "tooltip": {"trigger": "axis"},
        "legend": {"data": legend},
        "xAxis": {"type": "category", "data": x_axis},
        "yAxis": {"type": "value", "name": "运行率"},
        "series": series,
    }


def _build_area_trend_series(per_equipment: dict, report_date: str) -> tuple[list[dict], list[str]]:
    """Group per_equipment hourly data by area and build one series per area."""
    area_hours: dict[str, list[list[float]]] = {}
    for eq_data in per_equipment.values():
        area = eq_data.get("area", "未知")
        hourly = eq_data.get("hourly_runtime_rate")
        if not hourly or len(hourly) != 24:
            continue
        if area not in area_hours:
            area_hours[area] = []
        area_hours[area].append(hourly)

    if not area_hours or len(area_hours) <= 1:
        all_hourly: list[list[float]] = []
        for eq_data in per_equipment.values():
            h = eq_data.get("hourly_runtime_rate")
            if h and len(h) == 24:
                all_hourly.append(h)
        if all_hourly:
            avg = [round(sum(vals) / len(vals), 4) for vals in zip(*all_hourly)]
            label = f"{report_date} 整体均值"
            return [{"name": label, "type": "line", "smooth": True, "data": avg}], [label]
        return [], []

    series: list[dict] = []
    legend: list[str] = []
    for area in sorted(area_hours.keys()):
        hours_list = area_hours[area]
        avg = [round(sum(vals) / len(vals), 4) for vals in zip(*hours_list)]
        label = f"{area}（{len(hours_list)}台）"
        series.append({"name": label, "type": "line", "smooth": True, "data": avg})
        legend.append(label)
    return series, legend


def _compute_anomaly_score(eq_id: str, eq_kpis: dict) -> tuple[float, str]:
    """Return (score, issue_description) for a single device. Higher = worse."""
    max_score = 0.0
    worst_issue = ""
    for kpi_key, (direction, threshold) in KPI_THRESHOLDS.items():
        value = eq_kpis.get(kpi_key)
        if value is None or not isinstance(value, (int, float)):
            continue
        if direction == "above" and value > threshold:
            severity = (value - threshold) / max(threshold, 0.01)
            unit = KPI_DISPLAY_NAMES.get(kpi_key, kpi_key)
            issue = f"{unit} {value}（阈值 {threshold}）"
            if severity > max_score:
                max_score = severity
                worst_issue = issue
        elif direction == "below" and value < threshold:
            severity = (threshold - value) / max(threshold, 0.01)
            unit = KPI_DISPLAY_NAMES.get(kpi_key, kpi_key)
            issue = f"{unit} {value}（阈值 {threshold}）"
            if severity > max_score:
                max_score = severity
                worst_issue = issue
    return max_score, worst_issue


def _build_top_anomalies(per_equipment: dict, max_count: int = 10) -> list[dict]:
    """Identify top anomalous devices from per_equipment data."""
    scored: list[tuple[str, float, str, dict]] = []
    for eq_id, eq_data in per_equipment.items():
        eq_kpis = eq_data.get("kpis", {})
        score, issue = _compute_anomaly_score(eq_id, eq_kpis)
        if score > 0:
            scored.append((eq_id, score, issue, eq_data))
    scored.sort(key=lambda x: (-_severity_rank(x[1]), -x[1]))
    anomalies: list[dict] = []
    for rank, (eq_id, score, issue, eq_data) in enumerate(scored[:max_count], 1):
        severity = "high" if score > 1.0 else "warning"
        anomalies.append({
            "rank": rank,
            "equipment_id": eq_id,
            "name": eq_data.get("name", eq_id),
            "area": eq_data.get("area", ""),
            "issue": issue,
            "severity": severity,
        })
    return anomalies


def _severity_rank(score: float) -> int:
    """Map score to severity category for primary sort (high=1 > warning=0)."""
    return 1 if score > 1.0 else 0


def _overall_status(kpi_summary: list[dict], alarms: list[dict], equipment_count: int | None = None) -> dict:
    high_alarms = [a for a in alarms if a.get("level") == "high"]
    runtime = next((item for item in kpi_summary if item["key"] == "runtime_rate"), None)
    count_note = f"{equipment_count}台设备" if equipment_count else "设备"
    if high_alarms:
        level = "danger"
        summary = f"今日存在 {len(high_alarms)} 条高级告警，需重点关注。"
    elif runtime and isinstance(runtime["current"], (int, float)) and runtime["current"] < 0.85:
        level = "warning"
        summary = f"{count_note}运行率偏低，建议核查设备状态。"
    elif alarms:
        level = "warning"
        summary = f"{count_note}整体运行稳定，有少量异常需要关注。"
    else:
        level = "ok"
        summary = f"今日{count_note}运行平稳，无显著异常。"
    return {"level": level, "summary": summary}


def _recommendations(kpi_summary: list[dict], alarms: list[dict]) -> list[str]:
    recs: list[str] = []
    for alarm in alarms:
        if alarm.get("level") == "high":
            label = alarm.get("equipment") or alarm.get("equipment_id") or "unknown"
            recs.append(f"关注 {label} 的高级告警：{alarm.get('message', '')}")
    for item in kpi_summary:
        if item["key"] == "runtime_rate" and isinstance(item["current"], (int, float)) and item["current"] < 0.85:
            recs.append("运行率低于 85%，建议排查停机原因。")
        if item["key"] == "downtime_count" and isinstance(item["current"], (int, float)) and item["current"] >= 5:
            recs.append("停机次数偏多，建议分析停机分布。")
        if item["key"] == "corrosion_rate" and isinstance(item["current"], (int, float)) and item["current"] > 0.3:
            recs.append("腐蚀速率超标，建议加强防腐措施。")
        if item["key"] == "vibration_level" and isinstance(item["current"], (int, float)) and item["current"] > 10.0:
            recs.append("振动水平偏高，建议检查动平衡和基础。")
    if not recs:
        recs.append("无重点关注事项，继续保持。")
    return recs


def compute(payload: dict) -> dict:
    current = payload.get("current") or {}
    compare = payload.get("compare")
    units = current.get("kpi_units") or {}
    per_equipment = current.get("per_equipment")
    equipment_count = payload.get("equipment_count")

    is_aggregated = per_equipment is not None and isinstance(per_equipment, dict) and len(per_equipment) > 20

    current_kpis = current.get("kpis") or {}
    previous_kpis = (compare or {}).get("kpis") if compare else None

    if is_aggregated:
        kpi_keys = list(current_kpis.keys())
        kpi_summary = _build_aggregated_kpi_summary(per_equipment, previous_kpis, units, kpi_keys)
        trend_chart = _build_trend_chart(
            current.get("hourly_runtime_rate") or [],
            (compare or {}).get("hourly_runtime_rate") if compare else None,
            payload.get("report_date", ""),
            payload.get("compare_date"),
            equipment_count=equipment_count or len(per_equipment),
            per_equipment=per_equipment,
        )
        top_anomalies = _build_top_anomalies(per_equipment)
    else:
        kpi_summary = _build_kpi_summary(current_kpis, previous_kpis, units)
        trend_chart = _build_trend_chart(
            current.get("hourly_runtime_rate") or [],
            (compare or {}).get("hourly_runtime_rate") if compare else None,
            payload.get("report_date", ""),
            payload.get("compare_date"),
        )
        top_anomalies = []

    alarms = current.get("alarms") or []
    alarm_table = [
        {
            "time": a.get("time", ""),
            "equipment": a.get("equipment", ""),
            "level": a.get("level", "info"),
            "message": a.get("message", ""),
        }
        for a in alarms
    ]
    overall = _overall_status(kpi_summary, alarms, equipment_count if is_aggregated else None)
    recs = _recommendations(kpi_summary, alarms)

    result: dict = {
        "report_date": payload.get("report_date"),
        "equipment_ids": payload.get("equipment_ids", []),
        "equipment_names": payload.get("equipment_names", {}),
        "compare_type": payload.get("compare_type", "none"),
        "compare_date": payload.get("compare_date"),
        "overall_status": overall,
        "kpi_summary": kpi_summary,
        "trend_chart": trend_chart,
        "alarm_table": alarm_table,
        "recommendations": recs,
        "aggregation_mode": "grouped" if is_aggregated else "detail",
    }
    if is_aggregated:
        result["equipment_type"] = payload.get("equipment_type", "all")
        result["equipment_count"] = equipment_count or len(per_equipment)
        result["top_anomalies"] = top_anomalies
    return result


def read_input(path: Path | None = None) -> dict:
    target = path or (_output_dir() / INPUT_FILENAME)
    return json.loads(target.read_text(encoding="utf-8"))


def write_output(result: dict, path: Path | None = None) -> Path:
    out_path = path or (_output_dir() / OUTPUT_FILENAME)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Compute daily KPI summary")
    parser.add_argument("--input", default=None, help="Input JSON path")
    parser.add_argument("--output", default=None, help="Output JSON path")
    args = parser.parse_args()

    try:
        payload = read_input(Path(args.input)) if args.input else read_input()
    except FileNotFoundError as exc:
        print(json.dumps({"error": f"input not found: {exc}"}, ensure_ascii=False))
        return 0
    except json.JSONDecodeError as exc:
        print(json.dumps({"error": f"invalid input JSON: {exc}"}, ensure_ascii=False))
        return 0

    result = compute(payload)
    out_path = write_output(result, Path(args.output) if args.output else None)
    print(json.dumps({"output": str(out_path), "report_date": result["report_date"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
