"""Run the launcher and real port-wait loop without starting application services."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
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
sleep() {
    step=${1:-1}
    clock=$(( $(cat "$TEST_CLOCK") + step ))
    printf '%s\n' "$clock" > "$TEST_CLOCK"
    # The simulated clock is the budget. Assigning it drops wall time spent
    # spawning the compat watchdog, which must not consume the 240s case.
    SECONDS=$clock
}
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


def _run_launcher(
    tmp_path: Path,
    *,
    timeout: str | None,
    ready_at: int = 145,
    args: tuple[str, ...] = ("--dev",),
    dotenv: bool = False,
    force_compat: bool = False,
    subprocess_timeout: int = 60,
) -> subprocess.CompletedProcess[str]:
    checkout = tmp_path / "checkout"
    scripts = checkout / "scripts"
    scripts.mkdir(parents=True)
    (checkout / "backend").mkdir()
    for name in ("serve.sh", "dotenv_exports.py", "wait-for-port.sh", "wait-for-port-bash4.sh", "port-listening.sh", "detect_uv_extras.py"):
        shutil.copy2(REPO_ROOT / "scripts" / name, scripts / name)
    (scripts / "nginx-local-conf.sh").write_text("printf 'test-nginx.conf\\n'\n", encoding="utf-8", newline="\n")
    (scripts / "config-upgrade.sh").write_text("exit 0\n", encoding="utf-8", newline="\n")
    (scripts / "cleanup-containers.sh").write_text('printf "cleanup\\n" >> "$TEST_CLEANUP"\n', encoding="utf-8", newline="\n")
    (checkout / "config.yaml").write_text("models: []\n", encoding="utf-8", newline="\n")
    (tmp_path / "clock").write_text("0\n", encoding="utf-8", newline="\n")
    bash = require_script_bash()
    env = {key: value for key, value in os.environ.items() if key not in {"BASH_ENV", "ENV", "DEER_FLOW_GATEWAY_STARTUP_TIMEOUT", "DEER_FLOW_ENV_FILE"}}
    if force_compat:
        _force_compat_copy(scripts / "wait-for-port.sh")
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
    proc = subprocess.Popen(
        [bash, "-c", _PRELUDE, "startup-timeout-test", (scripts / "serve.sh").as_posix(), "--skip-install", *args],
        cwd=checkout,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
        errors="replace",
    )
    try:
        stdout, stderr = proc.communicate(timeout=subprocess_timeout)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, check=False)
        else:
            proc.kill()
        stdout, stderr = proc.communicate(timeout=5)
        raise
    return subprocess.CompletedProcess(proc.args, proc.returncode if proc.returncode is not None else 1, stdout or "", stderr or "")


@pytest.mark.parametrize("force_compat", [False, True])
@pytest.mark.parametrize("args", [("--dev",), ("--prod",), ("--dev", "--daemon")])
def test_configured_gateway_timeout_allows_slow_startup(tmp_path: Path, args: tuple[str, ...], force_compat: bool) -> None:
    """A listener ready at 145s still fits a 240s budget.

    force_compat runs the compat watchdog on this interpreter. That is not a
    Bash 3.2 parse and not a macOS set -m result. The watchdog uses the real
    sleep binary and is reaped after every probe, so this must not spend 240s.
    """
    limit = 210 if force_compat else 60
    started = time.monotonic()
    result = _run_launcher(tmp_path, timeout="240", args=args, force_compat=force_compat, subprocess_timeout=limit)
    elapsed = time.monotonic() - started
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Gateway started on localhost:8001" in result.stdout
    assert elapsed < limit, f"spent {elapsed:.0f}s"


@pytest.mark.parametrize("force_compat", [False, True])
def test_gateway_timeout_can_be_loaded_from_dotenv(tmp_path: Path, force_compat: bool) -> None:
    """Same 145s/240s case when the budget comes from .env. See the slow-startup test."""
    limit = 210 if force_compat else 60
    started = time.monotonic()
    result = _run_launcher(tmp_path, timeout="240", dotenv=True, force_compat=force_compat, subprocess_timeout=limit)
    elapsed = time.monotonic() - started
    assert result.returncode == 0, result.stdout + result.stderr
    assert elapsed < limit, f"spent {elapsed:.0f}s"


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
    for name in ("port-listening.sh", "wait-for-port.sh", "wait-for-port-bash4.sh"):
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


def _run_budgeted_wait(tmp_path: Path, *, timeout: int, netstat: str, subprocess_timeout: int) -> tuple[subprocess.CompletedProcess[str], int]:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    for name in ("port-listening.sh", "wait-for-port.sh", "wait-for-port-bash4.sh"):
        shutil.copy2(REPO_ROOT / "scripts" / name, scripts / name)
    prelude = "\n".join(
        (
            "command() {",
            '    if [ "$1" = -v ] && { [ "$2" = lsof ] || [ "$2" = ss ]; }; then',
            "        return 1",
            "    fi",
            '    builtin command "$@"',
            "}",
            netstat,
            "export -f command netstat",
            "start=$SECONDS",
            'bash "$TEST_SCRIPT" 8001 "$TEST_TIMEOUT" Gateway',
            "status=$?",
            'echo "ELAPSED:$((SECONDS - start))"',
            "exit $status",
        )
    )
    bash = require_script_bash()
    env = {key: value for key, value in os.environ.items() if key not in {"BASH_ENV", "ENV"}}
    env.update(
        OSTYPE="msys",
        TEST_SCRIPT=(scripts / "wait-for-port.sh").as_posix(),
        TEST_TIMEOUT=str(timeout),
        TEST_PROBE_CALLS=(tmp_path / "probe-calls").as_posix(),
        TEST_PROBE_SLOW=(tmp_path / "probe-slow").as_posix(),
        TEST_PROBE_DONE=(tmp_path / "probe-done").as_posix(),
    )
    result = subprocess.run(
        [bash, "-c", prelude, "budgeted-wait"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=subprocess_timeout,
        check=False,
    )
    elapsed = re.search(r"ELAPSED:(\d+)", result.stdout)
    assert elapsed is not None, result.stdout + result.stderr
    return result, int(elapsed.group(1))


_LISTENING_NETSTAT = """
netstat() {
    printf 'x\\n' >> "$TEST_PROBE_CALLS"
    printf 'slow\\n' >> "$TEST_PROBE_SLOW"
    sleep 2
    printf 'done\\n' >> "$TEST_PROBE_DONE"
    printf '%s\\n' '  TCP    127.0.0.1:8001         0.0.0.0:0              LISTENING       9'
    return 0
}
"""


def _probe_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8").splitlines()


def test_probe_that_outlasts_its_budget_is_not_a_success(tmp_path: Path) -> None:
    """A 1s budget and a 2s probe: the late listener is a timeout, and the probe is stopped."""
    result, seconds = _run_budgeted_wait(tmp_path, timeout=1, netstat=_LISTENING_NETSTAT, subprocess_timeout=8)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "after 1s" in result.stdout
    assert seconds < 3, result.stdout + result.stderr
    assert _probe_lines(tmp_path / "probe-calls") == ["x"]
    assert (tmp_path / "probe-slow").is_file()
    assert not (tmp_path / "probe-done").exists()


def test_later_probe_keeps_only_the_time_still_left(tmp_path: Path) -> None:
    """Misses spend the budget. The third probe is the slow one, and it does not get the budget back.

    Two fast misses plus the poll sleeps take a few seconds on Windows, so the
    budget is 5s and the third probe sleeps 4s. That sleep is longer than the
    time still left and shorter than a fresh 5s budget.
    """
    netstat = """
