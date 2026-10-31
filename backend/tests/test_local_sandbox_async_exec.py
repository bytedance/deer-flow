"""Parity tests for ``LocalSandbox.execute_command_async``.

The async execution path must produce byte-identical output to the sync path
and preserve the sync path's documented semantics: bounded capture, prompt
return while backgrounded children hold the pipes, process-group timeout kill
with split-tail decoding, env validation, and cancellation that drains the
in-flight command instead of orphaning it.
"""

from __future__ import annotations

import asyncio
import os
import shlex
import sys
import time
from pathlib import Path

import pytest

from deerflow.sandbox.local import local_sandbox
from deerflow.sandbox.local.local_sandbox import LocalSandbox

posix_only = pytest.mark.skipif(os.name == "nt", reason="POSIX async subprocess semantics")

pytestmark = pytest.mark.asyncio


@posix_only
@pytest.mark.parametrize(
    "command",
    [
        "echo parity",
        "echo out; echo err >&2",
        "exit 4",
        "printf 'no-newline'",
    ],
)
async def test_async_output_matches_sync_byte_for_byte(command: str) -> None:
    """Both paths share the env/output pipeline, so their outputs are
    byte-identical for the same command."""
    sandbox = LocalSandbox("t")

    assert await sandbox.execute_command_async(command) == sandbox.execute_command(command)


@posix_only
async def test_async_empty_output_placeholder() -> None:
    sandbox = LocalSandbox("t")

    assert await sandbox.execute_command_async("true") == "(no output)"


@posix_only
@pytest.mark.parametrize("exit_code", [0, 7])
async def test_async_deadline_preserves_completed_command_and_background_child(tmp_path: Path, monkeypatch, exit_code: int) -> None:
    """A delayed exit observation must not overwrite success or kill background work."""
    release = tmp_path / "release-background"
    completed = tmp_path / "background-completed"
    background = (
        "import pathlib, sys, time; "
        "release, completed = map(pathlib.Path, sys.argv[1:]); "
        "deadline = time.monotonic() + 5\n"
        "while not release.exists() and time.monotonic() < deadline: time.sleep(0.01)\n"
        "if release.exists(): completed.write_text('done')\n"
    )
    command = f"{shlex.quote(sys.executable)} -c {shlex.quote(background)} {shlex.quote(str(release))} {shlex.quote(str(completed))} >/dev/null 2>&1 & printf complete; exit {exit_code}"
    original_wait_for = asyncio.wait_for
    deadline_delivered = False

    async def deadline_after_exit(awaitable, timeout):
        nonlocal deadline_delivered
        if deadline_delivered:
            return await original_wait_for(awaitable, timeout)
        deadline_delivered = True
        await original_wait_for(awaitable, timeout)
        # Deliver the timer boundary after the real shell has already exited.
        raise TimeoutError

    monkeypatch.setattr(asyncio, "wait_for", deadline_after_exit)
    try:
        output = await LocalSandbox("t").execute_command_async(command, timeout=10)
    finally:
        release.touch()

    async def wait_for_background() -> None:
        while not completed.exists():
            await asyncio.sleep(0.01)

    await original_wait_for(wait_for_background(), timeout=3)
    assert completed.read_text() == "done"
    assert output == ("complete" if exit_code == 0 else "complete\nExit Code: 7")


@posix_only
async def test_async_backgrounded_process_returns_promptly(tmp_path: Path) -> None:
    marker = tmp_path / "background-completed"
    start = time.monotonic()
    output = await LocalSandbox("t").execute_command_async(f"(sleep 0.5; printf done > {shlex.quote(str(marker))}) & echo serving", timeout=10)
    assert time.monotonic() - start < 3
    assert "serving" in output

    async def wait_for_background() -> None:
        while not marker.exists():
            await asyncio.sleep(0.01)

    await asyncio.wait_for(wait_for_background(), timeout=3)
    assert marker.read_text() == "done"


@posix_only
async def test_async_foreground_blocking_command_times_out_with_notice() -> None:
    """A foreground command that never exits is terminated at the timeout and
    the caller receives the same explanatory notice and authoritative exit
    marker as the sync path."""
    sandbox = LocalSandbox("t")
    start = time.monotonic()

    output = await sandbox.execute_command_async("while true; do sleep 0.2; done", timeout=1)

    elapsed = time.monotonic() - start
    assert elapsed < 5, f"timeout not enforced, took {elapsed:.1f}s"
    assert "timed out" in output.lower()
    assert output.endswith("Exit Code: 124")


@posix_only
async def test_async_timeout_kills_whole_process_group(tmp_path: Path) -> None:
    """On timeout the entire process group is killed, not just the direct
    child, so child processes spawned by the command do not survive."""
    marker = tmp_path / "alive"
    sandbox = LocalSandbox("t")

    await sandbox.execute_command_async(f"while true; do touch {marker}; sleep 0.2; done", timeout=1)
    first_mtime = marker.stat().st_mtime
    await asyncio.sleep(1.5)

    assert marker.stat().st_mtime == first_mtime, "process group survived the timeout"


@posix_only
async def test_async_invalid_env_key_is_rejected() -> None:
    """The async path enforces the same POSIX env-name contract as the sync
    path before any process is spawned."""
    sandbox = LocalSandbox("t")

    with pytest.raises(ValueError, match="not a valid POSIX environment variable name"):
        await sandbox.execute_command_async("echo hi", env={"bad name": "x"})


