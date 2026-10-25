"""LocalSandbox async command execution must keep the event loop responsive."""

from __future__ import annotations

import asyncio
import os
import time

import pytest

from deerflow.sandbox.local.local_sandbox import LocalSandbox

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(os.name == "nt", reason="POSIX async subprocess semantics"),
]


async def test_async_command_keeps_event_loop_responsive() -> None:
    """A long-running sandbox command runs without monopolizing the loop: a
    concurrent timer must fire on time while the command is still in flight.
    This is the blocking-I/O guard for execute_command_async — the whole point
    of the async path is that the gateway loop keeps serving other tasks (IM
    channels, concurrent runs) while a command runs."""
    sandbox = LocalSandbox("t")

    started = time.monotonic()
    command_task = asyncio.create_task(sandbox.execute_command_async("sleep 1", timeout=10))
    await asyncio.sleep(0.2)
    timer_elapsed = time.monotonic() - started
    await command_task
    total = time.monotonic() - started

    assert timer_elapsed < 0.9, f"event loop stalled for {timer_elapsed:.2f}s during async command execution"
    assert total >= 1.0, "command should actually have run for its full duration"
