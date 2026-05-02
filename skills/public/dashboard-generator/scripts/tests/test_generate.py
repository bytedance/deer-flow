"""Tests for dashboard-generator/scripts/generate.py."""

import json
import os
import sys

import duckdb
import pytest

# Make the parent directory importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from generate import (
    THEMES,
    _safe_float,
    build_echarts_option,
    esc,
    format_kpi_value,
    generate_html,
    load_data,
    render_echarts_option,
    sanitize_identifier,
    validate_path,
)


# ---------------------------------------------------------------------------
# Security helpers
# ---------------------------------------------------------------------------


class TestValidatePath:
    def test_rejects_system_paths(self):
        with pytest.raises(ValueError, match="outside allowed"):
            validate_path("/etc/passwd")

    def test_allows_relative_path(self):
        # A file that exists relative to CWD should be allowed
        result = validate_path("generate.py", "test file")
        assert result == "generate.py"


class TestSanitizeIdentifier:
    def test_strips_special_chars(self):
        assert sanitize_identifier("hello world!") == "hello_world_"

    def test_preserves_alphanumeric(self):
        assert sanitize_identifier("table_123") == "table_123"

    def test_handles_unicode(self):
        result = sanitize_identifier("数据表")
        assert all(c == "_" or c.isalnum() for c in result)


class TestEsc:
    def test_escapes_html(self):
        assert esc("<script>alert(1)</script>") == "&lt;script&gt;alert(1)&lt;/script&gt;"

    def test_escapes_quotes(self):
        assert esc('"hello"') == "&quot;hello&quot;"

    def test_handles_none(self):
        result = esc(None)
        assert result == "None"


# ---------------------------------------------------------------------------
# KPI formatting
# ---------------------------------------------------------------------------


class TestFormatKpiValue:
    def test_none_returns_na(self):
        assert format_kpi_value(None, "number") == "N/A"

    def test_currency(self):
        assert format_kpi_value(1234.5, "currency") == "$1,234.50"

    def test_percent(self):
        assert format_kpi_value(85.3, "percent") == "85.3%"

    def test_integer_number(self):
        assert format_kpi_value(1000, "number") == "1,000"

    def test_float_number(self):
        assert format_kpi_value(1234.56, "number") == "1,234.6"


# ---------------------------------------------------------------------------
# ECharts option building
# ---------------------------------------------------------------------------


class TestBuildEchartsOption:
    def test_line_chart_has_required_keys(self, sample_data):
        spec = {"type": "line", "x": "order_date", "y": ["revenue"], "title": "Rev"}
        theme = THEMES["light"]
        option = build_echarts_option(spec, sample_data, theme)
        assert "xAxis" in option
        assert "yAxis" in option
        assert "series" in option
        assert option["xAxis"]["type"] == "category"
        assert len(option["series"]) == 1
        assert option["series"][0]["name"] == "revenue"

    def test_pie_chart(self, sample_data):
        spec = {"type": "pie", "x": "customer_id", "y": ["revenue"], "title": "By Customer"}
        theme = THEMES["light"]
        option = build_echarts_option(spec, sample_data, theme)
        assert "series" in option
        assert option["series"][0]["type"] == "pie"

    def test_bar_chart_swaps_axes(self, sample_data):
        spec = {"type": "bar", "x": "order_date", "y": ["revenue"], "title": "Rev"}
        theme = THEMES["light"]
        option = build_echarts_option(spec, sample_data, theme)
        assert option["xAxis"]["type"] == "value"
        assert option["yAxis"]["type"] == "category"

    def test_empty_data(self):
        spec = {"type": "line", "x": "x", "y": ["y"], "title": ""}
        theme = THEMES["light"]
        option = build_echarts_option(spec, [], theme)
        assert option["series"][0]["data"] == []


