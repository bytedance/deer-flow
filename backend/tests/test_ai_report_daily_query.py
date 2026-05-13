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


# --- New KPI and --type/--scope/--scope-filter tests ---


def test_new_kpi_units_registered(query_daily):
    """All 12 KPI keys must be in KPI_UNITS."""
    expected = {
        "runtime_rate", "downtime_count", "alarm_count", "output", "energy_consumption",
        "corrosion_rate", "thickness_loss", "vibration_level", "bearing_temp",
        "flow_rate", "outlet_pressure", "valve_temp",
    }
    assert expected.issubset(set(query_daily.KPI_UNITS.keys()))


def test_new_kpi_demo_values(query_daily):
    """New KPIs should produce valid demo data."""
    new_kpis = ["corrosion_rate", "thickness_loss", "vibration_level", "bearing_temp", "flow_rate", "outlet_pressure", "valve_temp"]
    payload = query_daily.fetch_day("2026-05-13", ["E001"], new_kpis)
    for key in new_kpis:
        assert key in payload["kpis"]
        assert key in payload["kpi_units"]
        assert isinstance(payload["kpis"][key], (int, float))


def test_scope_mode_returns_per_equipment(query_daily, monkeypatch, capsys, tmp_path):
    """--scope area mode should produce per_equipment for >20 devices."""
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "query_daily.py",
            "--date", "2026-05-13",
            "--type", "static_equipment",
            "--scope", "area",
            "--scope-filter", "A区",
            "--kpis", "runtime_rate,corrosion_rate",
            "--compare", "previous_day",
        ],
    )
    assert query_daily.main() == 0
    capsys.readouterr()
    loaded = json.loads((tmp_path / "daily_data.json").read_text(encoding="utf-8"))
    assert loaded["equipment_type"] == "static_equipment"
    assert loaded["equipment_count"] == 250
    assert "per_equipment" in loaded["current"]
    assert len(loaded["current"]["per_equipment"]) == 250


def test_scope_all_returns_all_devices(query_daily, monkeypatch, capsys, tmp_path):
    """--scope all --type pump should return 1000 pump devices."""
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "query_daily.py",
            "--date", "2026-05-13",
            "--type", "pump",
            "--scope", "all",
            "--kpis", "runtime_rate,flow_rate",
            "--compare", "none",
        ],
    )
    assert query_daily.main() == 0
    capsys.readouterr()
    loaded = json.loads((tmp_path / "daily_data.json").read_text(encoding="utf-8"))
    assert len(loaded["equipment_ids"]) == 1000
    assert loaded["equipment_count"] == 1000


def test_backward_compat_no_type_no_scope(query_daily, monkeypatch, capsys, tmp_path):
    """Without --type/--scope, behavior must match original."""
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "query_daily.py",
            "--date", "2026-05-13",
            "--equipment", "E001,E002",
            "--kpis", "runtime_rate,alarm_count",
            "--compare", "previous_day",
        ],
    )
    assert query_daily.main() == 0
    capsys.readouterr()
    loaded = json.loads((tmp_path / "daily_data.json").read_text(encoding="utf-8"))
    assert loaded["equipment_ids"] == ["E001", "E002"]
    assert "per_equipment" not in loaded["current"]
    assert "equipment_count" not in loaded


def test_type_specific_alarms(query_daily):
    """Alarm messages should differ by equipment type."""
    payload_static = query_daily.fetch_day("2026-05-13", ["SE-001"], ["runtime_rate"], eq_type="static_equipment")
    payload_pump = query_daily.fetch_day("2026-05-13", ["PP-001"], ["runtime_rate"], eq_type="pump")
    static_messages = set(query_daily.TYPE_ALARM_MESSAGES["static_equipment"])
    pump_messages = set(query_daily.TYPE_ALARM_MESSAGES["pump"])
    assert static_messages != pump_messages
