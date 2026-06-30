"""Unit tests for compute (新写, 仅任务 8 的 sub-commands: assemble-wide + extract-ir)."""

from __future__ import annotations

from compute import ComputeIR, assemble_wide, extract_ir


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


def test_assemble_wide_preserves_sentinel_cells():
    facts = [
        {"branch_num": "1", "idx_id": "A", "period_alias": "202603", "numeric_value": None, "status": "query_failed"},
    ]
    wide = assemble_wide(facts, run_id="r1", table_id="t1")
    assert wide[0]["A@202603"] == "⚠️QUERY_FAILED"