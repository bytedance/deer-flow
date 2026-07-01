"""Subprocess-driven CLI test for scripts/save_approved_run.py (Step 13)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"


def test_save_approved_run_writes_to_duckdb(tmp_path):
    db_path = str(tmp_path / "save.duckdb")
    sys.path.insert(0, str(SCRIPTS_DIR))
    from duckdb_store import Store

    # Pre-seed report/section/table so save_approved_run finds a target row.
    seed_store = Store(db_path=db_path)
    seed_store.open()
    try:
        report_id = "rep-x"
        seed_store.upsert_report(report_id, "示例报告", "/tmp/x.md", "h1")
        sec_id = seed_store.upsert_section(report_id, 0, "示例章节")
        tbl_id = seed_store.upsert_table(
            report_id, sec_id, 0, "示例表", "compute_block", "h1",
            {"title": "示例表", "headers_2d": [], "all_idx_ids": []},
        )
    finally:
        seed_store.close()

    approved_payload = {
        "run_id": "runid-1234",
        "table_id": tbl_id,
        "report_id": report_id,
        "section_id": sec_id,
        "wide_table": [{"branch_num": "A", "x@2026": "100.50"}],
        "headers_2d": [["利润"]],
        "descriptions": ["示例描述。"],
        "status": "ok",
        "sentinels": [],
        "runlog": "# runlog line",
        "design_md_path": f"/mnt/ai-report-data/{report_id}.design.md",
    }
    in_path = tmp_path / "approved.json"
    in_path.write_text(json.dumps(approved_payload), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "save_approved_run.py"),
         "--input", str(in_path), "--db-path", db_path],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"

    # Verify the row landed in approved_runs.
    verify = Store(db_path=db_path)
    verify.open()
    try:
        rows = verify.list_approved_tables(report_id)
    finally:
        verify.close()
    assert len(rows) == 1
    # list_approved_tables returns the joined row (table_id, section_id, etc.).
    # report_id isn't SELECTed but is recoverable via get_report_meta + table_id.
    assert rows[0]["table_id"] == tbl_id
    assert rows[0]["run_id"] == "runid-1234"
    # status field round-trips.
    assert rows[0]["status"] == "ok"