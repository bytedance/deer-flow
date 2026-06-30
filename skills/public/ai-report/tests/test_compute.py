"""Unit tests for compute (新写, task 8: assemble-wide + extract-ir)."""

from __future__ import annotations

from decimal import Decimal

import duckdb
import pytest

from compute import (
    ComputeIR,
    ValidationResult,
    assemble_wide,
    decimal_isclose,
    extract_ir,
    reset_conn_for_tests,
    validate,
)


@pytest.fixture(autouse=True)
def _reset_module_conn():
    """Each test starts and ends with no module-level DuckDB conn (test isolation)."""
    reset_conn_for_tests()
    yield
    reset_conn_for_tests()


def test_extract_ir_parses_compute_block():
    body = """
> 计算: name = "利润率", prompt = "利润总额 / 营业收入", examples = [{"row": 0, "value": 0.2}]
> 计算: name = "成本率", prompt = "(营业收入-利润总额) / 营业收入"
"""
    irs = extract_ir(body)
    assert len(irs) == 2
    assert irs[0].name == "利润率"
    assert irs[0].prompt == "利润总额 / 营业收入"
    assert irs[0].examples == [{"row": 0, "value": 0.2}]
    assert irs[1].name == "成本率"


def test_assemble_wide_pivots_metric_facts():
    facts = [
        {"branch_num": "1", "idx_id": "A", "period_alias": "202603", "numeric_value": 100, "status": "ok"},
        {"branch_num": "1", "idx_id": "B", "period_alias": "202603", "numeric_value": 200, "status": "ok"},
        {"branch_num": "2", "idx_id": "A", "period_alias": "202603", "numeric_value": 300, "status": "ok"},
    ]
    wide = assemble_wide(facts, run_id="r1", table_id="t1")
    assert len(wide) == 2
    by_branch = {r["branch_num"]: r for r in wide}
    assert by_branch["1"]["A@202603"] == 100
    assert by_branch["1"]["B@202603"] == 200
    assert by_branch["2"]["A@202603"] == 300


def test_assemble_wide_drops_failed_cells():
    """Failed facts are filtered out; their cells become NULL (not sentinel strings).

    Phase 1 policy: in-cell sentinels removed. Status info lives in
    metric_facts.status; aggregate-level sentinels (approved_table_runs.sentinels
    JSON) are computed separately by assemble_status (task 13).
    """
    facts = [
        {"branch_num": "1", "idx_id": "A", "period_alias": "202603", "numeric_value": 100, "status": "ok"},
        {"branch_num": "1", "idx_id": "B", "period_alias": "202603", "numeric_value": None, "status": "query_failed"},
        {"branch_num": "1", "idx_id": "C", "period_alias": "202603", "numeric_value": None, "status": "cast_failed"},
    ]
    wide = assemble_wide(facts, run_id="r1", table_id="t1")
    assert len(wide) == 1
    assert wide[0]["branch_num"] == "1"
    assert wide[0]["A@202603"] == 100
    assert wide[0]["B@202603"] is None
    assert wide[0]["C@202603"] is None


def test_assemble_wide_preserves_decimal_precision():
    """Banking requirement: no float. Decimal(38,10) precision survives PIVOT.

    This value would lose precision under float (IEEE 754 has ~15-17 sig digits).
    Under DECIMAL(38,10) + DuckDB PIVOT MAX(DECIMAL), value survives exactly.
    """
    precise_value = Decimal("1234567890.1234567890")
    facts = [
        {"branch_num": "1", "idx_id": "A", "period_alias": "202603",
         "numeric_value": precise_value, "status": "ok"},
    ]
    wide = assemble_wide(facts, run_id="r1", table_id="t1")
    cell = wide[0]["A@202603"]
    assert isinstance(cell, Decimal), f"cell must be Decimal, got {type(cell).__name__}"
    assert cell == precise_value


def test_assemble_wide_returns_decimal_type_for_all_cells():
    """All numeric cells should be Decimal, not float or int."""
    facts = [
        {"branch_num": "1", "idx_id": "A", "period_alias": "202603", "numeric_value": 100, "status": "ok"},
        {"branch_num": "2", "idx_id": "A", "period_alias": "202603", "numeric_value": 200, "status": "ok"},
    ]
    wide = assemble_wide(facts, run_id="r1", table_id="t1")
    for row in wide:
        cell = row["A@202603"]
        assert isinstance(cell, Decimal), f"cell must be Decimal, got {type(cell).__name__}"


