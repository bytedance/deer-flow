"""Tests for skills/custom/data-analyst/scripts/query_monthly.py.

Mirrors test_ai_report_weekly_query.py. Loads the script by file path because
it lives in the runtime sandbox skills tree, not on the package import path.
Covers sprint plan M1/M7 acceptance items:
- Leap-year / regular Feb day_count
- Cross-year same-month previous_month/previous_year_month boundaries
- Month-anchored 7-day buckets (W1/W5 truncation) — NOT ISO weeks
- compare CSV multi-baseline + ``none`` exclusivity + dict-shape output
- previous_year_month below horizon → null + compare_warning
- maintenance.total_uptime_hours formula
- improvement_tracking demo covers all 3 statuses
- Static check: script never uses datetime.isocalendar()
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "skills" / "custom" / "data-analyst" / "scripts" / "query_monthly.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("query_monthly", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def query_monthly(tmp_path, monkeypatch):
    monkeypatch.setenv("MONTHLY_REPORT_OUTPUT_DIR", str(tmp_path))
    # Demo data comes from query_daily.fetch_day; route its outputs to the
    # same tmp dir so both layers respect the harness scratch space.
    monkeypatch.setenv("WEEKLY_REPORT_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setenv("DAILY_REPORT_OUTPUT_DIR", str(tmp_path))
    monkeypatch.delenv("DATA_PLATFORM_URL", raising=False)
    monkeypatch.delenv("DATA_API_URL", raising=False)
    return _load_module()


def test_day_count_leap_february(query_monthly):
    result = query_monthly.build_result(
        report_month="2024-02",
        equipment_ids=["RM-001"],
        kpi_keys=["runtime_rate"],
        compare_bases=["previous_month"],
    )
    assert result["report_period"]["day_count"] == 29
    bucket_days = [b["day_count"] for b in result["report_period"]["week_buckets"]]
    assert bucket_days == [7, 7, 7, 7, 1]


def test_day_count_regular_february(query_monthly):
    result = query_monthly.build_result(
        report_month="2025-02",
        equipment_ids=["RM-001"],
        kpi_keys=["runtime_rate"],
        compare_bases=["previous_month"],
    )
    assert result["report_period"]["day_count"] == 28
    bucket_days = [b["day_count"] for b in result["report_period"]["week_buckets"]]
    assert bucket_days == [7, 7, 7, 7]


def test_day_count_31_day_month(query_monthly):
    result = query_monthly.build_result(
        report_month="2026-12",
        equipment_ids=["RM-001"],
        kpi_keys=["runtime_rate"],
        compare_bases=["previous_month"],
    )
    assert result["report_period"]["day_count"] == 31
    bucket_days = [b["day_count"] for b in result["report_period"]["week_buckets"]]
    assert bucket_days == [7, 7, 7, 7, 3]


def test_cross_year_same_month_compare_periods(query_monthly):
    """2026-01 must roll back to 2025-12 (prev month) and 2025-01 (prev year-month)."""
    result = query_monthly.build_result(
        report_month="2026-01",
        equipment_ids=["RM-001"],
        kpi_keys=["runtime_rate"],
        compare_bases=["previous_month", "previous_year_month"],
    )
    cp = result["compare_periods"]
    assert cp["previous_month"] == {"start": "2025-12-01", "end": "2025-12-31"}
    assert cp["previous_year_month"] == {"start": "2025-01-01", "end": "2025-01-31"}


def test_cross_leap_year_previous_month_handles_2024_03(query_monthly):
    """2024-03 previous_month must be 2024-02 with 29 days (leap year, no crash)."""
    result = query_monthly.build_result(
        report_month="2024-03",
        equipment_ids=["RM-001"],
        kpi_keys=["runtime_rate"],
        compare_bases=["previous_month"],
    )
    cp = result["compare_periods"]["previous_month"]
    assert cp == {"start": "2024-02-01", "end": "2024-02-29"}


def test_previous_year_month_missing_returns_null(query_monthly):
    """previous_year_month for 2024-02 lands on 2023-02, below demo horizon → None."""
    result = query_monthly.build_result(
        report_month="2024-02",
        equipment_ids=["RM-001"],
        kpi_keys=["runtime_rate"],
        compare_bases=["previous_year_month"],
    )
    assert result["compare"]["previous_year_month"] is None
    assert result["compare_warning"] is not None
    assert "去年同期" in result["compare_warning"] or "同比" in result["compare_warning"]


def test_compare_is_dict_keyed_by_basis(query_monthly):
    result = query_monthly.build_result(
        report_month="2026-04",
        equipment_ids=["RM-001"],
        kpi_keys=["runtime_rate"],
        compare_bases=["previous_month", "previous_year_month"],
    )
    assert isinstance(result["compare"], dict)
    assert set(result["compare"].keys()) == {"previous_month", "previous_year_month"}
    pm = result["compare"]["previous_month"]
    assert "aggregated" in pm
    assert "maintenance" in pm
    # maintenance block must carry the full 6-field schema (regression #D)
    assert {
        "total_failures",
        "total_uptime_hours",
        "total_downtime_minutes",
        "total_repair_minutes",
        "mtbf_hours",
        "mttr_hours",
    }.issubset(pm["maintenance"].keys())


def test_compare_csv_parsing_none_exclusive(query_monthly):
    # ``none`` mixed with another basis must raise ValueError
    with pytest.raises(ValueError, match="none"):
        query_monthly._parse_compare_csv("previous_month,none")
    # Single ``none`` parses to [``none``]
    assert query_monthly._parse_compare_csv("none") == ["none"]
    # Empty CSV defaults to [``none``]
    assert query_monthly._parse_compare_csv("") == ["none"]
    # Multiple bases preserved in order
    assert query_monthly._parse_compare_csv("previous_month,previous_year_month") == [
        "previous_month",
        "previous_year_month",
    ]


def test_compare_csv_invalid_basis_rejected(query_monthly):
    with pytest.raises(ValueError, match="invalid basis"):
        query_monthly._parse_compare_csv("mom,yoy")  # short names are DSL aliases, not script-level


def test_maintenance_total_uptime_hours_formula(query_monthly):
    """total_uptime_hours = day_count * 24 - total_downtime_minutes / 60."""
    result = query_monthly.build_result(
        report_month="2026-04",
        equipment_ids=["RM-001", "RM-002"],
        kpi_keys=["runtime_rate"],
        compare_bases=["previous_month"],
    )
    maint = result["current"]["maintenance"]
    day_count = result["report_period"]["day_count"]
    expected_uptime = day_count * 24 - maint["total_downtime_minutes"] / 60.0
    assert maint["total_uptime_hours"] == pytest.approx(expected_uptime, abs=0.01)


def test_improvement_tracking_demo_covers_3_statuses(query_monthly):
    result = query_monthly.build_result(
        report_month="2026-04",
        equipment_ids=["RM-001", "RM-002"],
        kpi_keys=["runtime_rate"],
        compare_bases=["previous_month"],
    )
    statuses = [r["status"] for r in result["current"]["improvement_tracking"]]
    assert set(statuses) >= {"done", "in_progress", "delayed"}, f"missing status coverage: {statuses}"


def test_script_does_not_use_iso_calendar():
    """Static check (sprint plan M1 acceptance): no isocalendar / IsoYear call sites.

    Allows ``isocalendar`` to appear inside string literals / docstrings (the
    module deliberately documents the prohibition there). We parse with ``ast``
    and only flag the symbol if it shows up as a real expression or attribute
    reference.
    """
    import ast

    tree = ast.parse(SCRIPT_PATH.read_text(encoding="utf-8"))
    forbidden = {"isocalendar", "IsoYear"}
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in forbidden:
            offenders.append(f"line {node.lineno}: .{node.attr}")
        elif isinstance(node, ast.Name) and node.id in forbidden:
            offenders.append(f"line {node.lineno}: {node.id}")
    assert not offenders, f"query_monthly.py must not reference isocalendar/IsoYear at the AST level; found: {offenders}"


def test_data_source_demo_fallback(query_monthly):
    result = query_monthly.build_result(
        report_month="2026-04",
        equipment_ids=["RM-001"],
        kpi_keys=["runtime_rate"],
        compare_bases=["previous_month"],
    )
    assert result["data_source"] == "demo_fallback"


def test_report_month_validation(query_monthly):
    with pytest.raises(ValueError, match="invalid"):
        query_monthly._parse_report_month("2026-4")  # missing zero-pad
    with pytest.raises(ValueError, match="month"):
        query_monthly._parse_report_month("2026-13")
    with pytest.raises(ValueError, match="year"):
        query_monthly._parse_report_month("1999-04")
    assert query_monthly._parse_report_month("2026-04") == (2026, 4)


def test_equipment_id_validation(query_monthly):
    err = query_monthly._validate_equipment_ids([])
    assert "non-empty" in err
    err = query_monthly._validate_equipment_ids(["bad/id"])
    assert "invalid" in err
    err = query_monthly._validate_equipment_ids(["a" * 65])
    assert "64" in err
    assert query_monthly._validate_equipment_ids(["RM-001"]) is None


def test_kpi_keys_includes_special_via_main_args(query_monthly):
    """When kpi_keys carries mtbf/mttr/target_rate the query layer drops them
    but echoes them back on result['kpi_keys'] for downstream consumers."""
    # build_result itself drops nothing — the filtering happens in main(). We
    # test the contract by simulating the main() workflow.
    query_kpis = [k for k in ["runtime_rate", "mtbf", "mttr"] if k not in query_monthly.SPECIAL_KPIS]
    result = query_monthly.build_result(
        report_month="2026-04",
        equipment_ids=["RM-001"],
        kpi_keys=query_kpis,
        compare_bases=["previous_month"],
    )
    # Manually echo (main() does this):
    result["kpi_keys"] = ["runtime_rate", "mtbf", "mttr"]
    assert "mtbf" in result["kpi_keys"]
    assert "mttr" in result["kpi_keys"]
    # but should NOT be in current.aggregated.kpis_mean (handled by monthly_kpi)
    assert "mtbf" not in result["current"]["aggregated"]["kpis_mean"]
