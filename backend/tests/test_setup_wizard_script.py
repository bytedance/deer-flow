"""CLI contract for scripts/setup_wizard.py, exercised in a disposable checkout."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def wizard_checkout(tmp_path: Path) -> Path:
    checkout = tmp_path / "checkout"
    scripts_dir = checkout / "scripts"
    scripts_dir.mkdir(parents=True)
    shutil.copyfile(REPO_ROOT / "scripts" / "setup_wizard.py", scripts_dir / "setup_wizard.py")
    return checkout


def _run_wizard(checkout: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {name: value for name, value in os.environ.items() if not name.startswith("DEER_FLOW_") and name not in {"PYTHONPATH", "PYTHONHOME"}}
    return subprocess.run(
        [sys.executable, str(checkout / "scripts" / "setup_wizard.py"), *args],
        cwd=checkout,
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=30,
    )


def test_help_prints_usage_without_starting_the_wizard(wizard_checkout: Path):
    result = _run_wizard(wizard_checkout, "--help")

    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout
    assert "Welcome to DeerFlow Setup!" not in result.stdout
    assert "Non-interactive environment detected" not in result.stdout


def test_unknown_flag_exits_2_with_usage_error(wizard_checkout: Path):
    result = _run_wizard(wizard_checkout, "--verbos")

    assert result.returncode == 2
    assert "unrecognized arguments: --verbos" in result.stderr
    assert "Welcome to DeerFlow Setup!" not in result.stdout


def test_no_arguments_still_enters_the_wizard(wizard_checkout: Path):
    result = _run_wizard(wizard_checkout)

    # The subprocess has no tty, so the wizard reports that instead of prompting.
    assert result.returncode == 1, result.stderr
    assert "Non-interactive environment detected" in result.stdout
