from __future__ import annotations

import asyncio
import threading
from contextlib import suppress
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest

from deerflow.agents.middlewares import read_before_write_middleware as gate
from deerflow.agents.middlewares.read_before_write_middleware import ReadBeforeWriteMiddleware, _await_off_thread
from deerflow.sandbox.exceptions import SandboxAuthorizationError

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

    async def acquire_async(self) -> None:
        self.acquire()

    def release(self) -> None:
        with self._guard:
            assert self.acquired
            self.acquired = False
            self.release_calls += 1


@pytest.mark.parametrize("tool_name", ["read_file", "write_file"])
def test_async_gate_cancellation_does_not_wait_for_another_holder(
    monkeypatch: pytest.MonkeyPatch,
    tool_name: str,
) -> None:
    async def scenario() -> None:
        gate_lock = gate._get_gate_lock(f"cancel-waiter-{tool_name}", _PATH)
        gate_lock.acquire()
        acquire_started = asyncio.Event()
        acquire = gate._acquire_gate_lock

        async def observed_acquire(lock):
            acquire_started.set()
            await acquire(lock)

        monkeypatch.setattr(gate, "_acquire_gate_lock", observed_acquire)
        middleware = ReadBeforeWriteMiddleware(content_reader=lambda _runtime, _path: "v1")
        monkeypatch.setattr(middleware, "_lock_for", lambda _request, _path: gate_lock)
        handler_called = False

        async def handler(_request: ToolCallRequest) -> ToolMessage:
            nonlocal handler_called
            handler_called = True
            return ToolMessage(content="OK", tool_call_id=f"call-{tool_name}", name=tool_name)

        task = asyncio.create_task(middleware.awrap_tool_call(_request(tool_name), handler))
        try:
            await asyncio.wait_for(acquire_started.wait(), 5)
            task.cancel("first cancellation")
            done, _ = await asyncio.wait((task,), timeout=5)
            assert task in done, "a cancelled waiter still depends on another holder"
            with pytest.raises(asyncio.CancelledError) as exc_info:
                await task
            assert exc_info.value.args == ("first cancellation",)
            # No synchronous acquisition was dispatched. Cancellation must not
            # release somebody else's gate or leave a later acquisition behind.
            assert gate_lock.locked()
            assert not handler_called
        finally:
            gate_lock.release()
            if not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
        await asyncio.wait_for(acquire(gate_lock), 5)
        gate_lock.release()

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


@pytest.mark.parametrize("tool_name", ["read_file", "write_file"])
def test_async_gate_cancellation_wins_over_sync_probe_authorization_error(
    monkeypatch: pytest.MonkeyPatch,
    tool_name: str,
) -> None:
    async def scenario() -> None:
        probe_started = threading.Event()
        allow_probe_finish = threading.Event()
        gate_lock = _TrackingLock()

        def reader(_runtime: object, _path: str) -> str:
            probe_started.set()
            assert allow_probe_finish.wait(timeout=5), "test did not unblock failing gate probe"
            raise SandboxAuthorizationError("probe denied")

        middleware = ReadBeforeWriteMiddleware(content_reader=reader)
        monkeypatch.setattr(middleware, "_lock_for", lambda _request, _path: gate_lock)
        handler_calls = 0

        async def handler(_request: ToolCallRequest) -> ToolMessage:
            nonlocal handler_calls
            handler_calls += 1
            return ToolMessage(content="v1", tool_call_id=f"call-{tool_name}", name=tool_name)

        task = asyncio.create_task(middleware.awrap_tool_call(_request(tool_name), handler))
        try:
            assert await asyncio.to_thread(probe_started.wait, 2), "failing gate probe did not start"
            assert gate_lock.acquired

            task.cancel("first cancellation")
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
