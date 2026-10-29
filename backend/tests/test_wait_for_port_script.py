"""Regression tests for scripts/wait-for-port.sh port validation."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "wait-for-port.sh"
BASH = shutil.which("bash")

pytestmark = pytest.mark.skipif(
    os.name == "nt" or BASH is None,
    reason="scripts/wait-for-port.sh is exercised with a POSIX bash",
)


def _run_script(tmp_path: Path, port: str) -> tuple[subprocess.CompletedProcess[str], Path]:
    """Run the script with an ``lsof`` stub that reports a listening port."""
    probe_log = tmp_path / "probe.log"
    stub_dir = tmp_path / "bin"
    stub_dir.mkdir()
    lsof = stub_dir / "lsof"
    lsof.write_text(f'#!/bin/sh\necho "$@" >> "{probe_log}"\nexit 0\n', encoding="utf-8")
    lsof.chmod(0o755)

    env = {**os.environ, "PATH": str(stub_dir)}
    result = subprocess.run(
        [str(BASH), str(SCRIPT), port, "0", "Demo"],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
        check=False,
    )
    return result, probe_log


@pytest.mark.parametrize("port", ["0", "0000", "65536", "9" * 40])
def test_rejects_ports_outside_the_valid_range(tmp_path: Path, port: str) -> None:
    result, probe_log = _run_script(tmp_path, port)

    assert result.returncode == 1
    assert "between 1 and 65535" in result.stderr
    assert not probe_log.exists(), "invalid ports must be rejected before probing"


@pytest.mark.parametrize("port", ["1", "80", "65535", "00080"])
def test_accepts_ports_inside_the_valid_range(tmp_path: Path, port: str) -> None:
    result, probe_log = _run_script(tmp_path, port)

    assert result.returncode == 0, result.stderr
    assert probe_log.exists(), "valid ports must reach the probe"
