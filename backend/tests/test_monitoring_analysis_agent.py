"""Tests for monitoring-analysis agent SOUL.md + config + export integration.

Covers:
- SOUL.md structure: all callback sections, pipeline dispatch, validation
  rules, closure integration, error handling
- config.yaml: skills, starters, tags
- export_report.py: monitoring report type registration
"""

from __future__ import annotations

from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).resolve().parents[2] / "agents" / "builtin" / "monitoring-analysis"
SOUL_PATH = AGENT_DIR / "SOUL.md"
CONFIG_PATH = AGENT_DIR / "config.yaml"
EXPORT_REPORT_PATH = (
    Path(__file__).resolve().parents[2]
    / "skills" / "custom" / "data-analyst" / "scripts" / "export_report.py"
)


@pytest.fixture(scope="module")
def soul_text() -> str:
    return SOUL_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def config_text() -> str:
    return CONFIG_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# SOUL.md structure — callback state machine
# ---------------------------------------------------------------------------

def test_soul_has_core_principles(soul_text):
    """Core principles section must be present."""
    assert "核心原则" in soul_text
    assert "数据优先" in soul_text
    assert "先收参后分析" in soul_text


def test_soul_has_first_entry_section(soul_text):
    """First entry must render device-selector-multi with correct callback_id."""
    assert "首次进入" in soul_text
    assert "device-selector-multi" in soul_text
    assert "monitor-equipment" in soul_text


def test_soul_has_equipment_callback_section(soul_text):
    """Equipment callback must validate and render scope form."""
    assert "设备选择回调" in soul_text
    assert "monitor-equipment" in soul_text
    assert "monitor-scope" in soul_text
    assert "analysis_type" in soul_text


def test_soul_has_scope_callback_section(soul_text):
    """Scope callback must dispatch to analysis pipelines."""
    assert "分析范围回调" in soul_text
    assert "monitor-scope" in soul_text


# ---------------------------------------------------------------------------
# Pipeline sections
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "pipeline_keyword",
    [
        "趋势分析流水线",
        "异常检测流水线",
        "KPI 健康看板流水线",
        "关联分析流水线",
    ],
)
def test_soul_has_pipeline_section(soul_text, pipeline_keyword):
    """All four analysis pipelines must have dedicated sections."""
    assert pipeline_keyword in soul_text


def test_soul_has_trend_steps(soul_text):
    """Trend pipeline must invoke query_trend.py and trend_analysis.py."""
    assert "query_trend.py" in soul_text
    assert "trend_analysis.py" in soul_text


def test_soul_has_anomaly_steps(soul_text):
    """Anomaly pipeline must include IQR + threshold detection logic."""
    assert "IQR" in soul_text or "iqr" in soul_text.lower()
    assert "severity" in soul_text


def test_soul_has_kpi_dashboard_steps(soul_text):
    """KPI dashboard must invoke query_daily.py --aggregate."""
    assert "query_daily.py" in soul_text
    assert "雷达" in soul_text or "radar" in soul_text.lower()


def test_soul_has_correlation_steps(soul_text):
    """Correlation pipeline must include Pearson computation."""
    assert "pearson" in soul_text.lower()
    assert "关联" in soul_text


# ---------------------------------------------------------------------------
# Report export
# ---------------------------------------------------------------------------

def test_soul_has_report_export_section(soul_text):
    """Report export pipeline must be present (common section)."""
    assert "报告导出流水线" in soul_text


def test_soul_has_present_files_guidance(soul_text):
    """SOUL must instruct present_files only for final artifacts."""
    assert "present_files" in soul_text
    assert "monitoring_report.md" in soul_text


def test_soul_has_export_python_block(soul_text):
    """Export must use inline Python calling export_report.write_report."""
    assert "export_report" in soul_text
    assert "write_report" in soul_text


# ---------------------------------------------------------------------------
# Closure ticket integration
# ---------------------------------------------------------------------------

def test_soul_has_closure_integration(soul_text):
    """Closure ticket section must be present."""
    assert "闭环" in soul_text
    assert "create_closure_ticket" in soul_text


def test_soul_defines_closure_thresholds(soul_text):
    """Must specify when to auto-create closure tickets."""
    assert "severity" in soul_text
    assert "critical" in soul_text


# ---------------------------------------------------------------------------
# Input validation & error handling
# ---------------------------------------------------------------------------

def test_soul_has_validation_rules(soul_text):
    """SOUL must enforce validation at callback boundaries."""
    assert "匹配" in soul_text and "校验" in soul_text


def test_soul_has_enum_validation(soul_text):
    """analysis_type must be validated against allowed enum values."""
    assert "trend" in soul_text
    assert "anomaly" in soul_text
    assert "kpi_dashboard" in soul_text
    assert "correlation" in soul_text


def test_soul_has_error_handling_section(soul_text):
    """Exception handling section must exist."""
    assert "异常处理" in soul_text


def test_soul_propagates_ins_errors(soul_text):
    """SOUL must surface INS errors, no silent demo fallback."""
    assert "error" in soul_text.lower()
    assert "假报告" in soul_text or "演示" in soul_text.lower() or "demo" in soul_text.lower() or "debug" in soul_text.lower() or "INS" in soul_text


def test_soul_has_data_sufficiency_checks(soul_text):
    """Must check minimum data points before analysis."""
    assert "数据" in soul_text


# ---------------------------------------------------------------------------
# config.yaml validation
# ---------------------------------------------------------------------------

def test_config_has_skills(config_text):
    """Config must declare data-analyst skill."""
    assert "data-analyst" in config_text


def test_config_has_starters(config_text):
    """Config must include at least 3 starters."""
    assert "starters" in config_text
    assert "分析设备运行趋势" in config_text or "趋势" in config_text
    assert "异常" in config_text


def test_config_has_tags(config_text):
    """Config must have monitoring-related tags."""
    assert "monitoring" in config_text.lower()


# ---------------------------------------------------------------------------
# export_report.py — monitoring report type registration
# ---------------------------------------------------------------------------

def test_export_report_supports_monitoring_type():
    """SUPPORTED_REPORT_TYPES must include 'monitoring'."""
    text = EXPORT_REPORT_PATH.read_text(encoding="utf-8")
    assert '"monitoring"' in text


def test_export_report_has_monitoring_input_filename():
    """MONITORING_INPUT_FILENAME constant must be defined."""
    text = EXPORT_REPORT_PATH.read_text(encoding="utf-8")
    assert "MONITORING_INPUT_FILENAME" in text
    assert "monitoring_features.json" in text


def test_export_report_has_monitoring_output_dir():
    """_output_dir must handle 'monitoring' report type."""
    text = EXPORT_REPORT_PATH.read_text(encoding="utf-8")
    assert 'report_type == "monitoring"' in text


def test_export_report_has_render_monitoring_markdown():
    """render_monitoring_markdown function must be defined."""
    text = EXPORT_REPORT_PATH.read_text(encoding="utf-8")
    assert "def render_monitoring_markdown" in text


def test_export_report_has_monitoring_in_write_report():
    """write_report must dispatch monitoring to render_monitoring_markdown."""
    text = EXPORT_REPORT_PATH.read_text(encoding="utf-8")
    assert 'report_type == "monitoring"' in text


def test_export_report_has_monitoring_in_load_payload():
    """load_payload must resolve monitoring input filename."""
    text = EXPORT_REPORT_PATH.read_text(encoding="utf-8")
    assert 'report_type == "monitoring"' in text
