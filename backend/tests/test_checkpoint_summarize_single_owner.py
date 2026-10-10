"""Ownership gate for the checkpoint benchmark family's shared reporting code.

``scripts/benchmark/checkpoint/summarize_channels.py`` and
``summarize_production.py`` each carried a byte-identical copy of four helpers
plus the ``_benchmark_input_index`` field name, even though their sibling
``bench_channels.py`` / ``bench_production.py`` already read JSONL-shaped
results and stats through ``checkpoint_bench_common.py``. ``backend/AGENTS.md``
says benchmarks in that folder must import shared code rather than duplicate it,
so the folder now has one implementation of reading, numeric filtering, column
selection and table printing, and each script keeps only what genuinely differs:
its own ``_GROUP_FIELDS``.

These tests pin:

1. the owner's behaviour, value by value (the bar);
2. that both scripts reach it — object identity for the aliased helpers, a
   single-delegation AST check for the two that pass the script's grouping, and
   an end-to-end table rendered through each script's real ``main()``;
3. a source census over ``scripts/benchmark/``: no other script may restate one
   of the four bodies, and exactly the two summarize scripts alias them.

Out of scope on purpose: the two ``scripts/eval_*.py`` harnesses still share a
nearest-rank ``_percentile`` with each other, which is a different function from
``checkpoint_bench_common.percentile`` (interpolated, 0-100 scale) — folding
those would change reported p95s, so they stay local.
"""

import ast
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_BACKEND = Path(__file__).resolve().parents[1]
CHECKPOINT_DIR = REPO_BACKEND / "scripts" / "benchmark" / "checkpoint"
OWNER_PATH = CHECKPOINT_DIR / "checkpoint_bench_common.py"
SCRIPTS = {
    "channels": CHECKPOINT_DIR / "summarize_channels.py",
    "production": CHECKPOINT_DIR / "summarize_production.py",
}


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# The scripts do a sibling ``sys.path`` insert and ``import
# checkpoint_bench_common``; registering the owner under that exact name first
# makes their binding and this test's ``owner`` the same object.
owner = _load("checkpoint_bench_common", OWNER_PATH)
scripts = {key: _load(f"summarize_single_owner_{key}", path) for key, path in SCRIPTS.items()}

GROUP_FIELDS = {key: list(module._GROUP_FIELDS) for key, module in scripts.items()}


def _body_hash(fn: ast.FunctionDef) -> str:
    body = list(fn.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) and isinstance(body[0].value.value, str):
        body = body[1:]
    return ast.unparse(ast.Module(body=body, type_ignores=[]))


def _top_level_functions(path: Path) -> list[ast.FunctionDef]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return [n for n in tree.body if isinstance(n, ast.FunctionDef)]


def _row(**values: Any) -> dict[str, Any]:
    return {"success": True, "mode": "full", **values}


# --- 1. the bar -----------------------------------------------------------------


def test_load_jsonl_skips_blanks_comments_and_tags_each_input_file(tmp_path: Path) -> None:
    first = tmp_path / "a.jsonl"
    first.write_text("\n".join(['{"metric": 1}', "", "# note", '{"metric": 2}']) + "\n", encoding="utf-8")
    second = tmp_path / "b.jsonl"
    second.write_text('{"metric": 3}\n', encoding="utf-8")

    rows = owner.load_jsonl([first, second])

    assert [row["metric"] for row in rows] == [1, 2, 3]
    assert [row[owner.INPUT_INDEX_FIELD] for row in rows] == [0, 0, 1], "repetition numbers restart per invocation, so the source input must be kept"


def test_load_jsonl_reports_every_malformed_line_together(tmp_path: Path) -> None:
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"metric": 1}\nnot json\n[1, 2]\n', encoding="utf-8")

    with pytest.raises(ValueError) as excinfo:
        owner.load_jsonl([bad])

    message = str(excinfo.value)
    assert message.startswith("Malformed JSONL row(s):")
    assert f"{bad}:2:" in message and f"{bad}:3: expected a JSON object" in message, "one bad row must not hide the next"


@pytest.mark.parametrize(("value", "expected"), [(7, 7.0), (7.5, 7.5), (True, None), (False, None), ("7", None), (None, None)])
def test_numeric_value_rejects_bool_and_non_numbers(value: Any, expected: float | None) -> None:
    assert owner.numeric_value({"metric": value}, "metric") == expected
    assert owner.numeric_value({}, "metric") is None, "an absent metric is not a number"


def test_table_columns_keeps_declared_group_order_then_sorted_extras() -> None:
    rows = [{"zeta": 1, "backend": "sqlite", "paired_repetitions": 2, "alpha": 3, "scenario": "append"}]
    columns = owner.table_columns(rows, ["backend", "scenario"])

    assert columns[:4] == ["backend", "scenario", "paired_repetitions", "alpha"], "group columns lead in declared order"
    assert columns[-1] == "zeta"


def test_print_table_aligns_and_names_the_empty_case(capsys: pytest.CaptureFixture[str]) -> None:
    owner.print_table([], ["backend"])
    assert capsys.readouterr().out.strip() == owner.NO_PAIRS_NOTICE

    rows = [{"backend": "sqlite", "metric": 1}, {"backend": "postgres", "metric": 1000, "extra": "x"}]
    owner.print_table(rows, ["backend"])
    lines = capsys.readouterr().out.splitlines()

    # "backend" is the declared group column and leads; the rest are sorted
    # extras, so "extra" comes before "metric". Widths are max(header, values).
    assert lines[0] == "  ".join(["backend".rjust(8), "extra".rjust(5), "metric".rjust(6)])
    assert lines[1].endswith("".rjust(5) + "  " + "1".rjust(6)), "a key the row lacks must render as blank padding"
    assert lines[2] == "  ".join(["postgres".rjust(8), "x".rjust(5), "1000".rjust(6)])