@posix_only
async def test_async_cancellation_drains_to_completion(tmp_path: Path) -> None:
    """Cancelling the awaiting task must not orphan the child: the in-flight
    command runs to completion (run_sync_lifecycle_operation's drain
    contract), then the caller's cancellation propagates."""
    marker = tmp_path / "drained"
    sandbox = LocalSandbox("t")

    task = asyncio.create_task(sandbox.execute_command_async(f"sleep 0.3 && touch {marker}", timeout=10))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert marker.exists(), "cancelled command must run to completion before the cancellation propagates"


async def test_async_windows_bridges_to_sync_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """Windows keeps the sync implementation via the bridge, so its behavior is
    byte-identical to the sync path (encoding, process-tree kill)."""
    monkeypatch.setattr(local_sandbox.os, "name", "nt")
    monkeypatch.setattr(LocalSandbox, "_get_shell", lambda self: "cmd.exe")
    monkeypatch.setattr(
        LocalSandbox,
        "_run_windows_command",
        staticmethod(lambda args, timeout, env, **kwargs: ("partial out", "partial err", 0, True)),
    )

    sandbox = LocalSandbox("t")
    output = await sandbox.execute_command_async("wait", timeout=1.5)

    assert sandbox._async_exec_unsupported is False
    assert "partial out" in output
    assert "Std Error:" in output
    assert "partial err" in output
    assert "after 1.5 seconds" in output
    assert "Unexpected error" not in output


@posix_only
async def test_async_unsupported_loop_falls_back_to_sync_bridge(monkeypatch: pytest.MonkeyPatch) -> None:
    """An event loop without subprocess support degrades permanently to the
    sync path instead of failing the command."""

    attempts = 0

    async def unsupported(*args: object, **kwargs: object) -> None:
        nonlocal attempts
        attempts += 1
        raise NotImplementedError

    monkeypatch.setattr(local_sandbox.asyncio, "create_subprocess_exec", unsupported)
    sandbox = LocalSandbox("t")
    assert sandbox._async_exec_unsupported is False

    assert "bridged" in await sandbox.execute_command_async("echo bridged")
    assert "cached" in await sandbox.execute_command_async("echo cached")
    assert attempts == 1
    assert sandbox._async_exec_unsupported is True
    assert LocalSandbox("fresh")._async_exec_unsupported is False


async def test_async_scoped_call_passthrough() -> None:
    """LocalSandbox has no server-side shell sessions, so the scoped async
    call matches the plain async call (mirroring the sync scoped pass-through)."""
    sandbox = LocalSandbox("t")

    assert await sandbox.execute_command_in_scope_async("echo scoped", scope_id="scope-1") == await sandbox.execute_command_async("echo scoped")


@posix_only
async def test_async_second_pipe_failure_closes_first_pipe(monkeypatch) -> None:
    original_pipe = os.pipe
    descriptors = []

    def pipe():
        if descriptors:
            raise OSError("second pipe failed")
        pair = original_pipe()
        descriptors.extend(pair)
        return pair

    monkeypatch.setattr(local_sandbox.os, "pipe", pipe)
    with pytest.raises(OSError, match="second pipe failed"):
        await LocalSandbox("t").execute_command_async("true")
    for descriptor in descriptors:
        with pytest.raises(OSError):
            os.fstat(descriptor)


@posix_only
async def test_async_reader_start_failure_reaps_child_and_closes_pipes(monkeypatch) -> None:
    original_spawn = asyncio.create_subprocess_exec
    original_start = LocalSandbox._start_pipe_drain
    processes = []
    descriptors = []
    threads = []

    async def spawn(*args, **kwargs):
        descriptors.extend((kwargs["stdout"], kwargs["stderr"]))
        process = await original_spawn(*args, **kwargs)
        processes.append(process)
        return process

    def start(fd, name):
        descriptors.append(fd)
        if threads:
            raise RuntimeError("reader start failed")
        capture, thread = original_start(fd, name)
        threads.append(thread)
        return capture, thread

    monkeypatch.setattr(local_sandbox.asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(LocalSandbox, "_start_pipe_drain", staticmethod(start))
    with pytest.raises(RuntimeError, match="reader start failed"):
        await LocalSandbox("t").execute_command_async("sleep 30")
    assert processes[0].returncode is not None
    assert processes[0].returncode < 0
    assert not threads[0].is_alive()
    for descriptor in descriptors:
        with pytest.raises(OSError):
            os.fstat(descriptor)


@posix_only
async def test_async_capture_stays_bounded_and_still_drains() -> None:
    emitted = local_sandbox._COMMAND_CAPTURE_LIMIT_BYTES + 1024
    script = f"import os; os.write(1, b'x' * {emitted}); os.write(2, b'finished')"
    output = await LocalSandbox("t").execute_command_async(f"{shlex.quote(sys.executable)} -c {shlex.quote(script)}", timeout=10)
    assert f"output truncated after 10485760 of {emitted} bytes" in output
    assert output.endswith("Std Error:\nfinished")


@posix_only
async def test_async_stdin_is_immediate_eof() -> None:
    output = await LocalSandbox("t").execute_command_async("read x; echo got", timeout=2)
    assert output.strip() == "got"


@posix_only
async def test_repeated_cancellation_keeps_command_drain(tmp_path: Path, monkeypatch) -> None:
    spawned = asyncio.Event()
    original_spawn = asyncio.create_subprocess_exec
    marker = tmp_path / "completed"

    async def spawn(*args, **kwargs):
        process = await original_spawn(*args, **kwargs)
        spawned.set()
        return process

    monkeypatch.setattr(local_sandbox.asyncio, "create_subprocess_exec", spawn)
    task = asyncio.create_task(LocalSandbox("t").execute_command_async(f"sleep 0.3; printf done > {shlex.quote(str(marker))}", timeout=3))
    await spawned.wait()
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert marker.read_text() == "done"
