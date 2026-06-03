"""Tests for skills/custom/weekly-report/scripts/weekly_kpi.py.

Verifies design doc §6.2 output shape and key calculation invariants:
- Weekly KPI summary fields use ``current_mean / current_peak / current_trough``
  to stay distinguishable from daily output.
- ``delta_pct`` is ``None`` when previous_mean is 0 (no NaN/Inf leak).
- ``anomaly_top_n`` sorts by count desc and limits to 10.
- ``next_week_focus`` is always populated.
- Contract: ``query_weekly`` output flows into ``weekly_kpi.compute`` unchanged.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
WEEKLY_KPI_PATH = REPO_ROOT / "skills" / "custom" / "weekly-report" / "scripts" / "weekly_kpi.py"
QUERY_WEEKLY_PATH = REPO_ROOT / "skills" / "custom" / "weekly-report" / "scripts" / "query_weekly.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def weekly_kpi(tmp_path, monkeypatch):
    monkeypatch.setenv("WEEKLY_REPORT_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setenv("DAILY_REPORT_OUTPUT_DIR", str(tmp_path))
    return _load(WEEKLY_KPI_PATH, "weekly_kpi")


def _stub_query_weekly(module):
    """Patch fetch_week_with_provenance to return InS-tagged synthetic data."""
    from datetime import datetime, timedelta

    def fake_fetch(week_start, equipment_ids, kpi_keys, eq_type="all", aggregate=False, equipment_meta=None):
        start_dt = datetime.strptime(week_start, "%Y-%m-%d")
        daily = []
        for offset in range(7):
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
        result: dict = {"daily": daily, "aggregated": agg, "alarms": [], "kpi_units": {key: "%" for key in kpi_keys}}
        return result, "ins", []

    module.fetch_week_with_provenance = fake_fetch


@pytest.fixture()
def query_weekly(tmp_path, monkeypatch):
    monkeypatch.setenv("WEEKLY_REPORT_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setenv("DAILY_REPORT_OUTPUT_DIR", str(tmp_path))
    module = _load(QUERY_WEEKLY_PATH, "query_weekly")
    _stub_query_weekly(module)
    return module


def _make_aggregated(mean=0.93, peak=0.96, trough=0.90, std=0.02):
    return {
        "kpis_mean": {"runtime_rate": mean},
        "kpis_max": {"runtime_rate": peak},
        "kpis_min": {"runtime_rate": trough},
        "kpis_std": {"runtime_rate": std},
    }


def test_compute_basic_shape(weekly_kpi):
    payload = {
        "report_period": {"week_start": "2026-05-11", "week_end": "2026-05-17", "day_count": 7},
        "compare_type": "previous_week",
        "compare_period": {"start": "2026-05-04", "end": "2026-05-10"},
        "equipment_ids": ["RM-001"],
        "kpi_keys": ["runtime_rate"],
        "current": {
            "daily": [
                {"date": "2026-05-11", "kpis": {"runtime_rate": 0.92}, "kpi_units": {"runtime_rate": "%"}, "alarms": []},
                {"date": "2026-05-12", "kpis": {"runtime_rate": 0.95}, "kpi_units": {"runtime_rate": "%"}, "alarms": []},
                {"date": "2026-05-13", "kpis": {"runtime_rate": 0.93}, "kpi_units": {"runtime_rate": "%"}, "alarms": []},
                {"date": "2026-05-14", "kpis": {"runtime_rate": 0.91}, "kpi_units": {"runtime_rate": "%"}, "alarms": []},
                {"date": "2026-05-15", "kpis": {"runtime_rate": 0.96}, "kpi_units": {"runtime_rate": "%"}, "alarms": []},
                {"date": "2026-05-16", "kpis": {"runtime_rate": 0.94}, "kpi_units": {"runtime_rate": "%"}, "alarms": []},
                {"date": "2026-05-17", "kpis": {"runtime_rate": 0.90}, "kpi_units": {"runtime_rate": "%"}, "alarms": []},
            ],
            "aggregated": _make_aggregated(mean=0.93, peak=0.96, trough=0.90, std=0.02),
            "alarms": [],
        },
        "compare": {
            "daily": [],
            "aggregated": _make_aggregated(mean=0.91),
            "alarms": [],
        },
        "data_source": "ins",
    }
    result = weekly_kpi.compute(payload)
    assert result["report_period"]["week_start"] == "2026-05-11"
    assert result["compare_type"] == "previous_week"
    summary = result["kpi_summary"]
    assert len(summary) == 1
    assert summary[0]["key"] == "runtime_rate"
    assert summary[0]["current_mean"] == 0.93
    assert summary[0]["current_peak"] == 0.96
    assert summary[0]["current_trough"] == 0.90
    assert summary[0]["previous_mean"] == 0.91
    assert summary[0]["delta_mean"] == pytest.approx(0.02, abs=1e-4)
    # delta_pct should be (0.02 / 0.91) ≈ 0.022
    assert summary[0]["delta_pct"] is not None
    assert summary[0]["direction"] == "up"
    assert summary[0]["better_when_higher"] is True


def test_compute_no_compare(weekly_kpi):
    payload = {
        "report_period": {"week_start": "2026-05-11", "week_end": "2026-05-17", "day_count": 7},
        "compare_type": "none",
        "compare_period": None,
        "kpi_keys": ["runtime_rate"],
        "current": {
            "daily": [
                {"date": "2026-05-11", "kpis": {"runtime_rate": 0.9}, "kpi_units": {"runtime_rate": "%"}, "alarms": []}
            ],
            "aggregated": _make_aggregated(),
            "alarms": [],
        },
        "compare": None,
        "data_source": "ins",
    }
    result = weekly_kpi.compute(payload)
    summary = result["kpi_summary"][0]
    assert summary["previous_mean"] is None
    assert summary["delta_mean"] is None
    assert summary["delta_pct"] is None
    assert summary["direction"] == "flat"


def test_compute_zero_previous_mean_returns_null_pct(weekly_kpi):
    """delta_pct must be None (not NaN/Inf) when previous_mean is 0."""
    payload = {
        "report_period": {"week_start": "2026-05-11", "week_end": "2026-05-17", "day_count": 7},
        "compare_type": "previous_week",
        "compare_period": {"start": "2026-05-04", "end": "2026-05-10"},
        "kpi_keys": ["downtime_count"],
        "current": {
            "daily": [
                {"date": "2026-05-11", "kpis": {"downtime_count": 1}, "kpi_units": {"downtime_count": "次"}, "alarms": []},
            ],
            "aggregated": {
                "kpis_mean": {"downtime_count": 1.4},
                "kpis_max": {"downtime_count": 3},
                "kpis_min": {"downtime_count": 0},
                "kpis_std": {"downtime_count": 1.0},
            },
            "alarms": [],
        },
        "compare": {
            "daily": [],
            "aggregated": {
                "kpis_mean": {"downtime_count": 0},
                "kpis_max": {"downtime_count": 0},
                "kpis_min": {"downtime_count": 0},
                "kpis_std": {"downtime_count": 0},
            },
            "alarms": [],
        },
        "data_source": "ins",
    }
    result = weekly_kpi.compute(payload)
    summary = result["kpi_summary"][0]
    assert summary["previous_mean"] == 0
    assert summary["delta_mean"] == 1.4
    assert summary["delta_pct"] is None  # no Inf/NaN leak


def test_daily_trend_chart_seven_x_labels(weekly_kpi):
    payload = {
        "report_period": {"week_start": "2026-05-11", "week_end": "2026-05-17", "day_count": 7},
        "compare_type": "none",
        "kpi_keys": ["runtime_rate", "alarm_count"],
        "current": {
            "daily": [
                {"date": f"2026-05-{11 + i:02d}", "kpis": {"runtime_rate": 0.9, "alarm_count": i}, "kpi_units": {"runtime_rate": "%", "alarm_count": "条"}, "alarms": []}
                for i in range(7)
            ],
            "aggregated": {
                "kpis_mean": {"runtime_rate": 0.9, "alarm_count": 3},
                "kpis_max": {"runtime_rate": 0.95, "alarm_count": 6},
                "kpis_min": {"runtime_rate": 0.85, "alarm_count": 0},
                "kpis_std": {"runtime_rate": 0.03, "alarm_count": 2},
            },
            "alarms": [],
        },
        "compare": None,
        "data_source": "ins",
    }
    result = weekly_kpi.compute(payload)
    chart = result["daily_trend_chart"]
    assert len(chart["xAxis"]["data"]) == 7
    assert chart["xAxis"]["data"][0].endswith("周一")
    assert chart["xAxis"]["data"][6].endswith("周日")
    legend = chart["legend"]["data"]
    assert "运行率" in legend
    assert "告警数量" in legend


def test_anomaly_top_n_sort_and_limit(weekly_kpi):
    alarms = []
    # 12 unique (equipment, level) groups so we can verify limit=10
    for i in range(12):
        alarms.append({"time": f"2026-05-11 {i:02d}:00", "equipment": f"E-{i:03d}", "level": "warning", "message": "振动"})
    # one bucket with high count
    for h in range(5):
        alarms.append({"time": f"2026-05-13 {h:02d}:00", "equipment": "RM-002", "level": "critical", "message": "轴承温度超限"})

    payload = {
        "report_period": {"week_start": "2026-05-11", "week_end": "2026-05-17", "day_count": 7},
        "compare_type": "none",
        "kpi_keys": ["runtime_rate"],
        "current": {
            "daily": [],
            "aggregated": _make_aggregated(),
            "alarms": alarms,
        },
        "compare": None,
        "data_source": "ins",
    }
    result = weekly_kpi.compute(payload)
    top = result["anomaly_top_n"]
    assert len(top) <= 10
    assert top[0]["equipment"] == "RM-002"
    assert top[0]["count"] == 5
    assert top[0]["dominant_message"] == "轴承温度超限"
    assert top[0]["latest_time"] == "2026-05-13 04:00"


def test_anomaly_top_n_empty(weekly_kpi):
    payload = {
        "report_period": {"week_start": "2026-05-11", "week_end": "2026-05-17", "day_count": 7},
        "compare_type": "none",
        "kpi_keys": ["runtime_rate"],
        "current": {"daily": [], "aggregated": _make_aggregated(), "alarms": []},
        "compare": None,
        "data_source": "ins",
    }
    result = weekly_kpi.compute(payload)
    assert result["anomaly_top_n"] == []


def test_overall_status_critical_when_high_alarms(weekly_kpi):
    payload = {
        "report_period": {"week_start": "2026-05-11", "week_end": "2026-05-17", "day_count": 7},
        "compare_type": "none",
        "kpi_keys": ["runtime_rate"],
        "current": {
            "daily": [],
            "aggregated": _make_aggregated(),
            "alarms": [
                {"time": "2026-05-13 14:02", "equipment": "RM-002", "level": "critical", "message": "轴承温度超限"},
            ],
        },
        "compare": None,
        "data_source": "ins",
    }
    result = weekly_kpi.compute(payload)
    assert result["overall_status"]["level"] == "critical"


def test_overall_status_warning_when_low_runtime(weekly_kpi):
    payload = {
        "report_period": {"week_start": "2026-05-11", "week_end": "2026-05-17", "day_count": 7},
        "compare_type": "none",
        "kpi_keys": ["runtime_rate"],
        "current": {
            "daily": [],
            "aggregated": _make_aggregated(mean=0.80, peak=0.85, trough=0.75),
            "alarms": [],
        },
        "compare": None,
        "data_source": "ins",
    }
    result = weekly_kpi.compute(payload)
    assert result["overall_status"]["level"] == "warning"


def test_next_week_focus_includes_top_anomaly(weekly_kpi):
    alarms = [
        {"time": "2026-05-13 14:02", "equipment": "RM-002", "level": "critical", "message": "轴承温度超限"},
        {"time": "2026-05-14 09:00", "equipment": "RM-002", "level": "critical", "message": "轴承温度超限"},
    ]
    payload = {
        "report_period": {"week_start": "2026-05-11", "week_end": "2026-05-17", "day_count": 7},
        "compare_type": "none",
        "kpi_keys": ["runtime_rate"],
        "current": {"daily": [], "aggregated": _make_aggregated(), "alarms": alarms},
        "compare": None,
        "data_source": "ins",
    }
    result = weekly_kpi.compute(payload)
    focus = result["next_week_focus"]
    assert any("RM-002" in s for s in focus)


def test_next_week_focus_never_empty(weekly_kpi):
    payload = {
        "report_period": {"week_start": "2026-05-11", "week_end": "2026-05-17", "day_count": 7},
        "compare_type": "none",
        "kpi_keys": ["runtime_rate"],
        "current": {"daily": [], "aggregated": _make_aggregated(), "alarms": []},
        "compare": None,
        "data_source": "ins",
    }
    result = weekly_kpi.compute(payload)
    assert len(result["next_week_focus"]) >= 1


def test_volatility_uses_std_over_mean(weekly_kpi):
    payload = {
        "report_period": {"week_start": "2026-05-11", "week_end": "2026-05-17", "day_count": 7},
        "compare_type": "none",
        "kpi_keys": ["runtime_rate"],
        "current": {
            "daily": [],
            "aggregated": {
                "kpis_mean": {"runtime_rate": 0.5},
                "kpis_max": {"runtime_rate": 0.6},
                "kpis_min": {"runtime_rate": 0.4},
                "kpis_std": {"runtime_rate": 0.1},
            },
            "alarms": [],
        },
        "compare": None,
        "data_source": "ins",
    }
    result = weekly_kpi.compute(payload)
    summary = result["kpi_summary"][0]
    assert summary["current_volatility"] == pytest.approx(0.2, abs=1e-4)


def test_contract_query_to_kpi(query_weekly, weekly_kpi):
    """query_weekly output must be consumable by weekly_kpi.compute unchanged."""
    payload = query_weekly.build_result(
        week_start="2026-05-11",
        equipment_ids=["RM-001", "RM-002"],
        kpi_keys=["runtime_rate", "downtime_count", "alarm_count"],
        compare="previous_week",
    )
    result = weekly_kpi.compute(payload)
    assert result["report_period"]["week_start"] == "2026-05-11"
    assert result["compare_type"] == "previous_week"
    assert len(result["kpi_summary"]) >= 1
    assert "daily_trend_chart" in result
    assert "anomaly_top_n" in result
    assert "alarm_table" in result
    assert "next_week_focus" in result
    # No NaN/Inf in any numeric field
    for item in result["kpi_summary"]:
        for k, v in item.items():
            if isinstance(v, float):
                assert not (v != v), f"NaN in {k}"


def test_main_handles_missing_input(weekly_kpi, capsys, tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["weekly_kpi.py", "--input", str(tmp_path / "missing.json")])
    rc = weekly_kpi.main()
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert "error" in out


def test_main_writes_output(weekly_kpi, query_weekly, tmp_path, capsys, monkeypatch):
    # First produce weekly_data.json via query_weekly
    payload = query_weekly.build_result(
        week_start="2026-05-11",
        equipment_ids=["RM-001"],
        kpi_keys=["runtime_rate"],
        compare="previous_week",
    )
    query_weekly.write_payload(payload)

    monkeypatch.setattr(sys, "argv", ["weekly_kpi.py"])
    rc = weekly_kpi.main()
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["week_start"] == "2026-05-11"
    out_file = tmp_path / "weekly_kpi.json"
    assert out_file.exists()
