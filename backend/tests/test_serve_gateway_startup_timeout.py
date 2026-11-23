"""Run the launcher and real port-wait loop without starting application services."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from support.shell import require_script_bash

REPO_ROOT = Path(__file__).resolve().parents[2]

# Stub process launches and readiness/time, retaining serve.sh's admission,
# timeout forwarding, failure diagnostics and cleanup, plus the real wait loop.
_PRELUDE = r"""
git() { return 1; }
pgrep() { return 1; }
nginx() { return 0; }
ss() { return 1; }
netstat() { return 1; }
powershell.exe() { return 1; }
lsof() {
    case "$*" in
        *-iTCP:8001*)
            if [ -f "$TEST_STARTED" ] && [ "$(cat "$TEST_CLOCK")" -ge "$TEST_READY_AT" ]; then
                echo 12345
                return 0
            fi
            ;;
    esac
    return 1
}
sleep() { printf '%s\n' "$(( $(cat "$TEST_CLOCK") + 1 ))" > "$TEST_CLOCK"; }
python3() { "$TEST_PYTHON" "$@"; }
env() {
    if [ "$1" = python3 ]; then shift; python3 "$@"; else command env "$@"; fi
}
sh() {
    case "$*" in
        *uvicorn*)
            printf 'Gateway is still initializing\n' > logs/gateway.log
            touch "$TEST_STARTED"
            ;;
    esac
}
nohup() { sh "$@"; }
bash() {
    if [ "$1" = ./scripts/wait-for-port.sh ] && [ "$2" != 8001 ]; then return 0; fi
    command "$TEST_BASH" "$@"
}
export -f lsof sleep ss netstat powershell.exe
source "$@"
"""


def _run_launcher(tmp_path: Path, *, timeout: str | None, ready_at: int = 145, args: tuple[str, ...] = ("--dev",), dotenv: bool = False) -> subprocess.CompletedProcess[str]:
    checkout = tmp_path / "checkout"
    scripts = checkout / "scripts"
    scripts.mkdir(parents=True)
    (checkout / "backend").mkdir()
    for name in ("serve.sh", "dotenv_exports.py", "wait-for-port.sh", "port-listening.sh", "detect_uv_extras.py"):
        shutil.copy2(REPO_ROOT / "scripts" / name, scripts / name)
    (scripts / "nginx-local-conf.sh").write_text("printf 'test-nginx.conf\\n'\n", encoding="utf-8", newline="\n")
    (scripts / "config-upgrade.sh").write_text("exit 0\n", encoding="utf-8", newline="\n")
    (scripts / "cleanup-containers.sh").write_text('printf "cleanup\\n" >> "$TEST_CLEANUP"\n', encoding="utf-8", newline="\n")
    (checkout / "config.yaml").write_text("models: []\n", encoding="utf-8", newline="\n")
    (tmp_path / "clock").write_text("0\n", encoding="utf-8", newline="\n")
    bash = require_script_bash()
    env = {key: value for key, value in os.environ.items() if key not in {"BASH_ENV", "ENV", "DEER_FLOW_GATEWAY_STARTUP_TIMEOUT", "DEER_FLOW_ENV_FILE"}}
    env.update(
        TEST_BASH=bash,
        TEST_PYTHON=Path(sys.executable).as_posix(),
        TEST_CLOCK=(tmp_path / "clock").as_posix(),
        TEST_STARTED=(tmp_path / "started").as_posix(),
        TEST_CLEANUP=(tmp_path / "cleanup").as_posix(),
        TEST_READY_AT=str(ready_at),
        DEER_FLOW_HOME=(tmp_path / "runtime").as_posix(),
        DEER_FLOW_PROJECT_ROOT=checkout.as_posix(),
        DEER_FLOW_CONFIG_PATH=(checkout / "config.yaml").as_posix(),
    )
    if timeout is not None:
        if dotenv:
            (checkout / ".env").write_text(f"DEER_FLOW_GATEWAY_STARTUP_TIMEOUT={timeout}\n", encoding="utf-8", newline="\n")
        else:
            env["DEER_FLOW_GATEWAY_STARTUP_TIMEOUT"] = timeout
    return subprocess.run(
        [bash, "-c", _PRELUDE, "startup-timeout-test", (scripts / "serve.sh").as_posix(), "--skip-install", *args],
        cwd=checkout,
        env=env,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
        check=False,
    )


@pytest.mark.parametrize("args", [("--dev",), ("--prod",), ("--dev", "--daemon")])
def test_configured_gateway_timeout_allows_slow_startup(tmp_path: Path, args: tuple[str, ...]) -> None:
    result = _run_launcher(tmp_path, timeout="240", args=args)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Gateway started on localhost:8001" in result.stdout


def test_gateway_timeout_can_be_loaded_from_dotenv(tmp_path: Path) -> None:
    result = _run_launcher(tmp_path, timeout="240", dotenv=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_default_gateway_timeout_accepts_a_fast_startup(tmp_path: Path) -> None:
    result = _run_launcher(tmp_path, timeout=None, ready_at=5)
    assert result.returncode == 0, result.stdout + result.stderr


def test_default_gateway_timeout_remains_bounded(tmp_path: Path) -> None:
    result = _run_launcher(tmp_path, timeout=None)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "after 30s" in result.stdout
    assert "Gateway is still initializing" in result.stdout
    assert "DEER_FLOW_GATEWAY_STARTUP_TIMEOUT" in result.stdout
    assert (tmp_path / "cleanup").read_text(encoding="utf-8").splitlines() == ["cleanup", "cleanup"]


def test_configured_gateway_timeout_still_times_out_and_cleans_up(tmp_path: Path) -> None:
    result = _run_launcher(tmp_path, timeout="40")
    assert result.returncode == 1, result.stdout + result.stderr
    assert "after 40s" in result.stdout
    assert (tmp_path / "cleanup").read_text(encoding="utf-8").splitlines() == ["cleanup", "cleanup"]


@pytest.mark.parametrize("value", ["", "0", "-1", "1.5", "abc", "9999999999999999999999999999999"])
@pytest.mark.parametrize("action", ["--dev", "--restart"])
def test_invalid_gateway_timeout_does_not_stop_services(tmp_path: Path, value: str, action: str) -> None:
    result = _run_launcher(tmp_path, timeout=value, args=(action,))
    assert result.returncode == 1, result.stdout + result.stderr
    assert "DEER_FLOW_GATEWAY_STARTUP_TIMEOUT must be a positive integer" in result.stdout + result.stderr
    assert not (tmp_path / "cleanup").exists()
    assert not (tmp_path / "started").exists()


def test_invalid_gateway_timeout_does_not_block_stop(tmp_path: Path) -> None:
    result = _run_launcher(tmp_path, timeout="invalid", args=("--stop",))
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "cleanup").exists()
    assert not (tmp_path / "started").exists()


# Windows netstat -ano rows. 18001 and 80010 must not count as 8001, and an
# established socket whose foreign port is 8001 is not a listener.
_WINDOWS_NETSTAT = r"""
  TCP    127.0.0.1:18001        0.0.0.0:0              LISTENING       4
  TCP    127.0.0.1:8001         0.0.0.0:0              LISTENING       9
  TCP    [::1]:8001             [::]:0                 LISTENING       9
  TCP    10.0.0.1:50000         1.2.3.4:8001           ESTABLISHED     9
  TCP    0.0.0.0:80010          0.0.0.0:0              LISTENING       3
