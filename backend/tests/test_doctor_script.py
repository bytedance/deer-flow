"""CLI contract for scripts/doctor.py: --help and unknown flags must not run
the diagnostics. The no-argument invocation used by `make doctor` is unaffected.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "doctor.py"


def test_help_prints_usage_without_running_diagnostics():
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout
    # The diagnostic suite is not run: no report footer, no probe output.
    assert "Status:" not in result.stdout


def test_unknown_flag_exits_2_with_usage_error():
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--verbos"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=60,
    )

    assert result.returncode == 2
    assert "unrecognized arguments: --verbos" in result.stderr
    assert "Status:" not in result.stdout


def test_no_arguments_still_runs_the_diagnostics():
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=180,
    )

    # 0 = all required checks passed, 1 = failures reported; either way the
    # suite ran and printed its report footer.
    assert result.returncode in (0, 1), result.stderr
    assert "Status:" in result.stdout