class TestRenderEchartsOption:
    def test_returns_valid_json(self, sample_data):
        spec = {"type": "line", "x": "order_date", "y": ["revenue"], "title": "Test"}
        result = render_echarts_option(spec, sample_data, THEMES["light"])
        parsed = json.loads(result)
        assert "xAxis" in parsed


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


class TestLoadData:
    def test_load_csv_with_sql(self, con, sample_csv):
        # DuckDB doesn't support prepared params in CREATE VIEW, so use f-string
        con.execute(f"CREATE OR REPLACE VIEW sales AS SELECT * FROM read_csv_auto('{sample_csv}')")
        ds = {"files": [], "sql": "SELECT * FROM sales ORDER BY revenue"}
        rows = load_data(con, ds)
        assert len(rows) == 5
        assert rows[0]["revenue"] == 50.0
        assert rows[-1]["revenue"] == 300.0

    def test_empty_sql_returns_empty(self, con):
        ds = {"files": [], "sql": ""}
        assert load_data(con, ds) == []


# ---------------------------------------------------------------------------
# Full HTML generation
# ---------------------------------------------------------------------------


class TestGenerateHtml:
    def test_produces_valid_html(self, sample_data, minimal_spec):
        kpi_values = {"Total Revenue": 800.0}
        html = generate_html(minimal_spec, sample_data, "light", kpi_values)
        assert "<!DOCTYPE html>" in html
        assert "</html>" in html
        assert "Test Dashboard" in html

    def test_script_escaping_in_output(self, sample_data):
        """Data containing </script> should be escaped in the embedded JSON."""
        data = [{"order_date": "2024-01-01", "revenue": 100.0, "customer_id": "</script>"}]
        spec = {
            "title": "Escaping Test",
            "layout": "grid",
            "charts": [
                {"id": "c1", "type": "line", "x": "order_date", "y": ["revenue"], "title": "T"},
            ],
            "kpis": [],
            "filters": [],
        }
        html = generate_html(spec, data, "light", {})
        # The embedded data JSON should have escaped </script>
        assert r"<\/script" in html

    def test_chart_spec_uses_chart_spec_not_shadowing(self, sample_data):
        """Verify the chart_specs_js uses chart_spec (not the outer spec param)."""
        spec = {
            "title": "Shadow Test",
            "layout": "grid",
            "charts": [
                {"id": "c1", "type": "bar", "x": "x", "y": ["y"], "title": "Bar Chart"},
            ],
            "kpis": [],
            "filters": [],
        }
        html = generate_html(spec, sample_data, "light", {})
        # Should contain the chart spec with type: bar (not overridden by outer spec)
        assert '"type":"bar"' in html or '"type": "bar"' in html


# ---------------------------------------------------------------------------
# New tests for bug fixes
# ---------------------------------------------------------------------------


class TestSafeFloat:
    def test_numeric_values(self):
        assert _safe_float(42) == 42.0
        assert _safe_float(3.14) == 3.14
        assert _safe_float("2.5") == 2.5

    def test_none_returns_default(self):
        assert _safe_float(None) == 0.0

    def test_non_numeric_returns_default(self):
        assert _safe_float("N/A") == 0.0
        assert _safe_float("abc") == 0.0
        assert _safe_float("") == 0.0

    def test_custom_default(self):
        assert _safe_float("bad", -1.0) == -1.0


class TestDuplicateXValueAggregation:
    """Issue #4: Cartesian charts should SUM duplicate x-values instead of
    silently discarding all but the first."""

    def test_sums_duplicate_x_values(self):
        data = [
            {"date": "2024-01-01", "revenue": 100},
            {"date": "2024-01-01", "revenue": 200},
            {"date": "2024-01-02", "revenue": 50},
        ]
        spec = {"type": "line", "x": "date", "y": ["revenue"], "title": "T"}
        option = build_echarts_option(spec, data, THEMES["light"])
        # 2024-01-01 should be 100+200=300, not just 100
        assert option["series"][0]["data"] == [300.0, 50.0]

    def test_pie_sums_duplicate_x_values(self):
        data = [
            {"cat": "A", "val": 10},
            {"cat": "A", "val": 20},
            {"cat": "B", "val": 30},
        ]
        spec = {"type": "pie", "x": "cat", "y": ["val"], "title": "T"}
        option = build_echarts_option(spec, data, THEMES["light"])
        pie = {d["name"]: d["value"] for d in option["series"][0]["data"]}
        assert pie["A"] == 30.0
        assert pie["B"] == 30.0


