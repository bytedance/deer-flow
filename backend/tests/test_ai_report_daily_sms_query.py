"""Tests for skills/custom/daily-report/scripts/query_sms_abnormal.py."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "skills" / "custom" / "daily-report" / "scripts" / "query_sms_abnormal.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("query_sms_abnormal", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def sms_module(monkeypatch):
    monkeypatch.setenv("INS_BASE_URL", "http://sms.test")
    monkeypatch.setenv("INS_ACCESS_TOKEN", "test-token")
    return _load_module()


# ── normalize_id ────────────────────────────────────────────────────────────


def test_normalize_id_strips_hyphens(sms_module):
    assert sms_module._normalize_id("P-203A") == "p203a"


def test_normalize_id_strips_underscores(sms_module):
    assert sms_module._normalize_id("K_101_B") == "k101b"


def test_normalize_id_lowercases(sms_module):
    assert sms_module._normalize_id("ABC-DEF") == "abcdef"


def test_normalize_id_noop_for_plain_id(sms_module):
    assert sms_module._normalize_id("p203a") == "p203a"


# ── severity_label ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("level,expected", [
    (60, "critical"),
    (75, "critical"),
    (59, "high"),
    (41, "high"),
    (40, "medium"),
    (21, "medium"),
    (20, "low"),
    (0, "low"),
    (-1, "low"),
])
def test_severity_label(sms_module, level, expected):
    assert sms_module._severity_label(level) == expected


# ── day_range_ms ────────────────────────────────────────────────────────────


def test_day_range_ms(sms_module):
    start, end = sms_module._day_range_ms("2026-06-04")
    # 24h range in ms
    assert end - start == 24 * 60 * 60 * 1000 - 1
    # verify round-trip via known value (2026-06-04T00:00:00Z)
    import datetime
    dt = datetime.datetime.fromtimestamp(start / 1000, tz=datetime.timezone.utc)
    assert dt.strftime("%Y-%m-%d") == "2026-06-04"


# ── fetch_sms_abnormal ──────────────────────────────────────────────────────


def test_short_circuit_for_non_rotating_type(sms_module):
    """Non-rotating types short-circuit without HTTP call."""
    result = sms_module.fetch_sms_abnormal("2026-06-04", ["P-203A"], eq_type="pump")
    assert result["sms_abnormal"]["total_count"] == 0
    assert result["sms_abnormal"]["top_events"] == []


def test_short_circuit_for_static_equipment(sms_module):
    result = sms_module.fetch_sms_abnormal("2026-06-04", [], eq_type="static_equipment")
    assert result["sms_abnormal"]["total_count"] == 0


def test_fetch_with_rotating_type_calls_sms(sms_module, monkeypatch):
    mock_request = MagicMock(return_value={"data": {"rows": []}})
    monkeypatch.setattr(sms_module, "_request_sms", mock_request)
    result = sms_module.fetch_sms_abnormal("2026-06-04", ["P-203A"], eq_type="rotating_machinery")
    mock_request.assert_called_once()
    call_args = mock_request.call_args[0]
    assert call_args[0] == "/api/abnormal/list"
    assert result["sms_abnormal"]["total_count"] == 0


def test_fetch_handles_sms_error(sms_module, monkeypatch):
    mock_request = MagicMock(return_value={"error": "HTTP 502", "detail": "bad gateway"})
    monkeypatch.setattr(sms_module, "_request_sms", mock_request)
    result = sms_module.fetch_sms_abnormal("2026-06-04", ["P-203A"], eq_type="rotating_machinery")
    assert "error" in result["sms_abnormal"]


def test_filters_by_equipment_ids(sms_module, monkeypatch):
    mock_request = MagicMock(return_value={
        "data": {
            "rows": [
                {"id": "ab1", "macId": "P-203A", "macName": "Pump A", "componentName": "Bearing",
                 "latestHealth": 80, "latestLevel": 45, "seriousLevel": 60, "eventCount": 2,
                 "processStatus": "待处理", "runStatus": "运行",
                 "firstEventTime": 1717459200000, "lastestEventTime": 1717545600000},
                {"id": "ab2", "macId": "K-999", "macName": "Other", "componentName": "Shaft",
                 "latestHealth": 90, "latestLevel": 10, "seriousLevel": 15, "eventCount": 1,
                 "processStatus": "已处理", "runStatus": "停机",
                 "firstEventTime": 1717459200000, "lastestEventTime": 1717545600000},
            ]
        }
    })
    monkeypatch.setattr(sms_module, "_request_sms", mock_request)
    result = sms_module.fetch_sms_abnormal("2026-06-04", ["P-203A"], eq_type="rotating_machinery")
    assert result["sms_abnormal"]["total_count"] == 1
    assert result["sms_abnormal"]["top_events"][0]["mac_name"] == "Pump A"


def test_id_normalization_in_filter(sms_module, monkeypatch):
    """Equipment ID matching is case-insensitive and hyphen-insensitive."""
    mock_request = MagicMock(return_value={
        "data": {
            "rows": [
                {"id": "ab1", "macId": "P203A", "macName": "Pump", "componentName": "X",
                 "latestHealth": 80, "latestLevel": 30, "seriousLevel": 40, "eventCount": 1,
                 "processStatus": "待处理", "runStatus": "运行",
                 "firstEventTime": 1717459200000, "lastestEventTime": 1717545600000},
            ]
        }
    })
    monkeypatch.setattr(sms_module, "_request_sms", mock_request)
    # Input with hyphen should match SMS without hyphen
    result = sms_module.fetch_sms_abnormal("2026-06-04", ["P-203A"], eq_type="rotating_machinery")
    assert result["sms_abnormal"]["total_count"] == 1


def test_aggregates_by_severity(sms_module, monkeypatch):
    mock_request = MagicMock(return_value={
        "data": {
            "rows": [
                {"id": "ab1", "macId": "A", "macName": "A", "componentName": "X",
                 "latestHealth": 80, "latestLevel": 65, "seriousLevel": 70, "eventCount": 1,
                 "processStatus": "待处理", "runStatus": "运行",
                 "firstEventTime": 0, "lastestEventTime": 0},
                {"id": "ab2", "macId": "B", "macName": "B", "componentName": "Y",
                 "latestHealth": 70, "latestLevel": 65, "seriousLevel": 80, "eventCount": 3,
                 "processStatus": "待处理", "runStatus": "运行",
                 "firstEventTime": 0, "lastestEventTime": 0},
            ]
        }
    })
    monkeypatch.setattr(sms_module, "_request_sms", mock_request)
    result = sms_module.fetch_sms_abnormal("2026-06-04", [], eq_type="all")
    assert result["sms_abnormal"]["by_severity"] == {"critical": 2}


def test_aggregates_by_status(sms_module, monkeypatch):
    mock_request = MagicMock(return_value={
        "data": {
            "rows": [
                {"id": "ab1", "macId": "A", "macName": "A", "componentName": "X",
                 "latestHealth": 80, "latestLevel": 10, "seriousLevel": 10, "eventCount": 1,
                 "processStatus": "待处理", "runStatus": "运行",
                 "firstEventTime": 0, "lastestEventTime": 0},
                {"id": "ab2", "macId": "B", "macName": "B", "componentName": "Y",
                 "latestHealth": 70, "latestLevel": 10, "seriousLevel": 10, "eventCount": 1,
                 "processStatus": "已处理", "runStatus": "运行",
                 "firstEventTime": 0, "lastestEventTime": 0},
            ]
        }
    })
    monkeypatch.setattr(sms_module, "_request_sms", mock_request)
    result = sms_module.fetch_sms_abnormal("2026-06-04", [], eq_type="all")
    assert result["sms_abnormal"]["by_status"] == {"待处理": 1, "已处理": 1}


def test_top_events_sorted_by_level(sms_module, monkeypatch):
    mock_request = MagicMock(return_value={
        "data": {
            "rows": [
                {"id": "ab_low", "macId": "A", "macName": "A", "componentName": "X",
                 "latestHealth": 90, "latestLevel": 10, "seriousLevel": 10, "eventCount": 1,
                 "processStatus": "已处理", "runStatus": "运行",
                 "firstEventTime": 0, "lastestEventTime": 0},
                {"id": "ab_high", "macId": "B", "macName": "B", "componentName": "Y",
                 "latestHealth": 60, "latestLevel": 75, "seriousLevel": 80, "eventCount": 5,
                 "processStatus": "待处理", "runStatus": "运行",
                 "firstEventTime": 0, "lastestEventTime": 0},
            ]
        }
    })
    monkeypatch.setattr(sms_module, "_request_sms", mock_request)
    result = sms_module.fetch_sms_abnormal("2026-06-04", [], eq_type="all")
    events = result["sms_abnormal"]["top_events"]
    assert events[0]["abnormal_id"] == "ab_high"
    assert events[0]["rank"] == 1
    assert events[1]["abnormal_id"] == "ab_low"
    assert events[1]["rank"] == 2


def test_equipment_names_prefer_meta(sms_module, monkeypatch):
    """When equipment_meta is provided, use Organize tree name over SMS name."""
    mock_request = MagicMock(return_value={
        "data": {
            "rows": [
                {"id": "ab1", "macId": "P-203A", "macName": "SMS_Name_Pump", "componentName": "X",
                 "latestHealth": 80, "latestLevel": 30, "seriousLevel": 30, "eventCount": 1,
                 "processStatus": "待处理", "runStatus": "运行",
                 "firstEventTime": 0, "lastestEventTime": 0},
            ]
        }
    })
    monkeypatch.setattr(sms_module, "_request_sms", mock_request)
    meta = {"P-203A": {"name": "进料泵P-203A"}}
    result = sms_module.fetch_sms_abnormal("2026-06-04", ["P-203A"], eq_type="rotating_machinery", equipment_meta=meta)
    assert result["sms_abnormal"]["top_events"][0]["mac_name"] == "进料泵P-203A"


# ── write_output ────────────────────────────────────────────────────────────


def test_write_output_creates_file(sms_module, tmp_path):
    payload = {"report_date": "2026-06-04", "sms_abnormal": {"total_count": 0}}
    out = tmp_path / "subdir" / "sms_abnormal.json"
    result = sms_module.write_output(payload, out)
    assert result == out
    assert out.exists()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["sms_abnormal"]["total_count"] == 0


# ── main CLI ────────────────────────────────────────────────────────────────


def test_main_exits_zero_on_error(sms_module, capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("DAILY_REPORT_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setattr(sms_module, "_request_sms", MagicMock(side_effect=Exception("connection refused")))
    import sys as _sys
    saved = _sys.argv[:]
    try:
        _sys.argv = ["query_sms_abnormal.py", "--date", "2026-06-04"]
        exit_code = sms_module.main()
        assert exit_code == 0
        captured = capsys.readouterr().out
        assert "error" in captured
    finally:
        _sys.argv = saved


def test_main_invalid_date(sms_module, capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("DAILY_REPORT_OUTPUT_DIR", str(tmp_path))
    import sys as _sys
    saved = _sys.argv[:]
    try:
        _sys.argv = ["query_sms_abnormal.py", "--date", "not-a-date"]
        exit_code = sms_module.main()
        assert exit_code == 0
        captured = capsys.readouterr().out
        assert "error" in captured
    finally:
        _sys.argv = saved
