"""Tests for skills/custom/data-analyst/scripts/query_weekly.py.

Mirrors test_ai_report_daily_query.py: loads the script by file path because
it lives in the runtime sandbox skills tree, not on the package import path.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "skills" / "custom" / "data-analyst" / "scripts" / "query_weekly.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("query_weekly", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def query_weekly(tmp_path, monkeypatch):
    monkeypatch.setenv("WEEKLY_REPORT_OUTPUT_DIR", str(tmp_path))
    # query_weekly delegates demo generation to query_daily, share the same
    # tmp dir so both scripts write to the harness-owned scratch space.
    monkeypatch.setenv("DAILY_REPORT_OUTPUT_DIR", str(tmp_path))
    monkeypatch.delenv("DATA_PLATFORM_URL", raising=False)
    monkeypatch.delenv("DATA_API_URL", raising=False)
    return _load_module()


def test_fetch_week_returns_seven_daily_entries(query_weekly):
    payload = query_weekly.fetch_week(
        "2026-05-11",
        ["RM-001", "RM-002"],
        ["runtime_rate", "downtime_count", "alarm_count"],
    )
    assert "daily" in payload
    assert "aggregated" in payload
    assert "alarms" in payload
    assert len(payload["daily"]) == 7
    for entry in payload["daily"]:
        assert "date" in entry
        assert "kpis" in entry
        assert "kpi_units" in entry
        assert "alarms" in entry
        for kpi in ("runtime_rate", "downtime_count", "alarm_count"):
            assert kpi in entry["kpis"]
            assert kpi in entry["kpi_units"]


def test_fetch_week_dates_are_consecutive_seven_days(query_weekly):
    payload = query_weekly.fetch_week(
        "2026-05-11",
        ["RM-001"],
        ["runtime_rate"],
    )
    expected = [(datetime(2026, 5, 11) + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]
    assert [d["date"] for d in payload["daily"]] == expected


def test_aggregated_contains_mean_max_min_std(query_weekly):
    payload = query_weekly.fetch_week(
        "2026-05-11",
        ["RM-001"],
        ["runtime_rate", "downtime_count"],
    )
    agg = payload["aggregated"]
    for bucket in ("kpis_mean", "kpis_max", "kpis_min", "kpis_std"):
        assert bucket in agg
        assert "runtime_rate" in agg[bucket]
        assert "downtime_count" in agg[bucket]
    assert agg["kpis_max"]["runtime_rate"] >= agg["kpis_mean"]["runtime_rate"] >= agg["kpis_min"]["runtime_rate"]


def test_build_result_previous_week(query_weekly):
    result = query_weekly.build_result(
        week_start="2026-05-11",
        equipment_ids=["RM-001"],
        kpi_keys=["runtime_rate"],
        compare="previous_week",
    )
    assert result["report_period"]["week_start"] == "2026-05-11"
    assert result["report_period"]["week_end"] == "2026-05-17"
    assert result["report_period"]["day_count"] == 7
    assert result["compare_type"] == "previous_week"
    assert result["compare_period"] == {"start": "2026-05-04", "end": "2026-05-10"}
    assert result["compare"] is not None
    assert len(result["compare"]["daily"]) == 7


def test_build_result_previous_year_missing(query_weekly):
    """Demo policy: previous_year that crosses 2025-01-01 horizon returns null compare."""
    result = query_weekly.build_result(
        week_start="2025-01-06",  # prev year start lands 2024-01-07, before horizon
        equipment_ids=["RM-001"],
        kpi_keys=["runtime_rate"],
        compare="previous_year",
    )
    assert result["compare_type"] == "previous_year"
    assert result["compare"] is None
    assert result["compare_period"] is None
    assert result["compare_warning"] is not None


def test_build_result_previous_year_available(query_weekly):
    """previous_year inside data horizon returns a populated compare block."""
    result = query_weekly.build_result(
        week_start="2026-05-11",
        equipment_ids=["RM-001"],
        kpi_keys=["runtime_rate"],
        compare="previous_year",
    )
    assert result["compare_type"] == "previous_year"
    assert result["compare"] is not None
    assert result["compare_period"] == {"start": "2025-05-11", "end": "2025-05-17"}


def test_build_result_no_compare(query_weekly):
    result = query_weekly.build_result(
        week_start="2026-05-11",
        equipment_ids=["RM-001"],
        kpi_keys=["runtime_rate"],
        compare="none",
    )
    assert result["compare_type"] == "none"
    assert result["compare"] is None
    assert result["compare_period"] is None
    assert result["compare_warning"] is None


def test_week_start_warning_when_non_monday(query_weekly):
    # 2026-05-13 is a Wednesday
    result = query_weekly.build_result(
        week_start="2026-05-13",
        equipment_ids=["RM-001"],
        kpi_keys=["runtime_rate"],
        compare="none",
    )
    assert result["week_start_warning"] is not None


def test_week_start_warning_absent_when_monday(query_weekly):
    # 2026-05-11 is a Monday
    result = query_weekly.build_result(
        week_start="2026-05-11",
        equipment_ids=["RM-001"],
        kpi_keys=["runtime_rate"],
        compare="none",
    )
    assert result["week_start_warning"] is None


def test_demo_data_is_deterministic(query_weekly):
    """Same inputs must yield same outputs so reports are reproducible."""
    first = query_weekly.fetch_week("2026-05-11", ["RM-001"], ["runtime_rate"])
    second = query_weekly.fetch_week("2026-05-11", ["RM-001"], ["runtime_rate"])
    assert first == second


def test_aggregate_mode_skips_per_day_detail(query_weekly):
    result = query_weekly.build_result(
        week_start="2026-05-11",
        equipment_ids=["RM-001", "RM-002"],
        kpi_keys=["runtime_rate"],
        compare="none",
        aggregate=True,
    )
    assert result["aggregate_mode"] == "aggregated"
    assert result["current"]["daily"] == []
    assert "aggregated" in result["current"]


def test_write_payload_creates_json(query_weekly, tmp_path):
    result = query_weekly.build_result(
        week_start="2026-05-11",
        equipment_ids=["RM-001"],
        kpi_keys=["runtime_rate"],
        compare="previous_week",
    )
    out_path = query_weekly.write_payload(result)
    assert out_path.exists()
    assert out_path.parent == tmp_path
    loaded = json.loads(out_path.read_text(encoding="utf-8"))
    assert loaded["report_period"]["week_start"] == "2026-05-11"


def test_data_source_marker_present(query_weekly):
    """Demo fallback must be self-identifying so SOUL can warn the user."""
    result = query_weekly.build_result(
        week_start="2026-05-11",
        equipment_ids=["RM-001"],
        kpi_keys=["runtime_rate"],
        compare="none",
    )
    assert result["data_source"] == "demo_fallback"


def test_main_rejects_bad_week_start(query_weekly, capsys, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["query_weekly.py", "--week-start", "not-a-date", "--equipment", "RM-001"])
    rc = query_weekly.main()
    captured = capsys.readouterr()
    assert rc == 0  # follows skill convention: always exit 0, signal via JSON
    out = json.loads(captured.out)
    assert "error" in out
    assert "invalid --week-start" in out["error"]


def test_main_rejects_bad_equipment_id(query_weekly, capsys, monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        ["query_weekly.py", "--week-start", "2026-05-11", "--equipment", "RM 001"],
    )
    rc = query_weekly.main()
    captured = capsys.readouterr()
    assert rc == 0
    out = json.loads(captured.out)
    assert "error" in out
    assert "equipment id" in out["error"]


def test_main_rejects_bad_kpi_key(query_weekly, capsys, monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        ["query_weekly.py", "--week-start", "2026-05-11", "--equipment", "RM-001", "--kpis", "Bad-KPI"],
    )
    rc = query_weekly.main()
    captured = capsys.readouterr()
    assert rc == 0
    out = json.loads(captured.out)
    assert "error" in out
    assert "KPI" in out["error"]


def test_main_writes_payload(query_weekly, tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "query_weekly.py",
            "--week-start",
            "2026-05-11",
            "--equipment",
            "RM-001,RM-002",
            "--kpis",
            "runtime_rate,downtime_count",
            "--compare",
            "previous_week",
        ],
    )
    rc = query_weekly.main()
    captured = capsys.readouterr()
    assert rc == 0
    out = json.loads(captured.out)
    assert out["week_start"] == "2026-05-11"
    assert out["week_end"] == "2026-05-17"
    written = tmp_path / "weekly_data.json"
    assert written.exists()
    payload = json.loads(written.read_text(encoding="utf-8"))
    assert payload["equipment_ids"] == ["RM-001", "RM-002"]
    assert payload["kpi_keys"] == ["runtime_rate", "downtime_count"]
