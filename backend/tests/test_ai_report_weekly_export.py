"""Tests for the weekly export branch in
skills/custom/data-analyst/scripts/export_report.py.

Key contracts:
- ``report_type="daily"`` is the default and behaves exactly as before
  (covered by test_ai_report_daily_export.py).
- ``report_type="weekly"`` writes ``weekly_report.{md,pdf}`` and uses
  ``render_weekly_markdown`` / ``render_weekly_html``.
- Weekly Markdown contains the seven required sections.
- PDF degrades to ``ImportError`` when weasyprint is missing — the SOUL
  layer is responsible for catching that.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
EXPORT_PATH = REPO_ROOT / "skills" / "custom" / "data-analyst" / "scripts" / "export_report.py"


def _load_export():
    spec = importlib.util.spec_from_file_location("export_report", EXPORT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def export_report(tmp_path, monkeypatch):
    monkeypatch.setenv("WEEKLY_REPORT_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setenv("DAILY_REPORT_OUTPUT_DIR", str(tmp_path))
    return _load_export()


def _weekly_payload(*, with_alarms: bool = True, demo: bool = True, compare: bool = True):
    payload = {
        "report_period": {"week_start": "2026-05-11", "week_end": "2026-05-17", "day_count": 7},
        "compare_type": "previous_week" if compare else "none",
        "compare_period": {"start": "2026-05-04", "end": "2026-05-10"} if compare else None,
        "overall_status": {"level": "warning", "summary": "本周运行率 93.2%，较上周提升 2.2pp。"},
        "kpi_summary": [
            {
                "key": "runtime_rate",
                "name": "运行率",
                "unit": "%",
                "current_mean": 0.932,
                "current_peak": 0.96,
                "current_trough": 0.895,
                "current_volatility": 0.022,
                "previous_mean": 0.91 if compare else None,
                "delta_mean": 0.022 if compare else None,
                "delta_pct": 0.024 if compare else None,
                "direction": "up" if compare else "flat",
                "better_when_higher": True,
            },
        ],
        "daily_trend_chart": {
            "title": {"text": "本周日趋势"},
            "tooltip": {"trigger": "axis"},
            "legend": {"data": ["运行率"], "selected": {"运行率": True}},
            "xAxis": {"type": "category", "data": [f"05-{11 + i:02d} 周{w}" for i, w in enumerate("一二三四五六日")]},
            "yAxis": [{"type": "value", "name": "%"}],
            "series": [{"name": "运行率", "type": "line", "yAxisIndex": 0, "data": [0.92, 0.94, 0.93, 0.91, 0.96, 0.95, 0.89]}],
        },
        "anomaly_top_n": [
            {"equipment": "RM-002", "level": "critical", "count": 3, "latest_time": "2026-05-16 10:22:08", "dominant_message": "轴承温度超限"},
        ] if with_alarms else [],
        "alarm_table": [
            {"time": "2026-05-13 14:02", "equipment": "RM-002", "level": "critical", "message": "轴承温度超限"},
        ] if with_alarms else [],
        "next_week_focus": ["RM-002 轴承温度持续异常,建议安排诊断"],
        "data_source": "demo_fallback" if demo else "ins",
        "week_start_warning": None,
        "compare_warning": None,
    }
    return payload


def test_render_weekly_markdown_has_seven_sections(export_report):
    md = export_report.render_weekly_markdown(_weekly_payload())
    # Heading + 6 sub-sections = 7 lines starting with '## ' or '# '.
    assert "# 设备运行周报" in md
    for section in ("## 本周概览", "## 周 KPI", "## 日趋势", "## 异常 TopN", "## 告警流水", "## 下周关注"):
        assert section in md, f"missing section: {section}"


def test_weekly_markdown_demo_banner(export_report):
    md = export_report.render_weekly_markdown(_weekly_payload(demo=True))
    assert "演示数据" in md
    md2 = export_report.render_weekly_markdown(_weekly_payload(demo=False))
    assert "演示数据" not in md2


def test_weekly_markdown_kpi_table_uses_weekly_headers(export_report):
    md = export_report.render_weekly_markdown(_weekly_payload())
    # The weekly KPI table must distinguish itself from daily ("当前/上一周期")
    assert "周均值" in md
    assert "周峰值" in md
    assert "波动率" in md
    assert "周环比" in md


def test_weekly_markdown_no_compare_handles_dashes(export_report):
    md = export_report.render_weekly_markdown(_weekly_payload(compare=False))
    # When no compare, previous_mean / delta are None → should render '—'
    assert "—" in md


def test_weekly_markdown_no_alarms_message(export_report):
    md = export_report.render_weekly_markdown(_weekly_payload(with_alarms=False))
    assert "本周无告警事件" in md


def test_write_report_weekly_writes_correct_filename(export_report, tmp_path):
    payload = _weekly_payload()
    out = export_report.write_report(payload, "md", report_type="weekly")
    assert out.name == "weekly_report.md"
    assert out.parent == tmp_path
    body = out.read_text(encoding="utf-8")
    assert body.startswith("> ⚠️ 当前使用演示数据（fallback）。原因：未配置真实数据源（DEER_FLOW_DATA_PROVIDER 未设置为 ins）")
    assert "\n\n# 设备运行周报\n" in body


def test_write_report_daily_default_unchanged(export_report, tmp_path):
    """Calling write_report with no report_type must keep daily filename."""
    daily_payload = {
        "report_date": "2026-05-13",
        "equipment_ids": ["E001"],
        "compare_type": "none",
        "overall_status": {"level": "ok", "summary": ""},
        "kpi_summary": [],
        "trend_chart": {},
        "alarm_table": [],
        "recommendations": [],
        "aggregation_mode": "detail",
    }
    out = export_report.write_report(daily_payload, "md")
    assert out.name == "daily_report.md"


def test_build_export_result_weekly(export_report):
    result = export_report.build_export_result(_weekly_payload(), "md", report_type="weekly")
    assert result["filename"] == "weekly_report.md"
    assert result["present_files_hint"] == ["/mnt/user-data/outputs/weekly_report.md"]


def test_write_report_weekly_pdf_without_weasyprint(export_report, monkeypatch, tmp_path):
    """Weekly PDF must raise ImportError when weasyprint is missing; SOUL handles fallback."""
    import sys as _sys
    monkeypatch.setitem(_sys.modules, "weasyprint", None)
    with pytest.raises(ImportError):
        export_report.write_report(_weekly_payload(), "pdf", report_type="weekly")


def test_write_report_rejects_bad_report_type(export_report):
    with pytest.raises(ValueError):
        export_report.write_report(_weekly_payload(), "md", report_type="quarterly")


def test_load_payload_weekly_reads_weekly_kpi_json(export_report, tmp_path):
    weekly_file = tmp_path / "weekly_kpi.json"
    weekly_file.write_text(json.dumps({"hello": "weekly"}), encoding="utf-8")
    daily_file = tmp_path / "daily_kpi.json"
    daily_file.write_text(json.dumps({"hello": "daily"}), encoding="utf-8")
    loaded = export_report.load_payload(report_type="weekly")
    assert loaded == {"hello": "weekly"}


def test_load_payload_daily_default_unchanged(export_report, tmp_path):
    daily_file = tmp_path / "daily_kpi.json"
    daily_file.write_text(json.dumps({"hello": "daily"}), encoding="utf-8")
    loaded = export_report.load_payload()
    assert loaded == {"hello": "daily"}


def test_main_weekly_writes_md(export_report, tmp_path, capsys, monkeypatch):
    weekly_file = tmp_path / "weekly_kpi.json"
    weekly_file.write_text(json.dumps(_weekly_payload()), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["export_report.py", "--report-type", "weekly"])
    rc = export_report.main()
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["filename"] == "weekly_report.md"
    md_path = tmp_path / "weekly_report.md"
    assert md_path.exists()
    md = md_path.read_text(encoding="utf-8")
    assert "# 设备运行周报" in md
    assert "## 下周关注" in md


def test_main_daily_default_unchanged(export_report, tmp_path, capsys, monkeypatch):
    """Backwards compatibility: bare --input with no --report-type stays daily."""
    daily_payload = {
        "report_date": "2026-05-13",
        "equipment_ids": ["E001"],
        "compare_type": "none",
        "overall_status": {"level": "ok", "summary": ""},
        "kpi_summary": [],
        "trend_chart": {},
        "alarm_table": [],
        "recommendations": ["保持现状"],
        "aggregation_mode": "detail",
    }
    daily_file = tmp_path / "daily_kpi.json"
    daily_file.write_text(json.dumps(daily_payload), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["export_report.py"])
    rc = export_report.main()
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["filename"] == "daily_report.md"


def test_render_weekly_html_wraps_markdown(export_report):
    html = export_report.render_weekly_html(_weekly_payload())
    assert html.startswith("<!DOCTYPE html>")
    assert "设备运行周报" in html


def test_weekly_markdown_compare_warning_surface(export_report):
    payload = _weekly_payload(compare=True)
    payload["compare_type"] = "previous_year"
    payload["compare_warning"] = "去年同期数据不可用"
    md = export_report.render_weekly_markdown(payload)
    assert "去年同期数据不可用" in md
