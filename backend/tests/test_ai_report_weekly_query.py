"""Tests for skills/custom/weekly-report/scripts/query_weekly.py.

After the demo data path was removed, every data fetch goes through the
InS-backed daily provider. These tests pin the script's CLI / validation /
output contract, mocking ``fetch_week_with_provenance`` with InS-tagged
synthetic payloads.

For end-to-end InS provider tests see
``test_ai_report_weekly_ins_provider.py``.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "skills" / "custom" / "weekly-report" / "scripts" / "query_weekly.py"

DAY_COUNT = 7


def _load_module():
    spec = importlib.util.spec_from_file_location("query_weekly", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _ins_week_payload(week_start: str, equipment_ids: list[str], kpi_keys: list[str], *, aggregate: bool = False) -> dict:
    """Return a minimal InS-shaped weekly payload (7 daily entries + aggregation)."""
    start_dt = datetime.strptime(week_start, "%Y-%m-%d")
    daily: list[dict] = []
    for offset in range(DAY_COUNT):
        date_str = (start_dt + timedelta(days=offset)).strftime("%Y-%m-%d")
        daily.append({
            "date": date_str,
            "kpis": {key: 0.5 for key in kpi_keys},
            "kpi_units": {key: "%" for key in kpi_keys},
            "alarms": [],
        })
    agg: dict = {"kpis_mean": {}, "kpis_max": {}, "kpis_min": {}, "kpis_std": {}}
    for key in kpi_keys:
        agg["kpis_mean"][key] = 0.5
        agg["kpis_max"][key] = 0.5
        agg["kpis_min"][key] = 0.5
        agg["kpis_std"][key] = 0.0
    result: dict = {"aggregated": agg, "alarms": []}
    if aggregate:
        result["daily"] = []
        result["kpi_units"] = {key: "%" for key in kpi_keys}
    else:
        result["daily"] = daily
    return result


def _stub_ins_fetch(query_weekly):
    """Patch ``fetch_week_with_provenance`` to return InS-tagged synthetic data."""

    def fake_fetch(week_start, equipment_ids, kpi_keys, eq_type="all", aggregate=False, equipment_meta=None):
        return _ins_week_payload(week_start, equipment_ids, kpi_keys, aggregate=aggregate), "ins", []

    query_weekly.fetch_week_with_provenance = fake_fetch


@pytest.fixture()
def query_weekly(tmp_path, monkeypatch):
    monkeypatch.setenv("WEEKLY_REPORT_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setenv("DAILY_REPORT_OUTPUT_DIR", str(tmp_path))
    monkeypatch.delenv("DATA_PLATFORM_URL", raising=False)
    monkeypatch.delenv("DATA_API_URL", raising=False)
    module = _load_module()
    _stub_ins_fetch(module)
    return module


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
        for kpi in ("runtime_rate", "downtime_count", "alarm_count"):
            assert kpi in entry["kpis"]


def test_fetch_week_dates_are_consecutive_seven_days(query_weekly):
    payload = query_weekly.fetch_week("2026-05-11", ["RM-001"], ["runtime_rate"])
    expected = [(datetime(2026, 5, 11) + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]
    assert [d["date"] for d in payload["daily"]] == expected


def test_aggregated_contains_mean_max_min_std(query_weekly):
    payload = query_weekly.fetch_week("2026-05-11", ["RM-001"], ["runtime_rate", "downtime_count"])
    agg = payload["aggregated"]
    for bucket in ("kpis_mean", "kpis_max", "kpis_min", "kpis_std"):
        assert bucket in agg
        assert "runtime_rate" in agg[bucket]
        assert "downtime_count" in agg[bucket]


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
    assert result["data_source"] == "ins"


def test_build_result_previous_year_available(query_weekly):
    """previous_year within data horizon returns a populated compare block."""
    result = query_weekly.build_result(
        week_start="2026-05-11",
        equipment_ids=["RM-001"],
        kpi_keys=["runtime_rate"],
        compare="previous_year",
    )
    assert result["compare_type"] == "previous_year"
    assert result["compare"] is not None
    assert result["compare_period"] == {"start": "2025-05-11", "end": "2025-05-17"}
    assert result["data_source"] == "ins"


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
    assert result["data_source"] == "ins"
    assert result["data_notes"] == []


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
    assert loaded["data_source"] == "ins"


def test_data_source_is_ins(query_weekly):
    result = query_weekly.build_result(
        week_start="2026-05-11",
        equipment_ids=["RM-001"],
        kpi_keys=["runtime_rate"],
        compare="none",
    )
    assert result["data_source"] == "ins"
    assert result["data_notes"] == []


def test_main_rejects_bad_week_start(query_weekly, capsys, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["query_weekly.py", "--week-start", "not-a-date", "--equipment", "RM-001"])
    rc = query_weekly.main()
    captured = capsys.readouterr()
    assert rc == 0
    out = json.loads(captured.out)
    assert "error" in out
    assert "invalid --week-start" in out["error"]


def test_main_rejects_bad_equipment_id(query_weekly, capsys, monkeypatch):
    monkeypatch.setattr(
        sys, "argv", ["query_weekly.py", "--week-start", "2026-05-11", "--equipment", "RM 001"]
    )
    rc = query_weekly.main()
    captured = capsys.readouterr()
    assert rc == 0
    out = json.loads(captured.out)
    assert "error" in out
    assert "equipment id" in out["error"]


def test_main_rejects_bad_kpi_key(query_weekly, capsys, monkeypatch):
    monkeypatch.setattr(
        sys, "argv",
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
            "--week-start", "2026-05-11",
            "--equipment", "RM-001,RM-002",
            "--kpis", "runtime_rate,downtime_count",
            "--compare", "previous_week",
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
    assert payload["data_source"] == "ins"


def test_main_emits_error_json_when_fetch_raises(query_weekly, monkeypatch, capsys, tmp_path):
    """main() converts fetch exceptions into ``{"error": ...}`` on stdout."""

    def fake_fetch(*args, **kwargs):
        raise RuntimeError("ins unreachable")

    monkeypatch.setattr(query_weekly, "fetch_week_with_provenance", fake_fetch)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "query_weekly.py",
            "--week-start", "2026-05-11",
            "--equipment", "RM-001",
            "--kpis", "runtime_rate",
            "--compare", "none",
        ],
    )
    rc = query_weekly.main()
    out = capsys.readouterr().out.strip()
    assert rc == 0
    payload = json.loads(out)
    assert "error" in payload
    assert "RuntimeError" in payload["error"]
    assert "ins unreachable" in payload["error"]
    assert not (tmp_path / "weekly_data.json").exists()
