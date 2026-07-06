"""CLI subprocess tests for scripts/pipeline.py — wire format kinds."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


SCRIPTS_DIR = Path(__file__).resolve().parent.parent
PIPELINE = SCRIPTS_DIR / "pipeline.py"
FIXTURE = SCRIPTS_DIR.parent / "example" / "mock_sqlbot" / "profit_yoy.json"
INPUT_MD = SCRIPTS_DIR.parent / "example" / "input.md"


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PIPELINE), *args],
        capture_output=True,
        text=True,
        cwd=str(SCRIPTS_DIR),
    )


def test_cli_phase1_emits_phase1_result_wire_format(tmp_path):
    """phase1 subcommand on happy MD emits last-line JSON with kind=phase1_result."""
    result = _run_cli(
        "phase1",
        "--md", str(INPUT_MD),
        "--out-dir", str(tmp_path),
        "--mock-fixture", str(FIXTURE),
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    last_line = result.stdout.strip().splitlines()[-1]
    payload = json.loads(last_line)
    assert payload["kind"] == "phase1_result"
    assert "result" in payload
    assert "parsed" in payload["result"]


def test_cli_phase1_emits_checkpoint_wire_format_on_broken_md(tmp_path):
    """phase1 subcommand on broken MD emits last-line JSON with kind=checkpoint."""
    broken = tmp_path / "broken.md"
    broken.write_text(
        "# Title\n\n"
        "> 机构:\n"
        ">   branch_num=27020199; branch_short_name=王益联社\n"
        "> 时期: time_info=[\"2025\"]\n\n"
        "## Section\n\n"
        "### Report\n\n"
        "| no-attr | header |\n"
        "| --- | --- |\n"
        "| a | b |\n",
        encoding="utf-8",
    )
    result = _run_cli(
        "phase1",
        "--md", str(broken),
        "--out-dir", str(tmp_path),
        "--mock-fixture", str(FIXTURE),
    )
    assert result.returncode == 0
    last_line = result.stdout.strip().splitlines()[-1]
    payload = json.loads(last_line)
    assert payload["kind"] == "checkpoint"
    assert payload["step"] == "1.5"


def test_cli_phase2_emits_phase2_result_wire_format(tmp_path):
    """phase2 subcommand emits last-line JSON with kind=phase2_result."""
    # First run phase1
    p1 = _run_cli(
        "phase1",
        "--md", str(INPUT_MD),
        "--out-dir", str(tmp_path),
        "--mock-fixture", str(FIXTURE),
    )
    assert p1.returncode == 0, f"phase1 stderr: {p1.stderr}"
    p1_payload = json.loads(p1.stdout.strip().splitlines()[-1])
    assert p1_payload["kind"] == "phase1_result"

    # Provide description files at <stem>.description.report-<idx>.txt
    # (matches render_markdown.attach_description_files fallback naming).
    desc_dir = tmp_path / "desc"
    desc_dir.mkdir()
    stem = INPUT_MD.stem
    for i, _ in enumerate(p1_payload["result"]["description_prompts"]):
        (desc_dir / f"{stem}.description.report-{i}.txt").write_text(
            f"desc {i}", encoding="utf-8"
        )

    p2 = _run_cli(
        "phase2",
        "--md", str(INPUT_MD),
        "--out-dir", str(tmp_path),
        "--descriptions-dir", str(desc_dir),
    )
    assert p2.returncode == 0, f"stderr: {p2.stderr}"
    last_line = p2.stdout.strip().splitlines()[-1]
    payload = json.loads(last_line)
    assert payload["kind"] == "phase2_result"
    assert Path(payload["result"]["report_md"]).exists()
    assert Path(payload["result"]["status_json"]).exists()