netstat() {
    printf 'x\\n' >> "$TEST_PROBE_CALLS"
    count=0
    while IFS= read -r _; do
        count=$((count + 1))
    done < "$TEST_PROBE_CALLS"
    if [ "$count" -lt 3 ]; then
        return 1
    fi
    printf 'slow\\n' >> "$TEST_PROBE_SLOW"
    sleep 4
    printf 'done\\n' >> "$TEST_PROBE_DONE"
    printf '%s\\n' '  TCP    127.0.0.1:8001         0.0.0.0:0              LISTENING       9'
    return 0
}
"""
    result, seconds = _run_budgeted_wait(tmp_path, timeout=5, netstat=netstat, subprocess_timeout=15)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "after 5s" in result.stdout
    assert seconds < 8, result.stdout + result.stderr
    assert len(_probe_lines(tmp_path / "probe-calls")) == 3, result.stdout + result.stderr
    assert (tmp_path / "probe-slow").is_file()
    assert not (tmp_path / "probe-done").exists()


def test_term_reaps_a_probe_that_ignores_term(tmp_path: Path) -> None:
    """TERM ends the wait, and a probe that ignores TERM does not stay behind."""
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    for name in ("port-listening.sh", "wait-for-port.sh", "wait-for-port-bash4.sh"):
        shutil.copy2(REPO_ROOT / "scripts" / name, scripts / name)
    probe_pid = tmp_path / "probe.pid"
    prelude = r"""
command() {
    if [ "$1" = -v ] && { [ "$2" = lsof ] || [ "$2" = ss ]; }; then
        return 1
    fi
    builtin command "$@"
}
netstat() {
    printf '%s\n' "$BASHPID" > "$TEST_PROBE_PID"
    trap '' TERM
    while true; do
        :
    done
}
export -f command netstat
finish() {
    if [ -n "${child:-}" ] && kill -0 "$child" 2>/dev/null; then
        kill -KILL "$child" 2>/dev/null || true
        wait "$child" 2>/dev/null || true
    fi
    if [ -s "$TEST_PROBE_PID" ]; then
        probe=$(cat "$TEST_PROBE_PID")
        kill -KILL -- "-$probe" 2>/dev/null || true
        kill -KILL "$probe" 2>/dev/null || true
    fi
}
trap finish EXIT
bash "$TEST_SCRIPT" 8001 30 Gateway &
child=$!
i=0
while [ "$i" -lt 50 ]; do
    if [ -s "$TEST_PROBE_PID" ]; then
        break
    fi
    i=$((i + 1))
    sleep 0.1
done
if [ ! -s "$TEST_PROBE_PID" ]; then
    echo "probe never started"
    exit 1
