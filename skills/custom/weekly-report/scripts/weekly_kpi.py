#!/usr/bin/env python
"""Compute weekly KPI summary, daily trend chart, anomaly TopN, and next-week focus.

Reads ``$WEEKLY_REPORT_OUTPUT_DIR/weekly_data.json`` and writes
``$WEEKLY_REPORT_OUTPUT_DIR/weekly_kpi.json`` matching design doc §6.2.

Key differences from daily_kpi.py:
- Weekly KPI summary exposes ``current_mean / current_peak / current_trough /
  current_volatility`` (not the single ``current`` value used in daily). This
  naming is deliberate to keep daily/weekly outputs distinguishable.
- ``daily_trend_chart`` x-axis is 7 day labels (``MM-DD 周X``) instead of the
  daily 24-hour ticks.
- ``anomaly_top_n`` is grouped by ``(equipment, level)`` over the full week.
- ``next_week_focus`` is mechanically derived (no LLM) from anomaly hot spots
  and KPIs that trended down vs. the previous period.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

_SCRIPT_DIR = str(Path(__file__).resolve().parent)
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from _report_common import (
    KPI_BETTER_WHEN_HIGHER,
    KPI_DISPLAY_NAMES,
    SMS_SEVERITY_DISPLAY,
    direction as _direction,
    safe_pct as _safe_pct,
)
from _perf import get_tracer

DEFAULT_OUTPUT_DIR = "/mnt/user-data/outputs"
INPUT_FILENAME = "weekly_data.json"
OUTPUT_FILENAME = "weekly_kpi.json"

WEEKDAY_LABELS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

TOP_N_LIMIT = 10
FOCUS_LIMIT = 5


def _output_dir() -> Path:
    return Path(os.environ.get("WEEKLY_REPORT_OUTPUT_DIR", DEFAULT_OUTPUT_DIR))


def _build_kpi_summary(
    current_agg: dict,
    previous_agg: dict | None,
    kpi_units: dict,
    kpi_keys: list[str],
) -> list[dict]:
    means = current_agg.get("kpis_mean", {})
    peaks = current_agg.get("kpis_max", {})
    troughs = current_agg.get("kpis_min", {})
    stds = current_agg.get("kpis_std", {})
    prev_means = (previous_agg or {}).get("kpis_mean", {}) if previous_agg else {}

    summary: list[dict] = []
    for key in kpi_keys:
        if key not in means:
            continue
        current_mean = means[key]
        previous_mean = prev_means.get(key) if previous_agg else None
        delta_mean = None
        delta_pct = None
        if previous_mean is not None:
            delta_mean = round(current_mean - previous_mean, 4)
            delta_pct = _safe_pct(delta_mean, previous_mean)
        volatility = _safe_pct(stds.get(key, 0.0), current_mean) if current_mean else None
        better = key in KPI_BETTER_WHEN_HIGHER
        summary.append(
            {
                "key": key,
                "name": KPI_DISPLAY_NAMES.get(key, key),
                "unit": kpi_units.get(key, ""),
                "current_mean": current_mean,
                "current_peak": peaks.get(key),
                "current_trough": troughs.get(key),
                "current_volatility": volatility,
                "previous_mean": previous_mean,
                "delta_mean": delta_mean,
                "delta_pct": delta_pct,
                "direction": _direction(delta_mean, better),
                "better_when_higher": better,
            }
        )
    return summary


def _build_daily_trend_chart(daily_entries: list[dict], kpi_keys: list[str], kpi_units: dict) -> dict:
    """Build a 2-axis ECharts option (line for rate-like, bar for count-like)."""
    if not daily_entries:
        return {}
    x_labels: list[str] = []
    for i, entry in enumerate(daily_entries):
        date = entry.get("date", "")
        suffix = date[5:] if len(date) >= 10 else date
        weekday = WEEKDAY_LABELS[i % 7]
        x_labels.append(f"{suffix} {weekday}")

    rate_keys = [k for k in kpi_keys if k in KPI_BETTER_WHEN_HIGHER or k in ("runtime_rate",)]
    count_keys = [k for k in kpi_keys if k not in rate_keys]

    series: list[dict] = []
    legend_data: list[str] = []
    for key in rate_keys:
        name = KPI_DISPLAY_NAMES.get(key, key)
        legend_data.append(name)
        series.append({
            "name": name,
            "type": "line",
            "yAxisIndex": 0,
            "smooth": True,
            "data": [d.get("kpis", {}).get(key) for d in daily_entries],
        })
    for key in count_keys:
        name = KPI_DISPLAY_NAMES.get(key, key)
        legend_data.append(name)
        series.append({
            "name": name,
            "type": "bar",
            "yAxisIndex": 1 if rate_keys else 0,
            "data": [d.get("kpis", {}).get(key) for d in daily_entries],
        })

    rate_unit = kpi_units.get(rate_keys[0], "") if rate_keys else ""
    count_unit = kpi_units.get(count_keys[0], "") if count_keys else ""
    y_axis: list[dict]
    if rate_keys and count_keys:
        y_axis = [
            {"type": "value", "name": rate_unit},
            {"type": "value", "name": count_unit},
        ]
    else:
        # Single axis fallback
        y_axis = [{"type": "value", "name": rate_unit or count_unit}]
        if not rate_keys:
            for s in series:
                s["yAxisIndex"] = 0

    return {
        "title": {"text": "本周日趋势"},
        "tooltip": {"trigger": "axis"},
        "legend": {"data": legend_data, "selected": {n: True for n in legend_data}},
        "xAxis": {"type": "category", "data": x_labels},
        "yAxis": y_axis,
        "series": series,
    }


def _build_anomaly_top_n(alarms: list[dict]) -> list[dict]:
    """Group alarms by (equipment, level) and rank by count desc, limit 10."""
    if not alarms:
        return []
    grouped: dict[tuple[str, str], dict] = {}
    for alarm in alarms:
        equipment = alarm.get("equipment", "unknown")
        equipment_id = alarm.get("equipment_id", equipment)
        level = alarm.get("level", "info")
        time = alarm.get("time", "")
        message = alarm.get("message", "")
        bucket = grouped.setdefault(
            (equipment_id, level),
            {
                "equipment": equipment,
                "equipment_id": equipment_id,
                "level": level,
                "count": 0,
                "latest_time": time,
                "_messages": {},
            },
        )
        bucket["count"] += 1
        if time > (bucket["latest_time"] or ""):
            bucket["latest_time"] = time
        bucket["_messages"][message] = bucket["_messages"].get(message, 0) + 1

    rows: list[dict] = []
    for bucket in grouped.values():
        msgs = bucket.pop("_messages")
        dominant = max(msgs.items(), key=lambda kv: kv[1])[0] if msgs else ""
        bucket["dominant_message"] = dominant
        rows.append(bucket)

    # Sort high level first within equal counts.
    level_rank = {"high": 0, "critical": 0, "warning": 1, "info": 2}
    rows.sort(key=lambda r: (-r["count"], level_rank.get(r["level"], 3), r["equipment"]))
    return rows[:TOP_N_LIMIT]


def _build_alarm_table(alarms: list[dict]) -> list[dict]:
    return [
        {
            "time": a.get("time", ""),
            "equipment_id": a.get("equipment_id", a.get("equipment", "")),
            "equipment": a.get("equipment", ""),
            "level": a.get("level", "info"),
            "message": a.get("message", ""),
        }
        for a in alarms
    ]


def _sms_kpi(key: str, value: int) -> dict:
    """Build a KPI summary entry for an SMS metric (no comparison/delta)."""
    return {
        "key": key,
        "name": KPI_DISPLAY_NAMES.get(key, key),
        "unit": "条",
        "current_mean": value, "current_peak": None, "current_trough": None,
        "current_volatility": None, "previous_mean": None, "delta_mean": None,
        "delta_pct": None, "direction": "flat", "better_when_higher": False,
    }


def _fetch_sms_direct(payload: dict) -> dict | None:
    """Fetch SMS abnormal data directly via API using payload parameters."""
    period = payload.get("report_period") or {}
    week_start = period.get("week_start")
    equipment_ids = payload.get("equipment_ids") or []
    eq_type = payload.get("equipment_type", "all")
    equipment_names = payload.get("equipment_names") or {}

    if not week_start or not equipment_ids:
        return None

    equipment_meta = (
        {eid: {"name": name} for eid, name in equipment_names.items()}
        if equipment_names
        else None
    )

    try:
        from query_sms_abnormal import fetch_sms_abnormal
        result = fetch_sms_abnormal(week_start, equipment_ids, eq_type, equipment_meta)
    except Exception:
        return None

    sms_data = result.get("sms_abnormal")
    if not isinstance(sms_data, dict):
        return None
    if "error" in sms_data:
        return None
    if sms_data.get("total_count", 0) == 0:
        return None
    return sms_data


def _build_sms_anomaly_table(sms_abnormal: dict | None) -> list[dict]:
    """Convert SMS top_events into display rows for the report."""
    if not sms_abnormal:
        return []
    events = sms_abnormal.get("top_events") or []
    rows: list[dict] = []
    for evt in events:
        level = evt.get("latest_level", 0)
        sev = _severity_label(level)
        rows.append({
            "rank": evt.get("rank", 0),
            "equipment": evt.get("mac_name", ""),
            "component": evt.get("component_name", ""),
            "health": evt.get("latest_health", 0),
            "level": level,
            "severity": SMS_SEVERITY_DISPLAY.get(sev, sev),
            "event_count": evt.get("event_count", 0),
            "process_status": evt.get("process_status", ""),
            "run_status": evt.get("run_status", ""),
        })
    return rows


def _severity_label(level: int) -> str:
    """Map SMS latest_level to severity label using SMS_SEVERITY_MAP from _report_common."""
    from _report_common import SMS_SEVERITY_MAP
    for threshold, label in SMS_SEVERITY_MAP:
        if level >= threshold:
            return label
    return "low"


def _build_overall_status(kpi_summary: list[dict], alarms: list[dict], sms_abnormal: dict | None = None) -> dict:
    high_alarms = [a for a in alarms if a.get("level") in ("high", "critical")]
    runtime = next((item for item in kpi_summary if item["key"] == "runtime_rate"), None)
    sms_critical = (
        (sms_abnormal or {}).get("by_severity", {}).get("critical", 0) +
        (sms_abnormal or {}).get("by_severity", {}).get("high", 0)
    ) if sms_abnormal else 0
    if high_alarms or sms_critical > 0:
        level = "critical"
        parts = [f"本周存在 {len(high_alarms)} 条高级告警" + (f"，{sms_critical} 条 SMS 严重/高异常" if sms_critical > 0 else "") + "，需重点关注。"]
    elif runtime and isinstance(runtime["current_mean"], (int, float)) and runtime["current_mean"] < 0.85:
        level = "warning"
        parts = ["本周运行率均值偏低，建议核查停机分布与值班排班。"]
    elif alarms:
        level = "warning"
        parts = [f"本周运行整体平稳,有 {len(alarms)} 条告警需要关注。"]
    else:
        level = "good"
        parts = ["本周设备运行平稳,未发现显著异常。"]
    return {"level": level, "summary": "".join(parts)}


def _build_next_week_focus(
    kpi_summary: list[dict],
    anomaly_top_n: list[dict],
    overall: dict,
    sms_abnormal: dict | None = None,
) -> list[str]:
    focus: list[str] = []
    for row in anomaly_top_n[:3]:
        focus.append(
            f"{row['equipment']} 本周 {row['level']} 级告警 {row['count']} 次（{row['dominant_message']}），建议优先排查。"
        )
    # SMS hot spots
    if sms_abnormal:
        top_events = sms_abnormal.get("top_events") or []
        for evt in top_events[:2]:
            level = evt.get("latest_level", 0)
            sev = _severity_label(level)
            if sev in ("critical", "high"):
                focus.append(
                    f"{evt.get('mac_name', '未知设备')} 本周存在 SMS {SMS_SEVERITY_DISPLAY.get(sev, sev)}异常"
                    f"（{evt.get('component_name', '')}，健康度 {evt.get('latest_health', 0)}），建议安排现场检查。"
                )
    for item in kpi_summary:
        if item["direction"] == "down" and item.get("delta_pct") is not None and abs(item["delta_pct"]) > 0.05:
            focus.append(
                f"{item['name']} 较上期 {('提升' if item['better_when_higher'] else '下降')}受阻"
                f"（{item['current_mean']}{item['unit']}），下周持续跟踪。"
            )
    if not focus:
        focus.append("本周无重点关注事项，保持当前预防性维护节奏。")
    return focus[:FOCUS_LIMIT]


def compute(payload: dict) -> dict:
    tracer = get_tracer(trace_id=os.environ.get("REPORT_RUN_ID"))
    tracer.start_span("kpi_compute")

    period = payload.get("report_period") or {}
    current = payload.get("current") or {}
    compare = payload.get("compare") or None
    kpi_keys = payload.get("kpi_keys") or list((current.get("aggregated") or {}).get("kpis_mean", {}).keys())

    # kpi_units: detail mode -> from first daily entry; aggregate mode -> top-level
    daily = current.get("daily") or []
    if daily:
        kpi_units = daily[0].get("kpi_units") or {}
    else:
        kpi_units = current.get("kpi_units") or {}

    current_agg = current.get("aggregated") or {}
    previous_agg = (compare or {}).get("aggregated") if compare else None

    with ThreadPoolExecutor(max_workers=1) as sms_pool:
        sms_future = sms_pool.submit(_fetch_sms_direct, payload)

        kpi_summary = _build_kpi_summary(current_agg, previous_agg, kpi_units, kpi_keys)
        daily_trend_chart = _build_daily_trend_chart(daily, kpi_keys, kpi_units)
        alarms = current.get("alarms") or []
        anomaly_top_n = _build_anomaly_top_n(alarms)
        alarm_table = _build_alarm_table(alarms)

        data_source = payload["data_source"]
        data_notes = list(payload.get("data_notes") or [])

        sms_abnormal = sms_future.result()

    sms_abnormal_table = _build_sms_anomaly_table(sms_abnormal)
    if sms_abnormal:
        sms_total = sms_abnormal.get("total_count", 0)
        sms_pending = (sms_abnormal.get("by_status") or {}).get("待处理", 0)
        kpi_summary = list(kpi_summary) + [
            _sms_kpi("sms_abnormal_count", sms_total),
            _sms_kpi("sms_abnormal_pending", sms_pending),
        ]

    overall = _build_overall_status(kpi_summary, alarms, sms_abnormal)
    next_week_focus = _build_next_week_focus(kpi_summary, anomaly_top_n, overall, sms_abnormal)

    tracer.end_span(record_count=len(kpi_summary))

    return {
        "report_period": period,
        "equipment_ids": payload.get("equipment_ids", []),
        "equipment_names": payload.get("equipment_names", {}),
        "compare_type": payload.get("compare_type", "none"),
        "compare_period": payload.get("compare_period"),
        "overall_status": overall,
        "kpi_summary": kpi_summary,
        "daily_trend_chart": daily_trend_chart,
        "anomaly_top_n": anomaly_top_n,
        "sms_abnormal_table": sms_abnormal_table,
        "alarm_table": alarm_table,
        "next_week_focus": next_week_focus,
        "data_source": data_source,
        "data_notes": data_notes,
        "week_start_warning": payload.get("week_start_warning"),
        "compare_warning": payload.get("compare_warning"),
    }


def read_input(path: Path | None = None) -> dict:
    target = path or (_output_dir() / INPUT_FILENAME)
    return json.loads(target.read_text(encoding="utf-8"))


def write_output(result: dict, path: Path | None = None) -> Path:
    out_path = path or (_output_dir() / OUTPUT_FILENAME)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Compute weekly KPI summary")
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
    print(
        json.dumps(
            {"output": str(out_path), "week_start": result["report_period"].get("week_start")},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
