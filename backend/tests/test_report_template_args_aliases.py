"""Tests for ``data_runner.apply_args_aliases`` — DSL short-name translation."""

from __future__ import annotations

from pathlib import Path

from deerflow.report_templates.runtime.data_runner import apply_args_aliases
from deerflow.report_templates.script_registry import (
    ArgSpec,
    ScriptDescriptor,
)


def _descriptor(
    *,
    args_schema: dict | None = None,
    args_aliases: dict | None = None,
) -> ScriptDescriptor:
    return ScriptDescriptor(
        qualified_name="daily-report/demo",
        skill_name="daily-report",
        script_name="demo",
        skill_dir=Path("."),
        entry="scripts/demo.py",
        kinds=("data_step",),
        description="",
        args_schema=args_schema or {"compare": ArgSpec(type="enum")},
        args_aliases=args_aliases or {},
        outputs_schema=None,
        output_files=(),
        timeout_seconds=60,
        max_output_bytes=1024,
    )


def test_no_aliases_passes_args_through_unchanged():
    desc = _descriptor()
    args = {"compare": "mom", "kpis": ["runtime_rate"], "month": "2026-05"}
    assert apply_args_aliases(args, desc) == args


def test_scalar_alias_is_translated():
    desc = _descriptor(
        args_aliases={"compare": {"mom": "previous_month", "yoy": "previous_year_month"}}
    )
    out = apply_args_aliases({"compare": "mom"}, desc)
    assert out == {"compare": "previous_month"}


def test_list_alias_is_translated_element_wise():
    desc = _descriptor(
        args_aliases={"compare": {"mom": "previous_month", "yoy": "previous_year_month"}}
    )
    out = apply_args_aliases({"compare": ["mom", "yoy", "none"]}, desc)
    assert out == {"compare": ["previous_month", "previous_year_month", "none"]}


def test_unknown_value_passes_through():
    desc = _descriptor(args_aliases={"compare": {"mom": "previous_month"}})
    out = apply_args_aliases({"compare": "weekly"}, desc)
    assert out == {"compare": "weekly"}


def test_unrelated_args_are_not_touched():
    desc = _descriptor(args_aliases={"compare": {"mom": "previous_month"}})
    args = {"compare": "mom", "date": "2026-05-01", "kpis": ["runtime_rate"]}
    out = apply_args_aliases(args, desc)
    assert out == {
        "compare": "previous_month",
        "date": "2026-05-01",
        "kpis": ["runtime_rate"],
    }


def test_non_string_scalar_value_passes_through():
    """Numbers / booleans must not be coerced by the alias step."""
    desc = _descriptor(args_aliases={"flag": {"on": "enabled"}})
    out = apply_args_aliases({"flag": True, "count": 7}, desc)
    assert out == {"flag": True, "count": 7}


def test_list_with_non_string_elements_keeps_them():
    desc = _descriptor(args_aliases={"kpis": {"x": "X"}})
    out = apply_args_aliases({"kpis": ["x", 1, True]}, desc)
    assert out == {"kpis": ["X", 1, True]}
