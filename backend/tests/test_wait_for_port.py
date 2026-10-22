"""Timeout arguments to the port-wait helper must fail fast when malformed."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from support.shell import require_script_bash

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "wait-for-port.sh"

_PRELUDE = """
powershell.exe() { return 1; }
lsof() { return ${TEST_PORT_LISTENING:-1}; }
ss() { return 1; }
netstat() { return 1; }
source "$1" "${@:2}"
"""


def _run(timeout: str | None, *, listening: bool = False) -> subprocess.CompletedProcess[str]:
    bash = require_script_bash()
    env = os.environ.copy()
    env.pop("BASH_ENV", None)
    env["TEST_PORT_LISTENING"] = "0" if listening else "1"
    command = [bash, "-c", _PRELUDE, "wait-for-port-test", SCRIPT.as_posix(), "54321"]
    if timeout is not None:
        command.append(timeout)
    return subprocess.run(
        command,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=5,
        check=False,
    )


@pytest.mark.parametrize(
    "timeout",
    ["abc", "1.5", "-1", "9223372036854775808"],
    ids=["text", "fraction", "negative", "integer-overflow"],
)
def test_invalid_timeout_is_rejected_before_waiting(timeout: str) -> None:
    result = _run(timeout)

    assert result.returncode == 1
    assert "Timeout" in result.stderr
    assert "Waiting for" not in result.stdout


def test_zero_timeout_still_probes_once() -> None:
    result = _run("0")

    assert result.returncode == 1
    assert "failed to start on port 54321 after 0s" in result.stdout
    assert "Waiting for" not in result.stdout


def test_leading_zero_timeout_is_decimal() -> None:
    result = _run("08", listening=True)

    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("timeout", [None, ""], ids=["omitted", "empty"])
def test_missing_timeout_uses_default(timeout: str | None) -> None:
    result = _run(timeout, listening=True)

    assert result.returncode == 0, result.stdout + result.stderr