fi
kill -TERM "$child"
wait "$child"
status=$?
probe=$(cat "$TEST_PROBE_PID")
i=0
while [ "$i" -lt 20 ]; do
    if ! kill -0 "$probe" 2>/dev/null; then
        echo "REAPED status=$status"
        exit 0
    fi
    i=$((i + 1))
    sleep 0.1
done
echo "PROBE_ALIVE:$probe"
exit 1
"""
    bash = require_script_bash()
    env = {key: value for key, value in os.environ.items() if key not in {"BASH_ENV", "ENV"}}
    env.update(OSTYPE="msys", TEST_SCRIPT=(scripts / "wait-for-port.sh").as_posix(), TEST_PROBE_PID=probe_pid.as_posix())
    proc = subprocess.Popen(
        [bash, "-c", prelude, "reap-probe"],
        cwd=tmp_path,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
        errors="replace",
    )
    try:
        stdout, stderr = proc.communicate(timeout=15)
    except subprocess.TimeoutExpired:
        stdout = stderr = ""
        raise
    finally:
        if proc.poll() is None:
            if os.name == "nt":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, check=False)
            else:
                proc.kill()
            proc.wait(timeout=5)
    assert proc.returncode == 0, stdout + stderr
    assert "REAPED" in stdout


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
    for name in ("serve.sh", "dotenv_exports.py", "wait-for-port.sh", "wait-for-port-bash4.sh", "port-listening.sh", "detect_uv_extras.py"):
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


# German netstat translates LISTENING to ABHÖREN and ESTABLISHED to HERGESTELLT.
# The foreign address of a listener stays 0.0.0.0:0 or [::]:0.
_GERMAN_NETSTAT = """
  TCP    127.0.0.1:8001         0.0.0.0:0              ABHÖREN         9
  TCP    [::1]:8001             [::]:0                 ABHÖREN         9
  TCP    10.0.0.1:50000         1.2.3.4:8001           HERGESTELLT     9
"""


def test_windows_netstat_accepts_a_localized_listening_state(tmp_path: Path) -> None:
    result = _run_port_probe(tmp_path, "port-listening.sh", ["8001"], uname_s="MINGW64_NT-10.0", netstat_flag="-ano", netstat_stdout=_GERMAN_NETSTAT)
    assert result.returncode == 0, result.stdout + result.stderr


def test_windows_netstat_ignores_a_localized_established_connection(tmp_path: Path) -> None:
    established = "  TCP    10.0.0.1:50000         1.2.3.4:8001           HERGESTELLT     9\n"
    result = _run_port_probe(tmp_path, "port-listening.sh", ["8001"], uname_s="MINGW64_NT-10.0", netstat_flag="-ano", netstat_stdout=established)
    assert result.returncode == 1, result.stdout + result.stderr


def _run_fallback_probe(tmp_path: Path, prelude: str) -> subprocess.CompletedProcess[str]:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copy2(REPO_ROOT / "scripts" / "port-listening.sh", scripts / "port-listening.sh")
    hung = tmp_path / "hung-helper"
    bash = require_script_bash()
    env = {key: value for key, value in os.environ.items() if key not in {"BASH_ENV", "ENV"}}
    env.update(
        OSTYPE="linux-gnu",
        TEST_HUNG=hung.as_posix(),
        TEST_SCRIPT=(scripts / "port-listening.sh").as_posix(),
    )
    result = subprocess.run(
        [bash, "-c", prelude, "fallback-probe", "8001"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=8,
        check=False,
    )
    assert not hung.exists(), result.stdout + result.stderr
    return result


def test_lsof_miss_falls_through_to_ss(tmp_path: Path) -> None:
    result = _run_fallback_probe(
        tmp_path,
        r"""
lsof() { return 1; }
ss() {
    printf '%s\n' 'State Recv-Q Send-Q Local Address:Port Peer Address:Port'
    printf '%s\n' 'LISTEN 0 128 127.0.0.1:8001 0.0.0.0:*'
}
netstat() { printf hung > "$TEST_HUNG"; sleep 30; }
export -f lsof ss netstat
bash "$TEST_SCRIPT" "$@"
""",
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_lsof_and_ss_miss_falls_through_to_netstat(tmp_path: Path) -> None:
    result = _run_fallback_probe(
        tmp_path,
        r"""
