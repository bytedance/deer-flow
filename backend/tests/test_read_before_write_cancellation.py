from __future__ import annotations

import asyncio
import threading
from contextlib import suppress
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest

from deerflow.agents.middlewares.read_before_write_middleware import ReadBeforeWriteMiddleware, _await_off_thread

_PATH = "/mnt/user-data/outputs/report.md"


def _request(tool_name: str) -> ToolCallRequest:
    runtime = MagicMock()
    runtime.context = {"thread_id": "thread-cancel"}
    args: dict[str, object] = {"description": "d", "path": _PATH}
    if tool_name == "write_file":
        args["content"] = "v2"
    return ToolCallRequest(
        tool_call={"name": tool_name, "args": args, "id": f"call-{tool_name}"},
        tool=None,
        state={"messages": []},
        runtime=runtime,
    )


class _BlockingAcquireLock:
    def __init__(self) -> None:
        self.acquire_started = threading.Event()
        self.allow_acquire = threading.Event()
        self.acquired = threading.Event()
        self.release_calls = 0
        self._guard = threading.Lock()

    def acquire(self) -> bool:
        self.acquire_started.set()
        assert self.allow_acquire.wait(timeout=5), "test did not unblock gate-lock acquisition"
        with self._guard:
            self.acquired.set()
        return True

    def release(self) -> None:
        with self._guard:
            assert self.acquired.is_set(), "gate lock released without ownership"
            self.acquired.clear()
            self.release_calls += 1


class _TrackingLock:
    def __init__(self) -> None:
        self.acquired = False
        self.release_calls = 0
        self._guard = threading.Lock()

    def acquire(self) -> bool:
        with self._guard:
            assert not self.acquired
            self.acquired = True
        return True

    def release(self) -> None:
        with self._guard:
            assert self.acquired
            self.acquired = False
            self.release_calls += 1


@pytest.mark.parametrize("tool_name", ["read_file", "write_file"])
def test_async_gate_cancellation_drains_queued_lock_acquisition(
    monkeypatch: pytest.MonkeyPatch,
    tool_name: str,
) -> None:
    async def scenario() -> None:
        gate_lock = _BlockingAcquireLock()
        middleware = ReadBeforeWriteMiddleware(content_reader=lambda _runtime, _path: "v1")
        monkeypatch.setattr(middleware, "_lock_for", lambda _request, _path: gate_lock)
        handler_called = False

        async def handler(_request: ToolCallRequest) -> ToolMessage:
            nonlocal handler_called
            handler_called = True
            return ToolMessage(content="OK", tool_call_id=f"call-{tool_name}", name=tool_name)

        task = asyncio.create_task(middleware.awrap_tool_call(_request(tool_name), handler))
        try:
            assert await asyncio.to_thread(gate_lock.acquire_started.wait, 2), "gate-lock acquisition did not start"

            task.cancel("first cancellation")
            await asyncio.sleep(0)

            # threading.Lock.acquire() is already running in a worker thread and
            # cannot be cancelled. The middleware must retain ownership of that
            # acquisition until it lands, then release it before propagating the
            # original cancellation. Returning cancellation here would orphan a
            # future successful acquire with nobody left to release it.
            assert not task.done()
            assert gate_lock.release_calls == 0

            task.cancel("second cancellation")
            await asyncio.sleep(0)

            assert not task.done()
            assert gate_lock.release_calls == 0
            assert not handler_called

            gate_lock.allow_acquire.set()
            with pytest.raises(asyncio.CancelledError) as exc_info:
                await task

            assert exc_info.value.args == ("first cancellation",)
            assert gate_lock.release_calls == 1
            assert not gate_lock.acquired.is_set()
            assert not handler_called
        finally:
            gate_lock.allow_acquire.set()
            await asyncio.to_thread(gate_lock.acquired.wait, 0.1)
            if gate_lock.acquired.is_set() and gate_lock.release_calls == 0:
                gate_lock.release()
            if not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    asyncio.run(scenario())


@pytest.mark.parametrize("tool_name", ["read_file", "write_file"])
def test_async_gate_cancellation_drains_sync_probe_before_unlocking(
    monkeypatch: pytest.MonkeyPatch,
    tool_name: str,
) -> None:
    async def scenario() -> None:
        probe_started = threading.Event()
        allow_probe_finish = threading.Event()
        gate_lock = _TrackingLock()

        def reader(_runtime: object, _path: str) -> str:
            probe_started.set()
            assert allow_probe_finish.wait(timeout=5), "test did not unblock gate probe"
            return "v1"

        middleware = ReadBeforeWriteMiddleware(content_reader=reader)
        monkeypatch.setattr(middleware, "_lock_for", lambda _request, _path: gate_lock)
        handler_calls = 0

        async def handler(_request: ToolCallRequest) -> ToolMessage:
            nonlocal handler_calls
            handler_calls += 1
            return ToolMessage(content="v1", tool_call_id=f"call-{tool_name}", name=tool_name)

        task = asyncio.create_task(middleware.awrap_tool_call(_request(tool_name), handler))
        try:
            assert await asyncio.to_thread(probe_started.wait, 2), "gate probe did not start"
            assert gate_lock.acquired

            task.cancel("first cancellation")
            await asyncio.sleep(0)

            # The synchronous probe is also non-cancellable once dispatched.
            # Releasing the gate lock before that worker returns lets another
            # same-path tool enter the critical section concurrently with work
            # that this task started under the lock.
            assert not task.done()
            assert gate_lock.acquired
            assert gate_lock.release_calls == 0

            task.cancel("second cancellation")
            await asyncio.sleep(0)

            assert not task.done()
            assert gate_lock.acquired
            assert gate_lock.release_calls == 0

            allow_probe_finish.set()
            with pytest.raises(asyncio.CancelledError) as exc_info:
                await task

            assert exc_info.value.args == ("first cancellation",)
            assert not gate_lock.acquired
            assert gate_lock.release_calls == 1
            assert handler_calls == (1 if tool_name == "read_file" else 0)
        finally:
            allow_probe_finish.set()
            if gate_lock.acquired:
                gate_lock.release()
            if not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    asyncio.run(scenario())


def test_await_off_thread_preserves_first_cancel_when_worker_task_is_cancelled() -> None:
    async def scenario() -> None:
        worker_started = asyncio.Event()
        worker_can_finish = asyncio.Event()

        async def worker() -> None:
            worker_started.set()
            await worker_can_finish.wait()

        worker_task = asyncio.create_task(worker())
        waiter = asyncio.create_task(_await_off_thread(worker_task))
        await worker_started.wait()

        waiter.cancel("first cancellation")
        await asyncio.sleep(0)
        assert not waiter.done()

        worker_task.cancel("inner cancellation")
        with pytest.raises(asyncio.CancelledError) as exc_info:
            await waiter

        assert exc_info.value.args == ("first cancellation",)

    asyncio.run(scenario())
