"""Unit tests for report_templates.validator — full DSL validation.

Covers all 3 passes:
1. Static cross-refs (next, options_source ordering, placeholder paths, section source)
2. Script registry (unknown script, missing required arg, unknown arg, enum value)
3. Component / source type hints (warning-only)

Includes a smoke test for the §5.2 "重点机泵日报" full DSL.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml

from deerflow.report_templates.schema import DSL_SCHEMA_VERSION
from deerflow.report_templates.script_registry import (
    REPORT_SCRIPTS_FILE,
    _build_registry_from_skills,
)
from deerflow.report_templates.validator import validate_dsl


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def registry(tmp_path: Path):
    skill_dir = tmp_path / "data-analyst"
    skill_dir.mkdir()
    manifest = {
        "schema_version": "1",
        "scripts": {
            "list_equipment": {
                "entry": "scripts/list_equipment.py",
                "kind": ["form_options"],
                "args_schema": {
                    "type": {
                        "type": "enum",
                        "values": ["all", "pump", "static_equipment"],
                        "required": True,
                    },
                    "scope": {"type": "enum", "values": ["all"], "default": "all"},
                    "limit": {"type": "integer", "min": 1, "max": 10000, "default": 10000},
                },
                "outputs_schema": {
                    "equipment": {"type": "array"},
                    "available_kpis": {"type": "array"},
                },
            },
            "query_daily": {
                "entry": "scripts/query_daily.py",
                "kind": ["data_step"],
                "args_schema": {
                    "date": {"type": "date", "required": True},
                    "equipment_type": {"type": "enum", "values": ["all", "pump"]},
                    "equipment_ids": {"type": "array"},
                    "kpis": {"type": "array"},
                    "compare": {"type": "enum", "values": ["previous_day", "none"]},
                },
                "output_files": [{"id": "daily_data", "path": "{run_output_dir}/data/daily_data.json"}],
            },
            "daily_kpi": {
                "entry": "scripts/daily_kpi.py",
                "kind": ["transform"],
                "args_schema": {"input": {"type": "file_path", "required": True}},
                "output_files": [{"id": "daily_kpi", "path": "{run_output_dir}/data/daily_kpi.json"}],
            },
        },
    }
    (skill_dir / REPORT_SCRIPTS_FILE).write_text(
        yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8"
    )
    return _build_registry_from_skills([("data-analyst", skill_dir, True)])


def _good_dsl() -> dict[str, Any]:
    """Mini DSL that should validate cleanly with the fixture registry."""
    return {
        "dsl_version": DSL_SCHEMA_VERSION,
        "name": "demo",
        "display_name": "Demo",
        "form_steps": [
            {
                "id": "scope",
                "title": "Scope",
                "fields": [
                    {"name": "report_date", "label": "Date", "type": "date", "required": True},
                    {
                        "name": "equipment_type",
                        "label": "Type",
                        "type": "select",
                        "required": True,
                        "options": [
                            {"label": "All", "value": "all"},
                            {"label": "Pump", "value": "pump"},
                        ],
                    },
                ],
                "next": "equipment",
            },
            {
                "id": "equipment",
                "title": "Equipment",
                "before_step": {
                    "id": "equipment_catalog",
                    "kind": "script",
                    "name": "data-analyst/list_equipment",
                    "args": {"type": "{{ $.form.scope.equipment_type }}", "scope": "all", "limit": 100},
                },
                "fields": [
                    {
                        "name": "equipment_ids",
                        "label": "IDs",
                        "type": "multi-select",
                        "required": True,
                        "options_source": {
                            "step": "equipment_catalog",
                            "path": "equipment",
                            "label": "id",
                            "value": "id",
                        },
                    }
                ],
                "next": "generate",
            },
        ],
        "data_steps": [
            {
                "id": "data1",
                "kind": "script",
                "name": "data-analyst/query_daily",
                "args": {
                    "date": "{{ $.form.scope.report_date }}",
                    "equipment_type": "{{ $.form.scope.equipment_type }}",
                    "equipment_ids": "{{ $.form.equipment.equipment_ids }}",
                    "compare": "previous_day",
                },
                "outputs": {"daily_data": "daily_data.json"},
            }
        ],
        "transforms": [
            {
                "id": "kpi1",
                "kind": "script",
                "name": "data-analyst/daily_kpi",
                "args": {"input": "data1.daily_data"},
                "outputs": {"daily_kpi": "daily_kpi.json"},
            }
        ],
        "sections": [
            {
                "id": "overview",
                "title": "Overview",
                "component": "markdown",
                "source": "$.steps.kpi1.daily_kpi.summary",
            }
        ],
        "export": {"formats": ["md", "pdf"], "renderer": "generic_report"},
    }


# ---------------------------------------------------------------------------
# Happy path — DSL must validate cleanly
# ---------------------------------------------------------------------------


class TestHappyPath:
    def test_good_dsl_passes_without_registry(self):
        report = validate_dsl(_good_dsl())
        # Without registry we can't verify script names, but static checks pass.
        assert report.valid is True, report.to_dict()
        assert all(e.code != "UNKNOWN_SCRIPT" for e in report.errors)

    def test_good_dsl_passes_with_registry(self, registry):
        report = validate_dsl(_good_dsl(), registry=registry)
        assert report.valid is True, report.to_dict()
        assert report.errors == []

    def test_returns_parsed_dsl(self, registry):
        report = validate_dsl(_good_dsl(), registry=registry)
        assert report.dsl is not None
        assert report.dsl.name == "demo"


# ---------------------------------------------------------------------------
# Schema pass failure surfaces in errors
# ---------------------------------------------------------------------------


class TestSchemaPass:
    def test_invalid_field_type_surfaced(self):
        dsl = _good_dsl()
        dsl["form_steps"][0]["fields"][0]["type"] = "rangepicker"
        report = validate_dsl(dsl)
        assert report.valid is False
        assert any(e.code == "SCHEMA_INVALID" for e in report.errors)


# ---------------------------------------------------------------------------
# Pass 1 — Static checks
# ---------------------------------------------------------------------------


class TestNextGraph:
    def test_unknown_next_id(self):
        dsl = _good_dsl()
        dsl["form_steps"][0]["next"] = "nowhere"
        report = validate_dsl(dsl)
        assert any(e.code == "UNKNOWN_NEXT" for e in report.errors)

    def test_self_loop(self):
        dsl = _good_dsl()
        dsl["form_steps"][0]["next"] = "scope"
        report = validate_dsl(dsl)
        assert any(e.code == "NEXT_SELF_LOOP" for e in report.errors)


class TestOptionsSourceOrdering:
    def test_options_source_from_unexecuted_step(self):
        dsl = _good_dsl()
        # equipment_catalog runs in the equipment form_step's before_step;
        # but if we move the multi-select to the *first* form_step, the
        # before_step has not executed yet.
        dsl["form_steps"][0]["fields"].append(
            {
                "name": "ids_too_early",
                "label": "Equipment too early",
                "type": "multi-select",
                "options_source": {
                    "step": "equipment_catalog",
                    "path": "equipment",
                    "label": "id",
                    "value": "id",
                },
            }
        )
        report = validate_dsl(dsl)
        assert any(e.code == "OPTIONS_SOURCE_NOT_EXECUTED" for e in report.errors)


class TestPlaceholders:
    def test_unknown_form_step_in_placeholder(self):
        dsl = _good_dsl()
        dsl["data_steps"][0]["args"]["date"] = "{{ $.form.nonexistent.x }}"
        report = validate_dsl(dsl)
        assert any(e.code == "UNKNOWN_FORM_STEP" for e in report.errors)

    def test_unknown_form_field_in_placeholder(self):
        dsl = _good_dsl()
        dsl["data_steps"][0]["args"]["date"] = "{{ $.form.scope.not_a_field }}"
        report = validate_dsl(dsl)
        assert any(e.code == "UNKNOWN_FORM_FIELD" for e in report.errors)

    def test_invalid_placeholder_syntax(self):
        dsl = _good_dsl()
        dsl["data_steps"][0]["args"]["date"] = "{{ $.form.scope.report_date[*] }}"
        report = validate_dsl(dsl)
        assert any(e.code == "INVALID_PLACEHOLDER_SYNTAX" for e in report.errors)

    def test_short_form_placeholder_accepted(self):
        dsl = _good_dsl()
        dsl["data_steps"][0]["args"]["date"] = "{{ form.scope.report_date }}"
        report = validate_dsl(dsl, registry=None)
        assert report.valid is True

    def test_unknown_step_in_steps_path(self):
        dsl = _good_dsl()
        dsl["data_steps"][0]["args"]["date"] = "{{ $.steps.missing_step.x }}"
        report = validate_dsl(dsl)
        assert any(e.code == "UNKNOWN_STEP" for e in report.errors)


class TestSectionSource:
    def test_unknown_step_in_section(self):
        dsl = _good_dsl()
        dsl["sections"][0]["source"] = "$.steps.no_such.output.summary"
        report = validate_dsl(dsl)
        assert any(e.code == "UNKNOWN_STEP" for e in report.errors)

    def test_unknown_output_in_section(self):
        dsl = _good_dsl()
        dsl["sections"][0]["source"] = "$.steps.data1.no_such_output.field"
        report = validate_dsl(dsl, registry=None)
        assert any(e.code == "UNKNOWN_STEP_OUTPUT" for e in report.errors)

    def test_short_form_section_source_accepted(self):
        dsl = _good_dsl()
        dsl["sections"][0]["source"] = "kpi1.daily_kpi.summary"
        report = validate_dsl(dsl)
        # Static check tolerates legacy short form.
        assert all(e.code != "UNKNOWN_STEP" for e in report.errors)

    def test_section_source_must_start_with_steps(self):
        dsl = _good_dsl()
        dsl["sections"][0]["source"] = "$.form.scope.report_date"
        report = validate_dsl(dsl)
        assert any(e.code == "SECTION_SOURCE_NOT_STEPS" for e in report.errors)


# ---------------------------------------------------------------------------
# Pass 2 — Script registry
# ---------------------------------------------------------------------------


class TestRegistryPass:
    def test_unknown_script(self, registry):
        dsl = _good_dsl()
        dsl["data_steps"][0]["name"] = "data-analyst/no_such_script"
        report = validate_dsl(dsl, registry=registry)
        assert any(e.code == "UNKNOWN_SCRIPT" for e in report.errors)

    def test_missing_skill_namespace(self, registry):
        dsl = _good_dsl()
        dsl["data_steps"][0]["name"] = "query_daily_no_namespace"
        report = validate_dsl(dsl, registry=registry)
        assert any(e.code == "MISSING_SKILL_NAMESPACE" for e in report.errors)

    def test_unknown_arg(self, registry):
        dsl = _good_dsl()
        dsl["data_steps"][0]["args"]["nonexistent_arg"] = "x"
        report = validate_dsl(dsl, registry=registry)
        assert any(e.code == "UNKNOWN_ARG" for e in report.errors)

    def test_missing_required_arg(self, registry):
        dsl = _good_dsl()
        del dsl["data_steps"][0]["args"]["date"]
        report = validate_dsl(dsl, registry=registry)
        assert any(e.code == "MISSING_REQUIRED_ARG" for e in report.errors)

    def test_arg_value_not_allowed(self, registry):
        dsl = _good_dsl()
        # `compare` arg accepts "previous_day" or "none"; "future_day" rejected.
        dsl["data_steps"][0]["args"]["compare"] = "future_day"
        report = validate_dsl(dsl, registry=registry)
        assert any(e.code == "ARG_VALUE_NOT_ALLOWED" for e in report.errors)

    def test_arg_placeholder_skipped_by_enum_check(self, registry):
        dsl = _good_dsl()
        # equipment_type accepts placeholder; we should NOT reject it.
        dsl["data_steps"][0]["args"]["equipment_type"] = "{{ $.form.scope.equipment_type }}"
        report = validate_dsl(dsl, registry=registry)
        assert all(e.code != "ARG_VALUE_NOT_ALLOWED" for e in report.errors)

    def test_before_step_validated(self, registry):
        dsl = _good_dsl()
        dsl["form_steps"][1]["before_step"]["name"] = "data-analyst/missing_script"
        report = validate_dsl(dsl, registry=registry)
        assert any(
            e.code == "UNKNOWN_SCRIPT" and "before_step" in e.path
            for e in report.errors
        )

    def test_before_step_outputs_enriched_for_options_source(self, registry):
        """When registry is provided, options_source can reference outputs declared by registry."""
        dsl = _good_dsl()
        # Remove explicit data_step outputs so we rely on registry-declared output_files.
        # query_daily declares output_files [{id: daily_data}], so transform input "data1.daily_data" should be fine.
        report = validate_dsl(dsl, registry=registry)
        assert all(e.code != "UNKNOWN_STEP_OUTPUT" for e in report.errors)


# ---------------------------------------------------------------------------
# Pass 3 — type hint warnings
# ---------------------------------------------------------------------------


class TestTypeHints:
    def test_echart_pointing_at_summary_warns(self, registry):
        dsl = _good_dsl()
        dsl["sections"].append(
            {
                "id": "weird",
                "title": "Weird",
                "component": "echart",
                "source": "$.steps.kpi1.daily_kpi.summary",
            }
        )
        report = validate_dsl(dsl, registry=registry)
        assert any(w.code == "SECTION_TYPE_HINT_MISMATCH" for w in report.warnings)

    def test_table_pointing_at_table_no_warning(self, registry):
        dsl = _good_dsl()
        dsl["sections"].append(
            {
                "id": "anomalies",
                "title": "Anomalies",
                "component": "table",
                "source": "$.steps.kpi1.daily_kpi.alarm_table",
            }
        )
        report = validate_dsl(dsl, registry=registry)
        anomaly_warnings = [
            w for w in report.warnings if "anomalies" in w.path
        ]
        assert anomaly_warnings == []


# ---------------------------------------------------------------------------
# Spec §5.2 smoke — full "重点机泵日报" template
# ---------------------------------------------------------------------------


def _spec_52_dsl() -> dict[str, Any]:
    """The full §5.2 example, ported into dict form."""
    return {
        "dsl_version": "1",
        "name": "equipment_daily_custom",
        "display_name": "重点机泵日报",
        "description": "面向重点机泵的运行日报",
        "visibility": "private",
        "form_steps": [
            {
                "id": "scope",
                "title": "生成重点机泵日报",
                "description": "请选择日报日期、设备类型和对比基准。",
                "fields": [
                    {"name": "report_date", "label": "日报日期", "type": "date", "required": True},
                    {
                        "name": "equipment_type",
                        "label": "设备类型",
                        "type": "select",
                        "required": True,
                        "default": "pump",
                        "options": [
                            {"label": "全部", "value": "all"},
                            {"label": "机泵", "value": "pump"},
                            {"label": "静设备", "value": "static_equipment"},
                        ],
                    },
                    {
                        "name": "compare_with",
                        "label": "对比基准",
                        "type": "select",
                        "required": True,
                        "default": "previous_day",
                        "options": [
                            {"label": "前一日", "value": "previous_day"},
                            {"label": "不对比", "value": "none"},
                        ],
                    },
                ],
                "next": "equipment",
            },
            {
                "id": "equipment",
                "title": "选择设备",
                "description": "请选择本次报告覆盖的设备。",
                "before_step": {
                    "id": "equipment_catalog",
                    "kind": "script",
                    "name": "data-analyst/list_equipment",
                    "args": {
                        "type": "{{ $.form.scope.equipment_type }}",
                        "scope": "all",
                        "limit": 10000,
                    },
                },
                "fields": [
                    {
                        "name": "equipment_ids",
                        "label": "设备列表",
                        "type": "multi-select",
                        "required": True,
                        "searchable": True,
                        "options_source": {
                            "step": "equipment_catalog",
                            "path": "equipment",
                            "label": "id",
                            "value": "id",
                            "group": "area",
                            "description": "name",
                        },
                    }
                ],
                "next": "kpis",
            },
            {
                "id": "kpis",
                "title": "选择 KPI",
                "fields": [
                    {
                        "name": "kpi_keys",
                        "label": "KPI 指标",
                        "type": "multi-select",
                        "required": True,
                        "options_source": {
                            "step": "equipment_catalog",
                            "path": "available_kpis",
                            "label": "label",
                            "value": "key",
                            "description": "description",
                        },
                    }
                ],
                "next": "generate",
            },
        ],
        "data_steps": [
            {
                "id": "daily_data",
                "kind": "script",
                "name": "data-analyst/query_daily",
                "args": {
                    "date": "{{ $.form.scope.report_date }}",
                    "equipment_type": "{{ $.form.scope.equipment_type }}",
                    "equipment_ids": "{{ $.form.equipment.equipment_ids }}",
                    "kpis": "{{ $.form.kpis.kpi_keys }}",
                    "compare": "{{ $.form.scope.compare_with }}",
                },
                "outputs": {"daily_data": "daily_data.json"},
            }
        ],
        "transforms": [
            {
                "id": "daily_kpi",
                "kind": "script",
                "name": "data-analyst/daily_kpi",
                "args": {"input": "daily_data.daily_data"},
                "outputs": {"daily_kpi": "daily_kpi.json"},
            }
        ],
        "sections": [
            {
                "id": "overview",
                "title": "总览",
                "component": "markdown",
                "source": "$.steps.daily_kpi.daily_kpi.overall_status.summary",
            },
            {
                "id": "kpi_cards",
                "title": "核心 KPI",
                "component": "card_group",
                "source": "$.steps.daily_kpi.daily_kpi.kpi_summary",
            },
            {
                "id": "trend",
                "title": "趋势图",
                "component": "echart",
                "source": "$.steps.daily_kpi.daily_kpi.trend_chart",
            },
            {
                "id": "anomalies",
                "title": "异常排行",
                "component": "table",
                "source": "$.steps.daily_kpi.daily_kpi.top_anomalies",
            },
            {
                "id": "alarms",
                "title": "告警事件",
                "component": "table",
                "source": "$.steps.daily_kpi.daily_kpi.alarm_table",
            },
            {
                "id": "recommendations",
                "title": "建议",
                "component": "markdown",
                "source": "$.steps.daily_kpi.daily_kpi.recommendations",
            },
        ],
        "export": {"formats": ["md", "pdf"], "renderer": "generic_report"},
    }


class TestSpec52Smoke:
    def test_spec_52_validates_with_registry(self, registry):
        report = validate_dsl(_spec_52_dsl(), registry=registry)
        assert report.valid is True, report.to_dict()
        assert report.errors == []

    def test_spec_52_validates_without_registry(self):
        # static-only pass should also be clean.
        report = validate_dsl(_spec_52_dsl())
        assert report.valid is True, report.to_dict()
