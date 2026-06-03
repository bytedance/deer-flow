"""Tests for the ECharts option sanitizer (design §11.3)."""

from __future__ import annotations

import pytest

from deerflow.report_templates.runtime.echart_sanitizer import (
    EchartsSanitizeError,
    sanitize_echart_option,
)


class TestSanitizeAllows:
    """Pure-JSON ECharts options must pass."""

    def test_basic_line_chart(self):
        option = {
            "xAxis": {"type": "category", "data": ["a", "b", "c"]},
            "yAxis": {"type": "value"},
            "series": [{"type": "line", "data": [1, 2, 3]}],
        }
        sanitize_echart_option(option)  # no raise

    def test_multi_series_with_tooltip_string(self):
        option = {
            "tooltip": {"trigger": "axis"},
            "legend": {"data": ["A", "B"]},
            "series": [
                {"name": "A", "type": "bar", "data": [1, 2]},
                {"name": "B", "type": "line", "data": [3, 4]},
            ],
        }
        sanitize_echart_option(option)

    def test_inline_data_uri_image_allowed(self):
        # data:image/* (SVG/PNG inline blobs) are allowed; only data:text/html is rejected.
        option = {"backgroundImage": "data:image/svg+xml;base64,PHN2Zz48L3N2Zz4="}
        sanitize_echart_option(option)

    def test_relative_image_path_allowed(self):
        option = {"image": "/artifacts/chart-bg.png"}
        sanitize_echart_option(option)

    def test_empty_option_is_fine(self):
        sanitize_echart_option({})


class TestSanitizeRejectsFunctions:
    """Function bodies in any string value must be rejected."""

    def test_function_formatter_rejected(self):
        option = {
            "tooltip": {"formatter": "function (params) { return params.value; }"},
        }
        with pytest.raises(EchartsSanitizeError) as exc:
            sanitize_echart_option(option)
        assert "function" in exc.value.reason.lower()

    def test_arrow_function_rejected(self):
        option = {"xAxis": {"axisLabel": {"formatter": "(v) => v + '%'"}}}
        with pytest.raises(EchartsSanitizeError):
            sanitize_echart_option(option)

    def test_async_function_rejected(self):
        option = {"tooltip": {"formatter": "async function(p) { return p; }"}}
        with pytest.raises(EchartsSanitizeError):
            sanitize_echart_option(option)

    def test_function_in_nested_array_rejected(self):
        option = {"series": [{"label": {"formatter": "function(){return 1}"}}]}
        with pytest.raises(EchartsSanitizeError) as exc:
            sanitize_echart_option(option)
        assert "series[0].label.formatter" in exc.value.path


class TestSanitizeRejectsHtml:
    def test_script_tag_rejected(self):
        option = {"title": {"text": "<script>alert(1)</script>"}}
        with pytest.raises(EchartsSanitizeError) as exc:
            sanitize_echart_option(option)
        assert "HTML" in exc.value.reason or "script" in exc.value.reason.lower()

    def test_iframe_tag_rejected(self):
        option = {"title": {"text": "<iframe src='evil'></iframe>"}}
        with pytest.raises(EchartsSanitizeError):
            sanitize_echart_option(option)

    def test_javascript_uri_rejected(self):
        option = {"toolbox": {"feature": {"myTool": {"icon": "javascript:alert(1)"}}}}
        with pytest.raises(EchartsSanitizeError):
            sanitize_echart_option(option)

    def test_data_text_html_rejected(self):
        option = {"backgroundImage": "data:text/html,<script>1</script>"}
        with pytest.raises(EchartsSanitizeError):
            sanitize_echart_option(option)

    def test_html_in_table_data_value_rejected(self):
        option = {"series": [{"data": [{"name": "<script>x</script>", "value": 1}]}]}
        with pytest.raises(EchartsSanitizeError):
            sanitize_echart_option(option)


