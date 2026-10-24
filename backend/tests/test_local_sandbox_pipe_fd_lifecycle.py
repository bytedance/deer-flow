"""Regression tests for the pipe fd lifecycle in LocalSandbox command runners.

``_run_windows_command`` and ``_run_posix_command`` closed the pipe write fds
twice when ``subprocess.Popen`` raised: once in the ``except`` block (all four
pipe fds) and once more in the ``finally`` block. Between the two closes
another thread can claim the freed descriptor number (a concurrent command's
capture pipe, an HTTP socket), and the second ``os.close`` then silently
closes that unrelated descriptor.
"""

from __future__ import annotations

import os
import subprocess
import sys
from unittest.mock import patch

import pytest

from deerflow.sandbox.local.local_sandbox import LocalSandbox


def _record_os_close(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Route os.close through a recorder that delegates to the real close."""
    closed: list[int] = []
    real_close = os.close

    def recording_close(fd: int) -> None:
        closed.append(fd)
        real_close(fd)

    monkeypatch.setattr(os, "close", recording_close)
    return closed


@pytest.mark.parametrize("runner_name", ["_run_windows_command", "_run_posix_command"])
def test_spawn_failure_closes_each_pipe_fd_exactly_once(monkeypatch: pytest.MonkeyPatch, runner_name: str) -> None:
    runner = getattr(LocalSandbox, runner_name)
    closed = _record_os_close(monkeypatch)

    def failing_popen(*args: object, **kwargs: object) -> subprocess.Popen:
        raise OSError("spawn failed (simulated)")

    with patch.object(subprocess, "Popen", side_effect=failing_popen):
        with pytest.raises(OSError, match="spawn failed"):
            runner(["whatever"], 1.0, None)

    duplicated = sorted({fd for fd in closed if closed.count(fd) > 1})
    assert not duplicated, f"fds {duplicated} were closed more than once; a concurrent thread may have claimed them in between: {closed}"
    assert len(closed) == 4, f"expected exactly one close per pipe end, got {closed}"


def test_successful_spawn_closes_write_fds_exactly_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """The guard must not skip the parent's write-end close after a real spawn."""
    if sys.platform == "win32":
        runner = LocalSandbox._run_windows_command
        command = ["cmd", "/c", "echo hi"]
    else:
        runner = LocalSandbox._run_posix_command
        command = ["echo", "hi"]

    closed = _record_os_close(monkeypatch)
    write_fds: list[int] = []
    real_popen = subprocess.Popen

    def spying_popen(args: object, *, stdout: int | None = None, stderr: int | None = None, **kwargs: object) -> subprocess.Popen:
        write_fds.extend(fd for fd in (stdout, stderr) if fd is not None)
        assert real_popen is not None
        return real_popen(args, stdout=stdout, stderr=stderr, **kwargs)  # type: ignore[arg-type]

    with patch.object(subprocess, "Popen", side_effect=spying_popen):
        stdout_text, _, _, timed_out = runner(command, 30.0, None)

    assert not timed_out
    assert "hi" in stdout_text
    assert len(write_fds) == 2, "expected the runner to hand both pipe write ends to Popen"
    for fd in write_fds:
        assert closed.count(fd) == 1, f"write fd {fd} closed {closed.count(fd)} times: {closed}"