def test_assemble_wide_handles_empty_input():
    """Truly empty input → empty output, no DuckDB error."""
    assert assemble_wide([], run_id="r1", table_id="t1") == []


def test_assemble_wide_all_facts_failed_emits_empty_rows():
    """If all facts failed, still emit one row per branch_num with NULL cells.

    Wide table shape (branch_num + all expected columns) is the contract; cells
    being NULL is what tells the renderer "data missing here". Dropping the row
    entirely would hide the column from the renderer.
    """
    facts = [
        {"branch_num": "1", "idx_id": "A", "period_alias": "202603", "numeric_value": None, "status": "query_failed"},
        {"branch_num": "1", "idx_id": "B", "period_alias": "202603", "numeric_value": None, "status": "cast_failed"},
    ]
    wide = assemble_wide(facts, run_id="r1", table_id="t1")
    assert len(wide) == 1
    assert wide[0] == {"branch_num": "1", "A@202603": None, "B@202603": None}


def test_assemble_wide_branch_set_is_complete():
    """All (branch_num, col_key) pairs in input appear as cells in output.

    DuckDB PIVOT does NOT guarantee row insertion order (groups by branch_num).
    We assert the SET of branches is complete; downstream sort-by-branch_num is
    the renderer's responsibility, not assemble_wide's contract.
    """
    facts = [
        {"branch_num": "3", "idx_id": "A", "period_alias": "202603", "numeric_value": 30, "status": "ok"},
        {"branch_num": "1", "idx_id": "A", "period_alias": "202603", "numeric_value": 10, "status": "ok"},
        {"branch_num": "2", "idx_id": "A", "period_alias": "202603", "numeric_value": 20, "status": "ok"},
    ]
    wide = assemble_wide(facts, run_id="r1", table_id="t1")
    assert {r["branch_num"] for r in wide} == {"1", "2", "3"}


# ---- task 9: validate (3 layers, simplified) ---- #

@pytest.fixture
def conn():
    """Per-test :memory: DuckDB conn (no module-level state for validate)."""
    c = duckdb.connect(":memory:")
    yield c
    c.close()


def test_validate_explain_fails_on_broken_sql(conn):
    """Layer 1: EXPLAIN catches syntax/semantic errors."""
    res = validate(conn, "SELECT * FORM wide", [], ["branch_num"], None, None)
    assert res.passed is False
    assert res.layer == "explain"


def test_validate_columns_passes_on_simple_select(conn):
    """Layer 2: SQL runs and returns expected columns → all pass."""
    res = validate(
        conn,
        "SELECT branch_num, 1 AS x FROM wide",
        [{"branch_num": "1"}, {"branch_num": "2"}, {"branch_num": "3"}],
        ["branch_num", "x"],
        None, None,
    )
    assert res.passed is True
    assert res.layer == "all"


def test_validate_columns_fails_when_missing_expected(conn):
    """Layer 2: missing expected column (here branch_num) → columns layer fails.

    Simplified design: Layer 2 runs SQL once and checks the output columns cover
    everything in expected_columns. No separate FROM-wide/branch_num text check
    (those were redundant — EXPLAIN + column check catches the same failures).
    """
    res = validate(
        conn,
        "SELECT 1 AS x FROM wide",  # missing branch_num
        [{"branch_num": "1"}],
        ["branch_num", "x"],
        None, None,
    )
    assert res.passed is False
    assert res.layer == "columns"


def test_validate_columns_fails_on_runtime_error(conn):
    """Layer 1 catches undefined functions during EXPLAIN (catalog resolution).

    DuckDB EXPLAIN resolves function references too, so undefined_fn is caught
    at EXPLAIN layer rather than runtime. This is a feature: cheap fail-fast.
    For genuine runtime-only errors (e.g. division-returns-inf at row level),
    DuckDB typically does not raise at all.
    """
    res = validate(
        conn,
        "SELECT branch_num, undefined_fn() AS x FROM wide",
        [{"branch_num": "1"}],
        ["branch_num", "x"],
        None, None,
    )
    assert res.passed is False
    assert res.layer == "explain"


