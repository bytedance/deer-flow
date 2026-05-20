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
    body = out_path.read_text(encoding="utf-8")
    assert body.startswith("> ⚠️ 当前使用演示数据（fallback）。原因：未配置真实数据源（DEER_FLOW_DATA_PROVIDER 未设置为 ins）")
    assert "\n\n# 设备运行日报\n" in body


def test_export_result_contract(export_report, kpi_payload, tmp_path):
    result = export_report.build_export_result(kpi_payload, "md")
    assert result["format"] == "md"
    assert result["filename"] == "daily_report.md"
    assert result["path"].endswith("daily_report.md")
    assert result["artifact_path"] == str(tmp_path / "daily_report.md")


def test_rejects_unsupported_format(export_report, kpi_payload):
    with pytest.raises(ValueError, match="Unsupported export format"):
        export_report.write_report(kpi_payload, "docx")


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


# --- PDF export tests ---


def test_pdf_format_accepted(export_report, kpi_payload, tmp_path, monkeypatch):
    """PDF format is in SUPPORTED_FORMATS and render_html produces valid HTML."""
    assert "pdf" in export_report.SUPPORTED_FORMATS
    html = export_report.render_html(kpi_payload)
    assert "<!DOCTYPE html>" in html
    assert "<body>" in html
    assert "KPI" in html


def test_pdf_export_without_weasyprint(export_report, kpi_payload, monkeypatch):
    """When weasyprint is not importable, write_report raises ImportError."""
    import builtins
    real_import = builtins.__import__

    def block_weasyprint(name, *args, **kwargs):
        if name == "weasyprint":
            raise ImportError("no weasyprint")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", block_weasyprint)
    with pytest.raises(ImportError, match="weasyprint"):
        export_report.write_report(kpi_payload, "pdf")


def test_render_html_escapes_special_chars(export_report):
    payload = {
        "report_date": "2026-05-14",
        "equipment_ids": ["E<1>"],
        "overall_status": {"level": "ok", "summary": "正常"},
        "kpi_summary": [],
        "alarm_table": [],
        "recommendations": [],
    }
    html = export_report.render_html(payload)
    assert "<script" not in html


# --- present_files_hint tests ---


def test_export_result_has_present_files_hint(export_report, kpi_payload, tmp_path):
    result = export_report.build_export_result(kpi_payload, "md")
    assert "present_files_hint" in result
    assert result["present_files_hint"] == ["/mnt/user-data/outputs/daily_report.md"]


def test_export_result_pdf_hint(export_report, kpi_payload, tmp_path, monkeypatch):
    """present_files_hint uses the correct extension for PDF."""
    import builtins
    real_import = builtins.__import__

    class FakeHTML:
        def __init__(self, string=None):
            pass
        def write_pdf(self, target):
            from pathlib import Path
            Path(target).write_bytes(b"%PDF-fake")

    def mock_import(name, *args, **kwargs):
        if name == "weasyprint":
            import types
            mod = types.ModuleType("weasyprint")
            mod.HTML = FakeHTML
            return mod
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", mock_import)
    result = export_report.build_export_result(kpi_payload, "pdf")
    assert result["present_files_hint"] == ["/mnt/user-data/outputs/daily_report.pdf"]
    assert result["filename"] == "daily_report.pdf"


# --- Chart image embedding tests ---


def test_render_markdown_with_chart_images(export_report, kpi_payload, tmp_path):
    img = tmp_path / "chart_001.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20)
    markdown = export_report.render_markdown(kpi_payload, chart_images=[str(img)])
    assert "## 运行趋势" in markdown
    assert "data:image/png;base64," in markdown
    assert "趋势图1" in markdown


def test_render_markdown_with_multiple_chart_images(export_report, kpi_payload, tmp_path):
    img1 = tmp_path / "chart_001.png"
    img2 = tmp_path / "chart_002.png"
    img1.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20)
    img2.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20)
    markdown = export_report.render_markdown(kpi_payload, chart_images=[str(img1), str(img2)])
    assert "趋势图1" in markdown
    assert "趋势图2" in markdown
    assert markdown.count("data:image/png;base64,") == 2


def test_render_markdown_no_chart_images(export_report, kpi_payload):
    markdown = export_report.render_markdown(kpi_payload)
    assert "## 运行趋势" not in markdown


def test_render_markdown_empty_chart_images(export_report, kpi_payload):
    markdown = export_report.render_markdown(kpi_payload, chart_images=[])
    assert "## 运行趋势" not in markdown


def test_render_html_with_chart_images(export_report, kpi_payload, tmp_path):
    img = tmp_path / "chart_001.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20)
    html = export_report.render_html(kpi_payload, chart_images=[str(img)])
    assert "data:image/png;base64," in html
    assert "<!DOCTYPE html>" in html


def test_write_report_with_chart_images(export_report, kpi_payload, tmp_path):
    img = tmp_path / "chart_001.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20)
    out_path = export_report.write_report(kpi_payload, "md", chart_images=[str(img)])
    content = out_path.read_text(encoding="utf-8")
    assert "## 运行趋势" in content
    assert "data:image/png;base64," in content


def test_build_export_result_with_chart_images(export_report, kpi_payload, tmp_path):
    img = tmp_path / "chart_001.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20)
    result = export_report.build_export_result(kpi_payload, "md", chart_images=[str(img)])
    assert result["format"] == "md"
    content = Path(result["path"]).read_text(encoding="utf-8")
    assert "data:image/png;base64," in content


# --- SVG trend chart fallback tests ---


