"""Cross-thread safety of the shared subagent execution capacity."""

import asyncio
from collections import deque

import pytest

from deerflow.config.subagent_runtime_config import SubagentRuntimeConfig
from deerflow.subagents.capacity import SubagentExecutionCapacity


class _NoIterationDeque(deque):
    """A deque whose iteration always fails, as if mutated concurrently."""

    def __iter__(self):
        raise RuntimeError("deque mutated during iteration")


def test_snapshot_does_not_iterate_waiters():
    """snapshot() must be readable from a non-loop thread.

    ``configure_subagent_execution_capacity`` reads a snapshot while the loop
    thread owns the waiters deque; iterating it cross-thread can raise
    ``deque mutated during iteration``. The snapshot must therefore derive
    ``queued`` without iterating.
    """
    capacity = SubagentExecutionCapacity(SubagentRuntimeConfig(max_running=2, max_queued=4))
    capacity._waiters = _NoIterationDeque(range(2))

    snapshot = capacity.snapshot()

    assert snapshot.max_running == 2
    assert snapshot.max_queued == 4
    assert snapshot.queued == 2
    assert snapshot.running == 0
    assert snapshot.admission_policy == "queue"


@pytest.mark.asyncio
async def test_snapshot_reports_running_and_queued_waiters():
    """The derived queued count still reflects pending waiters."""
    capacity = SubagentExecutionCapacity(SubagentRuntimeConfig(max_running=1, max_queued=4, queue_timeout_seconds=5))

    async def hold_slot():
        async with capacity.slot():
            await asyncio.sleep(60)

    holder = asyncio.create_task(hold_slot())
    queued = asyncio.create_task(capacity._acquire())
    try:
        await asyncio.sleep(0.05)

        snapshot = capacity.snapshot()
        assert snapshot.running == 1
        assert snapshot.queued == 1
    finally:
        queued.cancel()
        holder.cancel()
        await asyncio.gather(queued, holder, return_exceptions=True)


@pytest.mark.asyncio
async def test_repeated_cancellation_cannot_leak_running_slot(monkeypatch):
    """A second cancellation during cleanup must not strand process capacity."""
    capacity = SubagentExecutionCapacity(SubagentRuntimeConfig(max_running=1, max_queued=1, queue_timeout_seconds=1))
    entered = asyncio.Event()
    release_started = asyncio.Event()
    never = asyncio.Event()
    original_release = capacity._release

    async def observed_release():
        release_started.set()
        await original_release()

    monkeypatch.setattr(capacity, "_release", observed_release)

    async def hold_slot():
        async with capacity.slot():
            entered.set()
            await never.wait()

    holder = asyncio.create_task(hold_slot())
    await asyncio.wait_for(entered.wait(), timeout=1)
    await capacity._lock.acquire()
    try:
        holder.cancel()
        await asyncio.wait_for(release_started.wait(), timeout=1)
        holder.cancel()
        await asyncio.sleep(0)
    finally:
        capacity._lock.release()

    with pytest.raises(asyncio.CancelledError):
        await holder

    assert capacity.snapshot().running == 0
    async with asyncio.timeout(0.5):
        async with capacity.slot():
            pass
