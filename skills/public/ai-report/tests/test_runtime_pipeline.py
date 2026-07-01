"""Integration test for runtime_pipeline (in-memory store, pre-filled approved)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from duckdb_store import Store
from runtime_pipeline import RuntimePipeline


@pytest.fixture
def store_with_approved(tmp_path):
    """Per-test :memory: store with one approved snapshot (matches design_pipeline
    contract: descriptions stored as plain strings)."""
    db = str(tmp_path / "test.duckdb")
    s = Store(db_path=db)
    s.open()
    rid = s.upsert_report("rid", "Test Report", "/x.md", "h")
    sid = s.upsert_section(rid, 0, "S1")
    tid = s.upsert_table(rid, sid, 0, "R1", "md", "h", {
        "title": "R1",
        "headers_2d": [[{"text": "机构"}, {"text": "存款余额", "idx_id": "A", "period": "202603"}]],
        "rows": [{"branch_num": "1", "A@202603": 100.0}],
    })
    s.save_approved_run(
        "run1", tid, rid, sid,
        wide_table=[{"branch_num": "1", "A@202603": 100.0}],
        computed_columns=[],
        descriptions=["营业收入增长"],
        status="ok",
        sentinels=[],
        runlog_markdown="# run1",
        design_md_path="/mnt/ai-report-data/rid.design.md",
    )
    return s, rid, tid


def test_runtime_runs_5_steps(store_with_approved, tmp_path):
    """Happy path: 5 steps → report.md + report.docx written, status=completed."""
    s, rid, _ = store_with_approved
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    pipeline = RuntimePipeline(s)
    result = pipeline.run_report(rid, out_dir=str(out_dir))
    assert (out_dir / f"{rid}.report.md").exists()
    assert (out_dir / f"{rid}.report.docx").exists()
    assert "Test Report" in (out_dir / f"{rid}.report.md").read_text(encoding="utf-8")
    assert result["status"] == "completed"


def test_runtime_no_approved_returns_empty_status(store_with_approved, tmp_path):
    """If no approved snapshots, status=empty (non-strict)."""
    s, rid, tid = store_with_approved
    s.conn.execute("DELETE FROM approved_table_runs WHERE table_id=?", [tid])
    s.conn.execute("UPDATE report_tables SET approval_status='draft' WHERE table_id=?", [tid])
    pipeline = RuntimePipeline(s, strict=False)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    result = pipeline.run_report(rid, out_dir=str(out_dir))
    assert result["status"] == "empty"


def test_runtime_strict_mode_raises_on_no_approved(store_with_approved, tmp_path):
    """strict=True + no approved → RuntimeError (user opted into all-or-nothing)."""
    s, rid, tid = store_with_approved
    s.conn.execute("DELETE FROM approved_table_runs WHERE table_id=?", [tid])
    s.conn.execute("UPDATE report_tables SET approval_status='draft' WHERE table_id=?", [tid])
    pipeline = RuntimePipeline(s, strict=True)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    with pytest.raises(RuntimeError, match="no approved"):
        pipeline.run_report(rid, out_dir=str(out_dir))


def test_runtime_auto_creates_out_dir(store_with_approved, tmp_path):
    """Issue 19 修复: out_dir 不存在时自动 mkdir(parents=True, exist_ok=True).
    CLI first-run path: /mnt/ai-report-data 默认不存在, 旧版直接 FileNotFoundError."""
    s, rid, _ = store_with_approved
    out_dir = tmp_path / "nested" / "sub" / "out"  # 不 mkdir
    assert not out_dir.exists()
    pipeline = RuntimePipeline(s)
    result = pipeline.run_report(rid, out_dir=str(out_dir))
    assert result["status"] == "completed"
    assert out_dir.exists()
    assert (out_dir / f"{rid}.report.md").exists()


def test_cli_not_found_prints_to_stderr(store_with_approved, tmp_path, capsys):
    """Issue 22 修复: report_id 不存在 → stderr 提示 + exit 1 (不是静默退出)."""
    s, _, _ = store_with_approved
    import runtime_pipeline
    rc = runtime_pipeline.main(["--db-path", s._db_path, "--report-id", "no_such_rid", "--out-dir", str(tmp_path)])
    assert rc == 1
    err = capsys.readouterr().err
    assert "no_such_rid" in err
    assert "不存在" in err


def test_cli_empty_prints_to_stderr(store_with_approved, tmp_path, capsys):
    """Issue 22 修复: report 存在但无 approved → stderr 提示 + exit 1."""
    s, rid, tid = store_with_approved
    s.conn.execute("DELETE FROM approved_table_runs WHERE table_id=?", [tid])
    s.conn.execute("UPDATE report_tables SET approval_status='draft' WHERE table_id=?", [tid])
    import runtime_pipeline
    rc = runtime_pipeline.main(["--db-path", s._db_path, "--report-id", rid, "--out-dir", str(tmp_path)])
    assert rc == 1
    err = capsys.readouterr().err
    assert rid in err
    assert "approved" in err