def test_validate_example_passes_when_close(conn):
    """Layer 3: example comparison uses Decimal precision (banking requirement)."""
    res = validate(
        conn,
        "SELECT branch_num, 2.0 AS x FROM wide",
        [{"branch_num": "1"}],
        ["branch_num", "x"],
        example_input={"branch_num": "1"},
        example_expected=Decimal("2.0"),
    )
    assert res.passed is True
    assert res.layer == "all"


def test_validate_example_fails_when_far(conn):
    res = validate(
        conn,
        "SELECT branch_num, 5.0 AS x FROM wide",
        [{"branch_num": "1"}],
        ["branch_num", "x"],
        example_input={"branch_num": "1"},
        example_expected=Decimal("2.0"),
    )
    assert res.passed is False
    assert res.layer == "example"


def test_decimal_isclose_helper():
    """Unit test for the precision helper used by validate's example layer."""
    assert decimal_isclose(Decimal("2.0"), Decimal("2.0"))
    assert decimal_isclose(Decimal("2.0"), Decimal("2.0001"), rel_tol=Decimal("0.001"))
    assert not decimal_isclose(Decimal("2.0"), Decimal("5.0"))
    assert decimal_isclose(Decimal("0"), Decimal("0"))  # zero corner case


# ---- task 10: evaluate + apply-computed ---- #

from compute import apply_computed, evaluate


def test_evaluate_runs_sql_against_wide():
    sql = "SELECT branch_num, 2.0 AS x FROM wide"
    wide = [{"branch_num": "1"}, {"branch_num": "2"}]
    values, status = evaluate(sql, wide, "x")
    assert status == "ok"
    assert values == [Decimal("2.0"), Decimal("2.0")]


def test_evaluate_returns_none_cells_on_failure():
    """SQL failure → status='compute_failed', values all None (no sentinel strings).

    Phase 1 policy: in-cell sentinels removed (consistent with assemble_wide).
    Failure info flows to a separate sentinels collection via assemble_status
    (task 13). evaluate's status field tells caller "this compute failed;
    treat all cells as missing".

    Note: DuckDB returns `inf` for `1/0` (not an error). Use undefined_fn() to
    trigger a real catalog error.
    """
    sql = "SELECT branch_num, undefined_fn() AS x FROM wide"
    wide = [{"branch_num": "1"}, {"branch_num": "2"}]
    values, status = evaluate(sql, wide, "x")
    assert status == "compute_failed"
    assert values == [None, None]


def test_evaluate_returns_none_when_column_missing():
    """If SQL doesn't SELECT the requested column_name → status=compute_failed."""
    sql = "SELECT branch_num, 1 AS y FROM wide"  # produces 'y', not 'x'
    wide = [{"branch_num": "1"}]
    values, status = evaluate(sql, wide, "x")
    assert status == "compute_failed"
    assert values == [None]


def test_evaluate_preserves_decimal_precision():
    """Computed values should be Decimal, not float."""
    sql = "SELECT branch_num, CAST(1234567890.1234567890 AS DECIMAL(38,10)) AS x FROM wide"
    wide = [{"branch_num": "1"}]
    values, status = evaluate(sql, wide, "x")
    assert status == "ok"
    assert len(values) == 1
    assert isinstance(values[0], Decimal)
    assert values[0] == Decimal("1234567890.1234567890")


def test_apply_computed_merges_column():
    wide = [
        {"branch_num": "1", "A@202603": Decimal("100")},
        {"branch_num": "2", "A@202603": Decimal("200")},
    ]
    computed = {"利润率": [Decimal("0.1"), Decimal("0.2")]}
    out = apply_computed(wide, computed)
    assert out[0]["利润率"] == Decimal("0.1")
    assert out[1]["利润率"] == Decimal("0.2")
    assert out[0]["A@202603"] == Decimal("100")  # original column preserved


