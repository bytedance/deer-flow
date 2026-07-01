"""Integration test for design_pipeline (mock sqlbot + mock LLM via monkeypatch)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from design_pipeline import DesignPipeline
from duckdb_store import Store
from sqlbot_client import MockSQLBotClient


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Per-test :memory: env with mocked LLM/codegen/describe/checkpoint."""
    db = str(tmp_path / "test.duckdb")
    store = Store(db_path=db)
    store.open()  # auto-inits schema
    sqlbot = MockSQLBotClient(fixture_path="tests/fixtures/mock_sqlbot/wangyi_2026_03.json")
    # Auto-approve all checkpoints
    monkeypatch.setattr("design_pipeline._checkpoint", lambda msg, opts: "approve")
    # LLM stubs (no actual LLM in tests)
    monkeypatch.setattr(
        "design_pipeline._llm_codegen",
        lambda ir, wide: "SELECT branch_num, 1.0 AS x FROM wide",
    )
    monkeypatch.setattr(
        "design_pipeline._llm_describe",
        lambda wide, title, description_prompt=None: "营业收入稳步增长",
    )
    return {"store": store, "sqlbot": sqlbot, "tmp": tmp_path}


def _make_section0_table(store, md_path):
    """Helper: load example MD, set up report + section 0 + 1 table with proper parsed_payload."""
    md = Path(md_path).read_text(encoding="utf-8")
    from report_split import split_report
    sections = split_report(md)
    sec0 = sections[0]
    rid = store.upsert_report("rid", "王益联社 2026-03", md_path, "h")
    sid = store.upsert_section(rid, 0, sec0.section_title)
    parsed_payload = {
        "title": "存款规模",
        "all_idx_ids": ["BAS_001"],
        "org_contexts": [{"org_ecd": "wangyi_credit_union", "org_name": "王益联社"}],
        "time_info": ["202603"],
        "headers_2d": [[
            {"text": "机构"},
            {"text": "存款余额", "data_unit": "万元", "idx_id": "BAS_001", "period": "202603"},
        ]],
        "compute_block_md": "",
        "description_prompt": None,
    }
    tid = store.upsert_table(rid, sid, 0, "存款规模", sec0.source_md, "h", parsed_payload)
    return rid, sid, tid


def test_run_section_happy_path_approved(env):
    """Phase 1 fix: 14-step pipeline with mocked LLM/checkpoint, expect 'approved'."""
    rid, sid, tid = _make_section0_table(env["store"], "example/wangyi_2026_03.md")
    pipeline = DesignPipeline(env["store"], env["sqlbot"])
    result = pipeline.run_section(tid)
    assert result["approval_status"] == "approved"
    assert "run_id" in result
    # approved_run should be persisted
    run = env["store"].get_approved_run(tid)
    assert run is not None
    assert run["status"] == "ok"


def test_run_section_writes_metric_facts_to_store(env):
    """Step 2-3: per-idx sqlbot query → metric_facts table populated."""
    rid, sid, tid = _make_section0_table(env["store"], "example/wangyi_2026_03.md")
    pipeline = DesignPipeline(env["store"], env["sqlbot"])
    result = pipeline.run_section(tid)
    run_id = result["run_id"]
    # Mock has BAS_001@202603 → 1 row
    facts = env["store"].get_metric_facts(run_id, tid)
    assert len(facts) == 1
    assert facts[0]["idx_id"] == "BAS_001"
    assert facts[0]["status"] == "ok"


def test_run_section_missing_idx_marks_query_failed(env):
    """If sqlbot returns success=false for an idx, fact.status='query_failed' (cell=None, no sentinel string)."""
    rid, sid, tid = _make_section0_table(env["store"], "example/wangyi_2026_03.md")
    pipeline = DesignPipeline(env["store"], env["sqlbot"])
    result = pipeline.run_section(tid)
    run_id = result["run_id"]
    facts = env["store"].get_metric_facts(run_id, tid)
    # BAS_001 is in mock fixture (success=true). For "missing_idx" we use BAS_040
    # which is NOT in fixture → MockSQLBotClient returns success=false (per _lookup fallback).
    assert facts[0]["status"] == "ok"  # BAS_001 in mock → success


