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
import time
from pathlib import Path

import pytest

from deerflow.sandbox.local import local_sandbox
from deerflow.sandbox.local.local_sandbox import _DAEMON_DRAIN_TASKS, LocalSandbox

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
async def test_async_backgrounded_process_returns_promptly() -> None:
    """A backgrounded long-lived process must not block the async return any
    more than it blocks the sync path; its pipes are drained by a detached
    task that ends at EOF and leaves the strong-reference set."""
    sandbox = LocalSandbox("t")
    start = time.monotonic()

    output = await sandbox.execute_command_async("sleep 0.5 & echo serving", timeout=10)

    elapsed = time.monotonic() - start
    assert elapsed < 3, f"expected prompt return, took {elapsed:.1f}s"
    assert "serving" in output
    for _ in range(50):
        if not _DAEMON_DRAIN_TASKS:
            break
        await asyncio.sleep(0.1)
    assert not _DAEMON_DRAIN_TASKS, "detached drain tasks must end at EOF and leave the strong-reference set"


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

    output = await LocalSandbox("t").execute_command_async("wait", timeout=1.5)

    assert "partial out" in output
    assert "Std Error:" in output
    assert "partial err" in output
    assert "after 1.5 seconds" in output
    assert "Unexpected error" not in output


async def test_async_unsupported_loop_falls_back_to_sync_bridge(monkeypatch: pytest.MonkeyPatch) -> None:
    """An event loop without subprocess support degrades permanently to the
    sync path instead of failing the command."""

    async def unsupported(*args: object, **kwargs: object) -> None:
        raise NotImplementedError

    monkeypatch.setattr(local_sandbox.asyncio, "create_subprocess_exec", unsupported)
    sandbox = LocalSandbox("t")

    output = await sandbox.execute_command_async("echo bridged")

    assert "bridged" in output
    assert sandbox._async_exec_unsupported is True


async def test_async_scoped_call_passthrough() -> None:
    """LocalSandbox has no server-side shell sessions, so the scoped async
    call matches the plain async call (mirroring the sync scoped pass-through)."""
    sandbox = LocalSandbox("t")

    assert await sandbox.execute_command_in_scope_async("echo scoped", scope_id="scope-1") == await sandbox.execute_command_async("echo scoped")
