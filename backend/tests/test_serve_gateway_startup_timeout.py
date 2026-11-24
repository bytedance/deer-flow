"""Run the launcher and real port-wait loop without starting application services."""

from __future__ import annotations

import os
import re
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
sleep() {
    printf '%s\n' "$(( $(cat "$TEST_CLOCK") + 1 ))" > "$TEST_CLOCK"
    SECONDS=$((SECONDS + ${1:-1}))
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
        # Each simulated second may also run the netstat fallback. On Windows
        # that command substitution is slow enough that 145 polls exceed 20s.
        timeout=60,
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


def _run_budgeted_wait(tmp_path: Path, *, timeout: int, netstat: str, subprocess_timeout: int) -> tuple[subprocess.CompletedProcess[str], int]:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    for name in ("port-listening.sh", "wait-for-port.sh"):
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
    for name in ("port-listening.sh", "wait-for-port.sh"):
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