class TestClientSideXssEscape:
    """Issue #1: The generated HTML must include escapeHtml and use it."""

    def test_escapehtml_function_present(self, sample_data):
        spec = {
            "title": "XSS Test",
            "layout": "grid",
            "charts": [
                {"id": "t1", "type": "table", "columns": ["x"], "title": "T"},
            ],
            "kpis": [],
            "filters": [],
        }
        html = generate_html(spec, sample_data, "light", {})
        assert "function escapeHtml" in html

    def test_updateTableCard_uses_escapeHtml(self, sample_data):
        spec = {
            "title": "XSS Test",
            "layout": "grid",
            "charts": [
                {"id": "t1", "type": "table", "columns": ["x"], "title": "T"},
            ],
            "kpis": [],
            "filters": [],
        }
        html = generate_html(spec, sample_data, "light", {})
        assert "escapeHtml(row[c])" in html


class TestKpiCollisionByIndex:
    """Issue #9: KPI values must be keyed by index, not label."""

    def test_duplicate_labels_preserved(self, sample_data):
        spec = {
            "title": "KPI Collision",
            "layout": "grid",
            "charts": [],
            "kpis": [
                {"label": "Revenue", "format": "currency", "value_sql": "SELECT 100"},
                {"label": "Revenue", "format": "currency", "value_sql": "SELECT 200"},
            ],
            "filters": [],
        }
        kpi_values = {0: 100.0, 1: 200.0}
        html = generate_html(spec, sample_data, "light", kpi_values)
        assert "$100.00" in html
        assert "$200.00" in html


class TestTabsLayout:
    """Issue #8: Tabs layout should group charts by tab field."""

    def test_single_tab(self, sample_data):
        from generate import _render_tabs_layout

        charts = [
            {"id": "c1", "type": "line", "x": "x", "y": ["y"], "title": "A"},
            {"id": "c2", "type": "bar", "x": "x", "y": ["y"], "title": "B"},
        ]
        html = _render_tabs_layout(charts, sample_data, THEMES["light"])
        assert "Overview" in html
        assert "c1" in html
        assert "c2" in html

    def test_multiple_tabs(self, sample_data):
        from generate import _render_tabs_layout

        charts = [
            {"id": "c1", "type": "line", "x": "x", "y": ["y"], "title": "A", "tab": "Sales"},
            {"id": "c2", "type": "bar", "x": "x", "y": ["y"], "title": "B", "tab": "Costs"},
        ]
        html = _render_tabs_layout(charts, sample_data, THEMES["light"])
        assert "Sales" in html
        assert "Costs" in html
        # First tab visible, second hidden
        assert 'display:grid' in html
        assert 'display:none' in html

    def test_tab_buttons_count(self, sample_data):
        from generate import _render_tabs_layout

        charts = [
            {"id": "c1", "type": "line", "x": "x", "y": ["y"], "title": "A", "tab": "Tab1"},
            {"id": "c2", "type": "bar", "x": "x", "y": ["y"], "title": "B", "tab": "Tab2"},
            {"id": "c3", "type": "pie", "x": "x", "y": ["y"], "title": "C", "tab": "Tab3"},
        ]
        html = _render_tabs_layout(charts, sample_data, THEMES["light"])
        assert html.count("tab-btn") == 3
        assert html.count('data-tab="') == 3  # 3 tab panels rendered