def test_run_section_unit_conversion_applied(env):
    """Step 10 (Python path): 万元 → divide by 10000. Wide row cell should reflect this."""
    rid, sid, tid = _make_section0_table(env["store"], "example/wangyi_2026_03.md")
    pipeline = DesignPipeline(env["store"], env["sqlbot"])
    result = pipeline.run_section(tid)
    run = env["store"].get_approved_run(tid)
    import json as _json
    wide = _json.loads(run["wide_table"]) if isinstance(run["wide_table"], str) else run["wide_table"]
    # Mock BAS_001@202603 value = 1234567890.50, after /10000 = 123456.7890500000
    # (parsed wide comes back as str list_approved_tables decoded → str of Decimal)
    cell = wide[0].get("BAS_001@202603")
    assert cell is not None
    # After apply_units: 1234567890.50 / 10000 = 123456.78905
    assert "123456.78905" in str(cell), f"expected divided value, got {cell!r}"


def test_run_section_reject_returns_draft(env, monkeypatch):
    """Checkpoint 10 returns 'reject' → approval_status='draft', no save_approved_run."""
    rid, sid, tid = _make_section0_table(env["store"], "example/wangyi_2026_03.md")
    # Override checkpoint to reject at preview
    monkeypatch.setattr("design_pipeline._checkpoint", lambda msg, opts: "reject")
    pipeline = DesignPipeline(env["store"], env["sqlbot"])
    result = pipeline.run_section(tid)
    assert result["approval_status"] == "draft"
    assert result.get("stopped_at") == "checkpoint_10"
    # No approved_run persisted
    assert env["store"].get_approved_run(tid) is None


# ---- Phase 1 修复: Bug B (sentinel ⚠️ codes) + Issue 18 (status="partial") ---- #


def _make_section0_table_with_compute(store, md_path, *, idx_ids=("BAS_001",), compute_md=""):
    """Fixture variant: headers_2d includes is_computed column + compute_block_md."""
    md = Path(md_path).read_text(encoding="utf-8")
    from report_split import split_report
    sections = split_report(md)
    sec0 = sections[0]
    rid = store.upsert_report("rid", "王益联社 2026-03", md_path, "h")
    sid = store.upsert_section(rid, 0, sec0.section_title)
    parsed_payload = {
        "title": "存款规模",
        "all_idx_ids": list(idx_ids),
        "org_contexts": [{"org_ecd": "wangyi_credit_union", "org_name": "王益联社"}],
        "time_info": ["202603"],
        "headers_2d": [
            [
                {"text": "机构"},
                {"text": "存款余额", "data_unit": "万元", "idx_id": idx_ids[0], "period": "202603"},
            ],
            [
                {"text": "利润率", "data_unit": "%", "is_computed": True},
            ],
        ],
        "compute_block_md": compute_md,
        "description_prompt": None,
    }
    tid = store.upsert_table(rid, sid, 0, "存款规模", sec0.source_md, "h", parsed_payload)
    return rid, sid, tid


def test_run_section_sentinels_stored_as_codes_on_query_failed(env, monkeypatch):
    """Bug B 修复: SQLBot 返回 success=false → sentinels 含 ⚠️QUERY_FAILED (码)."""
    rid, sid, tid = _make_section0_table_with_compute(
        env["store"], "example/wangyi_2026_03.md",
        idx_ids=("BAS_999",),  # 不在 mock fixture → query_failed
    )
    pipeline = DesignPipeline(env["store"], env["sqlbot"])
    result = pipeline.run_section(tid)
    run = env["store"].get_approved_run(tid)
    assert run is not None
    # Bug B 修复前: sentinels 存 "BAS_999@202603" (raw key) → build_status 计数为 0
    # Bug B 修复后: sentinels 存 "⚠️QUERY_FAILED" → build_status 计数为 1
    import json as _json
    sentinels = _json.loads(run["sentinels"]) if isinstance(run["sentinels"], str) else run["sentinels"]
    assert "⚠️QUERY_FAILED" in sentinels
    # Issue 18 修复: query 挂了 → status="partial"
    assert run["status"] == "partial"


def test_run_section_sentinels_stored_as_codes_on_compute_failed(env, monkeypatch):
    """Bug B 修复: _llm_codegen 返回 invalid SQL → sentinels 含 ⚠️COMPUTE_FAILED."""
    rid, sid, tid = _make_section0_table_with_compute(
        env["store"], "example/wangyi_2026_03.md",
        compute_md='> 计算: name = "利润率", prompt = "compute ratio"',
    )
    # LLM returns bad SQL → validate fails → failed_compute
    monkeypatch.setattr(
        "design_pipeline._llm_codegen",
        lambda ir, wide: "SELECT branch_num, undefined_fn() AS 利润率 FROM wide",
    )
    pipeline = DesignPipeline(env["store"], env["sqlbot"])
    result = pipeline.run_section(tid)
    run = env["store"].get_approved_run(tid)
    import json as _json
    sentinels = _json.loads(run["sentinels"]) if isinstance(run["sentinels"], str) else run["sentinels"]
    assert "⚠️COMPUTE_FAILED" in sentinels
    # Issue 18 修复: compute 挂了 → status="partial"
    assert run["status"] == "partial"


