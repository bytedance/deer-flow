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
    for name in ("serve.sh", "wait-for-port.sh", "detect_uv_extras.py"):
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
