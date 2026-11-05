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


@pytest.mark.parametrize(
    "runner_name",
    [
        pytest.param(
            "_run_windows_command",
            marks=pytest.mark.skipif(sys.platform != "win32", reason="the runner reads subprocess.CREATE_NEW_PROCESS_GROUP, which only exists on Windows builds"),
        ),
        "_run_posix_command",
    ],
)
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


def test_spawn_interrupt_closes_each_pipe_fd_exactly_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """A BaseException (KeyboardInterrupt mid-spawn) must still release all four fds once."""
    runner = LocalSandbox._run_posix_command
    closed = _record_os_close(monkeypatch)

    def interrupted_popen(*args: object, **kwargs: object) -> subprocess.Popen:
        raise KeyboardInterrupt

    with patch.object(subprocess, "Popen", side_effect=interrupted_popen):
        with pytest.raises(KeyboardInterrupt):
            runner(["whatever"], 1.0, None)

    duplicated = sorted({fd for fd in closed if closed.count(fd) > 1})
    assert not duplicated, f"fds {duplicated} were closed more than once: {closed}"
    assert len(closed) == 4, f"expected exactly one close per pipe end, got {closed}"


@pytest.mark.parametrize("exception_type", [RuntimeError, KeyboardInterrupt])
def test_post_spawn_failure_closes_each_pipe_fd_exactly_once(monkeypatch: pytest.MonkeyPatch, exception_type: type[BaseException]) -> None:
    """An error after Popen returns must not give two handlers ownership of the write ends."""
    closed = _record_os_close(monkeypatch)
    pipe_fds: list[int] = []
    real_pipe = os.pipe
    error = exception_type("post-spawn failure")

    def recording_pipe() -> tuple[int, int]:
        fds = real_pipe()
        pipe_fds.extend(fds)
        return fds

    class StartedProcess:
        @property
        def pid(self) -> int:
            raise error

    monkeypatch.setattr(os, "pipe", recording_pipe)
    with patch.object(subprocess, "Popen", return_value=StartedProcess()):
        with pytest.raises(exception_type) as exc_info:
            LocalSandbox._run_posix_command(["whatever"], 1.0, None)

    assert exc_info.value is error
    assert len(pipe_fds) == 4
    assert sorted(closed) == sorted(pipe_fds), f"expected each pipe fd to close once, got {closed} for {pipe_fds}"


def test_successful_spawn_closes_write_fds_exactly_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """Successful startup must still close the parent's write ends."""
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


@pytest.mark.skipif(os.name == "nt", reason="POSIX post-spawn PID access")
@pytest.mark.parametrize("exception_type", [RuntimeError, KeyboardInterrupt])
def test_post_spawn_failure_kills_and_reaps_real_child(monkeypatch: pytest.MonkeyPatch, exception_type: type[BaseException]) -> None:
    """A startup failure must not leave a real child running in its own session."""
    error = exception_type("post-spawn failure")
    children: list[subprocess.Popen] = []
    cleanup_calls: list[object] = []
    real_popen = subprocess.Popen

    class InterruptedProcess:
        def __init__(self, child: subprocess.Popen) -> None:
            self.child = child

        @property
        def pid(self) -> int:
            raise error

        def kill(self) -> None:
            cleanup_calls.append("kill")
            self.child.kill()

        def wait(self, timeout: float) -> int:
            cleanup_calls.append(("wait", timeout))
            return self.child.wait(timeout=timeout)

    def interrupted_popen(*args, **kwargs):
        child = real_popen(*args, **kwargs)
        children.append(child)
        return InterruptedProcess(child)

    monkeypatch.setattr(subprocess, "Popen", interrupted_popen)
    try:
        with pytest.raises(exception_type) as exc_info:
            LocalSandbox._run_posix_command([sys.executable, "-c", "import time; time.sleep(60)"], 1.0, None)

        assert exc_info.value is error
        assert len(children) == 1
        # Do not poll or wait here: those could reap a child that the runner left
        # alive or unreaped and accidentally make this assertion pass.
        assert children[0].returncode is not None, "startup failure left the child running or unreaped"
        assert cleanup_calls == ["kill", ("wait", 10)]
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=10)


@pytest.mark.parametrize("cleanup_step", ["kill", "wait"])
@pytest.mark.parametrize("cleanup_error_type", [RuntimeError, KeyboardInterrupt])
def test_post_spawn_cleanup_failure_preserves_original_error(monkeypatch: pytest.MonkeyPatch, cleanup_step: str, cleanup_error_type: type[BaseException]) -> None:
    original_error = RuntimeError("post-spawn failure")
    cleanup_error = cleanup_error_type("cleanup failed")
    calls: list[object] = []

    class InterruptedProcess:
        @property
        def pid(self) -> int:
            raise original_error

        def kill(self) -> None:
            calls.append("kill")
            if cleanup_step == "kill":
                raise cleanup_error

        def wait(self, timeout: float) -> int:
            calls.append(("wait", timeout))
            if cleanup_step == "wait":
                raise cleanup_error
            return -1

    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: InterruptedProcess())
    with pytest.raises(RuntimeError) as exc_info:
        LocalSandbox._run_posix_command(["whatever"], 1.0, None)

    assert exc_info.value is original_error
    assert calls == ["kill", ("wait", 10)]