class TestSanitizeRejectsExternalUrls:
    def test_http_url_in_backgroundImage_rejected(self):
        option = {"backgroundImage": "https://evil.example.com/img.png"}
        with pytest.raises(EchartsSanitizeError) as exc:
            sanitize_echart_option(option)
        assert "external URL" in exc.value.reason or "external" in exc.value.reason.lower()

    def test_http_url_in_image_field_rejected(self):
        option = {"image": "http://example.com/x.png"}
        with pytest.raises(EchartsSanitizeError):
            sanitize_echart_option(option)

    def test_http_url_in_src_rejected(self):
        option = {"toolbox": {"feature": {"icon": {"src": "https://x.com/i.svg"}}}}
        with pytest.raises(EchartsSanitizeError):
            sanitize_echart_option(option)

    def test_ftp_url_rejected(self):
        option = {"url": "ftp://x.com/y"}
        with pytest.raises(EchartsSanitizeError):
            sanitize_echart_option(option)

    def test_http_url_in_non_url_field_allowed(self):
        """Plain text data values containing URLs (not in URL-shaped fields) pass."""
        option = {"title": {"text": "See https://example.com for context"}}
        sanitize_echart_option(option)  # ok — only URL-shaped fields are flagged


class TestPayloadBuilderIntegration:
    """End-to-end via payload_builder.assemble_payload."""

    def _state(self):
        from deerflow.report_templates.runtime.state import RuntimeState

        return RuntimeState(
            report_run_id="rr_TEST00000000000000000001",
            thread_id="t",
            template_id="builtin-test",
            template_version_ref="builtin-1",
            status="data_complete",
            created_at="2026-05-18T10:00:00+00:00",
        )

    def _minimal_dsl(self, section_source: str):
        return {
            "dsl_version": "1",
            "name": "test",
            "display_name": "test",
            "form_steps": [
                {
                    "id": "scope",
                    "title": "t",
                    "fields": [{"name": "x", "label": "x", "type": "text"}],
                    "next": "generate",
                }
            ],
            "data_steps": [
                {
                    "id": "demo_data",
                    "kind": "script",
                    "name": "daily-report/list_equipment",
                    "args": {"type": "all"},
                    "outputs": {"chart": "demo_data.json"},
                }
            ],
            "sections": [
                {"id": "trend", "title": "Trend", "component": "echart", "source": section_source}
            ],
        }

    def test_pure_json_option_passes(self):
        from deerflow.report_templates.runtime.payload_builder import assemble_payload

        state = self._state()
        state.step_outputs = {
            "demo_data": {"chart": {"xAxis": {"type": "value"}, "series": [{"type": "line", "data": [1, 2]}]}}
        }
        dsl = self._minimal_dsl("$.steps.demo_data.chart")
        payload = assemble_payload(dsl=dsl, state=state)
        assert payload["sections"][0]["component"] == "echart"

    def test_function_in_option_raises_payload_error(self):
        from deerflow.report_templates.runtime.payload_builder import (
            PayloadBuildError,
            assemble_payload,
        )

        state = self._state()
        state.step_outputs = {
            "demo_data": {"chart": {"tooltip": {"formatter": "function(p){return p}"}}}
        }
        dsl = self._minimal_dsl("$.steps.demo_data.chart")
        with pytest.raises(PayloadBuildError) as exc:
            assemble_payload(dsl=dsl, state=state)
        assert "echart option failed safety scan" in str(exc.value)

    def test_script_tag_raises_payload_error(self):
        from deerflow.report_templates.runtime.payload_builder import (
            PayloadBuildError,
            assemble_payload,
        )

        state = self._state()
        state.step_outputs = {
            "demo_data": {"chart": {"title": {"text": "<script>evil</script>"}}}
        }
        dsl = self._minimal_dsl("$.steps.demo_data.chart")
        with pytest.raises(PayloadBuildError) as exc:
            assemble_payload(dsl=dsl, state=state)
        assert "echart option failed safety scan" in str(exc.value)
