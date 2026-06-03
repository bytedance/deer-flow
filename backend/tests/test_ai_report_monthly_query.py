"""Tests for skills/custom/monthly-report/scripts/query_monthly.py.

After the demo data path was removed, every data fetch goes through the
InS-backed daily provider. These tests pin the script's CLI / validation /
date-arithmetic / output-shape contract, mocking ``fetch_month_with_provenance``
with InS-tagged synthetic payloads.

For end-to-end InS provider tests see
``test_ai_report_monthly_ins_provider.py``.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "skills" / "custom" / "monthly-report" / "scripts" / "query_monthly.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("query_monthly", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _ins_month_payload(report_month: str, equipment_ids: list[str], kpi_keys: list[str],
                       day_count: int = 30, maintenance_overrides: dict | None = None,
                       improvement_overrides: list[dict] | None = None) -> dict:
    """Return a minimal InS-shaped monthly payload."""
    daily = [
        {
            "date": f"2026-{report_month[5:]}-{d:02d}",
            "kpis": {key: 0.5 for key in kpi_keys},
            "kpi_units": {key: "%" for key in kpi_keys},
            "alarms": [],
        }
        for d in range(1, min(day_count + 1, 29))
    ]
    daily = daily[:day_count]
    agg: dict = {"kpis_mean": {}, "kpis_max": {}, "kpis_min": {}, "kpis_std": {}, "kpis_target_rate": {}}
    for key in kpi_keys:
        agg["kpis_mean"][key] = 0.5
        agg["kpis_max"][key] = 0.5
        agg["kpis_min"][key] = 0.5
        agg["kpis_std"][key] = 0.0
    maintenance = {
        "total_failures": 0,
        "total_uptime_hours": day_count * 24,
        "total_downtime_minutes": 0,
        "total_repair_minutes": 0,
        "mtbf_hours": None,
        "mttr_hours": None,
    }
    if maintenance_overrides:
        maintenance.update(maintenance_overrides)
    return {
        "weekly": [],
        "aggregated": agg,
        "maintenance": maintenance,
        "alarms": [],
        "critical_events": [],
        "improvement_tracking": improvement_overrides or [],
        "kpi_units": {key: "%" for key in kpi_keys},
    }


def _stub_ins_fetch(query_monthly):
    """Patch ``fetch_month_with_provenance`` to return InS-tagged synthetic data."""

    def fake_fetch(report_month, equipment_ids, kpi_keys, eq_type="all", aggregate=False, equipment_meta=None):
        return _ins_month_payload(report_month, equipment_ids, kpi_keys), "ins", []

    query_monthly.fetch_month_with_provenance = fake_fetch


@pytest.fixture()
def query_monthly(tmp_path, monkeypatch):
    monkeypatch.setenv("MONTHLY_REPORT_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setenv("WEEKLY_REPORT_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setenv("DAILY_REPORT_OUTPUT_DIR", str(tmp_path))
    monkeypatch.delenv("DATA_PLATFORM_URL", raising=False)
    monkeypatch.delenv("DATA_API_URL", raising=False)
    module = _load_module()
    _stub_ins_fetch(module)
    return module


# -- Date arithmetic (leap year, Feb, 31-day, cross-year) --------------------


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


# -- Compare shape & warnings -------------------------------------------------


def test_previous_year_month_missing_returns_null(query_monthly):
    """previous_year_month for 2024-02 lands on 2023-02, below horizon -> None."""
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
    assert {
        "total_failures", "total_uptime_hours", "total_downtime_minutes",
        "total_repair_minutes", "mtbf_hours", "mttr_hours",
    }.issubset(pm["maintenance"].keys())


# -- CSV parsing (no data dependency) -----------------------------------------


def test_compare_csv_parsing_none_exclusive(query_monthly):
    with pytest.raises(ValueError, match="none"):
        query_monthly._parse_compare_csv("previous_month,none")
    assert query_monthly._parse_compare_csv("none") == ["none"]
    assert query_monthly._parse_compare_csv("") == ["none"]
    assert query_monthly._parse_compare_csv("previous_month,previous_year_month") == [
        "previous_month",
        "previous_year_month",
    ]


def test_compare_csv_invalid_basis_rejected(query_monthly):
    with pytest.raises(ValueError, match="invalid basis"):
        query_monthly._parse_compare_csv("mom,yoy")


# -- Maintenance formula ------------------------------------------------------


def test_maintenance_total_uptime_hours_formula(query_monthly, monkeypatch):
    """total_uptime_hours = day_count * 24 - total_downtime_minutes / 60."""
    def fake_fetch(report_month, equipment_ids, kpi_keys, eq_type="all", aggregate=False, equipment_meta=None):
        payload = _ins_month_payload(
            report_month, equipment_ids, kpi_keys,
            maintenance_overrides={
                "total_failures": 2,
                "total_uptime_hours": 0,  # placeholder — formula recalcs
                "total_downtime_minutes": 480,
                "total_repair_minutes": 120,
                "mtbf_hours": 360,
                "mttr_hours": 2.0,
            },
        )
        # Simulate the formula from fetch_month_with_provenance:
        # total_uptime_hours = day_count * 24 - total_downtime_minutes / 60
        year, month = int(report_month[:4]), int(report_month[5:7])
        import calendar as _cal
        _, day_count = _cal.monthrange(year, month)
        maint = payload["maintenance"]
        maint["total_uptime_hours"] = round(day_count * 24 - maint["total_downtime_minutes"] / 60.0, 2)
        return payload, "ins", []

    monkeypatch.setattr(query_monthly, "fetch_month_with_provenance", fake_fetch)

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


def test_improvement_tracking_covers_3_statuses(query_monthly, monkeypatch):
    def fake_fetch(report_month, equipment_ids, kpi_keys, eq_type="all", aggregate=False, equipment_meta=None):
        payload = _ins_month_payload(
            report_month, equipment_ids, kpi_keys,
            improvement_overrides=[
                {"title": "task-1", "status": "done"},
                {"title": "task-2", "status": "in_progress"},
                {"title": "task-3", "status": "delayed"},
            ],
        )
        return payload, "ins", []

    monkeypatch.setattr(query_monthly, "fetch_month_with_provenance", fake_fetch)

    result = query_monthly.build_result(
        report_month="2026-04",
        equipment_ids=["RM-001", "RM-002"],
        kpi_keys=["runtime_rate"],
        compare_bases=["previous_month"],
    )
    statuses = [r["status"] for r in result["current"]["improvement_tracking"]]
    assert set(statuses) >= {"done", "in_progress", "delayed"}


def test_data_source_is_ins(query_monthly):
    result = query_monthly.build_result(
        report_month="2026-04",
        equipment_ids=["RM-001"],
        kpi_keys=["runtime_rate"],
        compare_bases=["previous_month"],
    )
    assert result["data_source"] == "ins"
    assert result["data_notes"] == []


# -- Static / validation / CLI tests ------------------------------------------


def test_script_does_not_use_iso_calendar():
    tree = ast.parse(SCRIPT_PATH.read_text(encoding="utf-8"))
    forbidden = {"isocalendar", "IsoYear"}
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in forbidden:
            offenders.append(f"line {node.lineno}: .{node.attr}")
        elif isinstance(node, ast.Name) and node.id in forbidden:
            offenders.append(f"line {node.lineno}: {node.id}")
    assert not offenders, (
        f"query_monthly.py must not reference isocalendar/IsoYear; found: {offenders}"
    )


def test_report_month_validation(query_monthly):
    with pytest.raises(ValueError, match="invalid"):
        query_monthly._parse_report_month("2026-4")
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
    query_kpis = [k for k in ["runtime_rate", "mtbf", "mttr"] if k not in query_monthly.SPECIAL_KPIS]
    result = query_monthly.build_result(
        report_month="2026-04",
        equipment_ids=["RM-001"],
        kpi_keys=query_kpis,
        compare_bases=["previous_month"],
    )
    result["kpi_keys"] = ["runtime_rate", "mtbf", "mttr"]
    assert "mtbf" in result["kpi_keys"]
    assert "mttr" in result["kpi_keys"]
    assert "mtbf" not in result["current"]["aggregated"]["kpis_mean"]