lsof() { return 1; }
ss() { return 1; }
netstat() {
    printf '%s\n' 'tcp 0 0 127.0.0.1:8001 0.0.0.0:* LISTEN'
    return 0
}
export -f lsof ss netstat
bash "$TEST_SCRIPT" "$@"
""",
    )
    assert result.returncode == 0, result.stdout + result.stderr


def _bash_version(bash: str) -> tuple[int, str]:
    major = subprocess.run([bash, "-c", 'printf %s "$BASH_VERSINFO"'], capture_output=True, text=True, timeout=10, check=False)
    full = subprocess.run([bash, "-c", 'printf %s "$BASH_VERSION"'], capture_output=True, text=True, timeout=10, check=False)
    assert major.returncode == 0 and full.returncode == 0, major.stderr + full.stderr
    return int(major.stdout.strip()), full.stdout.strip()


def _bash32_binary() -> str | None:
    candidates = [os.environ.get("DEER_FLOW_BASH32", ""), str(REPO_ROOT / ".tools" / "bash-3.2" / "bash")]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    return None


@pytest.fixture(params=["installed", "bash32"])
def wait_shell(request: pytest.FixtureRequest) -> tuple[str, str, int]:
    """Return (bash path, branch name, major version) for one real interpreter."""
    if request.param == "installed":
        bash = require_script_bash()
    else:
        found = _bash32_binary()
        if found is None:
            pytest.skip("No Bash 3.2 binary (DEER_FLOW_BASH32 or .tools/bash-3.2/bash). macOS /bin/bash was not run.")
        bash = found
    major, _full = _bash_version(bash)
    if request.param == "bash32" and major >= 4:
        pytest.fail(f"{bash} is bash {major}, not Bash 3.2")
    branch = "compat" if major < 4 else "bash4"
    return bash, branch, major


def _process_state(bash: str, pid: str) -> str:
    """Return gone, zombie, or a live state. An empty ps error is not treated as gone."""
    if not pid.strip().isdigit():
        return f"bad-pid:{pid!r}"
    posix = subprocess.run(
        [bash, "-c", 'ps -o stat= -p "$1"', "ps-state", pid],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    err = (posix.stderr or "").lower()
    if posix.returncode != 0 and ("not found" in err or "no such file" in err):
        return "no-ps"
    if "unknown option" in err or "illegal option" in err or "invalid option" in err:
        listing = subprocess.run(
            [bash, "-c", 'ps -l -p "$1"', "ps-state", pid],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if listing.returncode != 0 and "PID" not in listing.stdout:
            return "no-ps"
        for line in listing.stdout.splitlines():
            parts = line.split()
            if parts and parts[0] == pid:
                return "running"
        return "gone"
    state = posix.stdout.strip()
    if not state:
        return "gone"
    if state.startswith("Z"):
        return "zombie"
    return state


def _kill_pid(bash: str, pid: str) -> None:
    if not pid.strip().isdigit():
        return
    if _process_state(bash, pid) == "gone":
        return
    subprocess.run(
        [bash, "-c", 'kill -KILL "$1" 2>/dev/null || true', "kill-pid", pid],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


def _read_pid(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip().splitlines()[0]


class _WaitRun:
    def __init__(
        self,
        result: subprocess.CompletedProcess[str],
        elapsed: int,
        branch_line: str,
        pids: list[str],
        bash: str,
        elapsed_ms: int = -1,
    ) -> None:
        self.result = result
        self.elapsed = elapsed
        self.branch_line = branch_line
        self.pids = pids
        self.bash = bash
        self.elapsed_ms = elapsed_ms


def _force_compat_copy(script: Path) -> None:
    """Run the compat function on this interpreter. The binary is unchanged."""
    text = script.read_text(encoding="utf-8")
    needle = 'if [ "${BASH_VERSINFO[0]}" -lt 4 ]; then'
    if needle not in text:
        raise AssertionError(f"compat branch not found in {script}")
    script.write_text(text.replace(needle, "if true; then", 1), encoding="utf-8", newline="\n")


def _run_on_shell(
    tmp_path: Path,
    bash: str,
    *,
    netstat: str,
    timeout: int,
    signal: str = "",
    subprocess_timeout: int = 20,
    force_compat: bool = False,
    monotonic_ms: bool = False,
) -> _WaitRun:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    for name in ("port-listening.sh", "wait-for-port.sh", "wait-for-port-bash4.sh"):
        shutil.copy2(REPO_ROOT / "scripts" / name, scripts / name)
    if force_compat:
        _force_compat_copy(scripts / "wait-for-port.sh")
    branch_log = tmp_path / "branch.txt"
    called = tmp_path / "bash-called"
    probe_pid = tmp_path / "probe.pid"
    child_pid = tmp_path / "child.pid"
    calls = tmp_path / "probe-calls"
    slow = tmp_path / "probe-slow"
    done = tmp_path / "probe-done"
    if signal:
        launch = f"""
set -m
"$TEST_BASH" "$TEST_SCRIPT" 8001 "$TEST_TIMEOUT" Gateway >"$TEST_OUT" 2>"$TEST_ERR" &
child=$!
set +m
i=0
while [ "$i" -lt 8 ]; do
    if [ -s "$TEST_PROBE_PID" ] && [ -s "$TEST_CHILD_PID" ]; then
        break
    fi
    i=$((i + 1))
    sleep 1
done
if [ ! -s "$TEST_PROBE_PID" ] || [ ! -s "$TEST_CHILD_PID" ]; then
    echo "probe never started"
    kill -KILL "$child" 2>/dev/null || true
    exit 1
fi
kill -{signal} "$child" 2>/dev/null || true
i=0
while kill -0 "$child" 2>/dev/null && [ "$i" -lt 8 ]; do
    i=$((i + 1))
    sleep 1
done
if kill -0 "$child" 2>/dev/null; then
    echo "STILL_RUNNING"
    kill -KILL "$child" 2>/dev/null || true
    exit 1
fi
echo "SIGNAL_DONE"
cat "$TEST_OUT" 2>/dev/null || true
"""
    else:
        if monotonic_ms:
            launch = """
