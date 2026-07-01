"""Subprocess-driven CLI test for scripts/assemble_status.py."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"


def test_assemble_status_cli_writes_status_json_and_receipt(tmp_path):
    """Seed approved_runs with one approved row, run CLI, check status.json + 回执."""
    db_path = str(tmp_path / "status.duckdb")
    sys.path.insert(0, str(SCRIPTS_DIR))
    from duckdb_store import Store

    store = Store(db_path=db_path)
    store.open()
    try:
        report_id = "test-status"
        store.upsert_report(report_id, "测试", "/tmp/test.md", "h1")
        sec_id = store.upsert_section(report_id, 0, "示例章节")
        tbl_id = store.upsert_table(
            report_id, sec_id, 0, "示例表", "compute_block",
            "h1", {"title": "示例表", "headers_2d": []},
        )
        # Need run_id (uuid hex per make_run_id()) — make one up.
        run_id = "deadbeef" * 4
        store.save_approved_run(
            run_id, tbl_id, report_id, sec_id,
            [{"branch_num": "A", "x@2026": "100"}],
            [], [], "ok",
            [], "# runlog", f"/mnt/ai-report-data/{report_id}.design.md",
        )
    finally:
        store.close()

    out = tmp_path / f"{report_id}.status.json"
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "assemble_status.py"),
         "--report-id", report_id, "--db-path", db_path, "--out", str(out)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    status = json.loads(out.read_text(encoding="utf-8"))
    assert status["report_id"] == report_id
    assert status["approved_sections"] == 1
    assert status["total_sections"] == 1
    assert status["design_md_path"].endswith(".design.md")
    # stdout should contain 中文回执 — at minimum the report_id or approved count.
    assert "1/1 approved" in result.stdout or report_id in result.stdout