@pytest.fixture()
def trend_chart_option():
    """A realistic ECharts line-chart option with two series."""
    return {
        "title": {"text": "24h 振动趋势"},
        "xAxis": {"data": [f"{h:02d}:00" for h in range(24)]},
        "yAxis": {"name": "mm/s"},
        "series": [
            {
                "name": "X轴振动",
                "data": [0.12, 0.15, 0.14, 0.13, 0.16, 0.18, 0.22, 0.25,
                         0.30, 0.28, 0.26, 0.24, 0.23, 0.21, 0.20, 0.19,
                         0.18, 0.17, 0.16, 0.15, 0.14, 0.13, 0.12, 0.11],
            },
            {
                "name": "Y轴振动",
                "data": [0.08, 0.09, 0.10, 0.11, 0.12, 0.14, 0.16, 0.18,
                         0.20, 0.19, 0.17, 0.15, 0.14, 0.13, 0.12, 0.11,
                         0.10, 0.09, 0.08, 0.08, 0.07, 0.07, 0.06, 0.06],
            },
        ],
    }


def test_svg_basic_structure(export_report, trend_chart_option):
    svg = export_report.trend_chart_to_svg(trend_chart_option)
    assert svg.startswith("<svg")
    assert svg.endswith("</svg>")
    assert 'xmlns="http://www.w3.org/2000/svg"' in svg


def test_svg_contains_title(export_report, trend_chart_option):
    svg = export_report.trend_chart_to_svg(trend_chart_option)
    assert "24h 振动趋势" in svg


def test_svg_contains_y_axis_name(export_report, trend_chart_option):
    svg = export_report.trend_chart_to_svg(trend_chart_option)
    assert "mm/s" in svg


def test_svg_contains_polylines(export_report, trend_chart_option):
    svg = export_report.trend_chart_to_svg(trend_chart_option)
    assert "<polyline" in svg
    assert svg.count("<polyline") >= 2


def test_svg_contains_legend(export_report, trend_chart_option):
    svg = export_report.trend_chart_to_svg(trend_chart_option)
    assert "X轴振动" in svg
    assert "Y轴振动" in svg


def test_svg_contains_x_labels(export_report, trend_chart_option):
    svg = export_report.trend_chart_to_svg(trend_chart_option)
    assert "00:00" in svg
    assert "23:00" in svg


def test_svg_empty_series_returns_empty(export_report):
    chart = {"series": []}
    assert export_report.trend_chart_to_svg(chart) == ""


def test_svg_no_series_key_returns_empty(export_report):
    chart = {"title": {"text": "Empty"}}
    assert export_report.trend_chart_to_svg(chart) == ""


def test_svg_all_none_data_returns_empty(export_report):
    chart = {"series": [{"name": "test", "data": [None, None, None]}]}
    assert export_report.trend_chart_to_svg(chart) == ""


def test_svg_handles_none_gaps(export_report):
    chart = {
        "series": [{
            "name": "gapped",
            "data": [1.0, 2.0, None, None, 3.0, 4.0],
        }],
    }
    svg = export_report.trend_chart_to_svg(chart)
    assert "<polyline" in svg
    assert svg.count("<polyline") == 2


def test_svg_single_point_renders_circle(export_report):
    chart = {
        "series": [{
            "name": "single",
            "data": [None, None, 5.0, None, None],
        }],
    }
    svg = export_report.trend_chart_to_svg(chart)
    assert "<circle" in svg


def test_svg_dashed_line_style(export_report):
    chart = {
        "series": [{
            "name": "threshold",
            "lineStyle": {"type": "dashed"},
            "data": [1.0, 1.0, 1.0, 1.0],
        }],
    }
    svg = export_report.trend_chart_to_svg(chart)
    assert 'stroke-dasharray="6,3"' in svg


def test_svg_escapes_special_chars(export_report):
    chart = {
        "title": {"text": "Temperature <high> & \"alert\""},
        "series": [{"name": "T<1>", "data": [1.0, 2.0]}],
    }
    svg = export_report.trend_chart_to_svg(chart)
    assert "&lt;high&gt;" in svg
    assert "&amp;" in svg
    assert "&quot;alert&quot;" in svg
    assert "T&lt;1&gt;" in svg


def test_svg_flat_line_handled(export_report):
    """When all values are identical, y_min != y_max after adjustment."""
    chart = {
        "series": [{"name": "flat", "data": [5.0, 5.0, 5.0, 5.0]}],
    }
    svg = export_report.trend_chart_to_svg(chart)
    assert "<polyline" in svg


def test_markdown_fallback_uses_svg_when_no_images(export_report, kpi_payload, trend_chart_option):
    payload = {**kpi_payload, "trend_chart": trend_chart_option}
    markdown = export_report.render_markdown(payload)
    assert "## 运行趋势" in markdown
    assert "data:image/svg+xml;base64," in markdown


def test_markdown_prefers_chart_images_over_svg(export_report, kpi_payload, trend_chart_option, tmp_path):
    img = tmp_path / "chart_001.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20)
    payload = {**kpi_payload, "trend_chart": trend_chart_option}
    markdown = export_report.render_markdown(payload, chart_images=[str(img)])
    assert "data:image/png;base64," in markdown
    assert "data:image/svg+xml;base64," not in markdown


def test_html_fallback_uses_svg_when_no_images(export_report, kpi_payload, trend_chart_option):
    payload = {**kpi_payload, "trend_chart": trend_chart_option}
    html = export_report.render_html(payload)
    assert "运行趋势" in html
    assert "<svg" in html or "data:image/svg+xml;base64," in html
