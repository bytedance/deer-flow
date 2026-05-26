"""DSL Pydantic schema for the report-template platform.

Implements §5 of docs/plans/2026-05-14-ai-report-custom-template-design.md.

Top-level: ``ReportTemplateDSL`` ←→ DSL v1 YAML document.

Layout:
    ReportTemplateDSL
        form_steps:    list[FormStep]
            fields:        list[FormField]
                options:        list[FormFieldOption]    # static
                options_source: OptionsSource | None     # dynamic
                validation:     FieldValidation | None
            before_step:   DataStepRef | None
        data_steps:    list[DataStep]
        transforms:    list[TransformStep]
        sections:      list[Section]
        export:        ExportConfig

The schema enforces *shape* only. Cross-references (e.g. ``next`` points to an
existing step, ``options_source.step`` refers to an earlier step, JSONPath
expressions resolve, script namespaces exist) are validated by ``validator.py``
in a subsequent pass — keeping the schema small and the validator's error
messages structured.

The schema accepts both placeholder forms (with or without ``$.`` prefix). The
validator decides whether to reject or auto-prefix per §5.6.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

DSL_SCHEMA_VERSION = "1"


# ---------------------------------------------------------------------------
# Form layer
# ---------------------------------------------------------------------------

FieldType = Literal["text", "textarea", "number", "date", "select", "checkbox", "multi-select"]


class FormFieldOption(BaseModel):
    """Single option for a ``select`` / ``multi-select`` field with static options."""

    model_config = ConfigDict(extra="forbid")

    label: str
    value: str | int | float | bool


class OptionsSource(BaseModel):
    """Dynamic options sourced from a previously-executed step's output."""

    model_config = ConfigDict(extra="forbid")

    step: str
    path: str
    label: str
    value: str
    group: str | None = None
    description: str | None = None
    max_items: int | None = Field(default=None, gt=0)


class FieldValidation(BaseModel):
    """MVP-only validation knobs — see §5.3."""

    model_config = ConfigDict(extra="forbid")

    pattern: str | None = None
    min: float | None = None
    max: float | None = None
    min_length: int | None = Field(default=None, ge=0)
    max_length: int | None = Field(default=None, ge=0)
    min_items: int | None = Field(default=None, ge=0)
    max_items: int | None = Field(default=None, ge=0)


class FormField(BaseModel):
    """Single form field — surface matches FormBlock.tsx component prop schema."""

    model_config = ConfigDict(extra="forbid")

    name: str
    label: str
    type: FieldType
    required: bool = False
    default: Any | None = None
    placeholder: str | None = None
    description: str | None = None
    searchable: bool | None = None
    options: list[FormFieldOption] | None = None
    options_source: OptionsSource | None = None
    validation: FieldValidation | None = None

    @model_validator(mode="after")
    def _check_options_for_select(self) -> "FormField":
        if self.type in ("select", "multi-select"):
            has_static = bool(self.options)
            has_dynamic = self.options_source is not None
            if not has_static and not has_dynamic:
                raise ValueError(
                    f"field {self.name!r} of type {self.type!r} must declare 'options' or 'options_source'"
                )
            if has_static and has_dynamic:
                raise ValueError(
                    f"field {self.name!r} cannot declare both 'options' and 'options_source'"
                )
        elif self.options or self.options_source:
            raise ValueError(
                f"field {self.name!r} of type {self.type!r} cannot have options/options_source"
            )
        if self.type == "checkbox" and (self.options or self.options_source):
            raise ValueError(
                f"checkbox field {self.name!r} cannot carry options; use multi-select instead"
            )
        return self


# ---------------------------------------------------------------------------
# Script execution layer (form before_step / data_steps / transforms)
# ---------------------------------------------------------------------------


class DataStepRef(BaseModel):
    """Inline script invocation embedded inside a form_step.before_step.

    Output ID is derived from the enclosing ``before_step.id`` so that downstream
    references can use ``$.steps.<before_step.id>.<output_id>``.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    kind: Literal["script"] = "script"
    name: str
    args: dict[str, Any] = Field(default_factory=dict)


class DeviceSelectorConfig(BaseModel):
    """Configuration for a ``device-selector-multi`` component step.

    When ``component: device-selector-multi``, the step renders a browser-side
    org-tree device picker instead of a traditional form. The ``type_id_from``
    field references a prior form field (e.g. ``scope.equipment_type``) whose
    value is mapped to both an organize-tree ``typeId`` query parameter and a
    ``filterDeviceType`` prop at render time.
    """

    model_config = ConfigDict(extra="forbid")

    type_id_from: str | None = None


class FormStep(BaseModel):
    """One step of the multi-step parameter wizard."""

    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    description: str | None = None
    component: Literal["form", "device-selector-multi"] = "form"
    before_step: DataStepRef | None = None
    fields: list[FormField] = Field(default_factory=list)
    next: str
    device_filter: DeviceSelectorConfig | None = None
    max_select: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _check_fields_for_component(self) -> "FormStep":
        if self.component == "device-selector-multi":
            if self.fields:
                raise ValueError(
                    f"step {self.id!r}: device-selector-multi must not declare 'fields'"
                )
            if self.before_step is not None:
                raise ValueError(
                    f"step {self.id!r}: device-selector-multi must not declare 'before_step'"
                )
        else:
            if not self.fields:
                raise ValueError(
                    f"step {self.id!r}: form component requires at least one field"
                )
        return self

    @model_validator(mode="after")
    def _check_unique_field_names(self) -> "FormStep":
        seen: set[str] = set()
        for f in self.fields:
            if f.name in seen:
                raise ValueError(f"step {self.id!r}: duplicate field name {f.name!r}")
            seen.add(f.name)
        return self


class DataStep(BaseModel):
    """A top-level data fetch step executed during report generation."""

    model_config = ConfigDict(extra="forbid")

    id: str
    kind: Literal["script"] = "script"
    name: str
    args: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, str] = Field(default_factory=dict)


class TransformStep(BaseModel):
    """A transform on a prior step's output — runs in DSL order after data_steps."""

    model_config = ConfigDict(extra="forbid")

    id: str
    kind: Literal["script"] = "script"
    name: str
    input: str | None = None
    args: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, str] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Section / Export layer
