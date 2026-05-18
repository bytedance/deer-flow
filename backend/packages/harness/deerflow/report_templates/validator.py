"""DSL Validator — three-pass validation of a parsed ``ReportTemplateDSL``.

Implements §14.1 of the design (structured ``{code, path, message, severity}``
errors), powered by:

1. **Static pass**: cross-references, ``next`` graph reachability, options_source
   step ordering, JSONPath whitelist syntax.
2. **Registry pass**: script ``name`` namespaces (``<skill>/<script>``) must
   exist in the active Script Registry; argument keys / required-ness checked
   against ``args_schema``.
3. **Type pass**: ``sections[].component`` ↔ ``source`` output type basic
   sanity (best-effort; full type tracking is a Phase 4 improvement).

Top-level entry: ``validate_dsl(dsl_dict, *, registry=None) -> ValidationReport``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Iterable, Literal

from pydantic import ValidationError

logger = logging.getLogger(__name__)

from deerflow.report_templates.schema import (
    DataStep,
    FormStep,
    OptionsSource,
    ReportTemplateDSL,
    Section,
    TransformStep,
)
from deerflow.report_templates.script_registry import (
    ArgSpec,
    ScriptDescriptor,
    ScriptRegistry,
)
from deerflow.report_templates.source_resolver import (
    PathSyntaxError,
    extract_expressions,
    parse,
)

Severity = Literal["error", "warning"]


@dataclass(frozen=True)
class ValidationIssue:
    """One issue reported by the validator."""

    code: str
    path: str
    message: str
    severity: Severity = "error"

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "path": self.path,
            "message": self.message,
            "severity": self.severity,
        }


@dataclass
class ValidationReport:
    """Outcome of validating a DSL document."""

    valid: bool
    errors: list[ValidationIssue] = field(default_factory=list)
    warnings: list[ValidationIssue] = field(default_factory=list)
    dsl: ReportTemplateDSL | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "errors": [e.to_dict() for e in self.errors],
            "warnings": [w.to_dict() for w in self.warnings],
        }


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------


def validate_dsl(
    dsl_dict: dict[str, Any] | ReportTemplateDSL,
    *,
    registry: ScriptRegistry | None = None,
) -> ValidationReport:
    """Validate a DSL document. Pass ``registry=None`` to skip script existence checks."""
    errors: list[ValidationIssue] = []
    warnings: list[ValidationIssue] = []

    # ── Pass 0: Pydantic shape ─────────────────────────────────────────
    if isinstance(dsl_dict, ReportTemplateDSL):
        dsl = dsl_dict
    else:
        try:
            dsl = ReportTemplateDSL.model_validate(dsl_dict)
        except ValidationError as e:
            for err in e.errors():
                errors.append(
                    ValidationIssue(
                        code="SCHEMA_INVALID",
                        path=".".join(str(p) for p in err["loc"]),
                        message=err["msg"],
                    )
                )
            report = ValidationReport(valid=False, errors=errors, warnings=warnings)
            _emit_validator_telemetry(report)
            return report

    # ── Build execution ordering for static reference checks ───────────
    # All step IDs that, after execution, contribute outputs into the
    # JSONPath ``$.steps`` namespace. Order matters for options_source.
    step_order: list[str] = []
    step_kind: dict[str, str] = {}
    step_outputs: dict[str, set[str]] = {}

    # Form before_steps execute when their owning form_step is rendered.
    for fs in dsl.form_steps:
        if fs.before_step is not None:
            step_order.append(fs.before_step.id)
            step_kind[fs.before_step.id] = "before_step"
            # Outputs of a before_step are produced by its registered script.
            # We can't enumerate them without registry; capture as None and
            # let the registry pass populate.
            step_outputs[fs.before_step.id] = set()

    # data_steps + transforms run during ``generate`` after all forms.
    for ds in dsl.data_steps:
        step_order.append(ds.id)
        step_kind[ds.id] = "data_step"
        step_outputs[ds.id] = set(ds.outputs.keys())
    for tr in dsl.transforms:
        step_order.append(tr.id)
        step_kind[tr.id] = "transform"
        step_outputs[tr.id] = set(tr.outputs.keys())

    # form_step ids are referenced from JSONPath via ``$.form.<step_id>.<field>``
    form_field_names: dict[str, set[str]] = {
        fs.id: {f.name for f in fs.fields} for fs in dsl.form_steps
    }
    form_ids = list(form_field_names.keys())

    # ── Pass 1: Static cross-references ────────────────────────────────
    _check_next_graph(dsl.form_steps, errors)
    _check_options_source_ordering(dsl.form_steps, step_order, step_outputs, errors)
    _check_field_jsonpath_placeholders(dsl, form_field_names, step_outputs, errors, warnings)
    _check_section_sources(dsl.sections, step_outputs, errors)

    # ── Pass 2: Script registry ────────────────────────────────────────
    if registry is not None:
        _check_script_references(dsl, registry, step_outputs, errors)

    # ── Pass 3: Section component / source type sanity ─────────────────
    _check_section_component_type_hints(dsl.sections, warnings)

    report = ValidationReport(
        valid=not errors,
        errors=errors,
        warnings=warnings,
        dsl=dsl,
    )
    _emit_validator_telemetry(report)
    return report


def _emit_validator_telemetry(report: ValidationReport) -> None:
    """Fire a Phase 7 ``validator_outcome`` event. Never raises.

    For invalid reports we emit one event per distinct error code so the
    charter §4.3 "error-code distribution" can be reconstructed from counters
    alone, without re-aggregating raw events.
    """
    try:
        from deerflow.report_templates.telemetry import get_telemetry

        tele = get_telemetry()
        if report.valid:
            tele.record_validator(outcome="valid", error_code=None)
            return
        seen: set[str] = set()
        for issue in report.errors:
            if issue.code in seen:
                continue
            seen.add(issue.code)
            tele.record_validator(outcome="invalid", error_code=issue.code)
        if not report.errors:
            # Defensive: a !valid report with no errors shouldn't happen,
            # but if it does we still want a single counter increment.
            tele.record_validator(outcome="invalid", error_code=None)
    except Exception:  # noqa: BLE001
        logger.debug("validator telemetry failed", exc_info=True)


# ---------------------------------------------------------------------------
# Pass 1 helpers
# ---------------------------------------------------------------------------


def _check_next_graph(form_steps: list[FormStep], errors: list[ValidationIssue]) -> None:
    """Each form_step.next must point to an existing form_step id or ``generate``."""
    ids = {fs.id for fs in form_steps}
    for fs in form_steps:
        if fs.next == "generate":
            continue
        if fs.next not in ids:
            errors.append(
                ValidationIssue(
                    code="UNKNOWN_NEXT",
                    path=f"form_steps[{fs.id}].next",
                    message=f"next={fs.next!r} does not match any form_step id or 'generate'",
                )
            )
        elif fs.next == fs.id:
            errors.append(
                ValidationIssue(
                    code="NEXT_SELF_LOOP",
                    path=f"form_steps[{fs.id}].next",
                    message=f"form_step {fs.id!r} cannot point to itself",
                )
            )


def _check_options_source_ordering(
    form_steps: list[FormStep],
    step_order: list[str],
    step_outputs: dict[str, set[str]],
    errors: list[ValidationIssue],
) -> None:
    """An options_source.step must have been executed before the consuming form_step.

    The order is: for each form_step, its own before_step runs first, then its
    fields can reference any earlier (or own) before_step.
    """
    executed: set[str] = set()
    for fs in form_steps:
        if fs.before_step is not None:
            executed.add(fs.before_step.id)
        for field_obj in fs.fields:
            src = field_obj.options_source
            if src is None:
                continue
            _check_one_options_source(fs.id, field_obj.name, src, executed, step_outputs, errors)


def _check_one_options_source(
    form_step_id: str,
    field_name: str,
    src: OptionsSource,
    executed: set[str],
    step_outputs: dict[str, set[str]],
    errors: list[ValidationIssue],
) -> None:
    path = f"form_steps[{form_step_id}].fields[{field_name}].options_source"
    if src.step not in executed:
        errors.append(
            ValidationIssue(
                code="OPTIONS_SOURCE_NOT_EXECUTED",
                path=f"{path}.step",
                message=(
                    f"options_source.step={src.step!r} is not executed before this form step; "
                    f"executed-so-far: {sorted(executed)}"
                ),
            )
        )


def _check_field_jsonpath_placeholders(
    dsl: ReportTemplateDSL,
    form_field_names: dict[str, set[str]],
    step_outputs: dict[str, set[str]],
    errors: list[ValidationIssue],
    warnings: list[ValidationIssue],
) -> None:
    """Walk every ``args`` / ``input`` field and validate ``{{ ... }}`` placeholders."""

    def _visit_args(args: dict[str, Any], owner_path: str) -> None:
        for k, v in args.items():
            if isinstance(v, str):
                _validate_placeholders(v, form_field_names, step_outputs, f"{owner_path}.{k}", errors)
            elif isinstance(v, dict):
                _visit_args(v, f"{owner_path}.{k}")
            elif isinstance(v, list):
                for i, item in enumerate(v):
                    if isinstance(item, str):
                        _validate_placeholders(
                            item, form_field_names, step_outputs, f"{owner_path}.{k}[{i}]", errors
                        )

    for fs in dsl.form_steps:
        if fs.before_step is not None:
            _visit_args(fs.before_step.args, f"form_steps[{fs.id}].before_step.args")
    for ds in dsl.data_steps:
        _visit_args(ds.args, f"data_steps[{ds.id}].args")
    for tr in dsl.transforms:
        _visit_args(tr.args, f"transforms[{tr.id}].args")


def _validate_placeholders(
    text: str,
    form_field_names: dict[str, set[str]],
    step_outputs: dict[str, set[str]],
    owner_path: str,
    errors: list[ValidationIssue],
) -> None:
    for expr in extract_expressions(text):
        try:
            ast = parse(expr)
        except PathSyntaxError as e:
            errors.append(
                ValidationIssue(
                    code="INVALID_PLACEHOLDER_SYNTAX",
                    path=owner_path,
                    message=f"invalid JSONPath {expr!r}: {e}",
                )
            )
            continue
        # AST shape: [Root, *segments]. Inspect 1st segment.
        segments = ast[1:]
        if not segments:
            continue
        head = segments[0]
        head_name = getattr(head, "name", "")
        if head_name == "form":
            # form.<step_id>.<field>
            if len(segments) < 3:
                errors.append(
                    ValidationIssue(
                        code="FORM_PATH_TOO_SHORT",
                        path=owner_path,
                        message=f"form path must reference a step and field: {expr!r}",
                    )
                )
                continue
            step_seg, field_seg = getattr(segments[1], "name", ""), getattr(segments[2], "name", "")
            if step_seg not in form_field_names:
                errors.append(
                    ValidationIssue(
                        code="UNKNOWN_FORM_STEP",
                        path=owner_path,
                        message=f"form_step {step_seg!r} not declared (in {expr!r})",
                    )
                )
            elif field_seg not in form_field_names[step_seg]:
                errors.append(
                    ValidationIssue(
                        code="UNKNOWN_FORM_FIELD",
                        path=owner_path,
                        message=f"field {field_seg!r} not declared in form_step {step_seg!r} (in {expr!r})",
                    )
                )
        elif head_name == "steps":
            if len(segments) < 3:
                errors.append(
                    ValidationIssue(
                        code="STEPS_PATH_TOO_SHORT",
                        path=owner_path,
                        message=f"steps path must reference a step and output: {expr!r}",
                    )
                )
                continue
            step_seg = getattr(segments[1], "name", "")
            output_seg = getattr(segments[2], "name", "")
            if step_seg not in step_outputs:
                errors.append(
                    ValidationIssue(
                        code="UNKNOWN_STEP",
                        path=owner_path,
                        message=f"step {step_seg!r} not declared (in {expr!r})",
                    )
                )
            elif step_outputs[step_seg] and output_seg not in step_outputs[step_seg]:
                # before_step outputs are typed only by registry; skip when empty.
                errors.append(
                    ValidationIssue(
                        code="UNKNOWN_STEP_OUTPUT",
                        path=owner_path,
                        message=(
                            f"output {output_seg!r} not declared by step {step_seg!r}; "
                            f"available: {sorted(step_outputs[step_seg])}"
                        ),
                    )
                )


def _check_section_sources(
    sections: list[Section],
    step_outputs: dict[str, set[str]],
    errors: list[ValidationIssue],
) -> None:
    """``sections[].source`` is a dotted path; require it to reference a known step."""
    for sec in sections:
        src = sec.source.strip()
        # Try JSONPath form first (`$.steps.X.Y...`)
        if src.startswith("$.") or src.startswith("steps."):
            try:
                ast = parse(src)
            except PathSyntaxError as e:
                errors.append(
                    ValidationIssue(
                        code="INVALID_SOURCE_SYNTAX",
                        path=f"sections[{sec.id}].source",
                        message=f"invalid JSONPath: {e}",
                    )
                )
                continue
            segments = ast[1:]
            if not segments or getattr(segments[0], "name", "") != "steps":
                errors.append(
                    ValidationIssue(
                        code="SECTION_SOURCE_NOT_STEPS",
                        path=f"sections[{sec.id}].source",
                        message="section.source must start with $.steps.<id>.<output> (got non-steps root)",
                    )
                )
                continue
            if len(segments) < 3:
                errors.append(
                    ValidationIssue(
                        code="SECTION_SOURCE_TOO_SHORT",
                        path=f"sections[{sec.id}].source",
                        message="source must reference a step and output",
                    )
                )
                continue
            step_seg = getattr(segments[1], "name", "")
            output_seg = getattr(segments[2], "name", "")
            if step_seg not in step_outputs:
                errors.append(
                    ValidationIssue(
                        code="UNKNOWN_STEP",
                        path=f"sections[{sec.id}].source",
                        message=f"step {step_seg!r} not declared",
                    )
                )
            elif step_outputs[step_seg] and output_seg not in step_outputs[step_seg]:
                errors.append(
                    ValidationIssue(
                        code="UNKNOWN_STEP_OUTPUT",
                        path=f"sections[{sec.id}].source",
                        message=(
                            f"output {output_seg!r} not declared by step {step_seg!r}; "
                            f"available: {sorted(step_outputs[step_seg])}"
                        ),
                    )
                )
        else:
            # Legacy short form ``step.output.path...`` (no $/steps prefix).
            parts = src.split(".")
            if len(parts) < 2:
                errors.append(
                    ValidationIssue(
                        code="SECTION_SOURCE_TOO_SHORT",
                        path=f"sections[{sec.id}].source",
                        message="source must reference at least <step>.<output>",
                    )
                )
                continue
            step_seg, output_seg = parts[0], parts[1]
            if step_seg not in step_outputs:
                errors.append(
                    ValidationIssue(
                        code="UNKNOWN_STEP",
                        path=f"sections[{sec.id}].source",
                        message=f"step {step_seg!r} not declared",
                    )
                )
            elif step_outputs[step_seg] and output_seg not in step_outputs[step_seg]:
                errors.append(
                    ValidationIssue(
                        code="UNKNOWN_STEP_OUTPUT",
                        path=f"sections[{sec.id}].source",
                        message=(
                            f"output {output_seg!r} not declared by step {step_seg!r}; "
                            f"available: {sorted(step_outputs[step_seg])}"
                        ),
                    )
                )


# ---------------------------------------------------------------------------
# Pass 2 — Script registry
# ---------------------------------------------------------------------------


def _check_script_references(
    dsl: ReportTemplateDSL,
    registry: ScriptRegistry,
    step_outputs: dict[str, set[str]],
    errors: list[ValidationIssue],
) -> None:
    """Every script ``name`` (``<skill>/<script>``) must be in the registry.

    Also enriches ``step_outputs`` for before_step from the registry's
    declared ``output_files`` / ``outputs_schema`` so subsequent passes can
    catch unknown outputs. (We mutate ``step_outputs`` in place — caller is OK
    with this.)
    """
    for fs in dsl.form_steps:
        if fs.before_step is None:
            continue
        path = f"form_steps[{fs.id}].before_step"
        desc = _require_registered(fs.before_step.name, path, registry, errors)
        if desc is None:
            continue
        _check_args_against_schema(fs.before_step.args, desc, f"{path}.args", errors)
        _record_known_outputs(step_outputs, fs.before_step.id, desc)

    for ds in dsl.data_steps:
        path = f"data_steps[{ds.id}]"
        desc = _require_registered(ds.name, path, registry, errors)
        if desc is None:
            continue
        _check_args_against_schema(ds.args, desc, f"{path}.args", errors)
        _record_known_outputs(step_outputs, ds.id, desc)

    for tr in dsl.transforms:
        path = f"transforms[{tr.id}]"
        desc = _require_registered(tr.name, path, registry, errors)
        if desc is None:
            continue
        # ``input: <step_id>.<output_id>`` is a transform-level convenience the
        # runtime auto-resolves to ``args.input`` (an absolute file_path). Treat
        # it as a satisfied required arg during validation.
        effective_args = dict(tr.args)
        if tr.input and "input" not in effective_args:
            effective_args["input"] = tr.input
        _check_args_against_schema(effective_args, desc, f"{path}.args", errors)
        _record_known_outputs(step_outputs, tr.id, desc)


def _require_registered(
    qualified_name: str,
    path: str,
    registry: ScriptRegistry,
    errors: list[ValidationIssue],
) -> ScriptDescriptor | None:
    if "/" not in qualified_name:
        errors.append(
            ValidationIssue(
                code="MISSING_SKILL_NAMESPACE",
                path=f"{path}.name",
                message=(
                    f"script name {qualified_name!r} must be namespaced as 'skill/script' "
                    "(e.g. 'data-analyst/query_daily')"
                ),
            )
        )
        return None
    desc = registry.get(qualified_name)
    if desc is None:
        errors.append(
            ValidationIssue(
                code="UNKNOWN_SCRIPT",
                path=f"{path}.name",
                message=(
                    f"script {qualified_name!r} not in registry; "
                    f"registered: {sorted(registry.scripts.keys())}"
                ),
            )
        )
        return None
    return desc


def _check_args_against_schema(
    args: dict[str, Any],
    desc: ScriptDescriptor,
    args_path: str,
    errors: list[ValidationIssue],
) -> None:
    declared = set(desc.args_schema.keys())
    provided = set(args.keys())

    # Unknown args
    for name in sorted(provided - declared):
        errors.append(
            ValidationIssue(
                code="UNKNOWN_ARG",
                path=f"{args_path}.{name}",
                message=f"argument {name!r} not declared in script args_schema",
            )
        )

    # Missing required args
    for name in sorted(declared - provided):
        spec: ArgSpec = desc.args_schema[name]
        if spec.required:
            errors.append(
                ValidationIssue(
                    code="MISSING_REQUIRED_ARG",
                    path=f"{args_path}.{name}",
                    message=f"required argument {name!r} not provided",
                )
            )

    # Enum value check for **literal** values only (we cannot resolve
    # ``{{ ... }}`` placeholders at validate time).
    for name in sorted(declared & provided):
        spec = desc.args_schema[name]
        value = args[name]
        if spec.values is not None and not _is_placeholder_string(value):
            if value not in spec.values:
                errors.append(
                    ValidationIssue(
                        code="ARG_VALUE_NOT_ALLOWED",
                        path=f"{args_path}.{name}",
                        message=(
                            f"value {value!r} not in allowed set {spec.values}"
                        ),
                    )
                )


def _is_placeholder_string(value: Any) -> bool:
    return isinstance(value, str) and "{{" in value and "}}" in value


def _record_known_outputs(
    step_outputs: dict[str, set[str]],
    step_id: str,
    desc: ScriptDescriptor,
) -> None:
    outputs = set(step_outputs.get(step_id, set()))
    for of in desc.output_files:
        outputs.add(of.id)
    if desc.outputs_schema:
        outputs.update(desc.outputs_schema.keys())
    step_outputs[step_id] = outputs


# ---------------------------------------------------------------------------
# Pass 3 — Best-effort component / source compatibility
# ---------------------------------------------------------------------------


# Loose hints: section component → preferred output id substring or naming
# convention. This is a warning-only pass to surface "echart pointing at a
# string" without doing full type inference at validate time.
_COMPONENT_HINTS: dict[str, Iterable[str]] = {
    "echart": ("chart", "option"),
    "table": ("table", "rows", "data", "anomalies", "alarms", "events", "list"),
    "card": ("card", "kpi", "summary"),
    "card_group": ("cards", "kpis", "items", "summary"),
    "markdown": ("summary", "content", "markdown", "recommendations", "advice"),
}


def _check_section_component_type_hints(
    sections: list[Section],
    warnings: list[ValidationIssue],
) -> None:
    for sec in sections:
        hints = _COMPONENT_HINTS.get(sec.component)
        if not hints:
            continue
        last_seg = sec.source.rstrip().rsplit(".", maxsplit=1)[-1].lower()
        if not any(h in last_seg for h in hints):
            warnings.append(
                ValidationIssue(
                    code="SECTION_TYPE_HINT_MISMATCH",
                    path=f"sections[{sec.id}].source",
                    message=(
                        f"source tail {last_seg!r} does not look like a {sec.component} payload; "
                        f"expected substring of {sorted(hints)}"
                    ),
                    severity="warning",
                )
            )