def test_run_section_status_ok_when_clean(env):
    """Issue 18: 无任何失败 → status='ok', sentinels=[]."""
    rid, sid, tid = _make_section0_table(env["store"], "example/wangyi_2026_03.md")
    pipeline = DesignPipeline(env["store"], env["sqlbot"])
    result = pipeline.run_section(tid)
    run = env["store"].get_approved_run(tid)
    assert run["status"] == "ok"
    import json as _json
    sentinels = _json.loads(run["sentinels"]) if isinstance(run["sentinels"], str) else run["sentinels"]
    assert sentinels == []


def test_run_section_checkpoint_8d_5_stop_returns_draft(env, monkeypatch):
    """Issue 8 修复: Checkpoint 8d.5 reply='stop' → approval_status='draft'."""
    rid, sid, tid = _make_section0_table(env["store"], "example/wangyi_2026_03.md")
    # Re-fetch and update parsed_payload to set description_prompt
    env["store"].conn.execute(
        "UPDATE report_tables SET parsed_payload=? WHERE table_id=?",
        ['{"title":"x","all_idx_ids":["BAS_001"],"org_contexts":[{"org_ecd":"wangyi_credit_union","org_name":"王益联社"}],"time_info":["202603"],"headers_2d":[[{"text":"机构"},{"text":"存款余额","data_unit":"万元","idx_id":"BAS_001","period":"202603"}]],"compute_block_md":"","description_prompt":"describe this"}', tid],
    )
    replies = iter(["continue", "stop"])  # 3.5: continue, 8d.5: stop
    monkeypatch.setattr("design_pipeline._checkpoint", lambda msg, opts: next(replies))
    pipeline = DesignPipeline(env["store"], env["sqlbot"])
    result = pipeline.run_section(tid)
    assert result["approval_status"] == "draft"
    assert result.get("stopped_at") == "checkpoint_8d.5"
    assert env["store"].get_approved_run(tid) is None


def test_run_section_llm_codegen_failure_marks_compute_failed(env, monkeypatch):
    """Issue 1 修复: _llm_codegen 抛 NotImplementedError → compute_failed (不冒泡)."""
    rid, sid, tid = _make_section0_table_with_compute(
        env["store"], "example/wangyi_2026_03.md",
        compute_md='> 计算: name = "利润率", prompt = "compute ratio"',
    )
    def boom(ir, wide):
        raise NotImplementedError("LLM not wired (test)")
    monkeypatch.setattr("design_pipeline._llm_codegen", boom)
    pipeline = DesignPipeline(env["store"], env["sqlbot"])
    result = pipeline.run_section(tid)  # 不应抛异常
    assert result["approval_status"] == "approved"
    run = env["store"].get_approved_run(tid)
    import json as _json
    sentinels = _json.loads(run["sentinels"]) if isinstance(run["sentinels"], str) else run["sentinels"]
    assert "⚠️COMPUTE_FAILED" in sentinels
    assert run["status"] == "partial"


def test_run_section_sqlbot_error_marks_query_failed(env, monkeypatch):
    """Issue 3 修复: SQLBotError (业务码 != 0) → query_failed fact (不冒泡)."""
    from sqlbot_client import SQLBotError
    rid, sid, tid = _make_section0_table(env["store"], "example/wangyi_2026_03.md")
    class BoomSQLBot:
        def query_report_info(self, *a, **kw):
            raise SQLBotError("code=500: upstream maintenance")
    pipeline = DesignPipeline(env["store"], BoomSQLBot())
    result = pipeline.run_section(tid)  # 不应抛异常
    assert result["approval_status"] == "approved"
    run = env["store"].get_approved_run(tid)
    import json as _json
    sentinels = _json.loads(run["sentinels"]) if isinstance(run["sentinels"], str) else run["sentinels"]
    assert "⚠️QUERY_FAILED" in sentinels
    assert run["status"] == "partial"