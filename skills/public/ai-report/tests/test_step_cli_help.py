"""Smoke-test every step CLI's --help output."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"

CLI_STEPS = [
    ("parse_md.py", []),
    ("compute.py", []),
    ("unit_convert.py", []),
    ("assemble_status.py", []),
    ("assemble_wide_duckdb.py", []),
    ("save_approved_run.py", []),
]


@pytest.mark.parametrize("script,args", CLI_STEPS)
def test_step_cli_help(script: str, args: list[str]):
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / script), "--help"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, (
        f"{script} --help failed: stderr={result.stderr!r}"
    )
    assert "usage" in result.stdout.lower() or "options" in result.stdout.lower()