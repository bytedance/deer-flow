"""Unit tests for report_templates.generic_renderer — render_markdown_generic."""

from __future__ import annotations

import pytest

from deerflow.report_templates.generic_renderer import (
    REPORT_PAYLOAD_SCHEMA_VERSION,
    RenderError,
    render_markdown_generic,
)


def _payload(*sections, title: str = "Test", **extras) -> dict:
    base = {
        "schema_version": REPORT_PAYLOAD_SCHEMA_VERSION,
        "title": title,
        "sections": list(sections),
    }
    base.update(extras)
    return base


class TestSchemaValidation:
    def test_rejects_non_dict(self):
        with pytest.raises(RenderError, match="dict"):
            render_markdown_generic("not a dict")  # type: ignore[arg-type]

    def test_rejects_wrong_schema_version(self):
        with pytest.raises(RenderError, match="schema_version"):
            payload = _payload()
            payload["schema_version"] = "999"
            render_markdown_generic(payload)

    def test_rejects_missing_sections(self):
        with pytest.raises(RenderError, match="sections"):
            render_markdown_generic({"schema_version": "1", "title": "x"})

    def test_rejects_non_dict_section(self):
        with pytest.raises(RenderError, match="must be a dict"):
            render_markdown_generic(_payload("not a section"))

    def test_rejects_unknown_component(self):
        with pytest.raises(RenderError, match="not supported"):
            render_markdown_generic(
                _payload({"component": "weird_thing", "title": "x", "props": {}})
            )


class TestMarkdownSection:
    def test_renders_string_content(self):
        out = render_markdown_generic(
            _payload({"component": "markdown", "title": "总览", "props": {"content": "hello"}})
        )
        assert "# Test" in out
        assert "## 总览" in out
        assert "hello" in out

    def test_renders_list_content(self):
        out = render_markdown_generic(
            _payload(
                {
                    "component": "markdown",
                    "title": "建议",
                    "props": {"content": ["item 1", "item 2"]},
                }
            )
        )
        assert "item 1" in out
        assert "item 2" in out

    def test_escapes_html_in_content(self):
        out = render_markdown_generic(
            _payload(
                {"component": "markdown", "title": "x", "props": {"content": "<script>x</script>"}}
            )
        )
        assert "<script>" not in out
        assert "&lt;script&gt;" in out


class TestTableSection:
    def test_renders_columns_and_data(self):
        out = render_markdown_generic(
            _payload(
                {
                    "component": "table",
                    "title": "异常",
                    "props": {
                        "columns": ["设备", "等级"],
                        "data": [["P-001", "高"], ["P-002", "中"]],
                    },
                }
            )
        )
        assert "| 设备 | 等级 |" in out
        assert "| --- | --- |" in out
        assert "| P-001 | 高 |" in out
        assert "| P-002 | 中 |" in out

    def test_renders_rows_short_form(self):
        out = render_markdown_generic(
            _payload(
                {
                    "component": "table",
                    "title": "x",
                    "props": {"rows": [{"a": 1, "b": 2}, {"a": 3, "b": 4}]},
                }
            )
        )
        assert "| a | b |" in out
        assert "| 1 | 2 |" in out

    def test_empty_table(self):
        out = render_markdown_generic(
            _payload({"component": "table", "title": "x", "props": {"columns": [], "data": []}})
        )
        assert "_(empty table)_" in out

    def test_rejects_malformed_row(self):
        with pytest.raises(RenderError, match="row"):
            render_markdown_generic(
                _payload(
                    {
                        "component": "table",
                        "title": "x",
                        "props": {"columns": ["a"], "data": ["not a list"]},
                    }
                )
            )