# ---------------------------------------------------------------------------

SectionComponent = Literal[
    "markdown", "card", "card_group", "echart", "table", "image", "closure_section"
]
ExportFormat = Literal["md", "pdf"]

ClosureStatusLiteral = Literal[
    "pending", "assigned", "in_progress", "pending_verification", "closed", "rejected"
]


class ClosureSectionFilters(BaseModel):
    """Filters consumed by the ``closure_section`` block at render time.

    Resolved against ``closed_loop.service.list_for_report`` — period bounds are
    ISO-8601 strings (``2026-05-01`` or ``2026-05-01T00:00:00+08:00``) so the
    DSL stays declarative and JSON-safe. ``device_ids`` may be either literal
    ids or ``{{ $.form.<step>.<field> }}`` placeholders that the renderer
    resolves before invoking the service.
    """

    model_config = ConfigDict(extra="forbid")

    device_ids: list[str] | None = None
    statuses: list[ClosureStatusLiteral] | None = None
    period_start: str | None = None
    period_end: str | None = None
    page_size: int = Field(default=200, gt=0, le=1000)
    include_overdue_only: bool = False


class Section(BaseModel):
    """A rendered section in the assembled report payload.

    ``source`` is required for every component except ``closure_section``,
    which sources its rows from the closure-ticket service via ``filters``.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    component: SectionComponent
    source: str | None = None
    props: dict[str, Any] | None = None
    filters: ClosureSectionFilters | None = None

    @model_validator(mode="after")
    def _check_component_payload(self) -> "Section":
        if self.component == "closure_section":
            if self.source is not None:
                raise ValueError(
                    f"section {self.id!r}: closure_section must not declare 'source' (use 'filters' instead)"
                )
            # filters may be omitted -> defaults to "all open tickets, no period bound"
        else:
            if self.source is None:
                raise ValueError(
                    f"section {self.id!r}: component {self.component!r} requires 'source'"
                )
            if self.filters is not None:
                raise ValueError(
                    f"section {self.id!r}: 'filters' is only valid for component 'closure_section'"
                )
        return self


class ExportConfig(BaseModel):
    """Export settings — Markdown required, PDF optional per §12.2."""

    model_config = ConfigDict(extra="forbid")

    formats: list[ExportFormat] = Field(default_factory=lambda: ["md"])
    renderer: str = "generic_report"

    @model_validator(mode="after")
    def _require_markdown(self) -> "ExportConfig":
        if "md" not in self.formats:
            raise ValueError("export.formats must contain 'md' — Markdown is mandatory")
        return self


# ---------------------------------------------------------------------------
# Top-level DSL document
# ---------------------------------------------------------------------------

Visibility = Literal["private", "tenant", "builtin"]


class ReportTemplateDSL(BaseModel):
    """A complete DSL v1 document."""

    model_config = ConfigDict(extra="forbid")

    dsl_version: str
    name: str
    display_name: str
    description: str = ""
    visibility: Visibility = "private"

    form_steps: list[FormStep] = Field(min_length=1)
    data_steps: list[DataStep] = Field(default_factory=list)
    transforms: list[TransformStep] = Field(default_factory=list)
    sections: list[Section] = Field(min_length=1)
    export: ExportConfig = Field(default_factory=ExportConfig)

    @model_validator(mode="after")
    def _check_dsl_version(self) -> "ReportTemplateDSL":
        if self.dsl_version != DSL_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported dsl_version {self.dsl_version!r}; expected {DSL_SCHEMA_VERSION!r}"
            )
        return self

    @model_validator(mode="after")
    def _unique_top_level_ids(self) -> "ReportTemplateDSL":
        # form_step ids must be unique among themselves; same for data_steps,
        # transforms, and sections. Cross-bucket collisions are also disallowed
        # because all step IDs share a single namespace in JSONPath context.
        used: dict[str, str] = {}
        for step in self.form_steps:
            self._claim(used, step.id, "form_step")
            if step.before_step is not None:
                self._claim(used, step.before_step.id, "before_step")
        for ds in self.data_steps:
            self._claim(used, ds.id, "data_step")
        for tr in self.transforms:
            self._claim(used, tr.id, "transform")
        section_ids: set[str] = set()
        for sec in self.sections:
            if sec.id in section_ids:
                raise ValueError(f"duplicate section id {sec.id!r}")
            section_ids.add(sec.id)
        return self

    @staticmethod
    def _claim(used: dict[str, str], step_id: str, kind: str) -> None:
        if step_id in used:
            raise ValueError(
                f"step id {step_id!r} reused: already declared as {used[step_id]!r}, now {kind!r}"
            )
        used[step_id] = kind
