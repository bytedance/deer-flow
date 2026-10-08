"""Gate waiters must not consume the executor needed by the lock holder."""

import asyncio
import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest

from deerflow.agents.middlewares import read_before_write_middleware as gate


def _request(tag: str) -> ToolCallRequest:
    return ToolCallRequest(
        tool_call={"name": "read_file", "args": {"path": "/report.md", "description": "read"}, "id": tag},
        tool=None,
        state={"messages": []},
        runtime=SimpleNamespace(context={"thread_id": "gate-coordination"}, state={}),
    )


class _ObservedLock:
    """Observe arrivals without replacing the production locking behavior."""

    def __init__(self, lock, arrived):
        self.lock = lock
        self.arrived = arrived

    def acquire(self):
        self.arrived()
        return self.lock.acquire()

    async def acquire_async(self):
        self.arrived()
        return await self.lock.acquire_async()

    def release(self):
        self.lock.release()

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *_exc):
        self.release()


@pytest.mark.parametrize("workers", [2, 32])
def test_same_path_waiters_do_not_starve_the_holder_or_unrelated_work(tmp_path, monkeypatch, workers):
    path = tmp_path / "report.md"
    path.write_text("actual file bytes", encoding="utf-8")

    async def scenario():
        loop = asyncio.get_running_loop()
        pool = ThreadPoolExecutor(max_workers=workers)
        loop.set_default_executor(pool)
        holder_entered = asyncio.Event()
        return_read_result = asyncio.Event()
        waiters_entered = asyncio.Event()
        calls = 0
        count_guard = threading.Lock()

        def arrived():
            nonlocal calls
            with count_guard:
                calls += 1
                if calls == workers + 1:
                    loop.call_soon_threadsafe(waiters_entered.set)

        middleware = gate.ReadBeforeWriteMiddleware(content_reader=lambda _runtime, _path: path.read_text(encoding="utf-8"))
        observed = _ObservedLock(middleware._lock_for(_request("holder"), "/report.md"), arrived)
        monkeypatch.setattr(middleware, "_lock_for", lambda _request, _path: observed)

        async def handler(request):
            if request.tool_call["id"] == "holder":
                holder_entered.set()
                await return_read_result.wait()
            return ToolMessage(content="actual file bytes", tool_call_id=request.tool_call["id"], name="read_file")

        tasks = [asyncio.create_task(middleware.awrap_tool_call(_request("holder"), handler))]
        probe = None
        completed = set()
        try:
            await asyncio.wait_for(holder_entered.wait(), 5)
            tasks.extend(asyncio.create_task(middleware.awrap_tool_call(_request(f"waiter-{i}"), handler)) for i in range(workers))
            await asyncio.wait_for(waiters_entered.wait(), 5)
            return_read_result.set()
            probe = asyncio.create_task(asyncio.to_thread(lambda: "unrelated work"))
            completed, _ = await asyncio.wait((tasks[0], probe), timeout=5)
        finally:
            return_read_result.set()
            if tasks[0] not in completed:
                # Only a failing implementation needs this escape hatch. A
                # spare worker drains the cycle so pytest teardown cannot hang.
                pool._max_workers += 1
                pool._adjust_thread_count()
            results = await asyncio.wait_for(asyncio.gather(*tasks), 5)
            if probe is not None:
                await asyncio.wait_for(probe, 5)

        assert tasks[0] in completed, "gate holder cannot dispatch its read-mark worker"
        assert probe in completed, "contended file lock starved unrelated executor work"
        assert all(result.additional_kwargs[gate.READ_MARK_KEY]["hash"] == hashlib.sha256(b"actual file bytes").hexdigest() for result in results)

    asyncio.run(scenario())


def test_cancel_after_unlock_does_not_orphan_the_gate():
    async def scenario():
        loop = asyncio.get_running_loop()
        arrived = asyncio.Event()
        lock = gate._get_gate_lock("gate-cancel-after-unlock", "/report.md")
        lock.acquire()
        observed = _ObservedLock(lock, lambda: loop.call_soon_threadsafe(arrived.set))
        task = asyncio.create_task(gate._acquire_gate_lock(observed))
        try:
            await asyncio.wait_for(arrived.wait(), 5)
            lock.release()
            task.cancel("cancel before taking ownership")
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 5)
            await asyncio.wait_for(gate._acquire_gate_lock(lock), 5)
            lock.release()
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())