class TestCardSection:
    def test_single_card(self):
        out = render_markdown_generic(
            _payload(
                {
                    "component": "card",
                    "title": "KPI",
                    "props": {"title": "运行率", "value": "99.8%", "description": "vs 昨日 +0.2"},
                }
            )
        )
        assert "**运行率**" in out
        assert "99.8%" in out
        assert "vs 昨日 +0.2" in out

    def test_card_group(self):
        out = render_markdown_generic(
            _payload(
                {
                    "component": "card_group",
                    "title": "KPIs",
                    "props": {
                        "items": [
                            {"title": "k1", "value": "1"},
                            {"title": "k2", "value": "2"},
                        ]
                    },
                }
            )
        )
        assert "**k1**" in out
        assert "**k2**" in out


class TestEchartSection:
    def test_renders_chart_type_placeholder(self):
        out = render_markdown_generic(
            _payload(
                {
                    "component": "echart",
                    "title": "趋势",
                    "props": {"option": {"series": [{"type": "line", "data": [1, 2, 3]}]}},
                }
            )
        )
        assert "echart chart: line" in out

    def test_unknown_chart_falls_back_to_generic(self):
        out = render_markdown_generic(
            _payload({"component": "echart", "title": "趋势", "props": {"option": {}}})
        )
        assert "[echart chart]" in out


class TestImageSection:
    def test_renders_image(self):
        out = render_markdown_generic(
            _payload(
                {
                    "component": "image",
                    "title": "示意",
                    "props": {"alt": "示意图", "src": "https://example.com/x.png"},
                }
            )
        )
        assert "![示意图](https://example.com/x.png)" in out

    def test_missing_src(self):
        out = render_markdown_generic(
            _payload({"component": "image", "title": "x", "props": {"alt": "x"}})
        )
        assert "image missing src" in out


class TestMetadata:
    def test_renders_template_and_run_metadata(self):
        out = render_markdown_generic(
            _payload(
                {"component": "markdown", "title": "x", "props": {"content": "x"}},
                template={"id": "tpl_1", "version": 3, "name": "daily"},
                run={"id": "rr_1", "thread_id": "t1", "generated_at": "2026-05-18T10:00:00+08:00"},
            )
        )
        assert "`daily` v3" in out
        assert "2026-05-18T10:00:00+08:00" in out

    def test_skips_metadata_when_missing(self):
        out = render_markdown_generic(
            _payload({"component": "markdown", "title": "x", "props": {"content": "x"}})
        )
        # No "模板" line when metadata absent.
        assert "模板：" not in out


class TestDailyReportShape:
    """Smoke test resembling §5.2 daily-equipment payload sections."""

    def test_full_daily_report_renders(self):
        payload = _payload(
            {
                "component": "markdown",
                "title": "总览",
                "props": {"content": "今日运行正常"},
            },
            {
                "component": "card_group",
                "title": "核心 KPI",
                "props": {
                    "items": [
                        {"title": "运行率", "value": "99.8%"},
                        {"title": "告警数", "value": "3"},
                    ]
                },
            },
            {
                "component": "echart",
                "title": "趋势图",
                "props": {"option": {"series": [{"type": "line", "data": [1, 2, 3]}]}},
            },
            {
                "component": "table",
                "title": "异常排行",
                "props": {
                    "columns": ["设备", "得分"],
                    "data": [["P-001", "8.7"], ["P-002", "7.4"]],
                },
            },
            {
                "component": "markdown",
                "title": "建议",
                "props": {"content": ["关注 P-001 振动", "增加 P-002 巡检"]},
            },
            title="重点机泵日报",
            template={"id": "tpl_x", "version": 1, "name": "equipment_daily"},
            run={"id": "rr_x", "thread_id": "th", "generated_at": "2026-05-18T10:00:00+08:00"},
        )
        out = render_markdown_generic(payload)
        # Section ordering preserved.
        idx_overview = out.index("总览")
        idx_kpi = out.index("核心 KPI")
        idx_trend = out.index("趋势图")
        idx_anom = out.index("异常排行")
        idx_advice = out.index("建议")
        assert idx_overview < idx_kpi < idx_trend < idx_anom < idx_advice
        # Trailing newline contract.
        assert out.endswith("\n")