def test_apply_computed_handles_missing_computed():
    """If a computed column is shorter than wide, missing entries stay absent."""
    wide = [
        {"branch_num": "1", "A@202603": Decimal("100")},
        {"branch_num": "2", "A@202603": Decimal("200")},
    ]
    computed = {"利润率": [Decimal("0.1")]}  # only 1 entry, wide has 2 rows
    out = apply_computed(wide, computed)
    assert out[0]["利润率"] == Decimal("0.1")
    assert "利润率" not in out[1]


def test_apply_computed_empty_wide():
    out = apply_computed([], {"利润率": []})
    assert out == []


def test_apply_computed_multiple_columns():
    wide = [{"branch_num": "1"}, {"branch_num": "2"}]
    computed = {
        "利润率": [Decimal("0.1"), Decimal("0.2")],
        "成本率": [Decimal("0.9"), Decimal("0.8")],
    }
    out = apply_computed(wide, computed)
    assert out[0]["利润率"] == Decimal("0.1")
    assert out[0]["成本率"] == Decimal("0.9")
    assert out[1]["成本率"] == Decimal("0.8")


# ---- review fixes: P0-1 / P1-1 / P1-3 / P1-5 / P1-6 ---- #

from compute import _detect_column_types


def test_evaluate_returns_compute_failed_on_row_count_mismatch():
    """P0-1: SQL with WHERE/GROUP BY/DISTINCT can return fewer rows than wide_rows.
    Without a row-count check, evaluate would silently return a short list with
    status='ok' — caller gets truncated data.
    """
    sql = "SELECT branch_num, 1.0 AS x FROM wide WHERE branch_num != '1'"
    wide = [{"branch_num": "1"}, {"branch_num": "2"}, {"branch_num": "3"}]
    values, status = evaluate(sql, wide, "x")
    assert status == "compute_failed"
    assert values == [None, None, None]


def test_detect_column_types_mixed_values_falls_back_to_varchar():
    """P1-6: column with mixed Decimal+str values → VARCHAR (don't blow up on INSERT).

    Previous logic: any Decimal/int present → DECIMAL(38,10), then 'hello' insert
    would raise. Fix: only DECIMAL when ALL non-None values are numeric.
    """
    rows = [
        {"a": Decimal("1.0"), "b": "x"},
        {"a": "hello", "b": "y"},
    ]
    types = _detect_column_types(rows)
    assert types["a"] == "VARCHAR", "mixed column must fall back to VARCHAR"
    assert types["b"] == "VARCHAR"


def test_detect_column_types_all_numeric_is_decimal():
    """P1-6 sanity: all-numeric column stays DECIMAL."""
    rows = [{"a": Decimal("1.0")}, {"a": Decimal("2.0")}, {"a": None}]
    types = _detect_column_types(rows)
    assert types["a"] == "DECIMAL(38,10)"


def test_validate_uses_decimal_columns_consistent_with_evaluate(conn):
    """P1-1: validate must use same column type inference as evaluate, so SQL that
    passes validate also passes evaluate (no VARCHAR/DECIMAL divergence).

    Both should detect Decimal cells and use DECIMAL(38,10), so SQL like
    `CAST(col AS DECIMAL)` works identically in both.
    """
    wide = [{"branch_num": "1", "x": Decimal("2.0")}]
    # validate should accept this SQL on DECIMAL-typed sample rows
    res = validate(
        conn,
        "SELECT branch_num, x FROM wide",
        wide,
        ["branch_num", "x"],
        None, None,
    )
    assert res.passed is True, f"validate should pass with DECIMAL columns: {res}"
    # evaluate should produce the same result
    values, status = evaluate("SELECT branch_num, x FROM wide", wide, "x")
    assert status == "ok"
    assert values == [Decimal("2.0")]


def test_evaluate_preserves_row_order_and_count():
    """P1-3 side-effect check: executemany preserves row order (no reordering).
    Also doubles as a regression test that the new fast-path doesn't lose rows.
    """
    sql = "SELECT branch_num, CAST(branch_num AS DECIMAL(38,10)) AS x FROM wide"
    wide = [{"branch_num": str(i)} for i in range(20)]
    values, status = evaluate(sql, wide, "x")
    assert status == "ok"
    assert len(values) == 20
    assert values == [Decimal(str(i)) for i in range(20)]