start=$SECONDS
start_ns=$(date +%s%N)
"$TEST_BASH" "$TEST_SCRIPT" 8001 "$TEST_TIMEOUT" Gateway
status=$?
end_ns=$(date +%s%N)
echo "ELAPSED:$((SECONDS - start))"
echo "ELAPSED_MS:$(( (end_ns - start_ns) / 1000000 ))"
exit $status
"""
        else:
            launch = """
start=$SECONDS
"$TEST_BASH" "$TEST_SCRIPT" 8001 "$TEST_TIMEOUT" Gateway
status=$?
echo "ELAPSED:$((SECONDS - start))"
exit $status
"""
    prelude = "\n".join(
        (
            "command() {",
            '    if [ "$1" = -v ] && { [ "$2" = lsof ] || [ "$2" = ss ]; }; then',
            "        return 1",
            "    fi",
            '    builtin command "$@"',
            "}",
            "bash() { printf 'called\\n' >> \"$TEST_BASH_CALLED\"; return 99; }",
            netstat,
            "export -f command bash netstat",
            launch,
        )
    )
    env = {key: value for key, value in os.environ.items() if key not in {"BASH_ENV", "ENV"}}
    env.update(
        OSTYPE="msys",
        TEST_BASH=bash,
        TEST_SCRIPT=(scripts / "wait-for-port.sh").as_posix(),
        TEST_TIMEOUT=str(timeout),
        TEST_PROBE_CALLS=calls.as_posix(),
        TEST_PROBE_SLOW=slow.as_posix(),
        TEST_PROBE_DONE=done.as_posix(),
        TEST_PROBE_PID=probe_pid.as_posix(),
        TEST_CHILD_PID=child_pid.as_posix(),
        TEST_BASH_CALLED=called.as_posix(),
        DEER_FLOW_WAIT_PORT_BRANCH_LOG=branch_log.as_posix(),
        DEER_FLOW_WAIT_PORT_PID_LOG=(tmp_path / "wait-pids.txt").as_posix(),
        TEST_OUT=(tmp_path / "stdout.txt").as_posix(),
        TEST_ERR=(tmp_path / "stderr.txt").as_posix(),
    )
    started = time.perf_counter()
    proc = subprocess.Popen(
        [bash, "-c", prelude, "versioned-wait"],
        cwd=tmp_path,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
        errors="replace",
    )
    try:
        stdout, stderr = proc.communicate(timeout=subprocess_timeout)
    finally:
        if proc.poll() is None:
            if os.name == "nt":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, check=False)
            else:
                proc.kill()
            proc.wait(timeout=5)
    result = subprocess.CompletedProcess(proc.args, proc.returncode if proc.returncode is not None else 1, stdout or "", stderr or "")
    elapsed_match = re.search(r"ELAPSED:(\d+)", result.stdout)
    elapsed = int(elapsed_match.group(1)) if elapsed_match else -1
    ms_match = re.search(r"ELAPSED_MS:(\d+)", result.stdout)
    if monotonic_ms and ms_match:
        elapsed_ms = int(ms_match.group(1))
    else:
        elapsed_ms = int((time.perf_counter() - started) * 1000) if monotonic_ms else -1
    branch_line = branch_log.read_text(encoding="utf-8").strip() if branch_log.exists() else ""
    pids = [_read_pid(probe_pid), _read_pid(child_pid)]
    assert not called.exists(), "wait script invoked bash again\n" + result.stdout + result.stderr
    return _WaitRun(result, elapsed, branch_line, pids, bash, elapsed_ms)


def _assert_branch(run: _WaitRun, bash: str) -> None:
    _major, full = _bash_version(bash)
    assert run.branch_line == f"{'compat' if _major < 4 else 'bash4'} {full}", run.branch_line


def _assert_reaped(run: _WaitRun) -> None:
    for pid in run.pids:
        if not pid:
            continue
        state = _process_state(run.bash, pid)
        assert state == "gone", f"pid {pid} is {state}, not reaped"


def _logged_pids(tmp_path: Path) -> list[tuple[str, str]]:
    log = tmp_path / "wait-pids.txt"
    if not log.exists():
        return []
    found: list[tuple[str, str]] = []
    for line in log.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[-1].isdigit():
            found.append((parts[0], parts[-1]))
    return found


def _assert_logged_pids_reaped(run: _WaitRun, tmp_path: Path) -> None:
    rows = _logged_pids(tmp_path)
    assert rows, "compat path did not record probe and sleeper pids"
    for kind, pid in rows:
        state = _process_state(run.bash, pid)
        assert state == "gone", f"{kind} pid {pid} is {state}, not reaped"


_LISTENER_LINE = "  TCP    127.0.0.1:8001         0.0.0.0:0              LISTENING       9"


def test_wait_accepts_a_listener_that_is_already_up(tmp_path: Path, wait_shell: tuple[str, str, int]) -> None:
    bash, _branch, _major = wait_shell
    netstat = f"""
