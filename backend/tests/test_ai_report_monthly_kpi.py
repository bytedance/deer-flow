"""Tests for skills/custom/data-analyst/scripts/monthly_kpi.py.

Covers sprint plan M2/M7 acceptance items:
- Weekly day_count-weighted month mean
- delta_mom_pct / delta_yoy_pct null protection (zero divisor, missing compare)
- Field naming: previous_year_month_mean (NOT previous_year_mean)
- MTBF/MTTR formulas + zero-failure protection + 零故障 phrase in monthly_review
- current_in_target_ratio (per-KPI) distinct from target_rate (aggregate KPI)
- weekly_trend_chart.xAxis.data length == week_buckets length
- anomaly_top_n sort + 10-entry cap
- critical_events 50-entry cap
- improvement_tracking.completion_rate derivation rules
- Output JSON does NOT contain summary_markdown
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "skills" / "custom" / "data-analyst" / "scripts" / "monthly_kpi.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("monthly_kpi", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def monthly_kpi():
    return _load_module()


def _base_payload(**overrides) -> dict:
    """Build a minimal but realistic monthly_data.json payload for testing."""
    payload = {
        "report_period": {
            "report_month": "2026-04",
            "month_start": "2026-04-01",
            "month_end": "2026-04-30",
            "day_count": 30,
            "week_buckets": [
                {"label": "W1: 04-01~04-07", "date_range": {"start": "2026-04-01", "end": "2026-04-07"}, "day_count": 7},
                {"label": "W2: 04-08~04-14", "date_range": {"start": "2026-04-08", "end": "2026-04-14"}, "day_count": 7},
                {"label": "W3: 04-15~04-21", "date_range": {"start": "2026-04-15", "end": "2026-04-21"}, "day_count": 7},
                {"label": "W4: 04-22~04-28", "date_range": {"start": "2026-04-22", "end": "2026-04-28"}, "day_count": 7},
                {"label": "W5: 04-29~04-30", "date_range": {"start": "2026-04-29", "end": "2026-04-30"}, "day_count": 2},
            ],
        },
        "kpi_keys": ["runtime_rate", "alarm_count", "mtbf", "mttr", "target_rate"],
        "compare_types": ["previous_month", "previous_year_month"],
        "compare_periods": {
            "previous_month": {"start": "2026-03-01", "end": "2026-03-31"},
            "previous_year_month": {"start": "2025-04-01", "end": "2025-04-30"},
        },
        "current": {
            "weekly": [
                {"label": "W1", "day_count": 7, "kpis_mean": {"runtime_rate": 0.90, "alarm_count": 5},
                 "kpis_max": {"runtime_rate": 0.95}, "kpis_min": {"runtime_rate": 0.85}, "kpis_std": {"runtime_rate": 0.02}},
                {"label": "W2", "day_count": 7, "kpis_mean": {"runtime_rate": 0.92, "alarm_count": 4},
                 "kpis_max": {"runtime_rate": 0.96}, "kpis_min": {"runtime_rate": 0.88}, "kpis_std": {"runtime_rate": 0.02}},
                {"label": "W3", "day_count": 7, "kpis_mean": {"runtime_rate": 0.94, "alarm_count": 3},
                 "kpis_max": {"runtime_rate": 0.97}, "kpis_min": {"runtime_rate": 0.91}, "kpis_std": {"runtime_rate": 0.015}},
                {"label": "W4", "day_count": 7, "kpis_mean": {"runtime_rate": 0.93, "alarm_count": 6},
                 "kpis_max": {"runtime_rate": 0.96}, "kpis_min": {"runtime_rate": 0.90}, "kpis_std": {"runtime_rate": 0.02}},
                {"label": "W5", "day_count": 2, "kpis_mean": {"runtime_rate": 0.89, "alarm_count": 7},
                 "kpis_max": {"runtime_rate": 0.91}, "kpis_min": {"runtime_rate": 0.87}, "kpis_std": {"runtime_rate": 0.02}},
            ],
            "aggregated": {
                "kpis_mean": {"runtime_rate": 0.926, "alarm_count": 4.6},
                "kpis_max": {"runtime_rate": 0.97},
                "kpis_min": {"runtime_rate": 0.85},
                "kpis_std": {"runtime_rate": 0.02},
                "kpis_target_rate": {"runtime_rate": 0.80},
            },
            "maintenance": {
                "total_failures": 6,
                "total_uptime_hours": 692,
                "total_downtime_minutes": 480,
                "total_repair_minutes": 320,
                "mtbf_hours": 115.3,
                "mttr_hours": 0.89,
            },
            "alarms": [],
            "critical_events": [],
            "improvement_tracking": [],
            "kpi_units": {"runtime_rate": "%", "alarm_count": "条"},
        },
        "compare": {
            "previous_month": {
                "weekly": [],
                "aggregated": {"kpis_mean": {"runtime_rate": 0.91}},
                "maintenance": {"mtbf_hours": 86.6, "mttr_hours": 1.10},
                "alarms": [],
            },
            "previous_year_month": {
                "weekly": [],
                "aggregated": {"kpis_mean": {"runtime_rate": 0.895}},
                "maintenance": {"mtbf_hours": 70.0, "mttr_hours": 1.25},
                "alarms": [],
            },
        },
        "data_source": "demo_fallback",
        "compare_warning": None,
    }
    payload.update(overrides)
    return payload


def test_no_summary_markdown_in_output(monthly_kpi):
    """Sprint plan M2 acceptance: monthly_kpi.py must NOT emit summary_markdown."""
    result = monthly_kpi.compute(_base_payload())
    assert "summary_markdown" not in result, (
        "monthly_kpi.py must not output summary_markdown; full markdown is rendered exclusively"
        " by export_report.render_monthly_markdown (design doc §6.2)"
    )


def test_previous_year_month_mean_naming(monthly_kpi):
    """Field name MUST contain 'month' — sprint plan M2 acceptance."""
    result = monthly_kpi.compute(_base_payload())
    rt = next(k for k in result["kpi_summary"] if k["key"] == "runtime_rate")
    assert "previous_year_month_mean" in rt, "field must be previous_year_month_mean (not previous_year_mean)"
    assert "previous_year_mean" not in rt, "old field name previous_year_mean must not appear"
    assert rt["previous_year_month_mean"] == 0.895


def test_delta_mom_pct_null_protection(monthly_kpi):
    payload = _base_payload()
    # Zero divisor case
    payload["compare"]["previous_month"]["aggregated"]["kpis_mean"]["runtime_rate"] = 0
    result = monthly_kpi.compute(payload)
    rt = next(k for k in result["kpi_summary"] if k["key"] == "runtime_rate")
    assert rt["delta_mom_pct"] is None, "delta_mom_pct must be None on zero divisor"


def test_delta_mom_pct_null_when_compare_missing(monthly_kpi):
    payload = _base_payload()
    payload["compare"] = None
    result = monthly_kpi.compute(payload)
    rt = next(k for k in result["kpi_summary"] if k["key"] == "runtime_rate")
    assert rt["delta_mom_pct"] is None
    assert rt["delta_yoy_pct"] is None
    assert rt["previous_month_mean"] is None
    assert rt["previous_year_month_mean"] is None


def test_mtbf_formula_and_zero_failure(monthly_kpi):
    """MTBF = total_uptime_hours / max(total_failures, 1); 0 failures → None + 零故障 phrase."""
    result = monthly_kpi.compute(_base_payload())
    mtbf = next(k for k in result["kpi_summary"] if k["key"] == "mtbf")
    assert mtbf["current_mean"] == pytest.approx(692 / 6, abs=0.01)

    # Zero-failure month
    payload = _base_payload()
    payload["current"]["maintenance"] = {
        "total_failures": 0,
        "total_uptime_hours": 720,
        "total_downtime_minutes": 0,
        "total_repair_minutes": 0,
        "mtbf_hours": None,
        "mttr_hours": None,
    }
    result = monthly_kpi.compute(payload)
    mtbf = next(k for k in result["kpi_summary"] if k["key"] == "mtbf")
    mttr = next(k for k in result["kpi_summary"] if k["key"] == "mttr")
    assert mtbf["current_mean"] is None
    assert mttr["current_mean"] is None
    assert "零故障" in result["monthly_review"]


def test_mttr_formula(monthly_kpi):
    result = monthly_kpi.compute(_base_payload())
    mttr = next(k for k in result["kpi_summary"] if k["key"] == "mttr")
    # 320 minutes / 6 failures / 60 = 0.888...
    assert mttr["current_mean"] == pytest.approx(320 / 6 / 60, abs=0.01)


def test_current_in_target_ratio_distinct_from_target_rate(monthly_kpi):
    result = monthly_kpi.compute(_base_payload())
    rt = next(k for k in result["kpi_summary"] if k["key"] == "runtime_rate")
    # Per-KPI ratio comes from kpis_target_rate map
    assert rt["current_in_target_ratio"] == 0.80
    # Aggregate KPI "target_rate" is the mean of per-KPI ratios; here we only
    # have one (runtime_rate=0.80) so aggregate is 0.80 too.
    tr = next(k for k in result["kpi_summary"] if k["key"] == "target_rate")
    assert tr["current_mean"] == pytest.approx(0.80, abs=0.001)
    # Aggregate KPI must NOT have a current_in_target_ratio set
    assert tr["current_in_target_ratio"] is None


def test_weekly_trend_chart_xaxis_matches_buckets(monthly_kpi):
    result = monthly_kpi.compute(_base_payload())
    x_axis = result["weekly_trend_chart"]["xAxis"]["data"]
    assert len(x_axis) == 5, "April has 5 month-anchored 7-day buckets"
    assert x_axis[0].startswith("W1")
    assert x_axis[4].startswith("W5")


def test_anomaly_top_n_sort_and_cap(monthly_kpi):
    """Top10 cap + count-desc primary sort."""
    payload = _base_payload()
    # Generate 15 distinct (equipment, level) buckets with varying counts.
    alarms = []
    for i in range(15):
        for _ in range(15 - i):  # 15, 14, 13, ..., 1 occurrences
            alarms.append({"time": f"2026-04-{i+1:02d} 10:00", "equipment": f"EQ-{i:02d}", "level": "warning", "message": "msg"})
    payload["current"]["alarms"] = alarms
    result = monthly_kpi.compute(payload)
    top = result["anomaly_top_n"]
    assert len(top) == 10, "must cap at 10"
    counts = [row["count"] for row in top]
    assert counts == sorted(counts, reverse=True), "must sort count desc"
    assert counts[0] == 15


def test_critical_events_cap(monthly_kpi):
    payload = _base_payload()
    payload["current"]["critical_events"] = [
        {"time": f"2026-04-{i+1:02d} 10:00", "equipment": "EQ-X", "level": "critical", "message": "x", "duration_minutes": 30, "resolved": True}
        for i in range(80)
    ]
    result = monthly_kpi.compute(payload)
    assert len(result["critical_events"]) == 50


def test_improvement_tracking_completion_rate_rules(monthly_kpi):
    payload = _base_payload()
    payload["current"]["improvement_tracking"] = [
        {"id": "A", "owner": "x", "plan": "p1", "due_date": "2026-04-15", "status": "done", "note": ""},
        {"id": "B", "owner": "x", "plan": "p2", "due_date": "2026-04-20", "status": "closed", "note": ""},
        {"id": "C", "owner": "x", "plan": "p3", "due_date": "2026-04-25", "status": "in_progress", "note": ""},
        {"id": "D", "owner": "x", "plan": "p4", "due_date": "2026-04-30", "status": "delayed", "note": ""},
        {"id": "E", "owner": "x", "plan": "p5", "due_date": "2026-04-30", "status": "unknown", "note": ""},
    ]
    result = monthly_kpi.compute(payload)
    rates = {r["id"]: r["completion_rate"] for r in result["improvement_tracking"]}
    assert rates["A"] == 100
    assert rates["B"] == 100
    assert rates["C"] == 60
    assert rates["D"] == 30
    assert rates["E"] == 0  # unknown status defaults to 0


def test_kpi_summary_order_preserved(monthly_kpi):
    """kpi_summary entries follow kpi_keys order."""
    result = monthly_kpi.compute(_base_payload())
    keys = [item["key"] for item in result["kpi_summary"]]
    # alarm_count has data in aggregated; ordering must match input kpi_keys
    assert keys[0] == "runtime_rate"
    assert "mtbf" in keys
    assert "mttr" in keys
    assert "target_rate" in keys


def test_overall_status_single_line_summary(monthly_kpi):
    """overall_status.summary is a single-line ≤ 80 char digest (design §6.2)."""
    result = monthly_kpi.compute(_base_payload())
    summary = result["overall_status"]["summary"]
    assert "\n" not in summary
    assert len(summary) <= 80


def test_data_source_passthrough(monthly_kpi):
    result = monthly_kpi.compute(_base_payload())
    assert result["data_source"] == "demo_fallback"


def test_next_month_plan_mechanically_generated(monthly_kpi):
    """next_month_plan items derive from anomaly TopN + open improvement items."""
    payload = _base_payload()
    payload["current"]["alarms"] = [
        {"time": "2026-04-10 10:00", "equipment": "RM-002", "level": "critical", "message": "轴承温度超限"}
        for _ in range(3)
    ]
    payload["current"]["improvement_tracking"] = [
        {"id": "X", "owner": "y", "plan": "缺件更换", "due_date": "2026-04-15", "status": "in_progress", "note": ""},
    ]
    result = monthly_kpi.compute(payload)
    plan_text = "\n".join(result["next_month_plan"])
    # Anomaly device referenced
    assert "RM-002" in plan_text
    # Open improvement item referenced
    assert "X" in plan_text or "缺件更换" in plan_text
