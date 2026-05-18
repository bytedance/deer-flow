"""Unit tests for report_templates.source_resolver — JSONPath subset parser.

Covers §5.6 of docs/plans/2026-05-14-ai-report-custom-template-design.md:
- All whitelisted syntax forms (form / steps / steps[*] / run / template)
- All blacklisted syntax forms (filters, functions, recursion, etc.)
- Evaluator: legal paths, missing paths, array expansion
- Depth limit, expression rendering
"""

from __future__ import annotations

import pytest

from deerflow.report_templates.source_resolver import (
    ArrayAll,
    FieldAccess,
    JSONPathError,
    PathNotFoundError,
    PathSyntaxError,
    Root,
    evaluate,
    extract_expressions,
    parse,
    render,
)


# ---------------------------------------------------------------------------
# Whitelist: parsing
# ---------------------------------------------------------------------------


class TestWhitelistParse:
    def test_form_step_field(self) -> None:
        ast = parse("$.form.scope.report_date")
        assert ast == [Root(), FieldAccess("form"), FieldAccess("scope"), FieldAccess("report_date")]

    def test_steps_output(self) -> None:
        ast = parse("$.steps.daily_data.daily_data")
        assert len(ast) == 4
        assert isinstance(ast[0], Root)
        assert [n.name for n in ast[1:]] == ["steps", "daily_data", "daily_data"]

    def test_nested_step_field(self) -> None:
        ast = parse("$.steps.daily_kpi.daily_kpi.overall_status.summary")
        assert [n.name for n in ast[1:]] == [
            "steps",
            "daily_kpi",
            "daily_kpi",
            "overall_status",
            "summary",
        ]

    def test_array_expansion(self) -> None:
        ast = parse("$.steps.equipment_catalog.equipment[*].id")
        assert ast == [
            Root(),
            FieldAccess("steps"),
            FieldAccess("equipment_catalog"),
            FieldAccess("equipment"),
            ArrayAll(),
            FieldAccess("id"),
        ]

    def test_run_metadata(self) -> None:
        ast = parse("$.run.report_run_id")
        assert [n.name for n in ast[1:]] == ["run", "report_run_id"]

    def test_template_metadata(self) -> None:
        ast = parse("$.template.version")
        assert [n.name for n in ast[1:]] == ["template", "version"]

    def test_short_form_autoprefix(self) -> None:
        # validator-friendly: "form.scope.x" auto-prefixed with "$."
        assert parse("form.scope.report_date") == parse("$.form.scope.report_date")

    def test_field_name_with_underscore_and_hyphen(self) -> None:
        # both underscore and hyphen allowed in identifiers
        ast = parse("$.form.scope.my-field_name")
        assert ast[-1] == FieldAccess("my-field_name")


# ---------------------------------------------------------------------------
# Blacklist: parser must reject
# ---------------------------------------------------------------------------


class TestBlacklistParse:
    @pytest.mark.parametrize(
        "expr,reason",
        [
            ("$.form.x[?(@.y > 1)]", "filter expression"),
            ("$.form.x.length()", "function call"),
            ("$..form.x", "recursive descent"),
            ("$.form.x..y", "recursive descent in the middle"),
            ("$.form.x + 1", "arithmetic"),
            ("$.form.x[0]", "indexed access"),
            ("$.form.x[-1]", "negative index"),
            ("$.form.x[1:3]", "slice"),
            ("$.form.x[1,2]", "list of indices"),
            ("$.form.x | $.form.y", "union"),
            ("$.unknown_root.x", "unknown root key"),
            ("", "empty expression"),
            ("$", "root alone without segment"),
            ("$.", "trailing dot"),
            (".form.x", "no $"),  # note: '.' prefix is invalid; bare 'form.x' is valid
            ("$.form..x", "double dot"),
            ("$.form.x.[*]", "[*] without preceding field"),
            ("$.form.[*]", "[*] right after root"),
            ("$.form.x[*]", "[*] without trailing .field"),
        ],
    )
    def test_blacklisted(self, expr: str, reason: str) -> None:
        with pytest.raises(PathSyntaxError):
            parse(expr)

    def test_depth_limit(self) -> None:
        # 1=form + 8 deep fields = 9 segments → exceeds limit of 8.
        long_path = "$.form." + ".".join(f"l{i}" for i in range(9))
        with pytest.raises(PathSyntaxError, match="depth"):
            parse(long_path)


# ---------------------------------------------------------------------------
# Evaluator: happy paths
# ---------------------------------------------------------------------------