netstat() {{
    printf 'x\\n' >> "$TEST_PROBE_CALLS"
    printf '%s\\n' '{_LISTENER_LINE}'
    return 0
}}
"""
    run = _run_on_shell(tmp_path, bash, netstat=netstat, timeout=5)
    try:
        assert run.result.returncode == 0, run.result.stdout + run.result.stderr
        _assert_branch(run, bash)
        assert _probe_lines(tmp_path / "probe-calls") == ["x"]
        assert 0 <= run.elapsed < 4, run.result.stdout
    finally:
        for pid in run.pids:
            _kill_pid(bash, pid)


def test_compat_accepts_a_fast_listener_inside_one_second(tmp_path: Path) -> None:
    """A 1s budget must accept a listener that is ready well inside that second.

    The 5s already-up case allows almost four seconds, so it stays green when
    the compat loop sleeps the whole poll first and then rejects the success.
    The copy's version test is forced true. This is the installed bash running
    the compat function, not a Bash 3.2 binary and not macOS.
    """
    bash = require_script_bash()
    netstat = f"""
netstat() {{
    printf 'x\\n' >> "$TEST_PROBE_CALLS"
    printf '%s\\n' '{_LISTENER_LINE}'
    return 0
}}
"""
    run = _run_on_shell(tmp_path, bash, netstat=netstat, timeout=1, subprocess_timeout=8, force_compat=True, monotonic_ms=True)
    try:
        _major, full = _bash_version(bash)
        assert run.result.returncode == 0, run.result.stdout + run.result.stderr
        assert run.branch_line == f"compat {full}", run.branch_line
        assert _probe_lines(tmp_path / "probe-calls") == ["x"]
        assert 0 <= run.elapsed_ms < 1000, run.result.stdout + run.result.stderr
        _assert_logged_pids_reaped(run, tmp_path)
    finally:
        for pid in run.pids:
            _kill_pid(bash, pid)
        for _kind, pid in _logged_pids(tmp_path):
            _kill_pid(bash, pid)


def test_compat_waits_one_second_after_a_miss(tmp_path: Path) -> None:
    """A confirmed miss still waits about a second. That wait is not a timeout."""
    bash = require_script_bash()
    netstat = f"""
netstat() {{
    printf 'x\\n' >> "$TEST_PROBE_CALLS"
    count=0
    while IFS= read -r _; do
        count=$((count + 1))
    done < "$TEST_PROBE_CALLS"
    if [ "$count" -lt 2 ]; then
        return 1
    fi
    printf '%s\\n' '{_LISTENER_LINE}'
    return 0
}}
"""
    run = _run_on_shell(tmp_path, bash, netstat=netstat, timeout=5, subprocess_timeout=12, force_compat=True)
    try:
        _major, full = _bash_version(bash)
        assert run.result.returncode == 0, run.result.stdout + run.result.stderr
        assert run.branch_line == f"compat {full}"
        assert len(_probe_lines(tmp_path / "probe-calls")) == 2
        assert 1 <= run.elapsed < 4, run.result.stdout
        _assert_logged_pids_reaped(run, tmp_path)
    finally:
        for pid in run.pids:
            _kill_pid(bash, pid)
        for _kind, pid in _logged_pids(tmp_path):
            _kill_pid(bash, pid)


def test_compat_kills_a_probe_that_outlasts_one_second(tmp_path: Path) -> None:
    """A probe that ignores the deadline is stopped. A late listen is not success."""
    bash = require_script_bash()
    netstat = f"""
netstat() {{
    probe=$(sh -c 'echo "$PPID"')
    printf '%s\\n' "$probe" > "$TEST_PROBE_PID"
    printf 'slow\\n' >> "$TEST_PROBE_SLOW"
    sleep 30
    printf 'done\\n' >> "$TEST_PROBE_DONE"
    printf '%s\\n' '{_LISTENER_LINE}'
    return 0
}}
"""
    run = _run_on_shell(tmp_path, bash, netstat=netstat, timeout=1, subprocess_timeout=8, force_compat=True)
    try:
        _major, full = _bash_version(bash)
        assert run.result.returncode == 1, run.result.stdout + run.result.stderr
        assert "after 1s" in run.result.stdout
        assert run.branch_line == f"compat {full}"
        assert (tmp_path / "probe-slow").is_file()
        assert not (tmp_path / "probe-done").exists()
        assert 1 <= run.elapsed < 3, run.result.stdout
        assert run.pids[0], "probe pid was not recorded"
        _assert_reaped(run)
        _assert_logged_pids_reaped(run, tmp_path)
    finally:
        for pid in run.pids:
            _kill_pid(bash, pid)
        for _kind, pid in _logged_pids(tmp_path):
            _kill_pid(bash, pid)


def test_compat_term_before_the_sleep_pid_is_read(tmp_path: Path) -> None:
    """TERM before the fifo read must reap the watchdog sleep and close the pipe.

    The hold is test-only. This runs the compat function on the installed bash,
    which is not Bash 3.2 and not macOS.
    """
    bash = require_script_bash()
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    for name in ("port-listening.sh", "wait-for-port.sh", "wait-for-port-bash4.sh"):
        shutil.copy2(REPO_ROOT / "scripts" / name, scripts / name)
    _force_compat_copy(scripts / "wait-for-port.sh")
    hold = tmp_path / "hold"
    script_pid_file = tmp_path / "script.pid"
    pid_log = tmp_path / "wait-pids.txt"
    launch = r"""