def test_async_tool_waits_for_sync_tool_on_the_same_path(tmp_path, monkeypatch):
    path = tmp_path / "report.md"
    path.write_text("shared file", encoding="utf-8")

    async def scenario():
        loop = asyncio.get_running_loop()
        holder_entered = threading.Event()
        release_holder = threading.Event()
        waiter_arrived = asyncio.Event()
        waiter_ran = False
        sync_results = []
        sync_errors = []
        arrivals = 0
        guard = threading.Lock()
        middleware = gate.ReadBeforeWriteMiddleware(content_reader=lambda _runtime, _path: path.read_text(encoding="utf-8"))

        def arrived():
            nonlocal arrivals
            with guard:
                arrivals += 1
                if arrivals == 2:
                    loop.call_soon_threadsafe(waiter_arrived.set)

        observed = _ObservedLock(middleware._lock_for(_request("sync-holder"), "/report.md"), arrived)
        monkeypatch.setattr(middleware, "_lock_for", lambda _request, _path: observed)

        def sync_handler(request):
            holder_entered.set()
            assert release_holder.wait(5), "test did not release the synchronous holder"
            return ToolMessage(content="shared file", tool_call_id=request.tool_call["id"], name="read_file")

        def sync_call():
            try:
                sync_results.append(middleware.wrap_tool_call(_request("sync-holder"), sync_handler))
            except BaseException as exc:
                sync_errors.append(exc)

        async def async_handler(request):
            nonlocal waiter_ran
            waiter_ran = True
            return ToolMessage(content="shared file", tool_call_id=request.tool_call["id"], name="read_file")

        thread = threading.Thread(target=sync_call)
        task = None
        thread.start()
        try:
            assert await asyncio.to_thread(holder_entered.wait, 5)
            task = asyncio.create_task(middleware.awrap_tool_call(_request("async-waiter"), async_handler))
            await asyncio.wait_for(waiter_arrived.wait(), 5)
            assert not waiter_ran
            release_holder.set()
            result = await asyncio.wait_for(task, 5)
            assert waiter_ran
        finally:
            release_holder.set()
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            await asyncio.to_thread(thread.join, 5)
            assert not thread.is_alive()

        assert not sync_errors
        expected = hashlib.sha256(b"shared file").hexdigest()
        assert len(sync_results) == 1
        assert sync_results[0].additional_kwargs[gate.READ_MARK_KEY]["hash"] == expected
        assert result.additional_kwargs[gate.READ_MARK_KEY]["hash"] == expected

    asyncio.run(scenario())


def test_cancelled_waiter_does_not_cancel_another_event_loops_waiter():
    lock = gate._get_gate_lock("gate-cross-loop-cancellation", "/report.md")
    lock.acquire()
    owner_holds_lock = True
    arrived = [threading.Event(), threading.Event()]
    cancelled = threading.Event()
    tasks = {}
    errors = []
    acquired = []

    def worker(index):
        async def scenario():
            observed = _ObservedLock(lock, arrived[index].set)
            task = asyncio.create_task(gate._acquire_gate_lock(observed))
            tasks[index] = (asyncio.get_running_loop(), task)
            try:
                await task
            except asyncio.CancelledError:
                assert index == 0
                cancelled.set()
            else:
                try:
                    acquired.append(index)
                finally:
                    lock.release()

        try:
            asyncio.run(scenario())
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(index,)) for index in range(2)]
    for thread in threads:
        thread.start()
    try:
        assert all(event.wait(5) for event in arrived)
        loop, task = tasks[0]
        loop.call_soon_threadsafe(task.cancel)
        assert cancelled.wait(5), "cancellation waited for the synchronous holder"
        assert acquired == []
        owner_holds_lock = False
        lock.release()
    finally:
        if owner_holds_lock:
            lock.release()
        for thread in threads:
            thread.join(5)
        assert not any(thread.is_alive() for thread in threads)
    assert not errors
    assert acquired == [1]
    assert not lock.locked()
