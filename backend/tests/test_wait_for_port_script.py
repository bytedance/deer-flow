"""Run scripts/wait-for-port.sh against real loopback listeners with a hanging lsof."""

from __future__ import annotations

import os
import socket
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest
from support.shell import require_script_bash

REPO_ROOT = Path(__file__).resolve().parents[2]

# lsof spins forever, as on macOS in #1400; the marker records whether it ran.
_PRELUDE = r"""
lsof() { : > "$TEST_LSOF_MARKER"; while :; do :; done; }
ss() { return 1; }
netstat() { return 1; }
powershell.exe() { return 1; }
sleep() { return 0; }
export -f lsof ss netstat powershell.exe sleep
exec "$TEST_BASH" "$@"
"""


def _wait_for_port(tmp_path: Path, port: int, timeout: int) -> subprocess.CompletedProcess[str]:
    bash = require_script_bash()
    env = {key: value for key, value in os.environ.items() if key not in {"BASH_ENV", "ENV"}}
    env.update(TEST_BASH=bash, TEST_LSOF_MARKER=(tmp_path / "lsof-called").as_posix())
    return subprocess.run(
        [bash, "-c", _PRELUDE, "wait-for-port-test", (REPO_ROOT / "scripts" / "wait-for-port.sh").as_posix(), str(port), str(timeout), "Probe"],
        env=env,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
        check=False,
    )


def _listener(family: socket.AddressFamily, host: str) -> Iterator[int]:
    try:
        sock = socket.socket(family, socket.SOCK_STREAM)
        sock.bind((host, 0))
    except OSError as exc:
        pytest.skip(f"cannot bind {host}: {exc}")
    sock.listen()
    try:
        yield sock.getsockname()[1]
    finally:
        sock.close()


@pytest.fixture
def ipv4_port() -> Iterator[int]:
    yield from _listener(socket.AF_INET, "127.0.0.1")


@pytest.fixture
def ipv6_port() -> Iterator[int]:
    yield from _listener(socket.AF_INET6, "::1")


@pytest.fixture
def closed_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_ipv4_listener_is_ready_without_lsof(tmp_path: Path, ipv4_port: int) -> None:
    result = _wait_for_port(tmp_path, ipv4_port, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (tmp_path / "lsof-called").exists()


def test_ipv6_only_listener_is_ready_without_lsof(tmp_path: Path, ipv6_port: int) -> None:
    result = _wait_for_port(tmp_path, ipv6_port, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (tmp_path / "lsof-called").exists()


def test_closed_port_times_out_without_lsof(tmp_path: Path, closed_port: int) -> None:
    result = _wait_for_port(tmp_path, closed_port, timeout=3)
    assert result.returncode == 1, result.stdout + result.stderr
    assert f"Probe failed to start on port {closed_port} after 3s" in result.stdout
    assert not (tmp_path / "lsof-called").exists()
