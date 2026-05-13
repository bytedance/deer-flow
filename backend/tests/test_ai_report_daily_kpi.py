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
