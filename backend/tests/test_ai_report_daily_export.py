"""Tests for skills/custom/data-analyst/scripts/export_report.py."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "skills" / "custom" / "data-analyst" / "scripts" / "export_report.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("export_report", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def export_report(tmp_path, monkeypatch):
    monkeypatch.setenv("DAILY_REPORT_OUTPUT_DIR", str(tmp_path))
    return _load_module()


@pytest.fixture()
def kpi_payload():
    return {
        "report_date": "2026-05-13",
        "equipment_ids": ["E001"],
        "compare_type": "previous_day",
        "compare_date": "2026-05-12",
        "overall_status": {"level": "warning", "summary": "整体运行稳定，有少量异常。"},
        "kpi_summary": [
            {"key": "runtime_rate", "name": "运行率", "current": 0.92, "previous": 0.85, "delta": 0.07, "unit": "%", "direction": "up"},
            {"key": "downtime_count", "name": "停机次数", "current": 2, "previous": 5, "delta": -3, "unit": "次", "direction": "down"},
        ],
        "alarm_table": [
            {"time": "2026-05-13 03:00", "equipment": "E001", "level": "high", "message": "高温告警"},
        ],
        "recommendations": ["关注 E001 高温告警。"],
    }


def test_render_markdown_contains_sections(export_report, kpi_payload):
    markdown = export_report.render_markdown(kpi_payload)
    assert "# 设备运行日报" in markdown
    assert "## 概览" in markdown
    assert "## KPI 指标" in markdown
    assert "## 异常事件" in markdown
    assert "## 建议" in markdown
    assert "运行率" in markdown
    assert "高温告警" in markdown


def test_write_markdown_report(export_report, kpi_payload, tmp_path):
    out_path = export_report.write_report(kpi_payload, "md")
    assert out_path.parent == tmp_path
    assert out_path.name == "daily_report.md"
    assert out_path.read_text(encoding="utf-8").startswith("# 设备运行日报")


def test_export_result_contract(export_report, kpi_payload, tmp_path):
    result = export_report.build_export_result(kpi_payload, "md")
    assert result["format"] == "md"
    assert result["filename"] == "daily_report.md"
    assert result["path"].endswith("daily_report.md")
    assert result["artifact_path"] == str(tmp_path / "daily_report.md")


def test_rejects_unsupported_format(export_report, kpi_payload):
    with pytest.raises(ValueError, match="Unsupported export format"):
        export_report.write_report(kpi_payload, "pdf")


def test_load_input(export_report, kpi_payload, tmp_path):
    input_path = tmp_path / "daily_kpi.json"
    input_path.write_text(json.dumps(kpi_payload), encoding="utf-8")
    loaded = export_report.load_payload(input_path)
    assert loaded["report_date"] == "2026-05-13"


def test_escapes_markdown_table_pipes(export_report, kpi_payload):
    payload = {
        **kpi_payload,
        "alarm_table": [
            {"time": "2026-05-13 03:00", "equipment": "E|001", "level": "high", "message": "温度|异常"},
        ],
    }
    markdown = export_report.render_markdown(payload)
    assert "E\\|001" in markdown
    assert "温度\\|异常" in markdown
