import asyncio

import pytest

from deerflow.config.subagent_runtime_config import SubagentRuntimeConfig
from deerflow.subagents.capacity import (
    SubagentCapacityRejected,
    SubagentCapacityTimeout,
    configure_subagent_execution_capacity,
    configured_subagent_max_running,
    get_subagent_execution_capacity,
)


@pytest.mark.asyncio
async def test_capacity_queues_without_starting_more_than_configured_slots() -> None:
    configure_subagent_execution_capacity(SubagentRuntimeConfig(max_running=1, max_queued=2, queue_timeout_seconds=5))
    capacity = get_subagent_execution_capacity()
    release = asyncio.Event()
    started: list[str] = []

    async def work(name: str) -> None:
        async with capacity.slot():
            started.append(name)
            if name == "first":
                await release.wait()

    first = asyncio.create_task(work("first"))
    await asyncio.sleep(0)
    second = asyncio.create_task(work("second"))
    await asyncio.sleep(0)

    assert started == ["first"]
    assert capacity.snapshot().running == 1
    assert capacity.snapshot().queued == 1

    release.set()
    await asyncio.gather(first, second)
    assert started == ["first", "second"]
    assert capacity.snapshot().running == 0


@pytest.mark.asyncio
async def test_capacity_rejects_immediately_when_configured() -> None:
    configure_subagent_execution_capacity(SubagentRuntimeConfig(max_running=1, max_queued=10, admission_policy="reject"))
    capacity = get_subagent_execution_capacity()
    async with capacity.slot():
        with pytest.raises(SubagentCapacityRejected, match="capacity is full"):
            async with capacity.slot():
                raise AssertionError("unreachable")


@pytest.mark.asyncio
async def test_capacity_enforces_queue_bound() -> None:
    configure_subagent_execution_capacity(SubagentRuntimeConfig(max_running=1, max_queued=1, queue_timeout_seconds=5))
    capacity = get_subagent_execution_capacity()
    release = asyncio.Event()

    async def holder() -> None:
        async with capacity.slot():
            await release.wait()

    first = asyncio.create_task(holder())
    await asyncio.sleep(0)
    queued = asyncio.create_task(holder())
    await asyncio.sleep(0)
    with pytest.raises(SubagentCapacityRejected, match="1 queued"):
        async with capacity.slot():
            raise AssertionError("unreachable")
    release.set()
    await asyncio.gather(first, queued)


@pytest.mark.asyncio
async def test_capacity_timeout_removes_waiter_and_releases_slot() -> None:
    configure_subagent_execution_capacity(SubagentRuntimeConfig(max_running=1, max_queued=1, queue_timeout_seconds=1))
    capacity = get_subagent_execution_capacity()
    async with capacity.slot():
        with pytest.raises(SubagentCapacityTimeout, match="Timed out"):
            async with capacity.slot():
                raise AssertionError("unreachable")
        assert capacity.snapshot().queued == 0
    assert capacity.snapshot().running == 0


@pytest.mark.asyncio
async def test_capacity_cancelled_waiter_does_not_leak_queue_or_slot() -> None:
    configure_subagent_execution_capacity(SubagentRuntimeConfig(max_running=1, max_queued=2, queue_timeout_seconds=5))
    capacity = get_subagent_execution_capacity()
    release = asyncio.Event()

    async def holder() -> None:
        async with capacity.slot():
            await release.wait()

    first = asyncio.create_task(holder())
    await asyncio.sleep(0)
    waiting = asyncio.create_task(holder())
    await asyncio.sleep(0)
    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting
    assert capacity.snapshot().queued == 0
    release.set()
    await first
    assert capacity.snapshot().running == 0


@pytest.mark.asyncio
async def test_installing_same_startup_config_does_not_reset_live_capacity() -> None:
    config = SubagentRuntimeConfig(max_running=1, max_queued=2, queue_timeout_seconds=5)
    configure_subagent_execution_capacity(config)
    capacity = get_subagent_execution_capacity()

    async with capacity.slot():
        configure_subagent_execution_capacity(config)
        assert get_subagent_execution_capacity() is capacity
        assert capacity.snapshot().running == 1

    assert configured_subagent_max_running() == 1


@pytest.mark.asyncio
async def test_installing_different_config_while_active_is_rejected() -> None:
    configure_subagent_execution_capacity(SubagentRuntimeConfig(max_running=1))
    capacity = get_subagent_execution_capacity()

    async with capacity.slot():
        with pytest.raises(RuntimeError, match="while executions are active"):
            configure_subagent_execution_capacity(SubagentRuntimeConfig(max_running=2))
