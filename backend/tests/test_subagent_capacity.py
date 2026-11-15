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


@pytest.mark.asyncio
@pytest.mark.parametrize("owner_released", [False, True])
@pytest.mark.parametrize("abandonment", ["cancel", "timeout"])
async def test_abandoned_waiter_drains_cleanup_after_repeated_cancellation(monkeypatch, owner_released, abandonment):
    """Once cleanup starts, more cancellations cannot orphan a transferred slot."""
    waiter_ready = asyncio.Event()
    expire_waiter = asyncio.Event()
    cleanup_started = asyncio.Event()

    class ObservedLock(asyncio.Lock):
        async def acquire(self):
            if self.locked():
                cleanup_started.set()
            return await super().acquire()

    capacity = SubagentExecutionCapacity(SubagentRuntimeConfig(max_running=1, max_queued=1))
    capacity._lock = ObservedLock()
    real_wait_for = asyncio.wait_for

    async def wait_for_slot(awaitable, timeout):
        if capacity._waiters and awaitable is capacity._waiters[0]:
            waiter_ready.set()
            if abandonment == "timeout":
                # Exercise asyncio's timeout only once cleanup will contend for the lock.
                await expire_waiter.wait()
                timeout = 0
        return await real_wait_for(awaitable, timeout)

    monkeypatch.setattr(asyncio, "wait_for", wait_for_slot)
    await capacity._acquire()
    queued = asyncio.create_task(capacity._acquire())
    try:
        await real_wait_for(waiter_ready.wait(), 3)
        async with capacity._lock:
            if abandonment == "cancel":
                if owner_released:
                    capacity._release_locked()
                queued.cancel()
            else:
                expire_waiter.set()
            await real_wait_for(cleanup_started.wait(), 3)
            if owner_released and abandonment == "timeout":
                # A timed-out waiter's future is cancelled, so release skips it.
                capacity._release_locked()
            queued.cancel("cancelled while draining")
            await asyncio.sleep(0)
            queued.cancel("cancelled again")

        async with asyncio.timeout(3):
            with pytest.raises(asyncio.CancelledError, match="cancelled while draining"):
                await queued
    finally:
        if not queued.done():
            queued.cancel()
            await asyncio.gather(queued, return_exceptions=True)
    if not owner_released:
        await capacity._release()
    snapshot = capacity.snapshot()
    assert (snapshot.running, snapshot.queued) == (0, 0)
    async with asyncio.timeout(0.5):
        async with capacity.slot():
            pass
