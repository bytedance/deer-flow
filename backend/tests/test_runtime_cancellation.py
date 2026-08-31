import asyncio
from types import SimpleNamespace

import pytest

import deerflow.runtime.cancellation as cancellation
from deerflow.runtime.cancellation import wait_for_task_until


@pytest.mark.anyio
async def test_wait_for_task_until_reports_completion():
    child = asyncio.create_task(asyncio.sleep(0, result="done"))

    completed = await wait_for_task_until(child, deadline=asyncio.get_running_loop().time() + 1)

    assert completed is True
    assert child.result() == "done"


@pytest.mark.anyio
async def test_wait_for_task_until_times_out_without_cancelling_child():
    event = asyncio.Event()
    child = asyncio.create_task(event.wait())

    completed = await wait_for_task_until(child, deadline=asyncio.get_running_loop().time() + 0.01)

    assert completed is False
    assert child.done() is False
    event.set()
    await child


@pytest.mark.anyio
async def test_wait_for_task_until_zero_budget_returns_immediately():
    event = asyncio.Event()
    child = asyncio.create_task(event.wait())

    completed = await wait_for_task_until(child, deadline=asyncio.get_running_loop().time())

    assert completed is False
    assert child.done() is False
    child.cancel()
    with pytest.raises(asyncio.CancelledError):
        await child


@pytest.mark.anyio
async def test_wait_for_task_until_repeated_cancellation_keeps_original_deadline(monkeypatch):
    clock = iter((0.0, 0.01, 0.02, 0.05))
    clock_loop = SimpleNamespace(time=lambda: next(clock, 0.05))

    wait_timeouts = []
    entered_first_wait = asyncio.Event()
    entered_second_wait = asyncio.Event()

    async def fake_wait(tasks, *, timeout):
        del tasks
        wait_timeouts.append(timeout)
        if len(wait_timeouts) == 1:
            entered_first_wait.set()
            await asyncio.Future()
        if len(wait_timeouts) == 2:
            entered_second_wait.set()
            await asyncio.Future()
        return set(), set()

    monkeypatch.setattr(
        cancellation,
        "asyncio",
        SimpleNamespace(
            CancelledError=asyncio.CancelledError,
            get_running_loop=lambda: clock_loop,
            wait=fake_wait,
        ),
    )
    event = asyncio.Event()
    child = asyncio.create_task(event.wait())
    waiter = asyncio.create_task(wait_for_task_until(child, deadline=0.05))

    await entered_first_wait.wait()
    waiter.cancel()
    await entered_second_wait.wait()
    waiter.cancel()
    assert waiter.cancelling() == 2
    completed = await waiter

    assert completed is False
    assert wait_timeouts == pytest.approx([0.05, 0.04, 0.03])
    assert child.done() is False
    event.set()
    await child
