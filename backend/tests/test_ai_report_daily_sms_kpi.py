"""Tests for SMS merge logic in skills/custom/daily-report/scripts/daily_kpi.py."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "skills" / "custom" / "daily-report" / "scripts"
KPI_PATH = SCRIPTS_DIR / "daily_kpi.py"


def _load_kpi_module():
    spec = importlib.util.spec_from_file_location("daily_kpi", KPI_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def kpi_module(monkeypatch, tmp_path):
    monkeypatch.setenv("DAILY_REPORT_OUTPUT_DIR", str(tmp_path))
    return _load_kpi_module()


# ── _build_sms_anomaly_table ────────────────────────────────────────────────


def test_build_sms_anomaly_table_none(kpi_module):
    assert kpi_module._build_sms_anomaly_table(None) == []


def test_build_sms_anomaly_table_empty_dict(kpi_module):
    assert kpi_module._build_sms_anomaly_table({}) == []


def test_build_sms_anomaly_table_no_top_events(kpi_module):
    assert kpi_module._build_sms_anomaly_table({"top_events": []}) == []


def test_build_sms_anomaly_table_converts_events(kpi_module):
    sms_data = {
        "top_events": [
            {
                "rank": 1,
                "mac_name": "进料泵P-203A",
                "component_name": "轴承",
                "latest_health": 75,
                "latest_level": 65,
                "severity": "critical",
                "event_count": 3,
                "process_status": "待处理",
                "run_status": "运行",
            },
            {
                "rank": 2,
                "mac_name": "循环泵P-101",
                "component_name": "叶轮",
                "latest_health": 85,
                "latest_level": 45,
                "severity": "high",
                "event_count": 1,
                "process_status": "已处理",
                "run_status": "停机",
            },
        ]
    }
    rows = kpi_module._build_sms_anomaly_table(sms_data)
    assert len(rows) == 2
    assert rows[0]["rank"] == 1
    assert rows[0]["equipment"] == "进料泵P-203A"
    assert rows[0]["component"] == "轴承"
    assert rows[0]["health"] == 75
    assert rows[0]["level"] == 65
    assert rows[0]["severity"] == "严重"
    assert rows[0]["event_count"] == 3
    assert rows[0]["process_status"] == "待处理"
    assert rows[0]["run_status"] == "运行"
    assert rows[1]["severity"] == "高"


def test_build_sms_anomaly_table_defaults_missing_fields(kpi_module):
    sms_data = {
        "top_events": [
            {"rank": 1}
        ]
    }
    rows = kpi_module._build_sms_anomaly_table(sms_data)
    assert rows[0]["equipment"] == ""
    assert rows[0]["component"] == ""
    assert rows[0]["health"] == 0
    assert rows[0]["level"] == 0
    assert rows[0]["severity"] == "低"  # default sev="low" → "低"
    assert rows[0]["event_count"] == 0


# ── _overall_status with SMS ────────────────────────────────────────────────


def _make_kpi(key, current):
    return {"key": key, "name": key, "current": current, "previous": None,
            "delta": None, "unit": "", "direction": None, "better_when_higher": True}


def test_overall_status_sms_critical_alone_warning(kpi_module):
    """SMS critical events alone (no InS alarms) → warning."""
    kpi_summary = [_make_kpi("runtime_rate", 0.95)]
    sms = {"by_severity": {"critical": 2, "high": 1}}
    result = kpi_module._overall_status(kpi_summary, [], sms_abnormal=sms)
    assert result["level"] == "warning"
    assert "SMS 严重异常" in result["summary"]


def test_overall_status_sms_high_alone_warning(kpi_module):
    """SMS high events alone → warning."""
    kpi_summary = [_make_kpi("runtime_rate", 0.95)]
    sms = {"by_severity": {"high": 3}}
    result = kpi_module._overall_status(kpi_summary, [], sms_abnormal=sms)
    assert result["level"] == "warning"
    assert "SMS 高级异常" in result["summary"]


def test_overall_status_sms_critical_escalates_warning_to_danger(kpi_module):
    """SMS critical + low runtime (warning) → danger via escalation."""
    kpi_summary = [_make_kpi("runtime_rate", 0.70)]
    sms = {"by_severity": {"critical": 1}}
    result = kpi_module._overall_status(kpi_summary, [], sms_abnormal=sms)
    assert result["level"] == "danger"
    assert "等级提升" in result["summary"]


def test_overall_status_sms_critical_does_not_double_escalate(kpi_module):
    """SMS critical + high alarms (already danger) → stays danger."""
    kpi_summary = [_make_kpi("runtime_rate", 0.95)]
    alarms = [{"level": "high", "equipment": "P-101", "message": "振动超标"}]
    sms = {"by_severity": {"critical": 1}}
    result = kpi_module._overall_status(kpi_summary, alarms, sms_abnormal=sms)
    assert result["level"] == "danger"


def test_overall_status_no_sms_data(kpi_module):
    """No SMS data → normal logic (ok when everything is fine)."""
    kpi_summary = [_make_kpi("runtime_rate", 0.95)]
    result = kpi_module._overall_status(kpi_summary, [], sms_abnormal=None)
    assert result["level"] == "ok"


def test_overall_status_sms_with_equipment_count(kpi_module):
    """Equipment count is used in the summary text."""
    kpi_summary = [_make_kpi("runtime_rate", 0.95)]
    sms = {"by_severity": {"critical": 1}}
    result = kpi_module._overall_status(kpi_summary, [], equipment_count=5, sms_abnormal=sms)
    assert "5台设备" in result["summary"]


def test_overall_status_sms_empty_by_severity(kpi_module):
    """SMS with no by_severity acts like no SMS data."""
    kpi_summary = [_make_kpi("runtime_rate", 0.95)]
    sms = {"by_severity": {}}
    result = kpi_module._overall_status(kpi_summary, [], sms_abnormal=sms)
    assert result["level"] == "ok"


# ── _fetch_sms_direct ───────────────────────────────────────────────────────


def test_fetch_sms_direct_returns_none_without_date(kpi_module):
    assert kpi_module._fetch_sms_direct({}) is None


def test_fetch_sms_direct_returns_none_without_equipment_ids(kpi_module):
    assert kpi_module._fetch_sms_direct({"report_date": "2026-06-11"}) is None


def test_fetch_sms_direct_returns_none_on_import_error(kpi_module):
    """If query_sms_abnormal is not importable, returns None."""
    payload = {"report_date": "2026-06-11", "equipment_ids": ["EQ1"]}
    with patch.dict(sys.modules, {"query_sms_abnormal": None}):
        assert kpi_module._fetch_sms_direct(payload) is None


def test_fetch_sms_direct_returns_none_on_exception(kpi_module):
    """If fetch_sms_abnormal raises, returns None."""
    payload = {"report_date": "2026-06-11", "equipment_ids": ["EQ1"]}
    mock_fetch = pytest.importorskip("unittest.mock").MagicMock(side_effect=RuntimeError("boom"))
    mock_mod = pytest.importorskip("unittest.mock").MagicMock()
    mock_mod.fetch_sms_abnormal = mock_fetch
    with patch.dict(sys.modules, {"query_sms_abnormal": mock_mod}):
        assert kpi_module._fetch_sms_direct(payload) is None


def test_fetch_sms_direct_returns_none_on_error_key(kpi_module):
    payload = {"report_date": "2026-06-11", "equipment_ids": ["EQ1"]}
    mock_mod = pytest.importorskip("unittest.mock").MagicMock()
    mock_mod.fetch_sms_abnormal.return_value = {"sms_abnormal": {"error": "timeout"}}
    with patch.dict(sys.modules, {"query_sms_abnormal": mock_mod}):
        assert kpi_module._fetch_sms_direct(payload) is None


def test_fetch_sms_direct_returns_none_on_zero_total(kpi_module):
    payload = {"report_date": "2026-06-11", "equipment_ids": ["EQ1"]}
    mock_mod = pytest.importorskip("unittest.mock").MagicMock()
    mock_mod.fetch_sms_abnormal.return_value = {"sms_abnormal": {"total_count": 0}}
    with patch.dict(sys.modules, {"query_sms_abnormal": mock_mod}):
        assert kpi_module._fetch_sms_direct(payload) is None


def test_fetch_sms_direct_returns_sms_data(kpi_module):
    payload = {
        "report_date": "2026-06-11",
        "equipment_ids": ["EQ1", "EQ2"],
        "equipment_type": "rotating_machinery",
        "equipment_names": {"EQ1": "泵A"},
    }
    sms_data = {"total_count": 3, "by_severity": {"critical": 1}}
    mock_mod = pytest.importorskip("unittest.mock").MagicMock()
    mock_mod.fetch_sms_abnormal.return_value = {"sms_abnormal": sms_data}
    with patch.dict(sys.modules, {"query_sms_abnormal": mock_mod}):
        result = kpi_module._fetch_sms_direct(payload)
    assert result is not None
    assert result["total_count"] == 3
    mock_mod.fetch_sms_abnormal.assert_called_once()


# ── _sms_kpi ────────────────────────────────────────────────────────────────


def test_sms_kpi_builds_entry(kpi_module):
    entry = kpi_module._sms_kpi("sms_abnormal_count", 5)
    assert entry["key"] == "sms_abnormal_count"
    assert entry["current"] == 5
    assert entry["unit"] == "条"
    assert entry["previous"] is None
    assert entry["delta"] is None
    assert entry["better_when_higher"] is False


def test_sms_kpi_uses_display_name(kpi_module):
    entry = kpi_module._sms_kpi("sms_abnormal_pending", 0)
    assert entry["name"] == kpi_module.KPI_DISPLAY_NAMES.get("sms_abnormal_pending", "sms_abnormal_pending")


# ── compute() SMS integration ───────────────────────────────────────────────


def _base_payload():
    return {
        "report_date": "2026-06-04",
        "equipment_ids": ["P-203A"],
        "equipment_names": {"P-203A": "进料泵P-203A"},
        "compare_type": "none",
        "current": {
            "kpis": {"runtime_rate": 0.92, "alarm_count": 0},
            "kpi_units": {"runtime_rate": "%", "alarm_count": "条"},
            "hourly_runtime_rate": [0.9] * 24,
            "alarms": [],
        },
    }


def _sms_payload(total=5, critical=2, high=3, pending=3):
    return {
        "total_count": total,
        "by_severity": {"critical": critical, "high": high},
        "by_status": {"待处理": pending, "已处理": total - pending},
        "top_events": [],
    }


def test_compute_injects_sms_kpis(kpi_module):
    """When _fetch_sms_direct returns data, inject SMS KPI cards."""
    with patch.object(kpi_module, "_fetch_sms_direct", return_value=_sms_payload()):
        result = kpi_module.compute(_base_payload())

    sms_keys = {item["key"] for item in result["kpi_summary"]}
    assert "sms_abnormal_count" in sms_keys
    assert "sms_abnormal_pending" in sms_keys

    sms_count = next(item for item in result["kpi_summary"] if item["key"] == "sms_abnormal_count")
    assert sms_count["current"] == 5
    assert sms_count["unit"] == "条"

    sms_pending = next(item for item in result["kpi_summary"] if item["key"] == "sms_abnormal_pending")
    assert sms_pending["current"] == 3

    assert result["sms_abnormal_table"] is not None
    assert "sms_abnormal" in result


def test_compute_no_sms_returns_none_no_injection(kpi_module):
    """When _fetch_sms_direct returns None, no SMS KPIs are injected."""
    with patch.object(kpi_module, "_fetch_sms_direct", return_value=None):
        result = kpi_module.compute(_base_payload())

    sms_keys = {item["key"] for item in result["kpi_summary"]}
    assert "sms_abnormal_count" not in sms_keys
    assert "sms_abnormal_pending" not in sms_keys
    assert result["sms_abnormal_table"] == []
    assert "sms_abnormal" not in result


def test_compute_sms_does_not_break_detail_mode(kpi_module):
    """SMS data is compatible with detail mode (≤20 equipment)."""
    with patch.object(kpi_module, "_fetch_sms_direct", return_value=None):
        result = kpi_module.compute(_base_payload())
    assert result["aggregation_mode"] == "detail"
    assert result["overall_status"]["level"] == "ok"


def test_compute_sms_table_has_rows(kpi_module):
    """When SMS has top_events, sms_abnormal_table is populated."""
    sms_data = _sms_payload(total=2, critical=1, high=1, pending=1)
    sms_data["top_events"] = [
        {"rank": 1, "mac_name": "Pump A", "component_name": "Bearing",
         "latest_health": 70, "latest_level": 65, "severity": "critical",
         "event_count": 3, "process_status": "待处理", "run_status": "运行"},
    ]
    with patch.object(kpi_module, "_fetch_sms_direct", return_value=sms_data):
        result = kpi_module.compute(_base_payload())
    assert len(result["sms_abnormal_table"]) == 1
    assert result["sms_abnormal_table"][0]["equipment"] == "Pump A"
    assert result["sms_abnormal_table"][0]["severity"] == "严重"
