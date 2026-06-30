"""Unit tests for compute (新写, task 8: assemble-wide + extract-ir)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from compute import ComputeIR, assemble_wide, extract_ir, reset_conn_for_tests


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