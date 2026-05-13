"""Tests for skills/custom/data-analyst/scripts/query_daily.py.

The script is loaded by file path because it lives in the runtime sandbox skills
tree, not on the package import path.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "skills" / "custom" / "data-analyst" / "scripts" / "query_daily.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("query_daily", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def query_daily(tmp_path, monkeypatch):
    monkeypatch.setenv("DAILY_REPORT_OUTPUT_DIR", str(tmp_path))
    monkeypatch.delenv("DATA_PLATFORM_URL", raising=False)
    monkeypatch.delenv("DATA_API_URL", raising=False)
    return _load_module()


def test_demo_payload_contract(query_daily):
    """Demo fallback must satisfy design doc §6.1 shape."""
    payload = query_daily.fetch_day(
        "2026-05-13",
        ["E001", "E002"],
        ["runtime_rate", "downtime_count", "alarm_count"],
    )
    assert "kpis" in payload
    assert "kpi_units" in payload
    assert "hourly_runtime_rate" in payload
    assert "alarms" in payload
    assert len(payload["hourly_runtime_rate"]) == 24
    for kpi in ["runtime_rate", "downtime_count", "alarm_count"]:
        assert kpi in payload["kpis"]
        assert kpi in payload["kpi_units"]


def test_build_result_previous_day(query_daily):
    result = query_daily.build_result(
        date_str="2026-05-13",
        equipment_ids=["E001"],
        kpi_keys=["runtime_rate"],
        compare="previous_day",
    )
    assert result["report_date"] == "2026-05-13"
    assert result["compare_type"] == "previous_day"
    assert result["compare"] is not None
    assert result["current"]["kpis"]["runtime_rate"] is not None


def test_build_result_previous_week(query_daily):
    result = query_daily.build_result(
        date_str="2026-05-13",
        equipment_ids=["E001"],
        kpi_keys=["runtime_rate"],
        compare="previous_week",
    )
    expected = (datetime.strptime("2026-05-13", "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")
    assert result["compare_type"] == "previous_week"
    assert result["compare_date"] == expected


def test_build_result_no_compare(query_daily):
    result = query_daily.build_result(
        date_str="2026-05-13",
        equipment_ids=["E001"],
        kpi_keys=["runtime_rate"],
        compare="none",
    )
    assert result["compare"] is None
    assert result["compare_type"] == "none"


def test_writes_to_output_dir(query_daily, tmp_path):
    result = query_daily.build_result(
        date_str="2026-05-13",
        equipment_ids=["E001"],
        kpi_keys=["runtime_rate"],
        compare="previous_day",
    )
    out_path = query_daily.write_payload(result)
    assert out_path.parent == tmp_path
    assert out_path.name == "daily_data.json"
    loaded = json.loads(out_path.read_text(encoding="utf-8"))
    assert loaded["report_date"] == "2026-05-13"


def test_main_accepts_form_csv_payload(query_daily, monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "query_daily.py",
            "--date",
            "2026-05-13",
            "--equipment",
            "E001,E002",
            "--kpis",
            "runtime_rate,downtime_count",
            "--compare",
            "previous_day",
        ],
    )
    assert query_daily.main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output["output"] == str(tmp_path / "daily_data.json")
    loaded = json.loads((tmp_path / "daily_data.json").read_text(encoding="utf-8"))
    assert loaded["equipment_ids"] == ["E001", "E002"]
    assert loaded["kpi_keys"] == ["runtime_rate", "downtime_count"]


def test_main_rejects_empty_equipment(query_daily, monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        ["query_daily.py", "--date", "2026-05-13", "--equipment", "", "--kpis", "runtime_rate"],
    )
    assert query_daily.main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output["error"] == "--equipment must be a non-empty CSV"


def test_main_rejects_invalid_equipment_id(query_daily, monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        ["query_daily.py", "--date", "2026-05-13", "--equipment", "E001,$(touch pwned)", "--kpis", "runtime_rate"],
    )
    assert query_daily.main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output["error"] == "--equipment contains invalid equipment id(s): $(touch pwned)"


def test_main_rejects_invalid_kpi_key_format(query_daily, monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        ["query_daily.py", "--date", "2026-05-13", "--equipment", "E001", "--kpis", "runtime_rate,$bad"],
    )
    assert query_daily.main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output["error"] == "--kpis contains invalid KPI key(s): $bad"


def test_main_rejects_unsupported_kpi_key(query_daily, monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        ["query_daily.py", "--date", "2026-05-13", "--equipment", "E001", "--kpis", "runtime_rate,oee"],
    )
    assert query_daily.main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output["error"] == "--kpis contains unsupported KPI key(s): oee"


def test_main_deduplicates_equipment_and_kpis(query_daily, monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "query_daily.py",
            "--date",
            "2026-05-13",
            "--equipment",
            "E001,E002,E001",
            "--kpis",
            "runtime_rate,downtime_count,runtime_rate",
        ],
    )
    assert query_daily.main() == 0
    json.loads(capsys.readouterr().out)
    loaded = json.loads((tmp_path / "daily_data.json").read_text(encoding="utf-8"))
    assert loaded["equipment_ids"] == ["E001", "E002"]
    assert loaded["kpi_keys"] == ["runtime_rate", "downtime_count"]
