"""Payload assembler — turn DSL sections + step_outputs into ``report_payload.json``.

Pipeline:
    sections[]:
        - source: JSONPath/dotted ref into the runtime context
        - component: "markdown" | "card" | "card_group" | "echart" | "table" | "image"

For each section, the assembler:
  1. Resolves ``source`` against the context (form / steps / run / template).
  2. Wraps the resolved value into the correct ``props`` dict for the
     downstream renderer:
       - markdown      → ``{content: str|list[str]}``
       - card          → object with title/value/description
       - card_group    → ``{items: [...]}``
       - echart        → ``{option: {...}}`` (raw ECharts option)
       - table         → ``{columns: [...], data: [...]}`` or ``{rows: [...]}``
       - image         → ``{src, alt}``
  3. Emits one section dict matching the §12.1 payload schema.

The output is JSON-safe (i.e. ``json.dumps()`` works) — runtime tools just
``json.dump()`` the payload to disk.
"""

from __future__ import annotations

from typing import Any

from deerflow.report_templates.records import now_iso
from deerflow.report_templates.runtime.state import RuntimeState
from deerflow.report_templates.source_resolver import (
    JSONPathError,
    PathNotFoundError,
    evaluate,
    parse,
)

REPORT_PAYLOAD_SCHEMA_VERSION = "1"


class PayloadBuildError(Exception):
    """Raised when a section cannot be assembled."""


def assemble_payload(
    *,
    dsl: dict[str, Any],
    state: RuntimeState,
) -> dict[str, Any]:
    """Build the ``report_payload.json`` dict for a finished run."""
    sections_out: list[dict[str, Any]] = []
    context = _context(state)

    for section in dsl.get("sections", []) or []:
        try:
            sections_out.append(_assemble_section(section, context))
        except (JSONPathError, PathNotFoundError) as e:
            raise PayloadBuildError(
                f"section {section.get('id')!r} failed to resolve source {section.get('source')!r}: {e}"
            ) from e

    return {
        "schema_version": REPORT_PAYLOAD_SCHEMA_VERSION,
        "title": dsl.get("display_name") or dsl.get("name", ""),
        "template": {
            "id": state.template_id,
            "version": state.template_version,
            "name": dsl.get("name", ""),
        },
        "run": {
            "id": state.report_run_id,
            "thread_id": state.thread_id,
            "run_id": "",  # filled by tools layer (LangGraph run id)
            "generated_at": now_iso(),
        },
        "parameters": _flatten_form_state(state.form_state),
        "sections": sections_out,
    }


def _assemble_section(section: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    source = section["source"].strip()
    # Auto-prefix short form ``step.output.path``.
    expr = source if source.startswith("$.") else f"$.steps.{source}"
    ast = parse(expr)
    value = evaluate(ast, context)
    component = section["component"]
    props = _wrap_props(component, value, section.get("props"))
    return {
        "id": section["id"],
        "component": component,
        "title": section.get("title", section["id"]),
        "props": props,
    }


def _wrap_props(component: str, value: Any, extra_props: dict | None) -> dict[str, Any]:
    """Convert a resolved source value into the renderer-friendly props dict."""
    base: dict[str, Any] = dict(extra_props or {})
    if component == "markdown":
        if not isinstance(value, (str, list)):
            raise PayloadBuildError(
                f"markdown source must be a string or list of strings, got {type(value).__name__}"
            )
        base["content"] = value
        return base
    if component == "card":
        # Standard form: card source resolves to {title, value, ...} dict.
        if isinstance(value, dict):
            base.update(value)
            return base
        # Banner / confidence-badge form: card source resolves to a scalar
        # (bool/str/int/float) and DSL author-supplied ``props`` carry the
        # banner ``style`` + ``template`` text. The scalar becomes ``value`` so
        # generic_renderer can fall back to ``template`` or display the value
        # (e.g. ``confidence: high`` → 🟢 High badge).
        if isinstance(value, (bool, str, int, float)):
            base.setdefault("value", value)
            return base
        raise PayloadBuildError(
            f"card source must be an object or scalar, got {type(value).__name__}"
        )
    if component == "card_group":
        if not isinstance(value, list):
            raise PayloadBuildError(
                f"card_group source must be a list of objects, got {type(value).__name__}"
            )
        base["items"] = value
        return base
    if component == "echart":
        if not isinstance(value, dict):
            raise PayloadBuildError(
                f"echart source must be an ECharts option object, got {type(value).__name__}"
            )
        base["option"] = value
        return base
    if component == "table":
        if isinstance(value, dict) and "columns" in value and "data" in value:
            base["columns"] = value["columns"]
            base["data"] = value["data"]
            return base
        if isinstance(value, list):
            base["rows"] = value
            return base
        raise PayloadBuildError(
            "table source must be {columns, data} or a list of row dicts"
        )
    if component == "image":
        if not isinstance(value, dict):
            raise PayloadBuildError("image source must be {src, alt} dict")
        base.update(value)
        return base
    raise PayloadBuildError(f"unsupported section component {component!r}")


def _context(state: RuntimeState) -> dict[str, Any]:
    return {
        "form": state.form_state,
        "steps": state.step_outputs,
        "run": {
            "report_run_id": state.report_run_id,
            "thread_id": state.thread_id,
            "generated_at": state.created_at,
        },
        "template": {
            "id": state.template_id,
            "version": state.template_version,
            "name": "",
        },
    }


def _flatten_form_state(form_state: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Flatten ``{step_id: {field: value}}`` into a single dict for the payload.

    Field collisions across steps keep the last one. Used as a friendly summary
    on the report payload — not for downstream resolution (which reads
    ``state.form_state`` directly).
    """
    out: dict[str, Any] = {}
    for fields in form_state.values():
        out.update(fields)
    return out
