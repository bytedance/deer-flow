"""Repeated-cancellation regression for Gateway run draining on shutdown."""

from __future__ import annotations

import asyncio

import pytest


@pytest.mark.asyncio
async def test_run_drain_waits_for_shutdown_across_repeated_cancellation(monkeypatch):
    """A second cancellation cannot let checkpointer teardown outrun the drain."""
    from app.gateway import deps

    shutdown_started = asyncio.Event()
    allow_shutdown_finish = asyncio.Event()
    shutdown_finished = asyncio.Event()

    class _RunManager:
        async def shutdown(self, *, timeout: float) -> None:
            assert timeout == deps._RUN_DRAIN_TIMEOUT_SECONDS
            shutdown_started.set()
            await allow_shutdown_finish.wait()
            shutdown_finished.set()

    original_shield = asyncio.shield
    entered_second_shield = asyncio.Event()
    shield_calls = 0

    def tracked_shield(awaitable):
        nonlocal shield_calls
        shield_calls += 1
        if shield_calls == 2:
            entered_second_shield.set()
        return original_shield(awaitable)

    monkeypatch.setattr(deps.asyncio, "shield", tracked_shield)

    drain_task = asyncio.create_task(deps._drain_inflight_runs(_RunManager()))
    await asyncio.wait_for(shutdown_started.wait(), timeout=1.0)

    drain_task.cancel("first shutdown cancellation")
    await asyncio.wait_for(entered_second_shield.wait(), timeout=1.0)

    # A second SIGINT / graceful-shutdown cancellation arrives while the helper
    # is already waiting for RunManager.shutdown() to finish. The helper must
    # keep owning that wait so the surrounding AsyncExitStack cannot close the
    # checkpointer underneath still-running run tasks.
    drain_task.cancel("second shutdown cancellation")
    await asyncio.sleep(0)
    escaped_before_shutdown_finished = drain_task.done()

    allow_shutdown_finish.set()
    with pytest.raises(asyncio.CancelledError):
        await drain_task

    assert not escaped_before_shutdown_finished
    assert shutdown_finished.is_set()
