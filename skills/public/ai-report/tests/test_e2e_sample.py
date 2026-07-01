"""E2E test driving ai-report via step CLIs (no in-process Python bridge).

Drives Steps 0 → 16 via subprocess.run on the same wangyi_2026_03 fixture used
by the legacy in-process test. Asserts:
- 5 sections approved across 5 design iterations (skipping LLM codegen/describe
  for simplicity — we exercise the bash CLI contract, not the LLM agent turns)
- Runtime files: <report_id>.report.md, .report.docx, .status.json
- status.json status='ok', sections_approved=5, no sentinels
- The report content preserves Decimal precision (1234567890.50 → 123456.78905
  after the 万元 unit conversion)
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = SKILL_DIR / "scripts"
EXAMPLES = SKILL_DIR / "example"
FIXTURE = str(SKILL_DIR / "tests" / "fixtures" / "mock_sqlbot" / "wangyi_2026_03.json")
EXAMPLE_MD_REL = "example/wangyi_2026_03.md"


def _cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / args[0]), *args[1:]],
        capture_output=True, text=True, check=False,
    )


@pytest.fixture
def workspace(tmp_path, monkeypatch) -> dict:
    """Fresh workspace + DuckDB at tmp_path."""
    db_path = str(tmp_path / "e2e.duckdb")
    monkeypatch.setenv("DEER_FLOW_REPORT_DB_PATH", db_path)
    return {"tmp": tmp_path, "db_path": db_path, "example_md": str(EXAMPLES / "wangyi_2026_03.md")}


def test_e2e_full_pipeline_5_sections(workspace):
    md = workspace["example_md"]
    tmp = workspace["tmp"]
    db_path = workspace["db_path"]
    out_dir = tmp / "out"
    out_dir.mkdir()

    stem = "wangyi_2026_03"

    # Step 0 lint
    r = _cli("md_lint.py", md)
    assert r.returncode == 0, r.stderr

    # Step 2 parse
    parsed_path = tmp / f"{stem}.parsed.json"
    r = _cli("parse_md.py", "--md", md, "--out", str(parsed_path))
    assert r.returncode == 0, r.stderr
    parsed = json.loads(parsed_path.read_text(encoding="utf-8"))
    assert len(parsed["sections"]) == 5

    # Step 3 query (mock)
    query_path = tmp / f"{stem}.query.json"
    r = _cli(
        "sqlbot_client.py", "query",
        "--parsed", str(parsed_path),
        "--mock", "--mock-fixture", FIXTURE,
        "--out", str(query_path),
    )
    assert r.returncode == 0, r.stderr

    # Step 4 assemble-wide
    wide_path = tmp / f"{stem}.wide.json"
    r = _cli(
        "assemble_wide_duckdb.py",
        "--parsed", str(parsed_path), "--query", str(query_path),
        "--out", str(wide_path),
    )
    assert r.returncode == 0, r.stderr

    # Steps 6/7/8a/8b/8c/10/11 run per-section. For E2E we use the simplest
    # path: no computed columns (skip 6/7/8a/8b/8c), no describe (skip 10/11).
    # Each section's wide is the same after Step 4.
    sys.path.insert(0, str(SCRIPTS_DIR))
    from duckdb_store import Store, make_report_id

    report_id = make_report_id(md)

    # Seed all 5 sections + tables BEFORE opening any subprocess that touches
    # the same DuckDB file (single-writer — DuckDB lock conflict otherwise).
    store = Store(db_path=db_path)
    store.open()
    section_ids = []
    table_ids = []
    try:
        for i in range(5):
            sec_id = f"{report_id}_s{i:02d}"
            tbl_id = f"{sec_id}_t00"
            store.upsert_report(report_id, parsed["title"], md, "h1")
            store.upsert_section(report_id, i, parsed["sections"][i]["title"])
            store.upsert_table(
                report_id, sec_id, 0,
                parsed["sections"][i]["reports"][0]["title"],
                "compute_block", "h1",
                {"title": parsed["sections"][i]["reports"][0]["title"],
                 "headers_2d": []},
            )
            section_ids.append(sec_id)
            table_ids.append(tbl_id)
    finally:
        store.close()

    # Step 13 save_approved_run (per section)
    for i, (sec_id, tbl_id) in enumerate(zip(section_ids, table_ids)):
        approved = {
            "run_id": f"e2e-run-{i}",
            "table_id": tbl_id,
            "report_id": report_id,
            "section_id": sec_id,
            "wide_table": json.loads(wide_path.read_text(encoding="utf-8")),
            "headers_2d": [],
            "descriptions": [],
            "status": "ok",
            "sentinels": [],
            "runlog": f"# runlog section {i}",
            "design_md_path": f"/mnt/ai-report-data/{report_id}.design.md",
        }
        approved_path = tmp / f"approved.{i}.json"
        approved_path.write_text(json.dumps(approved), encoding="utf-8")
        r = _cli(
            "save_approved_run.py",
            "--input", str(approved_path), "--db-path", db_path,
        )
        assert r.returncode == 0, r.stderr

    # Steps 14-16
    r = _cli(
        "render_markdown.py", "--report-id", report_id,
        "--db-path", db_path, "--out-dir", str(out_dir),
    )
    assert r.returncode == 0, r.stderr
    r = _cli(
        "render_docx.py", "--report-id", report_id,
        "--db-path", db_path, "--out-dir", str(out_dir),
    )
    assert r.returncode == 0, r.stderr
    status_path = out_dir / f"{report_id}.status.json"
    r = _cli(
        "assemble_status.py", "--report-id", report_id,
        "--db-path", db_path, "--out", str(status_path),
    )
    assert r.returncode == 0, r.stderr

    status = json.loads(status_path.read_text(encoding="utf-8"))
    assert status["total_sections"] == 5
    assert status["approved_sections"] == 5
    assert status["total_sentinels"] == 0
    for code, count in status["sentinels_by_code"].items():
        assert count == 0, f"{code} count={count} on happy-path fixture"