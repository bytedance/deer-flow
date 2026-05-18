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
import math
import os
import sys
from pathlib import Path

DEFAULT_OUTPUT_DIR = "/mnt/user-data/outputs"
INPUT_FILENAME = "monthly_data.json"
OUTPUT_FILENAME = "monthly_kpi.json"

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
    "mtbf": "MTBF",
    "mttr": "MTTR",
    "target_rate": "达标率",
}

KPI_UNITS = {
    "mtbf": "小时",
    "mttr": "小时",
    "target_rate": "%",
}

KPI_BETTER_WHEN_HIGHER = {
    "runtime_rate",
    "output",
    "flow_rate",
    "outlet_pressure",
    "mtbf",
    "target_rate",
}

# MTTR / downtime_count / alarm_count / energy_consumption are lower-is-better
# by virtue of NOT being in KPI_BETTER_WHEN_HIGHER.

TOP_N_LIMIT = 10
CRITICAL_EVENTS_LIMIT = 50
NEXT_MONTH_PLAN_LIMIT = 6

ZERO_FAILURE_NOTE = "本月零故障，MTBF/MTTR 不适用"
DEMO_BANNER_NOTE = "本次月报使用演示数据回退，仅用于流程验证"

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


def _safe_pct(numerator: float, denominator: float | None) -> float | None:
    """Return numerator/denominator rounded to 4 decimals, or None on zero/None."""
    if denominator is None or denominator == 0:
        return None
    return round(numerator / denominator, 4)


def _direction(delta: float | None, better_when_higher: bool) -> str:
    if delta is None:
        return "flat"
    if abs(delta) < 1e-9:
        return "flat"
    if better_when_higher:
        return "up" if delta > 0 else "down"
    return "down" if delta > 0 else "up"


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
        level = alarm.get("level", "info")
        time = alarm.get("time", "")
        message = alarm.get("message", "")
        bucket = grouped.setdefault(
            (equipment, level),
            {
                "equipment": equipment,
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
                "equipment": e.get("equipment", ""),
                "level": e.get("level", "critical"),
                "message": e.get("message", ""),
                "duration_minutes": e.get("duration_minutes"),
                "resolved": e.get("resolved", False),
            }
        )
    return out


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
) -> dict:
    """Single-line summary (≤ 80 chars) for card/banner use.

    Multi-paragraph review lives in ``monthly_review`` — see design §6.2 note.
    """
    runtime = next((k for k in kpi_summary if k["key"] == "runtime_rate"), None)
    mtbf = next((k for k in kpi_summary if k["key"] == "mtbf"), None)
    if critical_events:
        level = "critical"
        parts = [f"本月发生 {len(critical_events)} 起重大事件，需复盘。"]
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
    data_source: str | None,
) -> str:
    """Multi-paragraph month-level review string (sprint plan M2)."""
    paragraphs: list[str] = []
    if data_source == "demo_fallback":
        paragraphs.append(f"> {DEMO_BANNER_NOTE}")
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
) -> list[str]:
    plan: list[str] = []
    # Carry-over from anomaly hot spots.
    for row in anomaly_top_n[:3]:
        plan.append(
            f"{row['equipment']} {row['level']} 级告警 {row['count']} 次（{row['dominant_message']}），"
            "下月优先排查"
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
    overall = _build_overall_status(kpi_summary, critical_events, notes)
    monthly_review = _build_monthly_review(
        kpi_summary, critical_events, improvement_tracking, notes, payload.get("data_source")
    )
    next_month_plan = _build_next_month_plan(kpi_summary, anomaly_top_n, improvement_tracking)

    # Slim down period for output: drop week_buckets (full buckets are available
    # via monthly_data.json; KPI consumers only need start/end/day_count).
    report_period = {
        "report_month": period.get("report_month"),
        "month_start": period.get("month_start"),
        "month_end": period.get("month_end"),
        "day_count": period.get("day_count"),
    }

    return {
        "report_period": report_period,
        "compare_types": payload.get("compare_types") or [],
        "compare_periods": payload.get("compare_periods") or {},
        "overall_status": overall,
        "kpi_summary": kpi_summary,
        "weekly_trend_chart": weekly_trend_chart,
        "anomaly_top_n": anomaly_top_n,
        "critical_events": critical_events,
        "improvement_tracking": improvement_tracking,
        "monthly_review": monthly_review,
        "next_month_plan": next_month_plan,
        "data_source": payload.get("data_source"),
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
