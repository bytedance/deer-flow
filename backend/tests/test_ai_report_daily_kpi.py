"""Tests for skills/custom/data-analyst/scripts/daily_kpi.py."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "skills" / "custom" / "data-analyst" / "scripts" / "daily_kpi.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("daily_kpi", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def daily_kpi(tmp_path, monkeypatch):
    monkeypatch.setenv("DAILY_REPORT_OUTPUT_DIR", str(tmp_path))
    return _load_module()


def _sample_input(compare_block=None, alarms=None):
    current = {
        "kpis": {"runtime_rate": 0.92, "downtime_count": 2, "alarm_count": 3},
        "kpi_units": {"runtime_rate": "%", "downtime_count": "次", "alarm_count": "条"},
        "hourly_runtime_rate": [0.9] * 24,
        "alarms": alarms if alarms is not None else [
            {"time": "2026-05-13 03:00", "equipment": "E001", "level": "high", "message": "高温告警"},
        ],
    }
    return {
        "report_date": "2026-05-13",
        "equipment_ids": ["E001"],
        "kpi_keys": ["runtime_rate", "downtime_count", "alarm_count"],
        "compare_type": "previous_day" if compare_block else "none",
        "compare_date": "2026-05-12" if compare_block else None,
        "current": current,
        "compare": compare_block,
    }


def test_build_kpi_summary_with_previous_day(daily_kpi, tmp_path):
    compare = {
        "kpis": {"runtime_rate": 0.85, "downtime_count": 5, "alarm_count": 6},
        "kpi_units": {"runtime_rate": "%", "downtime_count": "次", "alarm_count": "条"},
        "hourly_runtime_rate": [0.85] * 24,
        "alarms": [],
    }
    payload = _sample_input(compare_block=compare)
    result = daily_kpi.compute(payload)
    assert "kpi_summary" in result
    assert "trend_chart" in result
    assert "alarm_table" in result
    assert "overall_status" in result

    rates = {item["key"]: item for item in result["kpi_summary"]}
    assert rates["runtime_rate"]["current"] == pytest.approx(0.92)
    assert rates["runtime_rate"]["previous"] == pytest.approx(0.85)
    assert rates["runtime_rate"]["delta"] == pytest.approx(0.07)
    assert rates["downtime_count"]["delta"] == -3


def test_build_kpi_summary_no_compare(daily_kpi):
    payload = _sample_input(compare_block=None)
    result = daily_kpi.compute(payload)
    for item in result["kpi_summary"]:
        assert item["previous"] is None
        assert item["delta"] is None


def test_empty_alarms(daily_kpi):
    payload = _sample_input(compare_block=None, alarms=[])
    result = daily_kpi.compute(payload)
    assert result["alarm_table"] == []


def test_trend_chart_has_24_points(daily_kpi):
    payload = _sample_input(compare_block=None)
    result = daily_kpi.compute(payload)
    option = result["trend_chart"]
    assert "xAxis" in option and len(option["xAxis"]["data"]) == 24
    series = option["series"]
    assert len(series) >= 1
    assert len(series[0]["data"]) == 24


def test_write_output(daily_kpi, tmp_path):
    payload = _sample_input(compare_block=None)
    result = daily_kpi.compute(payload)
    out_path = daily_kpi.write_output(result)
    assert out_path.parent == tmp_path
    assert out_path.name == "daily_kpi.json"
    loaded = json.loads(out_path.read_text(encoding="utf-8"))
    assert loaded["report_date"] == "2026-05-13"


# --- Aggregation mode tests ---


def _aggregated_input(num_devices=50, kpi_keys=None):
    """Build a payload with per_equipment data for aggregation testing."""
    if kpi_keys is None:
        kpi_keys = ["runtime_rate", "corrosion_rate"]
    areas = ["A区", "B区", "C区", "D区"]
    sub_types = ["换热器", "冷却器", "塔器", "容器", "反应器"]
    per_equipment = {}
    for i in range(num_devices):
        eq_id = f"SE-{i+1:03d}"
        kpis = {}
        for key in kpi_keys:
            if key == "runtime_rate":
                kpis[key] = 0.85 + (i % 15) * 0.01
            elif key == "corrosion_rate":
                kpis[key] = 0.05 + (i % 10) * 0.05
            else:
                kpis[key] = 50.0 + i
        sub_type = sub_types[i % len(sub_types)]
        per_equipment[eq_id] = {
            "kpis": kpis,
            "hourly_runtime_rate": [0.9] * 24,
            "name": f"{sub_type}-{i+1:03d}",
            "area": areas[i % len(areas)],
        }
    avg_kpis = {}
    for key in kpi_keys:
        vals = [per_equipment[eid]["kpis"][key] for eid in per_equipment]
        avg_kpis[key] = round(sum(vals) / len(vals), 4)
    current = {
        "kpis": avg_kpis,
        "kpi_units": {k: "%" if k == "runtime_rate" else "mm/a" for k in kpi_keys},
        "hourly_runtime_rate": [0.9] * 24,
        "alarms": [],
        "per_equipment": per_equipment,
    }
    return {
        "report_date": "2026-05-13",
        "equipment_ids": list(per_equipment.keys()),
        "equipment_type": "static_equipment",
        "equipment_count": num_devices,
        "kpi_keys": kpi_keys,
        "compare_type": "none",
        "compare_date": None,
        "current": current,
        "compare": None,
    }


def test_aggregation_mode_grouped(daily_kpi):
    payload = _aggregated_input(num_devices=50)
    result = daily_kpi.compute(payload)
    assert result["aggregation_mode"] == "grouped"
    assert result["equipment_type"] == "static_equipment"
    assert result["equipment_count"] == 50


def test_aggregation_mode_detail_for_small(daily_kpi):
    payload = _sample_input(compare_block=None)
    result = daily_kpi.compute(payload)
    assert result["aggregation_mode"] == "detail"
    assert "top_anomalies" not in result


def test_aggregated_kpi_summary_has_min_max(daily_kpi):
    payload = _aggregated_input(num_devices=50)
    result = daily_kpi.compute(payload)
    for item in result["kpi_summary"]:
        assert "min" in item
        assert "max" in item
        assert "current_note" in item
        assert item["current_note"] == "均值"
        assert item["min"] <= item["current"] <= item["max"]


def test_top_anomalies_sorted_by_severity(daily_kpi):
    payload = _aggregated_input(num_devices=50, kpi_keys=["runtime_rate", "corrosion_rate"])
    result = daily_kpi.compute(payload)
    anomalies = result.get("top_anomalies", [])
    assert isinstance(anomalies, list)
    assert len(anomalies) <= 10
    for a in anomalies:
        assert "rank" in a
        assert "equipment_id" in a
        assert "issue" in a
        assert "severity" in a
        assert a["name"] != a["equipment_id"]
        assert a["area"] != ""
    if len(anomalies) > 1:
        assert anomalies[0]["rank"] == 1
        assert anomalies[-1]["rank"] == len(anomalies)
        high_indices = [i for i, a in enumerate(anomalies) if a["severity"] == "high"]
        warning_indices = [i for i, a in enumerate(anomalies) if a["severity"] == "warning"]
        if high_indices and warning_indices:
            assert max(high_indices) < min(warning_indices)


def test_aggregated_trend_chart_title(daily_kpi):
    payload = _aggregated_input(num_devices=50)
    result = daily_kpi.compute(payload)
    title = result["trend_chart"]["title"]["text"]
    assert "均值" in title
    assert "50" in title


def test_new_kpi_display_names(daily_kpi):
    expected_keys = [
        "corrosion_rate", "thickness_loss", "vibration_level",
        "bearing_temp", "flow_rate", "outlet_pressure", "valve_temp",
    ]
    for key in expected_keys:
        assert key in daily_kpi.KPI_DISPLAY_NAMES


def test_new_kpi_better_when_higher(daily_kpi):
    assert "flow_rate" in daily_kpi.KPI_BETTER_WHEN_HIGHER
    assert "outlet_pressure" in daily_kpi.KPI_BETTER_WHEN_HIGHER
    assert "corrosion_rate" not in daily_kpi.KPI_BETTER_WHEN_HIGHER
