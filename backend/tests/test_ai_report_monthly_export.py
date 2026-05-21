"""Tests for monthly export path in skills/custom/data-analyst/scripts/export_report.py.

Covers sprint plan M3/M7 acceptance items:
- write_report(report_type='monthly') writes monthly_report.{md,pdf} filenames
- write_report() with default report_type still produces daily_report (zero regression)
- write_report(report_type='weekly') still produces weekly_report (zero regression)
- render_monthly_markdown emits all 8 numbered section headings
- render_monthly_markdown contains "口径说明" reference block inside section 2 (Fix #F)
- render_monthly_markdown is insensitive to STALE summary_markdown injection (Fix #7)
- monthly Markdown contains conditional sections only when data is non-empty
"""

from __future__ import annotations

import importlib.util
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
    monkeypatch.setenv("MONTHLY_REPORT_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setenv("WEEKLY_REPORT_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setenv("DAILY_REPORT_OUTPUT_DIR", str(tmp_path))
    return _load_module()


def _monthly_payload(**overrides) -> dict:
    """Build a minimal monthly_kpi.json-shaped payload."""
    payload = {
        "report_period": {
            "report_month": "2026-04",
            "month_start": "2026-04-01",
            "month_end": "2026-04-30",
            "day_count": 30,
        },
        "compare_types": ["previous_month"],
        "compare_periods": {"previous_month": {"start": "2026-03-01", "end": "2026-03-31"}},
        "overall_status": {"level": "good", "summary": "本月运行平稳。"},
        "kpi_summary": [
            {
                "key": "runtime_rate", "name": "运行率", "unit": "%",
                "current_mean": 0.93, "current_peak": 0.97, "current_trough": 0.85, "current_volatility": 0.025,
                "current_in_target_ratio": 0.83,
                "previous_month_mean": 0.91, "delta_mom": 0.02, "delta_mom_pct": 0.022, "direction_mom": "up",
                "previous_year_month_mean": None, "delta_yoy": None, "delta_yoy_pct": None, "direction_yoy": "flat",
                "better_when_higher": True,
            },
        ],
        "weekly_trend_chart": {
            "title": {"text": "周维度趋势"},
            "tooltip": {"trigger": "axis"},
            "legend": {"data": ["运行率"]},
            "xAxis": {"type": "category", "data": ["W1: 04-01~04-07", "W2: 04-08~04-14"]},
            "yAxis": [{"type": "value"}],
            "series": [{"name": "运行率", "type": "line", "data": [0.92, 0.94]}],
        },
        "anomaly_top_n": [
            {"equipment": "RM-001", "level": "warning", "count": 5, "latest_time": "2026-04-26 10:00", "dominant_message": "振动"},
        ],
        "critical_events": [],
        "improvement_tracking": [],
        "monthly_review": "本月整体平稳。",
        "next_month_plan": ["保持当前节奏"],
        "data_source": "ins",
    }
    payload.update(overrides)
    return payload


def test_supported_report_types_includes_monthly(export_report):
    assert "monthly" in export_report.SUPPORTED_REPORT_TYPES
    assert "weekly" in export_report.SUPPORTED_REPORT_TYPES
    assert "daily" in export_report.SUPPORTED_REPORT_TYPES


def test_monthly_input_filename_constant(export_report):
    assert export_report.MONTHLY_INPUT_FILENAME == "monthly_kpi.json"


def test_write_report_monthly_filename(export_report, tmp_path):
    out = export_report.write_report(_monthly_payload(), "md", report_type="monthly")
    assert out.name == "monthly_report.md"
    assert out.exists()
    content = out.read_text(encoding="utf-8")
    assert "设备运行月报" in content


def test_render_monthly_markdown_has_8_sections(export_report):
    """All 8 numbered section headings (conditional ones present when data is)."""
    payload = _monthly_payload()
    # Populate critical_events + improvement_tracking so sections 5 and 7 render
    payload["critical_events"] = [
        {"time": "2026-04-17 14:02", "equipment": "RM-002", "level": "critical", "message": "x", "duration_minutes": 90, "resolved": True}
    ]
    payload["improvement_tracking"] = [
        {"id": "IMP-1", "owner": "X", "plan": "p", "due_date": "2026-04-15", "status": "done", "completion_rate": 100, "note": ""}
    ]
    md = export_report.render_monthly_markdown(payload)
    for heading in [
        "## 1. 月度总览",
        "## 2. 月 KPI",
        "## 3. 周维度趋势",
        "## 4. 异常 TopN",
        "## 5. 重大事件回顾",
        "## 6. 月环比 + 同比",
        "## 7. 改进措施跟踪",
        "## 8. 下月计划",
    ]:
        assert heading in md, f"missing heading: {heading}"


def test_render_monthly_markdown_skips_empty_critical_events(export_report):
    payload = _monthly_payload()
    payload["critical_events"] = []
    payload["improvement_tracking"] = []
    md = export_report.render_monthly_markdown(payload)
    assert "## 5. 重大事件回顾" not in md
    assert "## 7. 改进措施跟踪" not in md


def test_render_monthly_markdown_caliber_note_in_section_2(export_report):
    """Fix #F: ``口径说明`` is a quote block inside section 2, NOT a separate chapter."""
    md = export_report.render_monthly_markdown(_monthly_payload())
    assert "口径说明" in md
    # Should not be a standalone chapter — no "## 口径说明" heading.
    assert "## 口径说明" not in md, "口径说明 must be a quote block, not a separate section"
    # Should appear inside section 2 (Month KPI) — check ordering.
    section_2_pos = md.find("## 2. 月 KPI")
    caliber_pos = md.find("口径说明")
    section_3_pos = md.find("## 3. 周维度趋势")
    assert section_2_pos < caliber_pos < section_3_pos, "口径说明 must sit between section 2 and section 3"


def test_render_monthly_markdown_ignores_summary_markdown_injection(export_report):
    """Fix #7 / sprint plan M7: render_monthly_markdown must NOT consult summary_markdown."""
    payload = _monthly_payload()
    payload["summary_markdown"] = "STALE-MUST-NOT-APPEAR"
    md = export_report.render_monthly_markdown(payload)
    assert "STALE-MUST-NOT-APPEAR" not in md


def test_monthly_markdown_no_demo_banner(export_report):
    """After demo removal, the monthly markdown never contains demo banner text."""
    md = export_report.render_monthly_markdown(_monthly_payload())
    assert "演示数据" not in md


def test_write_report_default_daily_no_regression(export_report, tmp_path):
    """write_report() without report_type still writes daily_report.md (legacy contract)."""
    daily_payload = {
        "report_date": "2026-04-01",
        "compare_type": "none",
        "overall_status": {"level": "good", "summary": "ok"},
        "kpi_summary": [],
        "trend_chart": {},
        "alarm_table": [],
        "recommendations": [],
    }
    out = export_report.write_report(daily_payload, "md")
    assert out.name == "daily_report.md"
    assert out.exists()


def test_write_report_weekly_no_regression(export_report, tmp_path):
    """report_type='weekly' still produces weekly_report.md (legacy contract)."""
    weekly_payload = {
        "report_period": {"week_start": "2026-04-06", "week_end": "2026-04-12", "day_count": 7},
        "compare_type": "previous_week",
        "compare_period": None,
        "overall_status": {"level": "good", "summary": "本周平稳"},
        "kpi_summary": [],
        "daily_trend_chart": {},
        "anomaly_top_n": [],
        "alarm_table": [],
        "next_week_focus": ["保持节奏"],
        "data_source": "ins",
    }
    out = export_report.write_report(weekly_payload, "md", report_type="weekly")
    assert out.name == "weekly_report.md"
    assert out.exists()


def test_compare_warning_surfaced_in_markdown(export_report):
    payload = _monthly_payload()
    payload["compare_warning"] = "去年同期数据不可用，已跳过同比"
    md = export_report.render_monthly_markdown(payload)
    assert "去年同期数据不可用" in md


def test_unsupported_report_type_rejected(export_report):
    with pytest.raises(ValueError, match="Unsupported report type"):
        export_report.write_report(_monthly_payload(), "md", report_type="quarterly")
