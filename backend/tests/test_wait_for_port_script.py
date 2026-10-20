from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from support.shell import require_script_bash

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "wait-for-port.sh"


def run_wait(tmp_path: Path, timeout: str, *, listening: bool, stop_on_sleep: bool = False) -> subprocess.CompletedProcess[str]:
    bash = require_script_bash()
    # Isolate the probe tools from host listeners, PowerShell, and networking.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    probe_marker = tmp_path / "probed"
    for name, body in {
        "lsof": 'printf x >> "$PROBE_MARKER"\n' + ("exit 0\n" if listening else "exit 1\n"),
        "sleep": "exit 0\n",
    }.items():
        command = bin_dir / name
        command.write_text(f"#!{bash}\n{body}", encoding="utf-8", newline="\n")
        command.chmod(0o755)
    env = {**os.environ, "PATH": str(bin_dir), "PROBE_MARKER": str(probe_marker)}
    command = [bash, str(SCRIPT), "3000", timeout, "Test service"]
    if stop_on_sleep:
        # Exit the shell if invalid input reaches polling, without hanging the
        # regression test against the unfixed script or leaving child processes.
        command = [bash, "-c", 'sleep() { exit 99; }; source "$@"', "wait-for-port-test", *command[1:]]
    return subprocess.run(
        command,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=5,
        check=False,
    )


@pytest.mark.skipif(os.name == "nt", reason="isolated executable probe stubs require POSIX")
@pytest.mark.parametrize("timeout", ["abc", "1.5", "-1", "+1", " 1", "1 ", "999999999999999999999999999999999"])
def test_invalid_timeout_is_rejected_before_probing(tmp_path: Path, timeout: str):
    result = run_wait(tmp_path, timeout, listening=True)

    assert result.returncode == 1
    assert "Timeout must be a non-negative integer number of seconds" in result.stderr
    assert not (tmp_path / "probed").exists()


@pytest.mark.skipif(os.name == "nt", reason="isolated executable probe stubs require POSIX")
@pytest.mark.parametrize("timeout", ["abc", "1.5", "999999999999999999999999999999999"])
def test_invalid_timeout_cannot_enter_the_wait_loop(tmp_path: Path, timeout: str):
    result = run_wait(tmp_path, timeout, listening=False, stop_on_sleep=True)

    assert result.returncode == 1
    assert "Timeout must be a non-negative integer number of seconds" in result.stderr
    assert not (tmp_path / "probed").exists()


@pytest.mark.skipif(os.name == "nt", reason="isolated executable probe stubs require POSIX")
@pytest.mark.parametrize("timeout", ["0", "1", "08", ""])
def test_valid_timeout_accepts_an_already_listening_port(tmp_path: Path, timeout: str):
    result = run_wait(tmp_path, timeout, listening=True)

    assert result.returncode == 0
    assert result.stderr == ""
    assert (tmp_path / "probed").read_text() == "x"


@pytest.mark.skipif(os.name == "nt", reason="isolated executable probe stubs require POSIX")
@pytest.mark.parametrize("timeout,probes", [("0", 1), ("2", 3), ("02", 3)])
def test_closed_port_still_times_out(tmp_path: Path, timeout: str, probes: int):
    result = run_wait(tmp_path, timeout, listening=False)

    assert result.returncode == 1
    assert f"after {timeout}s" in result.stdout
    assert result.stderr == ""
    assert (tmp_path / "probed").read_text() == "x" * probes