set -m
"$TEST_BASH" "$TEST_SCRIPT" 8001 30 Gateway &
child=$!
printf '%s\n' "$child" > "$TEST_SCRIPT_PID"
set +m
wait "$child"
code=$?
printf 'WAIT_CODE:%s\n' "$code"
exit "$code"
"""
    prelude = "\n".join(
        (
            "command() {",
            '    if [ "$1" = -v ] && { [ "$2" = lsof ] || [ "$2" = ss ]; }; then',
            "        return 1",
            "    fi",
            '    builtin command "$@"',
            "}",
            "netstat() { sleep 30; }",
            "export -f command netstat",
            launch,
        )
    )
    env = {key: value for key, value in os.environ.items() if key not in {"BASH_ENV", "ENV"}}
    env.update(
        OSTYPE="msys",
        TEST_BASH=bash,
        TEST_SCRIPT=(scripts / "wait-for-port.sh").as_posix(),
        TEST_SCRIPT_PID=script_pid_file.as_posix(),
        DEER_FLOW_WAIT_PORT_PID_LOG=pid_log.as_posix(),
        DEER_FLOW_WAIT_PORT_HOLD_FIFO=hold.as_posix(),
    )
    proc = subprocess.Popen(
        [bash, "-c", prelude, "term-before-fifo"],
        cwd=tmp_path,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
        errors="replace",
    )
    script_pid = ""
    sleep_pids: list[str] = []
    deadline = time.monotonic() + 8
    try:
        while time.monotonic() < deadline:
            if script_pid_file.exists():
                script_pid = script_pid_file.read_text(encoding="utf-8").strip()
            sleep_pids = [pid for kind, pid in _logged_pids(tmp_path) if kind == "sleep"]
            if script_pid.isdigit() and hold.exists() and sleep_pids:
                break
            time.sleep(0.05)
        else:
            pytest.fail(f"handoff window did not open pid={script_pid!r} hold={hold.exists()} sleep={sleep_pids}")
        subprocess.run(
            [bash, "-c", 'kill -TERM "$1"', "term-script", script_pid],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        try:
            stdout, stderr = proc.communicate(timeout=12)
        except subprocess.TimeoutExpired:
            pytest.fail("captured pipe stayed open after TERM; the watchdog sleep was not reaped")
        assert proc.returncode == 143, f"rc={proc.returncode}\n{stdout}\n{stderr}"
        rows = _logged_pids(tmp_path)
        assert any(kind == "sleep" for kind, _pid in rows)
        for kind, pid in rows:
            state = _process_state(bash, pid)
            assert state == "gone", f"{kind} pid {pid} is {state}"
    finally:
        if proc.poll() is None:
            if os.name == "nt":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, check=False)
            else:
                proc.kill()
            proc.wait(timeout=5)
        if script_pid.isdigit():
            _kill_pid(bash, script_pid)
        for _kind, pid in _logged_pids(tmp_path):
            _kill_pid(bash, pid)


def test_wait_succeeds_after_two_misses(tmp_path: Path, wait_shell: tuple[str, str, int]) -> None:
    bash, _branch, _major = wait_shell
    netstat = f"""
netstat() {{
    printf 'x\\n' >> "$TEST_PROBE_CALLS"
    count=0
    while IFS= read -r _; do
        count=$((count + 1))
    done < "$TEST_PROBE_CALLS"
    if [ "$count" -lt 3 ]; then
        return 1
    fi
    printf '%s\\n' '{_LISTENER_LINE}'
    return 0
}}
"""
    run = _run_on_shell(tmp_path, bash, netstat=netstat, timeout=12, subprocess_timeout=20)
    try:
        assert run.result.returncode == 0, run.result.stdout + run.result.stderr
        _assert_branch(run, bash)
        assert len(_probe_lines(tmp_path / "probe-calls")) == 3
        assert 2 <= run.elapsed < 10, run.result.stdout
    finally:
        for pid in run.pids:
            _kill_pid(bash, pid)


def test_slow_third_probe_keeps_one_deadline(tmp_path: Path, wait_shell: tuple[str, str, int]) -> None:
    """Misses spend the one budget. The third probe does not get a fresh timeout.

    Two fast misses plus the poll sleeps leave less than 7s. The budget is 8s
    and the third probe sleeps 7s, so the slow branch runs but does not finish.
    A fresh 8s budget would let that sleep complete.
    """
    bash, _branch, _major = wait_shell
    netstat = f"""
netstat() {{
    printf 'x\\n' >> "$TEST_PROBE_CALLS"
    count=0
    while IFS= read -r _; do
        count=$((count + 1))
    done < "$TEST_PROBE_CALLS"
    if [ "$count" -lt 3 ]; then
        return 1
    fi
    printf 'slow\\n' >> "$TEST_PROBE_SLOW"
    sleep 7
    printf 'done\\n' >> "$TEST_PROBE_DONE"
    printf '%s\\n' '{_LISTENER_LINE}'
    return 0
}}
"""
    run = _run_on_shell(tmp_path, bash, netstat=netstat, timeout=8, subprocess_timeout=20)
    try:
        assert run.result.returncode == 1, run.result.stdout + run.result.stderr
        assert "after 8s" in run.result.stdout
        _assert_branch(run, bash)
        assert len(_probe_lines(tmp_path / "probe-calls")) == 3, run.result.stdout + run.result.stderr
        assert (tmp_path / "probe-slow").is_file()
        assert not (tmp_path / "probe-done").exists()
        assert 0 <= run.elapsed < 11, run.result.stdout
        _assert_reaped(run)
    finally:
        for pid in run.pids:
            _kill_pid(bash, pid)


def test_listener_after_the_deadline_is_not_success(tmp_path: Path, wait_shell: tuple[str, str, int]) -> None:
    bash, _branch, _major = wait_shell
    netstat = f"""