"""


def _run_port_probe(tmp_path: Path, script: str, args: list[str], *, uname_s: str, netstat_flag: str, netstat_stdout: str) -> subprocess.CompletedProcess[str]:
    """Run a copied probe with lsof/ss absent and a powershell.exe that hangs."""
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    for name in ("port-listening.sh", "wait-for-port.sh"):
        shutil.copy2(REPO_ROOT / "scripts" / name, scripts / name)
    marker = tmp_path / "powershell-called"
    fixture = tmp_path / "netstat.txt"
    fixture.write_text(netstat_stdout, encoding="utf-8", newline="\n")
    hung = tmp_path / "hung-helper"
    prelude = r"""
uname() { printf uname > "$TEST_HUNG"; sleep 30; }
dirname() { printf dirname > "$TEST_HUNG"; sleep 30; }
command() {
    if [ "$1" = -v ] && { [ "$2" = lsof ] || [ "$2" = ss ]; }; then
        return 1
    fi
    builtin command "$@"
}
powershell.exe() { printf hung > "$TEST_PS"; sleep 30; }
netstat() {
    if [ "$1" = "$TEST_NETSTAT_FLAG" ]; then
        cat "$TEST_NETSTAT_FILE"
        return 0
    fi
    printf 'unexpected netstat args: %s\n' "$*" >&2
    return 1
}
export -f uname dirname command powershell.exe netstat
bash "$TEST_SCRIPT" "$@"
"""
    bash = require_script_bash()
    env = {key: value for key, value in os.environ.items() if key not in {"BASH_ENV", "ENV"}}
    env.update(
        OSTYPE="msys" if uname_s.upper().startswith(("MINGW", "MSYS", "CYGWIN")) else "linux-gnu",
        TEST_NETSTAT_FLAG=netstat_flag,
        TEST_NETSTAT_FILE=fixture.as_posix(),
        TEST_PS=marker.as_posix(),
        TEST_HUNG=hung.as_posix(),
        TEST_SCRIPT=(scripts / script).as_posix(),
    )
    result = subprocess.run(
        [bash, "-c", prelude, "port-probe", *args],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=8,
        check=False,
    )
    assert not marker.exists(), result.stdout + result.stderr
    assert not hung.exists(), result.stdout + result.stderr
    return result


# 80010 is not a TCP port (1..65535), so the probe rejects it before netstat.
# 18001 is the in-range port that must still match as itself.
@pytest.mark.parametrize(("port", "expected"), [("8001", 0), ("18001", 0), ("80010", 1), ("801", 1), ("50000", 1)])
def test_windows_netstat_matches_only_the_listening_port(tmp_path: Path, port: str, expected: int) -> None:
    result = _run_port_probe(tmp_path, "port-listening.sh", [port], uname_s="MINGW64_NT-10.0", netstat_flag="-ano", netstat_stdout=_WINDOWS_NETSTAT)
    assert result.returncode == expected, result.stdout + result.stderr


def test_windows_netstat_does_not_treat_a_longer_port_as_8001(tmp_path: Path) -> None:
    nearby_only = "\n".join(
        (
            "  TCP    127.0.0.1:18001        0.0.0.0:0              LISTENING       4",
            "  TCP    0.0.0.0:80010          0.0.0.0:0              LISTENING       3",
            "  TCP    10.0.0.1:50000         1.2.3.4:8001           ESTABLISHED     9",
        )
    )
    result = _run_port_probe(tmp_path, "port-listening.sh", ["8001"], uname_s="MINGW64_NT-10.0", netstat_flag="-ano", netstat_stdout=nearby_only)
    assert result.returncode == 1, result.stdout + result.stderr


def test_windows_wait_returns_without_calling_powershell(tmp_path: Path) -> None:
    result = _run_port_probe(
        tmp_path,
        "wait-for-port.sh",
        ["8001", "5", "Gateway"],
        uname_s="MINGW64_NT-10.0",
        netstat_flag="-ano",
        netstat_stdout=_WINDOWS_NETSTAT,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "failed to start" not in result.stdout


def test_linux_netstat_listen_check_still_matches_local_address(tmp_path: Path) -> None:
    result = _run_port_probe(
        tmp_path,
        "port-listening.sh",
        ["8001"],
        uname_s="Linux",
        netstat_flag="-ltn",
        netstat_stdout="tcp        0      0 127.0.0.1:8001          0.0.0.0:*               LISTEN",
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_preflight_rejects_a_windows_listener(tmp_path: Path) -> None:
    checkout = tmp_path / "checkout"
    scripts = checkout / "scripts"
    scripts.mkdir(parents=True)
    (checkout / "backend").mkdir()
    for name in ("serve.sh", "dotenv_exports.py", "wait-for-port.sh", "port-listening.sh", "detect_uv_extras.py"):
        shutil.copy2(REPO_ROOT / "scripts" / name, scripts / name)
    (scripts / "nginx-local-conf.sh").write_text("printf 'test-nginx.conf\\n'\n", encoding="utf-8", newline="\n")
    (scripts / "config-upgrade.sh").write_text("exit 0\n", encoding="utf-8", newline="\n")
    (scripts / "cleanup-containers.sh").write_text('printf "cleanup\\n" >> "$TEST_CLEANUP"\n', encoding="utf-8", newline="\n")
    (checkout / "config.yaml").write_text("models: []\n", encoding="utf-8", newline="\n")
    marker = tmp_path / "powershell-called"
    prelude = r"""
