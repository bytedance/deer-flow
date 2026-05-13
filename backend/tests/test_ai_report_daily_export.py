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


# --- Aggregation mode export tests ---


@pytest.fixture()
def aggregated_payload():
    return {
        "report_date": "2026-05-13",
        "equipment_ids": [f"SE-{i+1:03d}" for i in range(50)],
        "equipment_type": "static_equipment",
        "equipment_count": 50,
        "compare_type": "previous_day",
        "compare_date": "2026-05-12",
        "aggregation_mode": "grouped",
        "overall_status": {"level": "warning", "summary": "50台静设备整体运行稳定，3台设备腐蚀速率偏高"},
        "kpi_summary": [
            {"key": "runtime_rate", "name": "运行率", "current": 0.943, "current_note": "均值", "min": 0.78, "max": 0.99, "previous": 0.951, "delta": -0.008, "unit": "%", "direction": "down", "better_when_higher": True},
            {"key": "corrosion_rate", "name": "腐蚀速率", "current": 0.12, "current_note": "均值", "min": 0.01, "max": 0.48, "previous": 0.11, "delta": 0.01, "unit": "mm/a", "direction": "up", "better_when_higher": False},
        ],
        "top_anomalies": [
            {"rank": 1, "equipment_id": "SE-042", "name": "E-142 换热器", "area": "A区", "issue": "腐蚀速率 0.48 mm/a（阈值 0.3）", "severity": "high"},
            {"rank": 2, "equipment_id": "SE-108", "name": "E-208 冷却器", "area": "A区", "issue": "壁厚减薄 1.8 mm", "severity": "warning"},
        ],
        "alarm_table": [
            {"time": "2026-05-13 10:00", "equipment": "SE-042", "level": "high", "message": "腐蚀速率超标"},
        ],
        "trend_chart": {"title": {"text": "24h趋势"}, "series": []},
        "recommendations": ["关注腐蚀速率超标设备。"],
    }


def test_aggregated_markdown_has_device_count(export_report, aggregated_payload):
    markdown = export_report.render_markdown(aggregated_payload)
    assert "共 50 台" in markdown


def test_aggregated_markdown_has_type_title(export_report, aggregated_payload):
    markdown = export_report.render_markdown(aggregated_payload)
    assert "# 静设备运行日报" in markdown


def test_aggregated_markdown_has_anomaly_table(export_report, aggregated_payload):
    markdown = export_report.render_markdown(aggregated_payload)
    assert "## 异常设备排行" in markdown
    assert "SE-042" in markdown
    assert "腐蚀速率 0.48" in markdown
    assert "E-142 换热器" in markdown


def test_aggregated_markdown_has_min_max_columns(export_report, aggregated_payload):
    markdown = export_report.render_markdown(aggregated_payload)
    assert "当前（均值）" in markdown
    assert "最小" in markdown
    assert "最大" in markdown


def test_detail_mode_no_anomaly_table(export_report, kpi_payload):
    markdown = export_report.render_markdown(kpi_payload)
    assert "## 异常设备排行" not in markdown


def test_detail_mode_no_device_count(export_report, kpi_payload):
    markdown = export_report.render_markdown(kpi_payload)
    assert "共" not in markdown
    assert "E001" in markdown


def test_aggregated_no_anomalies_skips_section(export_report, aggregated_payload):
    payload = {**aggregated_payload, "top_anomalies": []}
    markdown = export_report.render_markdown(payload)
    assert "## 异常设备排行" not in markdown