@pytest.fixture
def ctx() -> dict:
    return {
        "form": {
            "scope": {"report_date": "2026-05-14", "equipment_type": "pump"},
            "equipment": {"equipment_ids": ["P-001", "P-002"]},
            "kpis": {"kpi_keys": ["runtime_rate", "alarm_count"]},
        },
        "steps": {
            "equipment_catalog": {
                "equipment": [
                    {"id": "P-001", "area": "A区", "name": "Pump-001"},
                    {"id": "P-002", "area": "A区", "name": "Pump-002"},
                ],
                "available_kpis": [
                    {"key": "runtime_rate", "label": "运行率"},
                ],
            },
            "daily_kpi": {
                "daily_kpi": {
                    "overall_status": {"summary": "all good"},
                    "kpi_summary": [{"name": "k1", "value": 99}],
                },
            },
        },
        "run": {"report_run_id": "rr_xyz", "thread_id": "thr_abc"},
        "template": {"id": "tpl_xyz", "version": 3, "name": "equipment_daily"},
    }


class TestEvaluator:
    def test_form_field(self, ctx: dict) -> None:
        assert evaluate(parse("$.form.scope.report_date"), ctx) == "2026-05-14"

    def test_nested_steps_field(self, ctx: dict) -> None:
        assert (
            evaluate(parse("$.steps.daily_kpi.daily_kpi.overall_status.summary"), ctx)
            == "all good"
        )

    def test_array_expansion_returns_list(self, ctx: dict) -> None:
        result = evaluate(parse("$.steps.equipment_catalog.equipment[*].id"), ctx)
        assert result == ["P-001", "P-002"]

    def test_run_metadata(self, ctx: dict) -> None:
        assert evaluate(parse("$.run.report_run_id"), ctx) == "rr_xyz"

    def test_template_metadata(self, ctx: dict) -> None:
        assert evaluate(parse("$.template.version"), ctx) == 3

    def test_short_form_works(self, ctx: dict) -> None:
        # validator accepts "form.scope.x" without "$." prefix
        assert evaluate(parse("form.scope.equipment_type"), ctx) == "pump"


# ---------------------------------------------------------------------------
# Evaluator: error cases
# ---------------------------------------------------------------------------


class TestEvaluatorErrors:
    def test_missing_field_raises(self, ctx: dict) -> None:
        with pytest.raises(PathNotFoundError) as exc:
            evaluate(parse("$.form.scope.nonexistent"), ctx)
        assert "nonexistent" in str(exc.value)
        assert "$.form.scope" in str(exc.value)

    def test_missing_step_raises(self, ctx: dict) -> None:
        with pytest.raises(PathNotFoundError):
            evaluate(parse("$.steps.no_such_step.output"), ctx)

    def test_array_with_missing_field_raises(self, ctx: dict) -> None:
        with pytest.raises(PathNotFoundError):
            evaluate(parse("$.steps.equipment_catalog.equipment[*].nonexistent"), ctx)

    def test_array_on_non_list_raises(self, ctx: dict) -> None:
        # `form.scope.report_date` is a string, [*] should fail
        ast = [Root(), FieldAccess("form"), FieldAccess("scope"), FieldAccess("report_date"), ArrayAll(), FieldAccess("anything")]
        with pytest.raises(PathNotFoundError):
            evaluate(ast, ctx)

    def test_evaluator_rejects_non_root_ast(self, ctx: dict) -> None:
        with pytest.raises(PathSyntaxError):
            evaluate([FieldAccess("form")], ctx)


# ---------------------------------------------------------------------------
# Placeholder helpers
# ---------------------------------------------------------------------------


class TestPlaceholderHelpers:
    def test_extract_expressions(self) -> None:
        text = 'date: "{{ $.form.scope.report_date }}" and {{ form.scope.equipment_type }}'
        exprs = extract_expressions(text)
        assert exprs == ["$.form.scope.report_date", "form.scope.equipment_type"]

    def test_render_substitutes_values(self, ctx: dict) -> None:
        text = "date={{ $.form.scope.report_date }} type={{ form.scope.equipment_type }}"
        assert render(text, ctx) == "date=2026-05-14 type=pump"

    def test_render_propagates_path_errors(self, ctx: dict) -> None:
        with pytest.raises(JSONPathError):
            render("missing={{ $.form.scope.does_not_exist }}", ctx)

    def test_render_no_placeholders_returns_text_as_is(self, ctx: dict) -> None:
        assert render("plain text without braces", ctx) == "plain text without braces"
