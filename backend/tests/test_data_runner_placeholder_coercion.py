"""Tests for placeholder→file path coercion in data_runner.

Sprint follow-up: when an args value is a single full-string placeholder of
the form ``{{ $.steps.<step>.<output> }}`` AND it resolves to a dict AND
``{run_output_dir}/data/<output>.json`` exists, render_args coerces the arg
into that absolute file path. Otherwise falls back to existing behaviour
(stringified dict / raw value).

This file pins the trigger condition matrix so a future refactor can't
accidentally widen or narrow it.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def data_runner():
    fake_lg = types.ModuleType("langgraph")
    fake_config = types.ModuleType("langgraph.config")
    fake_config.get_config = lambda: {}
    fake_config.get_stream_writer = lambda: (lambda *a, **k: None)
    sys.modules.setdefault("langgraph", fake_lg)
    sys.modules.setdefault("langgraph.config", fake_config)
    repo_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(repo_root / "backend" / "packages" / "harness"))

    from deerflow.report_templates.runtime import data_runner as dr  # type: ignore

    return dr


@pytest.fixture()
def run_dir(tmp_path):
    """A tmp run output dir with a pre-written step-output file."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "fault_timeline.json").write_text(
        json.dumps({"timeline": [{"t": "2026-05-15", "type": "alarm"}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    return tmp_path


def _context_with_step(step_id: str, output_id: str, value: object) -> dict:
    """Build a minimal context with one step-output present."""
    return {
        "form": {},
        "steps": {step_id: {output_id: value}},
        "run": {},
        "template": {},
    }


# ---------------------------------------------------------------------------
# Trigger path — the happy case
# ---------------------------------------------------------------------------


def test_coerces_dict_step_output_to_file_path(data_runner, run_dir):
    ctx = _context_with_step("ft", "fault_timeline", {"some": "data"})
    result = data_runner.render_args(
        {"timeline": "{{ $.steps.ft.fault_timeline }}"}, ctx, run_output_dir=run_dir,
    )
    expected = str((run_dir / "data" / "fault_timeline.json").resolve())
    assert result["timeline"] == expected


def test_coerces_only_target_arg_other_args_untouched(data_runner, run_dir):
    """Other args (form values, scalars) pass through unchanged."""
    ctx = _context_with_step("ft", "fault_timeline", {"x": 1})
    ctx["form"] = {"scope": {"asset_id": "P-001"}}
    result = data_runner.render_args(
        {
            "input": "{{ $.steps.ft.fault_timeline }}",
            "asset_id": "{{ $.form.scope.asset_id }}",
            "literal": "hello",
        },
        ctx,
        run_output_dir=run_dir,
    )
    # Coerced
    assert result["input"].endswith("fault_timeline.json")
    # Plain form-substitution stays a string
    assert result["asset_id"] == "P-001"
    # Literal pass-through
    assert result["literal"] == "hello"


# ---------------------------------------------------------------------------
# Non-trigger paths — must silently fall back
# ---------------------------------------------------------------------------


def test_no_coercion_when_run_output_dir_missing(data_runner):
    """Backward compat: render_args called without run_output_dir keeps old behaviour."""
    ctx = _context_with_step("ft", "fault_timeline", {"y": 2})
    result = data_runner.render_args({"timeline": "{{ $.steps.ft.fault_timeline }}"}, ctx)
    assert result["timeline"] == {"y": 2}, "must keep dict (existing behaviour)"


def test_no_coercion_when_file_does_not_exist(data_runner, run_dir):
    """Trigger gate fails on file_exists — fallback to dict."""
    ctx = _context_with_step("ft", "nonexistent_output", {"z": 3})
    result = data_runner.render_args(
        {"input": "{{ $.steps.ft.nonexistent_output }}"}, ctx, run_output_dir=run_dir,
    )
    assert result["input"] == {"z": 3}


def test_no_coercion_when_resolved_is_not_dict(data_runner, run_dir):
    """Trigger gate requires dict; string / list / None all fall back."""
    ctx = _context_with_step("ft", "fault_timeline", "just-a-string")
    result = data_runner.render_args(
        {"input": "{{ $.steps.ft.fault_timeline }}"}, ctx, run_output_dir=run_dir,
    )
    assert result["input"] == "just-a-string", "scalar must pass through unchanged"


def test_no_coercion_for_deeper_paths(data_runner, run_dir):
    """``$.steps.<step>.<output>.<inner>`` — deeper than two segments after
    ``steps`` is NOT coerced. Author wanted the inner value, not a path."""
    ctx = _context_with_step("ft", "fault_timeline", {"events": [{"t": "x"}]})
    # Even though fault_timeline.json exists, the placeholder asks for a
    # deeper field — runtime returns the resolved value, not a path.
    result = data_runner.render_args(
        {"input": "{{ $.steps.ft.fault_timeline.events }}"}, ctx, run_output_dir=run_dir,
    )
    assert result["input"] == [{"t": "x"}]


def test_no_coercion_for_form_placeholder(data_runner, run_dir):
    """``$.form.X.Y`` placeholders must NEVER be treated as step outputs."""
    ctx = {"form": {"scope": {"asset_id": "P-001"}}, "steps": {}, "run": {}, "template": {}}
    result = data_runner.render_args(
        {"asset_id": "{{ $.form.scope.asset_id }}"}, ctx, run_output_dir=run_dir,
    )
    assert result["asset_id"] == "P-001"


def test_no_coercion_for_mixed_placeholder_text(data_runner, run_dir):
    """Mixed-text placeholders (not a single full-string placeholder) keep
    the existing string-interpolation behaviour. Coercion only applies to
    pure ``{{ ... }}`` values."""
    ctx = _context_with_step("ft", "fault_timeline", {"a": 1})
    result = data_runner.render_args(
        {"input": "prefix={{ $.steps.ft.fault_timeline }}/suffix"},
        ctx,
        run_output_dir=run_dir,
    )
    # Original behaviour: dict gets JSON-stringified into the surrounding text
    assert isinstance(result["input"], str)
    assert "prefix=" in result["input"]
    assert "suffix" in result["input"]


def test_no_coercion_for_array_all_selector(data_runner, run_dir):
    """``$.steps.<step>.<output>[*].field`` uses the JSONPath array selector —
    that expression's AST has > 4 nodes (Root, FieldAccess×3, ArrayAll,
    FieldAccess), so the segments parser rejects it and the trigger does
    not fire. The resolved list passes through unchanged."""
    ctx = _context_with_step("ft", "fault_timeline", [{"a": 1}, {"a": 2}])
    result = data_runner.render_args(
        {"input": "{{ $.steps.ft.fault_timeline[*].a }}"}, ctx, run_output_dir=run_dir,
    )
    # Resolved is a list of scalars — pass through unchanged
    assert result["input"] == [1, 2]


# ---------------------------------------------------------------------------
# Internal helpers — pin the exact gate behaviour
# ---------------------------------------------------------------------------


def test_step_output_segments_parses_two_layer(data_runner):
    assert data_runner._step_output_segments("$.steps.fault_timeline.fault_timeline") == (
        "fault_timeline",
        "fault_timeline",
    )


def test_step_output_segments_rejects_three_layer(data_runner):
    assert data_runner._step_output_segments("$.steps.a.b.c") is None


def test_step_output_segments_rejects_form(data_runner):
    assert data_runner._step_output_segments("$.form.a.b") is None


def test_step_output_segments_rejects_invalid_syntax(data_runner):
    # PathSyntaxError is a JSONPathError subclass; helper must return None,
    # NEVER raise.
    assert data_runner._step_output_segments("not-jsonpath") is None


def test_maybe_coerce_returns_none_when_run_output_dir_is_none(data_runner):
    out = data_runner._maybe_coerce_to_step_output_path(
        expr="$.steps.ft.fault_timeline", resolved={"a": 1}, run_output_dir=None,
    )
    assert out is None


def test_maybe_coerce_returns_path_when_all_gates_pass(data_runner, run_dir):
    out = data_runner._maybe_coerce_to_step_output_path(
        expr="$.steps.ft.fault_timeline", resolved={"a": 1}, run_output_dir=run_dir,
    )
    assert out is not None
    assert Path(out).name == "fault_timeline.json"


def test_maybe_coerce_returns_none_when_resolved_is_list(data_runner, run_dir):
    out = data_runner._maybe_coerce_to_step_output_path(
        expr="$.steps.ft.fault_timeline", resolved=[1, 2, 3], run_output_dir=run_dir,
    )
    assert out is None
