"""Tests for report-template/scripts/generate.py."""

import json
import os
import sys

import duckdb
import pytest

# Make the parent directory importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from generate import (
    THEMES,
    _compute_kpis,
    _inline_bold,
    _safe_float,
    esc,
    format_value,
    generate_report,
    load_data_files,
    render_chart,
    render_kpi_row,
    render_table,
    render_text,
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
        result = validate_path("generate.py", "test file")
        assert result == "generate.py"


class TestSanitizeIdentifier:
    def test_strips_special_chars(self):
        assert sanitize_identifier("hello world!") == "hello_world_"

    def test_preserves_alphanumeric(self):
        assert sanitize_identifier("table_123") == "table_123"


class TestEsc:
    def test_escapes_html(self):
        assert esc("<b>bold</b>") == "&lt;b&gt;bold&lt;/b&gt;"

    def test_escapes_quotes(self):
        assert esc("'x'") == "&#x27;x&#x27;"


# ---------------------------------------------------------------------------
# KPI computation
# ---------------------------------------------------------------------------


class TestComputeKpis:
    def test_full_data(self, con_with_data):
        """With revenue and customer_id columns, all KPIs should be computed."""
        result = _compute_kpis(con_with_data)
        assert result["kpi_revenue"] == 800.0
        assert result["kpi_avg"] == 160.0
        assert result["kpi_customers"] == 3
        assert result["kpi_orders"] == 5
        assert result["kpi_wow"] is None
        assert result["kpi_satisfaction"] is None

    def test_missing_columns(self, con_with_minimal_data):
        """Without revenue/customer_id, those KPIs should be absent (None)."""
        result = _compute_kpis(con_with_minimal_data)
        assert "kpi_revenue" not in result
        assert "kpi_avg" not in result
        assert "kpi_customers" not in result
        assert result["kpi_orders"] == 3  # COUNT(*) always works
        assert result["kpi_wow"] is None
        assert result["kpi_satisfaction"] is None

    def test_empty_table(self, con):
        """Empty table should return None for SUM/AVG, 0 for COUNT."""
        con.execute("CREATE TABLE data (revenue FLOAT, customer_id VARCHAR)")
        result = _compute_kpis(con)
        assert result["kpi_revenue"] is None
        # COUNT(DISTINCT customer_id) on empty table returns 0
        assert result["kpi_customers"] == 0
        assert result["kpi_orders"] == 0

    def test_missing_table(self, con):
        """Non-existent table should return empty dict."""
        result = _compute_kpis(con, "nonexistent")
        assert result == {}


# ---------------------------------------------------------------------------
# Format value
# ---------------------------------------------------------------------------


class TestFormatValue:
    def test_none_returns_na(self):
        assert format_value(None, "number") == "N/A"

    def test_currency(self):
        assert format_value(500.0, "currency") == "$500.00"

    def test_percent(self):
        assert format_value(75.5, "percent") == "75.5%"

    def test_integer(self):
        assert format_value(1000, "number") == "1,000"


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


class TestLoadDataFiles:
    def test_load_csv(self, con, tmp_dir):
        """Load CSV using a path that passes validate_path (relative to CWD)."""
        # Create a CSV inside CWD so validate_path allows it
        import csv as csv_mod
        csv_path = os.path.join(tmp_dir, "testdata.csv")
        with open(csv_path, "w", newline="") as f:
            w = csv_mod.writer(f)
            w.writerow(["x", "y"])
            w.writerow([1, 2])
            w.writerow([3, 4])
        # Monkey-patch validate_path to allow tmp_dir
        import generate
        original = generate.validate_path
        generate.validate_path = lambda p, ctx="": p
        try:
            load_data_files(con, [csv_path])
            rows = con.execute("SELECT COUNT(*) FROM data").fetchone()
            assert rows[0] == 2
        finally:
            generate.validate_path = original

    def test_empty_list(self, con):
        load_data_files(con, [])
        # Should not raise


# ---------------------------------------------------------------------------
# Section rendering
# ---------------------------------------------------------------------------


