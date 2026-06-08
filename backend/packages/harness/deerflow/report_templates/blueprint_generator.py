"""Generate blueprint definitions from builtin report templates.

Reverse-engineers blueprints from the 7 shipped builtin templates by:
1. Loading the YAML DSL
2. Extracting configurable field paths (form field defaults, descriptions)
3. Collecting script references from data_steps and transforms
4. Building preview section metadata
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from deerflow.report_templates.blueprint_schema import (
    BlueprintCategory,
    BlueprintDefinition,
    ConfigurableField,
    PreviewSection,
)
from deerflow.report_templates.schema import ReportTemplateDSL

logger = logging.getLogger(__name__)

BUILTIN_TEMPLATES_DIR = Path(__file__).parent.parent.parent.parent.parent.parent / "agents" / "builtin" / "report-templates"

TEMPLATE_TO_CATEGORY: dict[str, BlueprintCategory] = {
    "daily-equipment": "daily_report",
    "weekly-equipment": "weekly_report",
    "monthly-equipment": "monthly_report",
    "diagnosis-fault": "fault_diagnosis",
    "failure-analysis": "failure_analysis",
    "closure-summary": "closure_summary",
    "inspection": "inspection",
}

TEMPLATE_ICONS: dict[str, str] = {
    "daily-equipment": "calendar-day",
    "weekly-equipment": "calendar-week",
    "monthly-equipment": "calendar-month",
    "diagnosis-fault": "stethoscope",
    "failure-analysis": "alert-triangle",
    "closure-summary": "check-circle",
    "inspection": "clipboard-check",
}


def load_builtin_template(name: str) -> dict[str, Any]:
    """Load a builtin template YAML as a dict."""
    path = BUILTIN_TEMPLATES_DIR / name / "default.yaml"
    if not path.exists():
        raise FileNotFoundError(f"builtin template not found: {name}")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def extract_configurable_fields(dsl_dict: dict[str, Any]) -> list[ConfigurableField]:
    """Extract form field paths that users typically need to customize."""
    fields: list[ConfigurableField] = []

    form_steps = dsl_dict.get("form_steps", [])
    for step_idx, step in enumerate(form_steps):
        if step.get("component") == "device-selector-multi":
            continue

        step_fields = step.get("fields", [])
        for field_idx, field in enumerate(step_fields):
            field_name = field.get("name", "")
            field_label = field.get("label", field_name)

            if field.get("required") or field.get("default") is not None:
                fields.append(
                    ConfigurableField(
                        path=f"form_steps.{step_idx}.fields.{field_idx}.default",
                        label=field_label,
                        hint=f"Step '{step.get('title', step.get('id', ''))}' field: {field_name}",
                    )
                )

    return fields


def extract_recommended_scripts(dsl_dict: dict[str, Any]) -> list[str]:
    """Collect script names from data_steps, transforms, and before_steps."""
    scripts: list[str] = []

    for step in dsl_dict.get("data_steps", []):
        name = step.get("name")
        if name:
            scripts.append(name)

    for step in dsl_dict.get("transforms", []):
        name = step.get("name")
        if name:
            scripts.append(name)

    for step in dsl_dict.get("form_steps", []):
        before = step.get("before_step")
        if before and before.get("name"):
            scripts.append(before["name"])

    return list(dict.fromkeys(scripts))


def extract_preview_sections(dsl_dict: dict[str, Any]) -> list[PreviewSection]:
    """Build preview metadata from the sections array."""
    previews: list[PreviewSection] = []

    for section in dsl_dict.get("sections", []):
        previews.append(
            PreviewSection(
                id=section.get("id", ""),
                title=section.get("title", ""),
                component=section.get("component", ""),
                description=f"Source: {section.get('source', 'N/A')}",
            )
        )

    return previews


def generate_blueprint(template_name: str) -> BlueprintDefinition:
    """Generate a blueprint from a builtin template."""
    dsl_dict = load_builtin_template(template_name)
    dsl = ReportTemplateDSL.model_validate(dsl_dict)

    category = TEMPLATE_TO_CATEGORY.get(template_name, "daily_report")
    icon = TEMPLATE_ICONS.get(template_name)

    return BlueprintDefinition(
        id=template_name,
        name=dsl.display_name,
        description=dsl.description or f"Blueprint based on {template_name}",
        category=category,
        icon=icon,
        tags=[template_name.split("-")[0], category.replace("_", "-")],
        executor_type="direct",
        base_dsl=dsl,
        user_configurable=extract_configurable_fields(dsl_dict),
        recommended_scripts=extract_recommended_scripts(dsl_dict),
        preview_sections=extract_preview_sections(dsl_dict),
    )


def generate_all_blueprints() -> list[BlueprintDefinition]:
    """Generate blueprints for all 7 builtin templates."""
    blueprints: list[BlueprintDefinition] = []

    for template_name in TEMPLATE_TO_CATEGORY:
        try:
            bp = generate_blueprint(template_name)
            blueprints.append(bp)
            logger.info(f"Generated blueprint: {template_name}")
        except Exception as e:
            logger.warning(f"Failed to generate blueprint for {template_name}: {e}")

    return blueprints