# --- 2. both scripts go through the owner -------------------------------------


@pytest.mark.parametrize("key", sorted(scripts))
def test_scripts_alias_the_owner_objects(key: str) -> None:
    module = scripts[key]
    assert module._load_jsonl is owner.load_jsonl
    assert module._numeric is owner.numeric_value
    assert module._INPUT_INDEX_FIELD == owner.INPUT_INDEX_FIELD

    for name, owner_name in (("_columns", "table_columns"), ("_print_table", "print_table")):
        fn = next((f for f in _top_level_functions(Path(module.__file__)) if f.name == name), None)
        assert fn is not None, f"{key} lost its {name} adapter"
        statements = [n for n in fn.body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))]
        assert len(statements) == 1, f"{key}.{name} must stay a single delegation"
        call = statements[0].value
        assert isinstance(call, ast.Call) and getattr(call.func.value, "id", None) == "_common" and call.func.attr == owner_name
        assert call.args[-1].id == "_GROUP_FIELDS", f"{key}.{name} must still pass its own grouping"


@pytest.mark.parametrize("key", sorted(scripts))
def test_cli_still_runs_over_a_real_results_file(key: str, capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    """The script's own entry point keeps working now that reporting lives upstairs."""
    module = scripts[key]
    fields = GROUP_FIELDS[key]
    metric = module.DEFAULT_METRICS[0]
    rows = []
    for mode in ("full", "delta"):
        for repetition in (0, 1):
            row = dict.fromkeys(fields, "g")
            row.update({"mode": mode, "repetition": repetition, "success": True, metric: 4.0 if mode == "full" else 1.0})
            rows.append(row)
    results = tmp_path / "results.jsonl"
    results.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

    assert module.main([str(results)]) == 0
    out = capsys.readouterr().out
    assert out.strip(), f"{key} printed nothing"
    assert fields[0] in out or owner.NO_PAIRS_NOTICE in out, "the table header or its empty-case notice must still print"


def test_channels_paired_rows_still_render_a_real_table(capsys: pytest.CaptureFixture[str]) -> None:
    """A full/delta pair must still pair, so the shared table code is really in use."""
    module = scripts["channels"]

    def row(mode: str, repetition: int, write_ms: float) -> dict[str, Any]:
        return {
            "success": True,
            "mode": mode,
            "backend": "sqlite",
            "scenario": "append",
            "snapshot_frequency": 1000,
            "update_count": 100,
            "payload_bytes": 128,
            "repetition": repetition,
            "write_total_ms": write_ms,
        }

    rows = [row("full", 0, 10.0), row("delta", 0, 5.0), row("full", 1, 30.0), row("delta", 1, 15.0)]
    module._print_table(module._summarize(rows, metrics=["write_total_ms"]))
    out = capsys.readouterr().out

    assert out.strip() != owner.NO_PAIRS_NOTICE
    header = out.splitlines()[0]
    for column in ("backend", "scenario", "paired_repetitions", "ratio_write_total_ms"):
        assert column in header, f"{column} missing from the shared table header: {header}"
    assert "0.5" in out.splitlines()[1], "the ratio column is what proves the table came from real summaries"


# --- 3. census over scripts/benchmark/ ---------------------------------------


def test_no_other_benchmark_script_restates_an_owned_body() -> None:
    owned_names = {"load_jsonl", "numeric_value", "table_columns", "print_table"}
    owned = {_body_hash(fn) for fn in _top_level_functions(OWNER_PATH) if fn.name in owned_names}
    assert len(owned) == 4, "the four owned bodies must stay distinguishable for this gate to mean anything"
    offenders = []
    for path in sorted((REPO_BACKEND / "scripts" / "benchmark").rglob("*.py")):
        if path == OWNER_PATH:
            continue
        for fn in _top_level_functions(path):
            if _body_hash(fn) in owned:
                offenders.append(f"{path.relative_to(REPO_BACKEND)}::{fn.name}")
    assert offenders == [], f"shared benchmark reporting belongs to checkpoint_bench_common: found in {offenders}"


def test_exactly_the_two_summarize_scripts_alias_the_shared_reporting() -> None:
    aliasers = {
        path.name for path in sorted((REPO_BACKEND / "scripts" / "benchmark").rglob("*.py")) if "_common.load_jsonl" in path.read_text(encoding="utf-8") or "from checkpoint_bench_common import load_jsonl" in path.read_text(encoding="utf-8")
    }
    assert aliasers == {"summarize_channels.py", "summarize_production.py"}


def test_the_owner_still_exports_the_rest_of_the_family_contract() -> None:
    """The pre-existing shared API must not have been narrowed by the move."""
    for name in (
        "percentile",
        "parse_positive_int_csv",
        "parse_choice_csv",
        "canonical_messages_digest",
        "window_median",
        "resolve_git_sha",
        "safe_error",
        "file_size",
        "peak_rss_bytes",
        "run_profiled",
        "run_child_case",
        "load_jsonl",
        "numeric_value",
        "table_columns",
        "print_table",
    ):
        assert hasattr(owner, name), f"checkpoint_bench_common lost {name}"
