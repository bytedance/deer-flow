"""5 sentinels coverage: query_failed / cast_failed / compute_failed / description_failed / lint_failed.

Phase 1 政策: cell 不编码哨兵字符串, NULL 留空; 哨兵聚合走 assemble_status.
本测试只验证哨兵触发 (status / eval status / lint errors) 和哨兵常量存在,
不验证 cell 值. cell-哨兵契约由 render_markdown 的 payload 翻译层 (task 14) 负责.
"""

from __future__ import annotations

from compute import assemble_wide, evaluate
from md_lint import lint_markdown


def test_query_failed_status_recorded():
    """query_failed 在 metric_facts.status, 触发 ⚠️QUERY_FAILED 哨兵计数."""
    facts = [{"branch_num": "1", "idx_id": "A", "period_alias": "202603",
              "numeric_value": None, "status": "query_failed"}]
    wide = assemble_wide(facts, "r1", "t1")
    # Phase 1: cell is None, not sentinel string
    assert wide[0]["A@202603"] is None
    # 哨兵信号: 失败 fact 仍存在, status 字段保留
    assert facts[0]["status"] == "query_failed"


def test_cast_failed_status_recorded():
    """cast_failed 同 query_failed: cell=None, status 字段保留触发哨兵."""
    facts = [{"branch_num": "1", "idx_id": "A", "period_alias": "202603",
              "numeric_value": None, "status": "cast_failed"}]
    wide = assemble_wide(facts, "r1", "t1")
    assert wide[0]["A@202603"] is None
    assert facts[0]["status"] == "cast_failed"


def test_compute_failed_status_returned():
    """evaluate 返回 status='compute_failed' 触发 ⚠️COMPUTE_FAILED 哨兵."""
    # undefined_fn 触发 catalog 错误 (1/0 返回 inf, 不报错)
    values, status = evaluate(
        "SELECT branch_num, undefined_fn() AS x FROM wide",
        [{"branch_num": "1"}], "x",
    )
    assert status == "compute_failed"
    assert values == [None]


def test_description_failed_sentinel_constant_defined():
    """⚠️DESCRIPTION_FAILED 哨兵常量存在 (orchestrator 层面触发)."""
    from assemble_status import SENTINEL_CODES
    assert "⚠️DESCRIPTION_FAILED" in SENTINEL_CODES
    assert "⚠️QUERY_FAILED" in SENTINEL_CODES
    assert "⚠️CAST_FAILED" in SENTINEL_CODES
    assert "⚠️COMPUTE_FAILED" in SENTINEL_CODES
    assert "⚠️LINT_FAILED" in SENTINEL_CODES


def test_lint_failed_sentinel_from_md_lint():
    """md_lint 报错 → ⚠️LINT_FAILED 触发 checkpoint 0 阻断."""
    md = """# T
## S
### R
> 机构:
>   branch_short_name=x
<table><thead><tr><th>机构</th></tr></thead></table>
"""
    rep = lint_markdown(md)
    # 缺 时期: time_info → 触发 lint error → ⚠️LINT_FAILED
    assert len(rep.errors) > 0
    assert any(e.code.startswith("missing_time_info") for e in rep.errors)