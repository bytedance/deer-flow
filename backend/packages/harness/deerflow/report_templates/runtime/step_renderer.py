"""Form step renderer — turn a DSL ``form_step`` into a GenUI ``form`` block.

For each form_step the runtime tool ``report_template_render_step`` calls
``render_form_step(...)`` to:

  1. Run the optional ``before_step`` script (if not yet cached in step_outputs).
  2. Materialise dynamic ``options_source`` references into a static ``options``
     list using the freshly produced step output.
  3. Build the props dict for a ``component="form"`` block and push it via
     ``push_block_to_sse``.

The block stays interactive (``form`` → ``render_ui_tool``), but in this
runtime path we **do not** use ``push_block_to_sse`` (that helper is for
non-interactive blocks); instead the runtime tool calls the public
``render_ui`` tool directly. This module focuses on **building the props** so
the runtime tool stays a thin shell.
"""

from __future__ import annotations

from typing import Any

from deerflow.report_templates.runtime.data_runner import (
    StepResult,
    run_script,
)
from deerflow.report_templates.runtime.state import RuntimeState
from deerflow.report_templates.script_registry import ScriptRegistry
from deerflow.report_templates.source_resolver import evaluate, parse


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class StepRenderError(Exception):
    """Raised when a step cannot be rendered (missing fields, bad source, etc.)."""


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------


def find_step(dsl: dict[str, Any], step_id: str) -> dict[str, Any]:
    for step in dsl.get("form_steps", []) or []:
        if step["id"] == step_id:
            return step
    raise StepRenderError(f"form_step {step_id!r} not in DSL")


def maybe_run_before_step(
    *,
    step: dict[str, Any],
    state: RuntimeState,
    registry: ScriptRegistry,
    run_output_dir,
) -> StepResult | None:
    """Execute ``form_step.before_step`` if declared and not yet cached."""
    before = step.get("before_step")
    if not before:
        return None
    bs_id = before["id"]
    if bs_id in state.step_outputs:
        return None
    context = build_context(state)
    return run_script(
        step_id=bs_id,
        script_qualified_name=before["name"],
        args=dict(before.get("args") or {}),
        registry=registry,
        run_output_dir=run_output_dir,
        context=context,
    )


def build_form_props(
    *,
    step: dict[str, Any],
    state: RuntimeState,
    callback_id: str,
) -> dict[str, Any]:
    """Build the props dict for a ``component="form"`` GenUI block."""
    fields_props: list[dict[str, Any]] = []
    for field_obj in step.get("fields", []) or []:
        fields_props.append(_render_field(field_obj, state))

    props: dict[str, Any] = {
        "title": step.get("title", step["id"]),
        "description": step.get("description") or "",
        "fields": fields_props,
        "submit_label": "下一步" if step.get("next") != "generate" else "生成报告",
        "callback_id": callback_id,
    }
    return props


def build_context(state: RuntimeState) -> dict[str, Any]:
    """Construct the JSONPath context for the current state.

    Mirrors §5.6: keys are ``form`` / ``steps`` / ``run`` / ``template``.
    """
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
            "name": "",  # set by tools that have the DSL handy
        },
    }


# ---------------------------------------------------------------------------
# Field-level rendering
# ---------------------------------------------------------------------------


def _render_field(field_obj: dict[str, Any], state: RuntimeState) -> dict[str, Any]:
    """Materialise dynamic options for ``select``/``multi-select`` fields."""
    out = dict(field_obj)
    src = out.pop("options_source", None)
    if src is None:
        return out

    step_id = src["step"]
    if step_id not in state.step_outputs:
        raise StepRenderError(
            f"options_source step {step_id!r} has not run yet; cannot render field {out.get('name')!r}"
        )

    # path may be a bare property name or a dotted JSON path.
    raw_path = src["path"]
    base_obj = state.step_outputs[step_id]
    path_value = _resolve_options_path(base_obj, raw_path)
    if not isinstance(path_value, list):
        raise StepRenderError(
            f"options_source.path {raw_path!r} did not resolve to a list (got {type(path_value).__name__})"
        )

    options: list[dict[str, Any]] = []
    label_key = src["label"]
    value_key = src["value"]
    group_key = src.get("group")
    desc_key = src.get("description")
    max_items = src.get("max_items")
    for item in path_value:
        if not isinstance(item, dict):
            continue
        opt: dict[str, Any] = {
            "label": str(item.get(label_key, "")),
            "value": item.get(value_key),
        }
        if group_key and item.get(group_key) is not None:
            opt["group"] = item[group_key]
        if desc_key and item.get(desc_key) is not None:
            opt["description"] = item[desc_key]
        options.append(opt)
        if max_items and len(options) >= max_items:
            break

    out["options"] = options
    return out


def _resolve_options_path(base: Any, raw_path: str) -> Any:
    """Resolve an ``options_source.path`` against ``base``.

    ``path`` is a bare or dotted path inside ``base`` (e.g. ``"equipment"`` or
    ``"groups.equipment"``). For full JSONPath syntax callers should use the
    ``source_resolver`` directly via ``$.steps...`` placeholders elsewhere.
    """
    if "." in raw_path:
        # Dotted path — wrap in a synthetic context so we can reuse the parser.
        ast = parse(f"$.{raw_path}")
        # Skip the synthetic root by directly traversing
        out = base
        from deerflow.report_templates.source_resolver import (
            FieldAccess,
            PathNotFoundError,
        )

        for node in ast[1:]:
            if isinstance(node, FieldAccess):
                if not isinstance(out, dict) or node.name not in out:
                    raise PathNotFoundError(raw_path, node.name)
                out = out[node.name]
            else:
                raise StepRenderError(
                    f"options_source.path {raw_path!r}: array access not supported here"
                )
        return out
    if not isinstance(base, dict) or raw_path not in base:
        raise StepRenderError(
            f"options_source.path {raw_path!r} not found in step output"
        )
    return base[raw_path]
