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
