from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def doctor_checkout(tmp_path: Path) -> Path:
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (tmp_path / "frontend").mkdir()
    shutil.copyfile(REPO_ROOT / "scripts" / "doctor.py", scripts_dir / "doctor.py")
    return tmp_path


def test_doctor_help_prints_usage_without_running_diagnostics(doctor_checkout: Path):
    result = subprocess.run(
        [sys.executable, str(doctor_checkout / "scripts" / "doctor.py"), "--help"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert "usage: doctor.py" in result.stdout
    assert "DeerFlow Health Check" in result.stdout
    # argparse exits before the diagnostics sections are rendered
    assert "System Requirements" not in result.stdout


def test_doctor_rejects_unknown_flags(doctor_checkout: Path):
    result = subprocess.run(
        [sys.executable, str(doctor_checkout / "scripts" / "doctor.py"), "--not-a-real-flag"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=30,
    )

    assert result.returncode == 2
    assert "unrecognized arguments" in result.stderr
    assert "System Requirements" not in result.stdout


def test_doctor_without_args_still_runs_diagnostics(doctor_checkout: Path):
    env = {k: v for k, v in os.environ.items() if not k.startswith("DEER_FLOW_")}
    result = subprocess.run(
        [sys.executable, str(doctor_checkout / "scripts" / "doctor.py")],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=60,
        cwd=doctor_checkout,
    )

    assert result.returncode in (0, 1), result.stderr
    assert "DeerFlow Health Check" in result.stdout
    assert "System Requirements" in result.stdout