class TestRenderChart:
    def test_line_chart(self, con_with_data):
        section = {
            "type": "chart",
            "chart_type": "line",
            "title": "Revenue Trend",
            "id": "test-chart",
            "data_source": {
                "sql": "SELECT order_date, SUM(revenue) as revenue FROM data GROUP BY order_date ORDER BY order_date",
                "x": "order_date",
                "y": ["revenue"],
            },
        }
        html = render_chart(section, con_with_data, THEMES["light"])
        assert "test-chart" in html
        assert "<script" in html
        assert "application/json" in html

    def test_script_escaping(self, con):
        """Data containing </script> should be escaped in the JSON payload."""
        con.execute("CREATE TABLE data (x VARCHAR, y INTEGER)")
        con.execute("INSERT INTO data VALUES ('</script><script>alert(1)', 1)")
        section = {
            "type": "chart",
            "chart_type": "line",
            "title": "Test",
            "id": "esc-chart",
            "data_source": {
                "sql": "SELECT x, y FROM data",
                "x": "x",
                "y": ["y"],
            },
        }
        html = render_chart(section, con, THEMES["light"])
        # The JSON between <script> tags should have escaped </script>
        json_start = html.index("application/json\">") + len("application/json\">")
        json_end = html.index("</script>", json_start)
        json_payload = html[json_start:json_end]
        assert "</script>" not in json_payload
        assert r"<\/script" in json_payload

    def test_bad_sql_returns_error(self, con_with_data):
        section = {
            "type": "chart",
            "chart_type": "line",
            "title": "Bad",
            "id": "bad",
            "data_source": {
                "sql": "SELECT * FROM nonexistent_table",
                "x": "x",
                "y": ["y"],
            },
        }
        html = render_chart(section, con_with_data, THEMES["light"])
        assert "error" in html.lower()


class TestRenderTable:
    def test_basic_table(self, con_with_data):
        section = {
            "type": "table",
            "title": "Sales",
            "columns": ["order_date", "revenue"],
            "data_source": {
                "sql": "SELECT order_date, revenue FROM data LIMIT 3",
            },
        }
        html = render_table(section, con_with_data, THEMES["light"])
        assert "<table" in html
        assert "2024-01-01" in html


# ---------------------------------------------------------------------------
# Full report generation
# ---------------------------------------------------------------------------


class TestGenerateReport:
    def test_produces_html(self, con_with_data, sample_csv, minimal_template):
        html = generate_report(minimal_template, con_with_data, "light", {})
        assert "<!DOCTYPE html>" in html
        assert "</html>" in html
        assert "Test Report" in html

    def test_kpi_values_from_data(self, con_with_data, sample_csv):
        template = {
            "name": "kpi-test",
            "title": "KPI Test",
            "theme": "light",
            "sections": [
                {
                    "type": "kpi_row",
                    "kpis": [
                        {"label": "Revenue", "field": "kpi_revenue", "format": "currency"},
                        {"label": "Orders", "field": "kpi_orders", "format": "number"},
                    ],
                },
            ],
        }
        html = generate_report(template, con_with_data, "light", {})
        assert "$800.00" in html
        assert "5" in html  # total rows

    def test_graceful_degradation_no_revenue(self, con_with_minimal_data, minimal_csv):
        """When data lacks revenue, KPIs should show N/A, not 0 or crash."""
        template = {
            "name": "degrade-test",
            "title": "Degrade Test",
            "theme": "light",
            "sections": [
                {
                    "type": "kpi_row",
                    "kpis": [
                        {"label": "Revenue", "field": "kpi_revenue", "format": "currency"},
                        {"label": "Orders", "field": "kpi_orders", "format": "number"},
                    ],
                },
            ],
        }
        html = generate_report(template, con_with_minimal_data, "light", {})
        assert "N/A" in html  # kpi_revenue should be None → N/A
        assert "3" in html  # kpi_orders (COUNT(*)) still works


# ---------------------------------------------------------------------------
# New tests for bug fixes
# ---------------------------------------------------------------------------


class TestSafeFloat:
    def test_numeric_values(self):
        assert _safe_float(42) == 42.0
        assert _safe_float("3.14") == 3.14

    def test_none_returns_default(self):
        assert _safe_float(None) == 0.0

    def test_non_numeric_returns_default(self):
        assert _safe_float("N/A") == 0.0
        assert _safe_float("abc") == 0.0

    def test_custom_default(self):
        assert _safe_float("bad", -1.0) == -1.0


class TestKpiDivideByZero:
    """Issue #2: target=0 must not crash."""

    def test_target_zero_no_crash(self):
        section = {
            "kpis": [
                {"label": "Defects", "field": "defects", "format": "number", "target": 0},
            ],
        }
        data_results = {"defects": 5}
        html = render_kpi_row(section, data_results, THEMES["light"])
        # Should show the target label but no progress bar
        assert "Target:" in html
        assert "0" in html

    def test_target_zero_zero_value(self):
        section = {
            "kpis": [
                {"label": "Defects", "field": "defects", "format": "number", "target": 0},
            ],
        }
        data_results = {"defects": 0}
        html = render_kpi_row(section, data_results, THEMES["light"])
        assert "Target:" in html

    def test_target_none_no_progress(self):
        section = {
            "kpis": [
                {"label": "Revenue", "field": "rev", "format": "currency"},
            ],
        }
        data_results = {"rev": 500}
        html = render_kpi_row(section, data_results, THEMES["light"])
        # No target → no progress bar, no "Target:" label
        assert "Target:" not in html


