"""Unit tests for report_templates.schema — DSL Pydantic shape validation.

Cross-reference / type-match / script-existence validation lives in
``test_report_template_validator.py``. These tests only assert pure schema
shape and per-field invariants.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest
from pydantic import ValidationError

from deerflow.report_templates.schema import (
    DSL_SCHEMA_VERSION,
    DataStep,
    FormField,
    FormStep,
    ReportTemplateDSL,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _minimal_dsl_dict() -> dict[str, Any]:
    """A minimal DSL document that parses cleanly. Reused across tests."""
    return {
        "dsl_version": DSL_SCHEMA_VERSION,
        "name": "demo",
        "display_name": "Demo Template",
        "description": "Smoke fixture",
        "visibility": "private",
        "form_steps": [
            {
                "id": "scope",
                "title": "Scope",
                "fields": [
                    {"name": "report_date", "label": "Date", "type": "date", "required": True}
                ],
                "next": "generate",
            }
        ],
        "data_steps": [
            {
                "id": "data1",
                "kind": "script",
                "name": "daily-report/query_daily",
                "args": {"date": "{{ $.form.scope.report_date }}"},
                "outputs": {"daily_data": "daily_data.json"},
            }
        ],
        "transforms": [
            {
                "id": "kpi1",
                "kind": "script",
                "name": "daily-report/daily_kpi",
                "input": "data1.daily_data",
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


@pytest.fixture
def minimal_dsl() -> dict[str, Any]:
    return _minimal_dsl_dict()


# ---------------------------------------------------------------------------
# Top-level
# ---------------------------------------------------------------------------


class TestTopLevel:
    def test_minimal_dsl_parses(self, minimal_dsl):
        ReportTemplateDSL.model_validate(minimal_dsl)

    def test_rejects_unsupported_dsl_version(self, minimal_dsl):
        minimal_dsl["dsl_version"] = "0"
        with pytest.raises(ValidationError, match="dsl_version"):
            ReportTemplateDSL.model_validate(minimal_dsl)

    def test_rejects_extra_keys_at_root(self, minimal_dsl):
        minimal_dsl["mystery_field"] = 1
        with pytest.raises(ValidationError, match="Extra inputs"):
            ReportTemplateDSL.model_validate(minimal_dsl)

    def test_requires_form_steps(self, minimal_dsl):
        minimal_dsl["form_steps"] = []
        with pytest.raises(ValidationError):
            ReportTemplateDSL.model_validate(minimal_dsl)

    def test_requires_sections(self, minimal_dsl):
        minimal_dsl["sections"] = []
        with pytest.raises(ValidationError):
            ReportTemplateDSL.model_validate(minimal_dsl)

    def test_visibility_must_be_enum(self, minimal_dsl):
        minimal_dsl["visibility"] = "world"
        with pytest.raises(ValidationError):
            ReportTemplateDSL.model_validate(minimal_dsl)


# ---------------------------------------------------------------------------
# Form fields
# ---------------------------------------------------------------------------


class TestFormField:
    def test_text_field_no_options(self):
        FormField.model_validate({"name": "x", "label": "X", "type": "text"})

    def test_select_with_static_options(self):
        FormField.model_validate(
            {
                "name": "t",
                "label": "Type",
                "type": "select",
                "options": [{"label": "All", "value": "all"}],
            }
        )

    def test_select_with_options_source(self):
        FormField.model_validate(
            {
                "name": "ids",
                "label": "Equipment",
                "type": "multi-select",
                "options_source": {
                    "step": "catalog",
                    "path": "equipment",
                    "label": "id",
                    "value": "id",
                },
            }
        )

    def test_select_without_options_or_source_rejected(self):
        with pytest.raises(ValidationError, match="options"):
            FormField.model_validate({"name": "x", "label": "X", "type": "select"})

    def test_select_with_both_options_and_source_rejected(self):
        with pytest.raises(ValidationError, match="cannot declare both"):
            FormField.model_validate(
                {
                    "name": "x",
                    "label": "X",
                    "type": "select",
                    "options": [{"label": "A", "value": "a"}],
                    "options_source": {
                        "step": "s",
                        "path": "p",
                        "label": "l",
                        "value": "v",
                    },
                }
            )

    def test_text_field_cannot_have_options(self):
        with pytest.raises(ValidationError, match="cannot have options"):
            FormField.model_validate(
                {
                    "name": "x",
                    "label": "X",
                    "type": "text",
                    "options": [{"label": "A", "value": "a"}],
                }
            )

    def test_checkbox_field_cannot_have_options(self):
        with pytest.raises(ValidationError, match="cannot"):
            FormField.model_validate(
                {
                    "name": "x",
                    "label": "X",
                    "type": "checkbox",
                    "options": [{"label": "A", "value": "a"}],
                }
            )

    def test_unknown_field_type_rejected(self):
        with pytest.raises(ValidationError):
            FormField.model_validate({"name": "x", "label": "X", "type": "rangepicker"})

    def test_validation_allows_min_max_pattern(self):
        FormField.model_validate(
            {
                "name": "n",
                "label": "N",
                "type": "number",
                "validation": {"min": 0, "max": 100},
            }
        )
        FormField.model_validate(
            {
                "name": "m",
                "label": "M",
                "type": "text",
                "validation": {"pattern": "^[a-z]+$"},
            }
        )


# ---------------------------------------------------------------------------
# Form step
# ---------------------------------------------------------------------------


class TestFormStep:
    def test_step_requires_at_least_one_field(self):
        with pytest.raises(ValidationError):
            FormStep.model_validate(
                {"id": "s", "title": "S", "fields": [], "next": "generate"}
            )

    def test_step_rejects_duplicate_field_names(self):
        with pytest.raises(ValidationError, match="duplicate"):
            FormStep.model_validate(
                {
                    "id": "s",
                    "title": "S",
                    "fields": [
                        {"name": "x", "label": "X", "type": "text"},
                        {"name": "x", "label": "Y", "type": "text"},
                    ],
                    "next": "generate",
                }
            )

    def test_step_with_before_step(self):
        FormStep.model_validate(
            {
                "id": "equipment",
                "title": "Choose",
                "before_step": {
                    "id": "catalog",
                    "kind": "script",
                    "name": "daily-report/list_equipment",
                    "args": {"type": "pump"},
                },
                "fields": [{"name": "ids", "label": "IDs", "type": "text"}],
                "next": "generate",
            }
        )


# ---------------------------------------------------------------------------
# Data step / transform
# ---------------------------------------------------------------------------


class TestDataStep:
    def test_minimal_data_step(self):
        DataStep.model_validate({"id": "d", "kind": "script", "name": "ns/foo"})

    def test_data_step_kind_must_be_script(self):
        with pytest.raises(ValidationError):
            DataStep.model_validate({"id": "d", "kind": "other", "name": "ns/foo"})


# ---------------------------------------------------------------------------
# ID uniqueness across step namespaces
# ---------------------------------------------------------------------------


class TestUniqueIds:
    def test_form_step_and_data_step_cannot_share_id(self, minimal_dsl):
        minimal_dsl["data_steps"][0]["id"] = "scope"  # collides with form_step id
        with pytest.raises(ValidationError, match="reused"):
            ReportTemplateDSL.model_validate(minimal_dsl)

    def test_before_step_id_cannot_collide_with_data_step(self, minimal_dsl):
        minimal_dsl["form_steps"][0]["before_step"] = {
            "id": "data1",  # collides
            "kind": "script",
            "name": "ns/x",
        }
        with pytest.raises(ValidationError, match="reused"):
            ReportTemplateDSL.model_validate(minimal_dsl)

    def test_duplicate_section_id_rejected(self, minimal_dsl):
        minimal_dsl["sections"].append(copy.deepcopy(minimal_dsl["sections"][0]))
        with pytest.raises(ValidationError, match="duplicate section"):
            ReportTemplateDSL.model_validate(minimal_dsl)


# ---------------------------------------------------------------------------
# Export config
# ---------------------------------------------------------------------------


class TestExportConfig:
    def test_default_includes_markdown(self, minimal_dsl):
        del minimal_dsl["export"]
        parsed = ReportTemplateDSL.model_validate(minimal_dsl)
        assert "md" in parsed.export.formats

    def test_markdown_required(self, minimal_dsl):
        minimal_dsl["export"]["formats"] = ["pdf"]
        with pytest.raises(ValidationError, match="Markdown is mandatory"):
            ReportTemplateDSL.model_validate(minimal_dsl)

    def test_unknown_format_rejected(self, minimal_dsl):
        minimal_dsl["export"]["formats"] = ["md", "docx"]
        with pytest.raises(ValidationError):
            ReportTemplateDSL.model_validate(minimal_dsl)


# ---------------------------------------------------------------------------
# Section
# ---------------------------------------------------------------------------


class TestSection:
    def test_section_requires_component(self, minimal_dsl):
        minimal_dsl["sections"][0]["component"] = "weird"
        with pytest.raises(ValidationError):
            ReportTemplateDSL.model_validate(minimal_dsl)
