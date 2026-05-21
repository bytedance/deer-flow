"""Tests for skills/custom/data-analyst/scripts/list_equipment.py."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "skills" / "custom" / "data-analyst" / "scripts" / "list_equipment.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("list_equipment", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def list_equipment():
    return _load_module()


def test_query_all_returns_2200(list_equipment):
    result = list_equipment.query_equipment("all", "all", "", limit=10000)
    assert result["total_matched"] == 2200
    assert result["equipment_type"] == "all"
    assert result["type_display"] == "全部"


def test_query_static_equipment_returns_1000(list_equipment):
    result = list_equipment.query_equipment("static_equipment", "all", "", limit=10000)
    assert result["total_matched"] == 1000
    assert result["total_in_type"] == 1000
    assert result["equipment_type"] == "static_equipment"
    assert result["type_display"] == "静设备"


def test_query_area_filter(list_equipment):
    result = list_equipment.query_equipment("static_equipment", "area", "A区", limit=10000)
    assert result["total_matched"] == 250
    assert result["scope"] == "area"
    for eq in result["equipment"]:
        assert eq["area"] == "A区"


def test_query_specific_filter(list_equipment):
    result = list_equipment.query_equipment("static_equipment", "specific", "SE-001,SE-002", limit=10000)
    assert result["total_matched"] == 2
    ids = {e["id"] for e in result["equipment"]}
    assert ids == {"SE-001", "SE-002"}


def test_limit_truncation(list_equipment):
    result = list_equipment.query_equipment("static_equipment", "all", "", limit=50)
    assert result["total_matched"] == 1000
    assert len(result["equipment"]) == 50
    assert result["equipment_truncated"] is True


def test_no_truncation_when_under_limit(list_equipment):
    result = list_equipment.query_equipment("static_equipment", "specific", "SE-001", limit=50)
    assert result["equipment_truncated"] is False


def test_available_kpis_for_static_equipment(list_equipment):
    result = list_equipment.query_equipment("static_equipment", "all", "")
    kpi_keys = [k["key"] for k in result["available_kpis"]]
    assert "runtime_rate" in kpi_keys
    assert "corrosion_rate" in kpi_keys
    assert "thickness_loss" in kpi_keys
    assert "vibration_level" not in kpi_keys


def test_available_kpis_for_rotating_machinery(list_equipment):
    result = list_equipment.query_equipment("rotating_machinery", "all", "")
    kpi_keys = [k["key"] for k in result["available_kpis"]]
    assert "vibration_level" in kpi_keys
    assert "bearing_temp" in kpi_keys
    assert "corrosion_rate" not in kpi_keys


def test_available_kpis_for_pump(list_equipment):
    result = list_equipment.query_equipment("pump", "all", "")
    kpi_keys = [k["key"] for k in result["available_kpis"]]
    assert "vibration_velocity_rms" in kpi_keys
    assert "vibration_acceleration_peak" in kpi_keys
    assert "bearing_temp" in kpi_keys
    assert "kurtosis_index" in kpi_keys


def test_available_kpis_for_reciprocating(list_equipment):
    result = list_equipment.query_equipment("reciprocating_machinery", "all", "")
    kpi_keys = [k["key"] for k in result["available_kpis"]]
    assert "valve_temp" in kpi_keys
    assert "vibration_level" in kpi_keys


def test_default_kpis_first_three(list_equipment):
    result = list_equipment.query_equipment("static_equipment", "all", "")
    defaults = [k for k in result["available_kpis"] if k["default"]]
    non_defaults = [k for k in result["available_kpis"] if not k["default"]]
    assert len(defaults) == 3
    assert all(not k["default"] for k in non_defaults)


def test_areas_always_present(list_equipment):
    result = list_equipment.query_equipment("all", "all", "")
    assert result["areas"] == ["A区", "B区", "C区", "D区"]


def test_equipment_has_required_fields(list_equipment):
    result = list_equipment.query_equipment("static_equipment", "all", "", limit=5)
    for eq in result["equipment"]:
        assert "id" in eq
        assert "name" in eq
        assert "area" in eq
        assert "sub_type" in eq


def test_id_prefix_matches_type(list_equipment):
    for eq_type, prefix in [("static_equipment", "SE"), ("rotating_machinery", "RM"), ("pump", "PP"), ("reciprocating_machinery", "RC")]:
        result = list_equipment.query_equipment(eq_type, "all", "", limit=5)
        for eq in result["equipment"]:
            assert eq["id"].startswith(f"{prefix}-")


def test_main_rejects_invalid_type(list_equipment, monkeypatch, capsys):
    import sys
    monkeypatch.setattr(sys, "argv", ["list_equipment.py", "--type", "bad_type"])
    assert list_equipment.main() == 0
    output = json.loads(capsys.readouterr().out)
    assert "error" in output
    assert "bad_type" in output["error"]


def test_main_rejects_invalid_scope(list_equipment, monkeypatch, capsys):
    import sys
    monkeypatch.setattr(sys, "argv", ["list_equipment.py", "--scope", "invalid"])
    assert list_equipment.main() == 0
    output = json.loads(capsys.readouterr().out)
    assert "error" in output


def test_main_rejects_injection_in_filter(list_equipment, monkeypatch, capsys):
    import sys
    monkeypatch.setattr(sys, "argv", ["list_equipment.py", "--scope", "specific", "--filter", "$(touch pwned)"])
    assert list_equipment.main() == 0
    output = json.loads(capsys.readouterr().out)
    assert "error" in output
    assert "invalid equipment id" in output["error"]


def test_main_success(list_equipment, monkeypatch, capsys):
    import sys
    monkeypatch.setattr(sys, "argv", ["list_equipment.py", "--type", "pump", "--scope", "all"])
    assert list_equipment.main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output["total_matched"] == 1000
    assert output["equipment_type"] == "pump"


# --- area_counts tests ---


def test_area_counts_present(list_equipment):
    result = list_equipment.query_equipment("static_equipment", "all", "", limit=10000)
    assert "area_counts" in result
    assert isinstance(result["area_counts"], dict)


def test_area_counts_static_equipment(list_equipment):
    result = list_equipment.query_equipment("static_equipment", "all", "", limit=10000)
    counts = result["area_counts"]
    assert counts == {"A区": 250, "B区": 250, "C区": 250, "D区": 250}
    assert sum(counts.values()) == result["total_matched"]


def test_area_counts_rotating_machinery(list_equipment):
    result = list_equipment.query_equipment("rotating_machinery", "all", "", limit=10000)
    counts = result["area_counts"]
    assert sum(counts.values()) == 100
    assert len(counts) == 4


def test_area_counts_filtered_by_area(list_equipment):
    result = list_equipment.query_equipment("static_equipment", "area", "A区", limit=10000)
    counts = result["area_counts"]
    assert counts == {"A区": 250}


def test_area_counts_filtered_specific(list_equipment):
    result = list_equipment.query_equipment("static_equipment", "specific", "SE-001,SE-002", limit=10000)
    counts = result["area_counts"]
    assert sum(counts.values()) == 2


def test_area_counts_all_types(list_equipment):
    result = list_equipment.query_equipment("all", "all", "", limit=10000)
    counts = result["area_counts"]
    assert sum(counts.values()) == 2200