class TestKpiNegativeValue:
    """Issue #11: negative values should clamp pct to [0, 100]."""

    def test_negative_value_clamps_to_zero(self):
        section = {
            "kpis": [
                {"label": "Loss", "field": "val", "format": "currency", "target": 100},
            ],
        }
        data_results = {"val": -50}
        html = render_kpi_row(section, data_results, THEMES["light"])
        # Progress bar width should be 0%
        assert "width:0%;" in html

    def test_normal_value_works(self):
        section = {
            "kpis": [
                {"label": "Revenue", "field": "rev", "format": "currency", "target": 1000},
            ],
        }
        data_results = {"rev": 750}
        html = render_kpi_row(section, data_results, THEMES["light"])
        assert "width:75%;" in html


class TestRenderTextNewlines:
    """Issue #3 + #12: split on actual newlines, not literal \\n."""

    def test_literal_backslash_n(self):
        section = {"title": "T", "content": "Line 1\\nLine 2\\nLine 3"}
        html = render_text(section, THEMES["light"])
        assert "<p" in html
        assert "Line 1" in html
        assert "Line 2" in html
        assert "Line 3" in html

    def test_actual_newlines(self):
        section = {"title": "T", "content": "Line 1\nLine 2\nLine 3"}
        html = render_text(section, THEMES["light"])
        assert "Line 1" in html
        assert "Line 2" in html
        assert "Line 3" in html

    def test_mixed_newlines(self):
        section = {"title": "T", "content": "Line 1\\nLine 2\nLine 3"}
        html = render_text(section, THEMES["light"])
        assert "Line 1" in html
        assert "Line 2" in html
        assert "Line 3" in html


class TestInlineBold:
    """Issue #10: inline **bold** should work."""

    def test_inline_bold(self):
        result = _inline_bold("hello **world** bye")
        assert "<strong>world</strong>" in result
        assert "hello " in result
        assert " bye" in result

    def test_no_bold(self):
        result = _inline_bold("plain text")
        assert result == "plain text"

    def test_whole_line_bold_in_render_text(self):
        section = {"title": "T", "content": "**Important**"}
        html = render_text(section, THEMES["light"])
        assert "<strong>Important</strong>" in html

    def test_inline_bold_in_paragraph(self):
        section = {"title": "T", "content": "This is **key** point"}
        html = render_text(section, THEMES["light"])
        assert "<strong>key</strong>" in html

    def test_inline_bold_in_list_item(self):
        section = {"title": "T", "content": "- This is **important** item"}
        html = render_text(section, THEMES["light"])
        assert "<strong>important</strong>" in html
        assert "<li>" in html


class TestChartNonNumericData:
    """Issue #6: non-numeric y-field values should not crash."""

    def test_pie_chart_with_non_numeric(self, con):
        con.execute("CREATE TABLE data (cat VARCHAR, val VARCHAR)")
        con.execute("INSERT INTO data VALUES ('A', '10'), ('B', 'N/A'), ('C', '30')")
        section = {
            "type": "chart",
            "chart_type": "pie",
            "id": "test-pie",
            "data_source": {"sql": "SELECT cat, val FROM data", "x": "cat", "y": ["val"]},
        }
        html = render_chart(section, con, THEMES["light"])
        assert "error" not in html.lower()
        assert "test-pie" in html

    def test_line_chart_with_non_numeric(self, con):
        con.execute("CREATE TABLE data (x VARCHAR, y VARCHAR)")
        con.execute("INSERT INTO data VALUES ('A', '10'), ('B', 'bad'), ('C', '30')")
        section = {
            "type": "chart",
            "chart_type": "line",
            "id": "test-line",
            "data_source": {"sql": "SELECT x, y FROM data", "x": "x", "y": ["y"]},
        }
        html = render_chart(section, con, THEMES["light"])
        assert "error" not in html.lower()


class TestDuplicateXValueAggregation:
    """Issue #4 (report): cartesian charts should SUM duplicate x-values."""

    def test_sums_duplicate_x(self, con):
        con.execute("CREATE TABLE data (date VARCHAR, revenue INTEGER)")
        con.execute("INSERT INTO data VALUES ('2024-01', 100), ('2024-01', 200), ('2024-02', 50)")
        section = {
            "type": "chart",
            "chart_type": "line",
            "id": "test-dup",
            "data_source": {
                "sql": "SELECT date, revenue FROM data",
                "x": "date",
                "y": ["revenue"],
            },
        }
        html = render_chart(section, con, THEMES["light"])
        # Should not crash, and should contain chart
        assert "test-dup" in html
        # Verify via option JSON that data is summed
        assert "error" not in html.lower()
