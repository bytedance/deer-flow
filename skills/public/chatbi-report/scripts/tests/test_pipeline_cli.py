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
    # Default mode: status.json and runlog.md paths are OMITTED from the wire
    # format (the agent is told not to surface them in the user reply).
    assert "status_json" not in payload["result"]
    assert "runlog_md" not in payload["result"]
    # ...but the status.json file is still written to disk at the spec-pinned path.
    expected_status = tmp_path / f"{stem}.status.json"
    assert expected_status.exists()


def test_cli_phase2_debug_includes_status_json_and_runlog(tmp_path):
    """--debug exposes status_json and runlog_md paths in the wire format."""
    p1 = _run_cli(
        "phase1",
        "--md", str(INPUT_MD),
        "--out-dir", str(tmp_path),
        "--mock-fixture", str(FIXTURE),
    )
    assert p1.returncode == 0
    p1_payload = json.loads(p1.stdout.strip().splitlines()[-1])
    assert p1_payload["kind"] == "phase1_result"

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
        "--debug",
    )
    assert p2.returncode == 0
    last_line = p2.stdout.strip().splitlines()[-1]
    payload = json.loads(last_line)
    assert payload["kind"] == "phase2_result"
    assert Path(payload["result"]["status_json"]).exists()
    assert payload["result"]["runlog_md"] == str(tmp_path / f"{stem}.runlog.md")


def test_cli_phase1_debug_includes_runlog_md(tmp_path):
    """phase1 --debug exposes runlog_md path in the wire format."""
    result = _run_cli(
        "phase1",
        "--md", str(INPUT_MD),
        "--out-dir", str(tmp_path),
        "--mock-fixture", str(FIXTURE),
        "--debug",
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    last_line = result.stdout.strip().splitlines()[-1]
    payload = json.loads(last_line)
    assert payload["kind"] == "phase1_result"
    assert "runlog_md" in payload["result"]
    assert payload["result"]["runlog_md"] == str(tmp_path / f"{INPUT_MD.stem}.runlog.md")
    # Default mode would have omitted runlog_md; assert the negative for clarity.
    no_debug = _run_cli(
        "phase1",
        "--md", str(INPUT_MD),
        "--out-dir", str(tmp_path),
        "--mock-fixture", str(FIXTURE),
    )
    assert no_debug.returncode == 0
    no_debug_payload = json.loads(no_debug.stdout.strip().splitlines()[-1])
    assert no_debug_payload["kind"] == "phase1_result"
    assert "runlog_md" not in no_debug_payload["result"]
