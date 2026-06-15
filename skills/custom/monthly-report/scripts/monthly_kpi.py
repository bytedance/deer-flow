#!/usr/bin/env python
"""Compute monthly KPI summary, weekly trend chart, anomaly TopN,
critical events, improvement tracking, and monthly review / next-month plan.

Reads ``$MONTHLY_REPORT_OUTPUT_DIR/monthly_data.json`` (with the same env
var fallback chain as ``query_monthly.py``) and writes
``$MONTHLY_REPORT_OUTPUT_DIR/monthly_kpi.json`` matching design doc §6.2.

Key contracts (sprint plan M2):
- Month-level mean is a weekly day_count-weighted average (NOT a 30-day
  simple mean and NOT identical to weekly's 7-day simple mean).
- Field names ``previous_year_month_mean`` / ``delta_yoy`` / ``delta_yoy_pct``
  must contain ``month`` so YoY is unambiguous; ``previous_year_mean`` is a
  regression failure.
- Per-KPI ``current_in_target_ratio`` is "days within target / month days"
  and is distinct from the aggregate-KPI ``key == "target_rate"`` (which
  is the simple mean of all single-KPI ratios).
- ``mtbf`` formula: ``total_uptime_hours / max(total_failures, 1)``; outputs
  ``null`` when ``total_failures == 0`` and tags ``monthly_review`` with
  "本月零故障，MTBF/MTTR 不适用". Same guard for ``mttr``.
- This script does NOT emit a ``summary_markdown`` field — full markdown is
  rendered exclusively by ``export_report.render_monthly_markdown``.
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
    KPI_BETTER_WHEN_HIGHER_MONTHLY as KPI_BETTER_WHEN_HIGHER,
    KPI_DISPLAY_NAMES_MONTHLY as KPI_DISPLAY_NAMES,
    KPI_UNITS,
    SMS_SEVERITY_DISPLAY,
    direction as _direction,
    safe_pct as _safe_pct,
)
from _perf import get_tracer

DEFAULT_OUTPUT_DIR = "/mnt/user-data/outputs"
INPUT_FILENAME = "monthly_data.json"
OUTPUT_FILENAME = "monthly_kpi.json"

# MTTR / downtime_count / alarm_count are lower-is-better
# by virtue of NOT being in KPI_BETTER_WHEN_HIGHER.

TOP_N_LIMIT = 10
CRITICAL_EVENTS_LIMIT = 50
NEXT_MONTH_PLAN_LIMIT = 6

ZERO_FAILURE_NOTE = "本月零故障，MTBF/MTTR 不适用"

# completion_rate mapping for demo improvement tracking (sprint plan M2):
COMPLETION_RATE_BY_STATUS = {
    "done": 100,
    "closed": 100,
    "in_progress": 60,
    "delayed": 30,
}


def _output_dir() -> Path:
    return Path(
        os.environ.get(
            "MONTHLY_REPORT_OUTPUT_DIR",
            os.environ.get(
                "WEEKLY_REPORT_OUTPUT_DIR",
                os.environ.get("DAILY_REPORT_OUTPUT_DIR", DEFAULT_OUTPUT_DIR),
            ),
        )
    )


def _resolve_baseline_mean(
    compare_block: dict | None,
    basis: str,
    key: str,
    maintenance_field: str | None = None,
) -> float | None:
    """Pull a single baseline mean from compare[basis].

    For ordinary KPIs, looks at ``compare[basis].aggregated.kpis_mean[key]``.
    For MTBF/MTTR (driven by ``maintenance_field``), reads from
    ``compare[basis].maintenance.<field>`` so the YoY/MoM math for derived
    metrics stays consistent with the current-period derivation.
    """
    if not compare_block:
        return None
    block = compare_block.get(basis)
    if not block:
        return None
    if maintenance_field:
        m = block.get("maintenance") or {}
        v = m.get(maintenance_field)
        return float(v) if isinstance(v, (int, float)) else None
    means = (block.get("aggregated") or {}).get("kpis_mean") or {}
    v = means.get(key)
    return float(v) if isinstance(v, (int, float)) else None


def _build_ordinary_kpi_entry(
    key: str,
    current_agg: dict,
    compare_block: dict | None,
    kpi_units: dict,
    target_rates: dict[str, float],
) -> dict | None:
    means = current_agg.get("kpis_mean", {})
    if key not in means:
        return None
    current_mean = means[key]
    peaks = current_agg.get("kpis_max", {})
    troughs = current_agg.get("kpis_min", {})
    stds = current_agg.get("kpis_std", {})

    volatility = _safe_pct(stds.get(key, 0.0), current_mean) if current_mean else None
    better = key in KPI_BETTER_WHEN_HIGHER

    prev_mo = _resolve_baseline_mean(compare_block, "previous_month", key)
    prev_yr = _resolve_baseline_mean(compare_block, "previous_year_month", key)

    delta_mom, delta_mom_pct = _delta(current_mean, prev_mo)
    delta_yoy, delta_yoy_pct = _delta(current_mean, prev_yr)

    return {
        "key": key,
        "name": KPI_DISPLAY_NAMES.get(key, key),
        "unit": kpi_units.get(key, ""),
        "current_mean": round(current_mean, 4),
        "current_peak": peaks.get(key),
        "current_trough": troughs.get(key),
        "current_volatility": volatility,
        "current_in_target_ratio": target_rates.get(key),
        "previous_month_mean": prev_mo,
        "delta_mom": delta_mom,
        "delta_mom_pct": delta_mom_pct,
        "direction_mom": _direction(delta_mom, better),
        "previous_year_month_mean": prev_yr,
        "delta_yoy": delta_yoy,
        "delta_yoy_pct": delta_yoy_pct,
        "direction_yoy": _direction(delta_yoy, better),
        "better_when_higher": better,
    }


def _delta(current: float | None, previous: float | None) -> tuple[float | None, float | None]:
    """Return (delta_abs, delta_pct). Both None when current or previous is None.

    delta_pct is None when previous is 0 (avoids ZeroDivisionError → NaN%).
    """
    if current is None or previous is None:
        return None, None
    delta_abs = round(current - previous, 4)
    delta_pct = _safe_pct(delta_abs, previous)
    return delta_abs, delta_pct


def _build_mtbf_entry(
    maintenance: dict,
    compare_block: dict | None,
    note_accumulator: list[str],
) -> dict:
    failures = maintenance.get("total_failures", 0) or 0
    uptime = maintenance.get("total_uptime_hours")
    if failures <= 0 or uptime is None:
        current_mean: float | None = None
        if ZERO_FAILURE_NOTE not in note_accumulator:
            note_accumulator.append(ZERO_FAILURE_NOTE)
    else:
        current_mean = round(uptime / max(failures, 1), 2)

    prev_mo = _resolve_baseline_mean(compare_block, "previous_month", "mtbf", "mtbf_hours")
    prev_yr = _resolve_baseline_mean(compare_block, "previous_year_month", "mtbf", "mtbf_hours")
    delta_mom, delta_mom_pct = _delta(current_mean, prev_mo)
    delta_yoy, delta_yoy_pct = _delta(current_mean, prev_yr)

    return {
        "key": "mtbf",
        "name": KPI_DISPLAY_NAMES["mtbf"],
        "unit": KPI_UNITS["mtbf"],
        "current_mean": current_mean,
        "current_peak": None,
        "current_trough": None,
        "current_volatility": None,
        "current_in_target_ratio": None,
        "previous_month_mean": prev_mo,
        "delta_mom": delta_mom,
        "delta_mom_pct": delta_mom_pct,
        "direction_mom": _direction(delta_mom, True),
        "previous_year_month_mean": prev_yr,
        "delta_yoy": delta_yoy,
        "delta_yoy_pct": delta_yoy_pct,
        "direction_yoy": _direction(delta_yoy, True),
        "better_when_higher": True,
    }


def _build_mttr_entry(
    maintenance: dict,
    compare_block: dict | None,
    note_accumulator: list[str],
) -> dict:
    failures = maintenance.get("total_failures", 0) or 0
    repair_min = maintenance.get("total_repair_minutes")
    if failures <= 0 or repair_min is None:
        current_mean: float | None = None
        if ZERO_FAILURE_NOTE not in note_accumulator:
            note_accumulator.append(ZERO_FAILURE_NOTE)
    else:
        current_mean = round(repair_min / max(failures, 1) / 60.0, 2)

    prev_mo = _resolve_baseline_mean(compare_block, "previous_month", "mttr", "mttr_hours")
    prev_yr = _resolve_baseline_mean(compare_block, "previous_year_month", "mttr", "mttr_hours")
    delta_mom, delta_mom_pct = _delta(current_mean, prev_mo)
    delta_yoy, delta_yoy_pct = _delta(current_mean, prev_yr)

    return {
        "key": "mttr",
        "name": KPI_DISPLAY_NAMES["mttr"],
        "unit": KPI_UNITS["mttr"],
        "current_mean": current_mean,
        "current_peak": None,
        "current_trough": None,
        "current_volatility": None,
        "current_in_target_ratio": None,
        "previous_month_mean": prev_mo,
        "delta_mom": delta_mom,
        "delta_mom_pct": delta_mom_pct,
        "direction_mom": _direction(delta_mom, False),
        "previous_year_month_mean": prev_yr,
        "delta_yoy": delta_yoy,
        "delta_yoy_pct": delta_yoy_pct,
        "direction_yoy": _direction(delta_yoy, False),
        "better_when_higher": False,
    }


def _build_target_rate_entry(target_rates: dict[str, float]) -> dict | None:
    """Aggregate target_rate KPI = simple mean of all per-KPI ratios.

    Distinct from the per-KPI ``current_in_target_ratio`` field — see
    sprint plan M2 acceptance.
    """
    if not target_rates:
        return None
    values = [v for v in target_rates.values() if isinstance(v, (int, float))]
    if not values:
        return None
    mean = round(sum(values) / len(values), 4)
    return {
        "key": "target_rate",
        "name": KPI_DISPLAY_NAMES["target_rate"],
        "unit": KPI_UNITS["target_rate"],
        "current_mean": mean,
        "current_peak": None,
        "current_trough": None,
        "current_volatility": None,
        "current_in_target_ratio": None,
        "previous_month_mean": None,
        "delta_mom": None,
        "delta_mom_pct": None,
        "direction_mom": "flat",
        "previous_year_month_mean": None,
        "delta_yoy": None,
        "delta_yoy_pct": None,
        "direction_yoy": "flat",
        "better_when_higher": True,
    }


def _build_kpi_summary(
    kpi_keys: list[str],
    current_agg: dict,
    maintenance: dict,
    compare_block: dict | None,
    kpi_units: dict,
    note_accumulator: list[str],
) -> list[dict]:
    target_rates: dict[str, float] = current_agg.get("kpis_target_rate") or {}
    summary: list[dict] = []
    seen_special: set[str] = set()
    for key in kpi_keys:
        if key == "mtbf":
            summary.append(_build_mtbf_entry(maintenance, compare_block, note_accumulator))
            seen_special.add("mtbf")
            continue
        if key == "mttr":
            summary.append(_build_mttr_entry(maintenance, compare_block, note_accumulator))
            seen_special.add("mttr")
            continue
        if key == "target_rate":
            entry = _build_target_rate_entry(target_rates)
            if entry is not None:
                summary.append(entry)
                seen_special.add("target_rate")
            continue
        entry = _build_ordinary_kpi_entry(key, current_agg, compare_block, kpi_units, target_rates)
        if entry is not None:
            summary.append(entry)
    return summary


def _build_weekly_trend_chart(weekly: list[dict], kpi_keys: list[str], kpi_units: dict) -> dict:
    """ECharts option: 4-5 buckets on x-axis, line for rate-like, bar for count-like."""
    if not weekly:
        return {}
    x_labels = [b.get("label", "") for b in weekly]

    plottable_keys = [k for k in kpi_keys if k not in ("mtbf", "mttr", "target_rate")]
    rate_keys = [k for k in plottable_keys if k in KPI_BETTER_WHEN_HIGHER]
    count_keys = [k for k in plottable_keys if k not in rate_keys]

    series: list[dict] = []
    legend_data: list[str] = []
    for key in rate_keys:
        name = KPI_DISPLAY_NAMES.get(key, key)
        legend_data.append(name)
        series.append(
            {
                "name": name,
                "type": "line",
                "yAxisIndex": 0,
                "smooth": True,
                "data": [(b.get("kpis_mean") or {}).get(key) for b in weekly],
            }
        )
    for key in count_keys:
        name = KPI_DISPLAY_NAMES.get(key, key)
        legend_data.append(name)
        series.append(
            {
                "name": name,
                "type": "bar",
                "yAxisIndex": 1 if rate_keys else 0,
                "data": [(b.get("kpis_mean") or {}).get(key) for b in weekly],
            }
        )

    rate_unit = kpi_units.get(rate_keys[0], "") if rate_keys else ""
    count_unit = kpi_units.get(count_keys[0], "") if count_keys else ""
    y_axis: list[dict]
    if rate_keys and count_keys:
        y_axis = [
            {"type": "value", "name": rate_unit},
            {"type": "value", "name": count_unit},
        ]
    else:
        y_axis = [{"type": "value", "name": rate_unit or count_unit}]
        if not rate_keys:
            for s in series:
                s["yAxisIndex"] = 0

    return {
        "title": {"text": "本月周维度趋势"},
        "tooltip": {"trigger": "axis"},
        "legend": {"data": legend_data, "selected": {n: True for n in legend_data}},
        "xAxis": {"type": "category", "data": x_labels},
        "yAxis": y_axis,
        "series": series,
    }


def _build_anomaly_top_n(alarms: list[dict]) -> list[dict]:
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

    level_rank = {"critical": 0, "high": 0, "warning": 1, "info": 2}
    rows.sort(key=lambda r: (-r["count"], level_rank.get(r["level"], 3), r["equipment"]))
    return rows[:TOP_N_LIMIT]


def _build_critical_events(events: list[dict]) -> list[dict]:
    """Pass-through with 50-entry cap; preserves duration_minutes + resolved."""
    out: list[dict] = []
    for e in events[:CRITICAL_EVENTS_LIMIT]:
        out.append(
            {
                "time": e.get("time", ""),
                "equipment_id": e.get("equipment_id", e.get("equipment", "")),
                "equipment": e.get("equipment", ""),
                "level": e.get("level", "critical"),
                "message": e.get("message", ""),
                "duration_minutes": e.get("duration_minutes"),
                "resolved": e.get("resolved", False),
            }
        )
    return out


def _sms_kpi(key: str, value: int) -> dict:
    """Build a KPI summary entry for an SMS metric (no comparison/delta)."""
    return {
        "key": key,
        "name": KPI_DISPLAY_NAMES.get(key, key),
        "unit": "条",
        "current_mean": value, "current_peak": None, "current_trough": None,
        "current_volatility": None, "current_in_target_ratio": None,
        "previous_month_mean": None, "delta_mom": None, "delta_mom_pct": None,
        "direction_mom": "flat",
        "previous_year_month_mean": None, "delta_yoy": None, "delta_yoy_pct": None,
        "direction_yoy": "flat",
        "better_when_higher": False,
    }


def _fetch_sms_direct(payload: dict) -> dict | None:
    """Fetch SMS abnormal data directly via API using payload parameters."""
    period = payload.get("report_period") or {}
    report_month = period.get("report_month")
    equipment_ids = payload.get("equipment_ids") or []
    eq_type = payload.get("equipment_type", "all")
    equipment_names = payload.get("equipment_names") or {}

    if not report_month or not equipment_ids:
        return None

    equipment_meta = (
        {eid: {"name": name} for eid, name in equipment_names.items()}
        if equipment_names
        else None
    )

    try:
        from query_sms_abnormal import fetch_sms_abnormal
        result = fetch_sms_abnormal(report_month, equipment_ids, eq_type, equipment_meta)
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
        sev = _sms_severity_label(level)
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


def _sms_severity_label(level: int) -> str:
    """Map SMS latest_level to severity label."""
    from _report_common import SMS_SEVERITY_MAP
    for threshold, label in SMS_SEVERITY_MAP:
        if level >= threshold:
            return label
    return "low"


def _build_improvement_tracking(records: list[dict]) -> list[dict]:
    """Pass-through with derived completion_rate (sprint plan M2 mapping)."""
    out: list[dict] = []
    for r in records:
        status = r.get("status", "in_progress")
        completion = COMPLETION_RATE_BY_STATUS.get(status, 0)
        out.append(
            {
                "id": r.get("id", ""),
                "owner": r.get("owner", ""),
                "plan": r.get("plan", ""),
                "due_date": r.get("due_date", ""),
                "status": status,
                "completion_rate": completion,
                "note": r.get("note", ""),
            }
        )
    return out


def _build_overall_status(
    kpi_summary: list[dict],
    critical_events: list[dict],
    notes: list[str],
    sms_abnormal: dict | None = None,
) -> dict:
    """Single-line summary (≤ 80 chars) for card/banner use.

    Multi-paragraph review lives in ``monthly_review`` — see design §6.2 note.
    """
    runtime = next((k for k in kpi_summary if k["key"] == "runtime_rate"), None)
    mtbf = next((k for k in kpi_summary if k["key"] == "mtbf"), None)
    sms_critical = (
        (sms_abnormal or {}).get("by_severity", {}).get("critical", 0) +
        (sms_abnormal or {}).get("by_severity", {}).get("high", 0)
    ) if sms_abnormal else 0
    if critical_events or sms_critical > 0:
        level = "critical"
        parts = [f"本月发生 {len(critical_events)} 起重大事件" + (f"，{sms_critical} 条 SMS 严重/高异常" if sms_critical > 0 else "") + "，需复盘。"]
    elif runtime and isinstance(runtime.get("current_mean"), (int, float)) and runtime["current_mean"] < 0.85:
        level = "warning"
        parts = [f"运行率均值 {runtime['current_mean']*100 if runtime['current_mean'] <= 1 else runtime['current_mean']:.1f}%, 低于目标。"]
    elif mtbf and mtbf.get("current_mean") is None:
        level = "good"
        parts = ["本月零故障。"]
    else:
        level = "good"
        parts = ["本月运行平稳。"]
    if runtime and runtime.get("delta_mom_pct") is not None:
        pct = runtime["delta_mom_pct"] * 100
        parts.append(f"运行率环比 {pct:+.1f}%。")
    summary = "".join(parts)[:80]
    return {"level": level, "summary": summary}


def _build_monthly_review(
    kpi_summary: list[dict],
    critical_events: list[dict],
    improvement_tracking: list[dict],
    notes: list[str],
) -> str:
    """Multi-paragraph month-level review string (sprint plan M2)."""
    paragraphs: list[str] = []
    if notes:
        paragraphs.append(" ".join(notes))

    # Headline paragraph: runtime + MTBF.
    runtime = next((k for k in kpi_summary if k["key"] == "runtime_rate"), None)
    mtbf = next((k for k in kpi_summary if k["key"] == "mtbf"), None)
    headline_parts: list[str] = []
    if runtime:
        mean = runtime.get("current_mean")
        if mean is not None:
            headline_parts.append(f"运行率均值 {mean}{runtime.get('unit','')}")
            if runtime.get("delta_mom_pct") is not None:
                headline_parts.append(f"环比 {runtime['delta_mom_pct']*100:+.1f}%")
            if runtime.get("delta_yoy_pct") is not None:
                headline_parts.append(f"同比 {runtime['delta_yoy_pct']*100:+.1f}%")
    if mtbf and mtbf.get("current_mean") is not None:
        headline_parts.append(f"MTBF {mtbf['current_mean']}h")
    if headline_parts:
        paragraphs.append("、".join(headline_parts) + "。")

    # Anomaly paragraph.
    if critical_events:
        eq_set = sorted({e["equipment"] for e in critical_events if e.get("equipment")})
        paragraphs.append(
            f"本月发生 {len(critical_events)} 起重大（critical）事件，涉及设备 {', '.join(eq_set[:5])}。"
        )

    # Improvement paragraph.
    if improvement_tracking:
        done = sum(1 for r in improvement_tracking if r.get("status") in ("done", "closed"))
        total = len(improvement_tracking)
        delayed = [r for r in improvement_tracking if r.get("status") == "delayed"]
        line = f"上月改进措施完成 {done}/{total}。"
        if delayed:
            line += f"延期项目：{', '.join(r.get('id', '') for r in delayed[:3])}。"
        paragraphs.append(line)

    if not paragraphs:
        paragraphs.append("本月数据不足以生成详细复盘，请补全数据源后重新生成。")
    return "\n\n".join(paragraphs)


def _build_next_month_plan(
    kpi_summary: list[dict],
    anomaly_top_n: list[dict],
    improvement_tracking: list[dict],
    sms_abnormal: dict | None = None,
) -> list[str]:
    plan: list[str] = []
    # Carry-over from anomaly hot spots.
    for row in anomaly_top_n[:3]:
        plan.append(
            f"{row['equipment']} {row['level']} 级告警 {row['count']} 次（{row['dominant_message']}），"
            "下月优先排查"
        )
    # SMS hot spots
    if sms_abnormal:
        top_events = sms_abnormal.get("top_events") or []
        for evt in top_events[:2]:
            level = evt.get("latest_level", 0)
            sev = _sms_severity_label(level)
            if sev in ("critical", "high"):
                plan.append(
                    f"{evt.get('mac_name', '未知设备')} 本月存在 SMS {SMS_SEVERITY_DISPLAY.get(sev, sev)}异常"
                    f"（{evt.get('component_name', '')}），下月安排现场检查"
                )
    # Persistent down-trend KPIs (excluding derived metrics).
    for item in kpi_summary:
        if item["key"] in ("mtbf", "mttr", "target_rate"):
            continue
        if item.get("direction_mom") == "down" and item.get("delta_mom_pct") is not None and abs(item["delta_mom_pct"]) > 0.05:
            plan.append(
                f"{item['name']} 环比下行 {item['delta_mom_pct']*100:+.1f}%，下月持续跟踪"
            )
    # Open improvement items.
    for r in improvement_tracking:
        if r.get("status") in ("in_progress", "delayed"):
            plan.append(
                f"延续改进 {r.get('id','')}：{r.get('plan','')}（{r.get('status','')})"
            )
    if not plan:
        plan.append("本月无显著异常，下月保持当前预防性维护节奏")
    return plan[:NEXT_MONTH_PLAN_LIMIT]


def compute(payload: dict) -> dict:
    tracer = get_tracer(trace_id=os.environ.get("REPORT_RUN_ID"))
    tracer.start_span("kpi_compute")

    period = payload.get("report_period") or {}
    current = payload.get("current") or {}
    compare = payload.get("compare") or None
    kpi_keys = payload.get("kpi_keys") or list(
        (current.get("aggregated") or {}).get("kpis_mean", {}).keys()
    )

    current_agg = current.get("aggregated") or {}
    maintenance = current.get("maintenance") or {}
    kpi_units = current.get("kpi_units") or {}
    # MTBF/MTTR/target_rate units come from the local table — the raw query
    # doesn't have them in kpi_units.
    for k, u in KPI_UNITS.items():
        kpi_units.setdefault(k, u)

    notes: list[str] = []

    with ThreadPoolExecutor(max_workers=1) as sms_pool:
        sms_future = sms_pool.submit(_fetch_sms_direct, payload)

        kpi_summary = _build_kpi_summary(
            kpi_keys=kpi_keys,
            current_agg=current_agg,
            maintenance=maintenance,
            compare_block=compare,
            kpi_units=kpi_units,
            note_accumulator=notes,
        )
        weekly_trend_chart = _build_weekly_trend_chart(current.get("weekly") or [], kpi_keys, kpi_units)
        anomaly_top_n = _build_anomaly_top_n(current.get("alarms") or [])
        critical_events = _build_critical_events(current.get("critical_events") or [])
        improvement_tracking = _build_improvement_tracking(current.get("improvement_tracking") or [])

        sms_abnormal = sms_future.result()

    sms_abnormal_table = _build_sms_anomaly_table(sms_abnormal)
    if sms_abnormal:
        sms_total = sms_abnormal.get("total_count", 0)
        sms_pending = (sms_abnormal.get("by_status") or {}).get("待处理", 0)
        kpi_summary = list(kpi_summary) + [
            _sms_kpi("sms_abnormal_count", sms_total),
            _sms_kpi("sms_abnormal_pending", sms_pending),
        ]

    overall = _build_overall_status(kpi_summary, critical_events, notes, sms_abnormal)
    monthly_review = _build_monthly_review(
        kpi_summary, critical_events, improvement_tracking, notes
    )
    next_month_plan = _build_next_month_plan(kpi_summary, anomaly_top_n, improvement_tracking, sms_abnormal)

    # Slim down period for output: drop week_buckets (full buckets are available
    # via monthly_data.json; KPI consumers only need start/end/day_count).
    report_period = {
        "report_month": period.get("report_month"),
        "month_start": period.get("month_start"),
        "month_end": period.get("month_end"),
        "day_count": period.get("day_count"),
    }

    data_source = payload["data_source"]
    data_notes = list(payload.get("data_notes") or [])

    tracer.end_span(record_count=len(kpi_summary))

    return {
        "report_period": report_period,
        "equipment_ids": payload.get("equipment_ids", []),
        "equipment_names": payload.get("equipment_names", {}),
        "compare_types": payload.get("compare_types") or [],
        "compare_periods": payload.get("compare_periods") or {},
        "overall_status": overall,
        "kpi_summary": kpi_summary,
        "weekly_trend_chart": weekly_trend_chart,
        "anomaly_top_n": anomaly_top_n,
        "sms_abnormal_table": sms_abnormal_table,
        "critical_events": critical_events,
        "improvement_tracking": improvement_tracking,
        "monthly_review": monthly_review,
        "next_month_plan": next_month_plan,
        "data_source": data_source,
        "data_notes": data_notes,
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
    parser = argparse.ArgumentParser(description="Compute monthly KPI summary")
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
            {
                "output": str(out_path),
                "report_month": result["report_period"].get("report_month"),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
