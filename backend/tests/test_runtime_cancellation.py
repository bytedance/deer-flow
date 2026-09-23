import asyncio
from types import SimpleNamespace

import pytest

import deerflow.runtime.cancellation as cancellation
from deerflow.runtime.cancellation import drained_async_context, wait_for_task_until


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


class _RecordingAsyncContext:
    def __init__(self, *, suppress: bool = False, exit_error: Exception | None = None) -> None:
        self.suppress = suppress
        self.exit_error = exit_error
        self.exit_args = None

    async def __aenter__(self):
        return "resource"

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        self.exit_args = (exc_type, exc, tb)
        if self.exit_error is not None:
            raise self.exit_error
        return self.suppress


@pytest.mark.anyio
async def test_drained_async_context_suppresses_when_exit_returns_true():
    manager = _RecordingAsyncContext(suppress=True)

    async with drained_async_context(manager):
        raise asyncio.CancelledError()

    assert manager.exit_args is not None
    assert manager.exit_args[0] is asyncio.CancelledError


@pytest.mark.anyio
async def test_drained_async_context_reraises_when_exit_returns_false():
    manager = _RecordingAsyncContext()

    with pytest.raises(ValueError, match="body failed"):
        async with drained_async_context(manager):
            raise ValueError("body failed")

    assert manager.exit_args is not None
    assert manager.exit_args[0] is ValueError


@pytest.mark.anyio
async def test_drained_async_context_exit_error_replaces_body_error():
    manager = _RecordingAsyncContext(exit_error=RuntimeError("exit failed"))

    with pytest.raises(RuntimeError, match="exit failed") as exc_info:
        async with drained_async_context(manager):
            raise ValueError("body failed")

    assert isinstance(exc_info.value.__context__, ValueError)


@pytest.mark.anyio
async def test_drained_async_context_drains_repeated_cancellation_during_exit():
    exit_started = asyncio.Event()
    allow_exit = asyncio.Event()
    exit_finished = asyncio.Event()
    entered = asyncio.Event()

    class _BlockingContext:
        async def __aenter__(self):
            return "resource"

        async def __aexit__(self, _exc_type, _exc, _tb) -> bool:
            exit_started.set()
            await allow_exit.wait()
            exit_finished.set()
            return False

    async def owner() -> None:
        async with drained_async_context(_BlockingContext()):
            entered.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(owner())
    try:
        await asyncio.wait_for(entered.wait(), timeout=1)
        task.cancel()
        await asyncio.wait_for(exit_started.wait(), timeout=1)
        task.cancel()
        for _ in range(5):
            await asyncio.sleep(0)
        assert not task.done()

        allow_exit.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert exit_finished.is_set()
    finally:
        allow_exit.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.anyio
async def test_drained_async_context_exit_failure_replaces_cancellation_during_exit():
    exit_started = asyncio.Event()
    allow_exit = asyncio.Event()
    entered = asyncio.Event()
    leave = asyncio.Event()

    class _FailingExitContext:
        async def __aenter__(self):
            return "resource"

        async def __aexit__(self, _exc_type, _exc, _tb) -> bool:
            exit_started.set()
            await allow_exit.wait()
            raise RuntimeError("exit failed")

    async def owner() -> None:
        async with drained_async_context(_FailingExitContext()):
            entered.set()
            await leave.wait()

    task = asyncio.create_task(owner())
    try:
        await asyncio.wait_for(entered.wait(), timeout=1)
        leave.set()
        await asyncio.wait_for(exit_started.wait(), timeout=1)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()

        allow_exit.set()
        with pytest.raises(RuntimeError, match="exit failed") as exc_info:
            await task
        assert isinstance(exc_info.value.__context__, asyncio.CancelledError)
    finally:
        allow_exit.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