netstat() {{
    printf 'x\\n' >> "$TEST_PROBE_CALLS"
    printf 'slow\\n' >> "$TEST_PROBE_SLOW"
    sleep 4
    printf 'done\\n' >> "$TEST_PROBE_DONE"
    printf '%s\\n' '{_LISTENER_LINE}'
    return 0
}}
"""
    run = _run_on_shell(tmp_path, bash, netstat=netstat, timeout=2, subprocess_timeout=12)
    try:
        assert run.result.returncode == 1, run.result.stdout + run.result.stderr
        assert "after 2s" in run.result.stdout
        _assert_branch(run, bash)
        assert (tmp_path / "probe-slow").is_file()
        assert not (tmp_path / "probe-done").exists()
        assert 0 <= run.elapsed < 5, run.result.stdout
        _assert_reaped(run)
    finally:
        for pid in run.pids:
            _kill_pid(bash, pid)


def test_probe_that_never_returns_still_hits_the_deadline(tmp_path: Path, wait_shell: tuple[str, str, int]) -> None:
    bash, _branch, _major = wait_shell
    netstat = """
netstat() {
    probe=$(sh -c 'echo "$PPID"')
    printf '%s\\n' "$probe" > "$TEST_PROBE_PID"
    sleep 30 &
    printf '%s\\n' "$!" > "$TEST_CHILD_PID"
    wait
}
"""
    run = _run_on_shell(tmp_path, bash, netstat=netstat, timeout=2, subprocess_timeout=12)
    try:
        assert run.result.returncode == 1, run.result.stdout + run.result.stderr
        assert "after 2s" in run.result.stdout
        _assert_branch(run, bash)
        assert 0 <= run.elapsed < 5, run.result.stdout
        assert run.pids[0] and run.pids[1], "probe and sleep pids were not recorded"
        _assert_reaped(run)
    finally:
        for pid in run.pids:
            _kill_pid(bash, pid)


def test_probe_that_ignores_term_is_still_reaped(tmp_path: Path, wait_shell: tuple[str, str, int]) -> None:
    bash, _branch, _major = wait_shell
    netstat = """
netstat() {
    probe=$(sh -c 'echo "$PPID"')
    printf '%s\\n' "$probe" > "$TEST_PROBE_PID"
    trap '' TERM
    sleep 30 &
    printf '%s\\n' "$!" > "$TEST_CHILD_PID"
    wait
}
"""
    run = _run_on_shell(tmp_path, bash, netstat=netstat, timeout=2, subprocess_timeout=12)
    try:
        assert run.result.returncode == 1, run.result.stdout + run.result.stderr
        _assert_branch(run, bash)
        assert 0 <= run.elapsed < 5, run.result.stdout
        assert run.pids[0] and run.pids[1]
        _assert_reaped(run)
    finally:
        for pid in run.pids:
            _kill_pid(bash, pid)


def test_probe_child_is_reaped_with_the_probe(tmp_path: Path, wait_shell: tuple[str, str, int]) -> None:
    bash, _branch, _major = wait_shell
    netstat = """
netstat() {
    probe=$(sh -c 'echo "$PPID"')
    printf '%s\\n' "$probe" > "$TEST_PROBE_PID"
    trap '' TERM
    ( trap '' TERM; exec sleep 40 ) &
    printf '%s\\n' "$!" > "$TEST_CHILD_PID"
    wait
}
"""
    run = _run_on_shell(tmp_path, bash, netstat=netstat, timeout=2, subprocess_timeout=12)
    try:
        assert run.result.returncode == 1, run.result.stdout + run.result.stderr
        _assert_branch(run, bash)
        assert run.pids[0] and run.pids[1]
        _assert_reaped(run)
    finally:
        for pid in run.pids:
            _kill_pid(bash, pid)


@pytest.mark.parametrize("signal", ["TERM", "INT"])
def test_signal_reaps_the_probe_and_its_child(tmp_path: Path, wait_shell: tuple[str, str, int], signal: str) -> None:
    bash, _branch, _major = wait_shell
    netstat = """
netstat() {
    probe=$(sh -c 'echo "$PPID"')
    printf '%s\\n' "$probe" > "$TEST_PROBE_PID"
    trap '' TERM
    ( trap '' TERM; exec sleep 40 ) &
    printf '%s\\n' "$!" > "$TEST_CHILD_PID"
    wait
}
"""
    run = _run_on_shell(tmp_path, bash, netstat=netstat, timeout=30, signal=signal, subprocess_timeout=20)
    try:
        assert run.result.returncode == 0, run.result.stdout + run.result.stderr
        assert "SIGNAL_DONE" in run.result.stdout
        _assert_branch(run, bash)
        assert run.pids[0] and run.pids[1]
        _assert_reaped(run)
    finally:
        for pid in run.pids:
            _kill_pid(bash, pid)
