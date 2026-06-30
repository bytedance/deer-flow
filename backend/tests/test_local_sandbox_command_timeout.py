"""Regression tests for blocking-command timeout handling in LocalSandbox.

These pin the fix for the "starting a server hangs the whole turn" bug:
a backgrounded long-lived process must not keep the bash tool blocked until
the timeout, and a genuinely blocking foreground command must be terminated
(process group and all) once it exceeds the timeout.

The POSIX cases exercise real subprocess/process-group semantics, so they are
skipped on Windows. Windows keeps the ``subprocess.run`` path, but timeout
errors still use the same user-facing notice.
"""

import os
import shlex
import sys
import time
from pathlib import Path

import pytest

from deerflow.config.sandbox_config import SandboxConfig
from deerflow.sandbox.local import local_sandbox
from deerflow.sandbox.local.local_sandbox import LocalSandbox

posix_only = pytest.mark.skipif(os.name == "nt", reason="POSIX process-group semantics")
linux_proc_fd_only = pytest.mark.skipif(not Path("/proc/self/fd").exists(), reason="requires Linux /proc fd links")


@posix_only
def test_backgrounded_process_returns_promptly():
    """A backgrounded long-lived process (e.g. a dev server started with `&`)
    must return as soon as the foreground command finishes, instead of
    blocking the bash tool until the timeout because it inherited the
    captured pipe."""
    sandbox = LocalSandbox("t")
    start = time.monotonic()
    output = sandbox.execute_command("sleep 5 & echo serving", timeout=10)
    elapsed = time.monotonic() - start

    assert elapsed < 3, f"expected prompt return, took {elapsed:.1f}s"
    assert "serving" in output


@posix_only
@linux_proc_fd_only
def test_backgrounded_process_does_not_inherit_deleted_temp_capture(tmp_path):
    """A backgrounded process that forgets to redirect output must not inherit
    an anonymous deleted temp file for fd 1. That would be an invisible,
    unbounded disk leak for long-lived processes that keep writing."""
    marker = tmp_path / "fd1"
    script = f"import os, pathlib, time; pathlib.Path({str(marker)!r}).write_text(os.readlink('/proc/self/fd/1')); time.sleep(2)"
    sandbox = LocalSandbox("t")

    output = sandbox.execute_command(f"{shlex.quote(sys.executable)} -c {shlex.quote(script)} & echo launched", timeout=10)

    assert "launched" in output
    for _ in range(50):
        if marker.exists():
            break
        time.sleep(0.1)
    assert marker.exists()
    assert " (deleted)" not in marker.read_text()


@posix_only
def test_foreground_blocking_command_times_out_with_notice():
    """A foreground command that never exits is terminated at the timeout and
    the agent receives an explanatory notice instead of a generic error."""
    sandbox = LocalSandbox("t")
    start = time.monotonic()
    output = sandbox.execute_command("while true; do sleep 0.2; done", timeout=1)
    elapsed = time.monotonic() - start

    assert elapsed < 5, f"timeout not enforced, took {elapsed:.1f}s"
    assert "timed out" in output.lower()


def test_timeout_notice_formats_fractional_and_singular_timeouts(monkeypatch):
    monkeypatch.setattr(LocalSandbox, "_get_shell", lambda self: "/bin/sh")
    monkeypatch.setattr(LocalSandbox, "_run_posix_command", staticmethod(lambda args, timeout: ("", "", 0, True)))

    assert "after 1.5 seconds" in LocalSandbox("t").execute_command("wait", timeout=1.5)
    assert "after 1 second" in LocalSandbox("t").execute_command("wait", timeout=1)


def test_windows_timeout_expired_returns_notice(monkeypatch):
    def fake_run(*args, **kwargs):
        raise local_sandbox.subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs["timeout"], output="partial out", stderr="partial err")

    monkeypatch.setattr(local_sandbox.os, "name", "nt")
    monkeypatch.setattr(LocalSandbox, "_get_shell", lambda self: "cmd.exe")
    monkeypatch.setattr(local_sandbox.subprocess, "run", fake_run)

    output = LocalSandbox("t").execute_command("wait", timeout=1.5)

    assert "partial out" in output
    assert "Std Error:" in output
    assert "partial err" in output
    assert "after 1.5 seconds" in output
    assert "Unexpected error" not in output


@posix_only
def test_foreground_timeout_kills_whole_process_group(tmp_path):
    """On timeout the entire process group is killed, not just the direct
    child, so child processes spawned by the command do not survive."""
    marker = tmp_path / "alive"
    sandbox = LocalSandbox("t")
    sandbox.execute_command(f"while true; do touch {marker}; sleep 0.2; done", timeout=1)

    assert marker.exists()
    first_mtime = marker.stat().st_mtime
    time.sleep(1.5)
    assert marker.stat().st_mtime == first_mtime, "process group survived the timeout"


@posix_only
def test_command_reading_stdin_does_not_block():
    """stdin is redirected from /dev/null, so a command that reads stdin gets
    immediate EOF instead of blocking until the timeout."""
    sandbox = LocalSandbox("t")
    start = time.monotonic()
    output = sandbox.execute_command("read x; echo got", timeout=10)
    elapsed = time.monotonic() - start

    assert elapsed < 3, f"stdin read blocked, took {elapsed:.1f}s"
    assert "got" in output


@posix_only
def test_normal_command_output_exit_code_and_stderr():
    """Ordinary commands keep their existing output contract: stdout,
    appended Std Error section, and a non-zero Exit Code line."""
    sandbox = LocalSandbox("t")

    assert "hello" in sandbox.execute_command("echo hello")
    assert "Exit Code: 3" in sandbox.execute_command("exit 3")

    combined = sandbox.execute_command("echo out; echo oops >&2")
    assert "out" in combined
    assert "Std Error:" in combined
    assert "oops" in combined


def test_sandbox_config_exposes_command_timeout_default():
    cfg = SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider")
    assert cfg.bash_command_timeout == 600


def test_bash_tool_description_guides_backgrounding_long_lived_processes():
    """The bash tool description (seen by the model) must tell it to background
    long-lived processes like servers, so it doesn't block the turn in the
    foreground. This is the prompt-side half of the server-hang fix."""
    from deerflow.sandbox.tools import bash_tool

    description = bash_tool.description.lower()
    assert "background" in description
    assert "server" in description
