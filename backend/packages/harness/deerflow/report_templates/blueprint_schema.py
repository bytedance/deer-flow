"""Blueprint definition schema for the template marketplace.

A blueprint is a "template of templates" — a pre-filled DSL skeleton with
annotations that guide users through configuring the business-specific parts.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from deerflow.report_templates.schema import ReportTemplateDSL

BlueprintCategory = Literal[
    "daily_report",
    "weekly_report",
    "monthly_report",
    "fault_diagnosis",
    "failure_analysis",
    "closure_summary",
    "inspection",
]


class ConfigurableField(BaseModel):
    """A DSL field path that the user should configure when using this blueprint."""

    model_config = ConfigDict(extra="forbid")

    path: str = Field(description="Dot-separated path, e.g. 'form_steps.0.fields.0.default'")
    label: str = Field(description="Human-readable label shown in the wizard")
    hint: str | None = Field(default=None, description="Optional tooltip or guidance")


class PreviewSection(BaseModel):
    """Description of an expected output section for preview purposes."""

    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    component: str
    description: str | None = None


class BlueprintDefinition(BaseModel):
    """A complete blueprint definition."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="Unique blueprint identifier, e.g. 'daily-equipment'")
    name: str = Field(description="Short display name")
    description: str = Field(description="What this blueprint produces")
    category: BlueprintCategory
    icon: str | None = Field(default=None, description="Icon name for the catalog card")
    tags: list[str] = Field(default_factory=list)

    base_dsl: ReportTemplateDSL = Field(description="Pre-filled DSL that the editor starts with")
    user_configurable: list[ConfigurableField] = Field(
        default_factory=list,
        description="Field paths the wizard highlights for user configuration",
    )
    recommended_scripts: list[str] = Field(
        default_factory=list,
        description="Script registry names used by this blueprint",
    )
    preview_sections: list[PreviewSection] = Field(
        default_factory=list,
        description="Expected output sections for the preview pane",
    )