git() { return 1; }
pgrep() { return 1; }
nginx() { return 0; }
command() {
    if [ "$1" = -v ] && { [ "$2" = lsof ] || [ "$2" = ss ]; }; then
        return 1
    fi
    builtin command "$@"
}
sleep() { return 0; }
uname() { printf '%s\n' 'MINGW64_NT-10.0'; }
powershell.exe() { printf hung > "$TEST_PS"; sleep 30; }
netstat() {
    printf '%s\n' '  TCP    127.0.0.1:8001         0.0.0.0:0              LISTENING       42'
    return 0
}
python3() { "$TEST_PYTHON" "$@"; }
env() {
    if [ "$1" = python3 ]; then shift; python3 "$@"; else command env "$@"; fi
}
sh() { touch "$TEST_STARTED"; }
nohup() { sh "$@"; }
bash() { command "$TEST_BASH" "$@"; }
export -f command sleep uname powershell.exe netstat
source "$@"
"""
    bash = require_script_bash()
    env = {key: value for key, value in os.environ.items() if key not in {"BASH_ENV", "ENV", "DEER_FLOW_GATEWAY_STARTUP_TIMEOUT", "DEER_FLOW_ENV_FILE"}}
    env.update(
        TEST_BASH=bash,
        TEST_PYTHON=Path(sys.executable).as_posix(),
        TEST_PS=marker.as_posix(),
        TEST_CLEANUP=(tmp_path / "cleanup").as_posix(),
        TEST_STARTED=(tmp_path / "started").as_posix(),
        OSTYPE="msys",
        DEER_FLOW_HOME=(tmp_path / "runtime").as_posix(),
        DEER_FLOW_PROJECT_ROOT=checkout.as_posix(),
        DEER_FLOW_CONFIG_PATH=(checkout / "config.yaml").as_posix(),
    )
    result = subprocess.run(
        [bash, "-c", prelude, "windows-preflight", (scripts / "serve.sh").as_posix(), "--skip-install", "--dev"],
        cwd=checkout,
        env=env,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
        check=False,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "port 8001 is already in use" in result.stdout
    assert not marker.exists()
    assert not (tmp_path / "started").exists()
