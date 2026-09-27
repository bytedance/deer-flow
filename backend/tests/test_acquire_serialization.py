"""Contract tests for AcquireSerializer (RFC #4741 §5)."""

from __future__ import annotations

import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from deerflow.sandbox.acquire_serialization import AcquireSerializer
from deerflow.trace_context import get_current_trace_id, request_trace_context


class TestSyncMutualExclusion:
    def test_same_key_never_overlaps(self):
        serializer = AcquireSerializer()
        active = 0
        max_active = 0
        counter_lock = threading.Lock()

        def worker():
            nonlocal active, max_active
            with serializer.hold("k"):
                with counter_lock:
                    active += 1
                    max_active = max(max_active, active)
                time.sleep(0.02)
                with counter_lock:
                    active -= 1

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert max_active == 1

    def test_different_keys_proceed_concurrently(self):
        serializer = AcquireSerializer()
        barrier = threading.Barrier(2, timeout=2)

        def worker(key):
            with serializer.hold(key):
                barrier.wait()  # raises BrokenBarrierError if serialized

        t1 = threading.Thread(target=worker, args=("a",))
        t2 = threading.Thread(target=worker, args=("b",))
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)
        assert not t1.is_alive() and not t2.is_alive()

    def test_lock_table_reclaims_entries(self):
        serializer = AcquireSerializer()
        for i in range(50):
            with serializer.hold(f"scope-{i}"):
                pass
        assert len(serializer._table) == 0


class TestAsyncContract:
    @pytest.mark.asyncio
    async def test_cancellation_before_acquire_leaks_nothing(self):
        serializer = AcquireSerializer()
        with serializer.hold("k"):  # uncontended acquire, safe on the loop
            waiter = asyncio.create_task(_hold_once(serializer, "k"))
            await asyncio.sleep(0.05)  # let the waiter start blocking in the worker
            waiter.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiter
        # The worker acquires the now-free lock in the background; its done
        # callback must release it and reclaim the entry.
        async with serializer.hold_async("k"):
            pass
        await _wait_for_table_empty(serializer)

    @pytest.mark.asyncio
    async def test_cancelled_wait_releases_without_event_loop_callback(self):
        serializer = AcquireSerializer()
        holder_ready = threading.Event()
        release_holder = threading.Event()

        def hold_in_thread():
            with serializer.hold("k"):
                holder_ready.set()
                release_holder.wait(2)

        holder = threading.Thread(target=hold_in_thread)
        holder.start()
        assert holder_ready.wait(2)
        waiter = asyncio.create_task(_hold_once(serializer, "k"))
        await asyncio.sleep(0.05)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter

        # Once cancellation has been observed, cleanup must be completed by
        # the acquire worker itself. Blocking this loop keeps asyncio Future
        # callbacks from hiding a lock leak here.
        release_holder.set()
        deadline = time.monotonic() + 2
        while serializer._table and time.monotonic() < deadline:
            time.sleep(0.01)
        holder.join(timeout=2)
        assert not holder.is_alive()
        assert len(serializer._table) == 0

    @pytest.mark.asyncio
    async def test_cancellation_after_acquire_releases(self):
        serializer = AcquireSerializer()

        async def run():
            async with serializer.hold_async("k"):
                await asyncio.sleep(10)

        task = asyncio.create_task(run())
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        async with serializer.hold_async("k"):  # must not hang
            pass
        assert len(serializer._table) == 0

    @pytest.mark.asyncio
    async def test_async_wait_keeps_loop_alive_and_off_default_executor(self):
        serializer = AcquireSerializer()
        loop = asyncio.get_running_loop()

        class ExplodingExecutor(ThreadPoolExecutor):
            def submit(self, *args, **kwargs):
                raise AssertionError("serializer wait used the default executor")

        previous = loop._default_executor
        loop.set_default_executor(ExplodingExecutor())
        try:
            entered = asyncio.Event()

            async def holder():
                async with serializer.hold_async("k"):
                    entered.set()
                    await asyncio.sleep(0.2)

            h = asyncio.create_task(holder())
            await entered.wait()
            w = asyncio.create_task(_hold_once(serializer, "k"))
            for _ in range(5):  # loop stays responsive while w waits
                await asyncio.sleep(0.02)
            assert not w.done()
            await h
            await asyncio.wait_for(w, 2)
        finally:
            if previous is not None:  # fresh loops have no default executor yet
                loop.set_default_executor(previous)

    @pytest.mark.asyncio
    async def test_concurrent_async_waiters_serialize(self):
        serializer = AcquireSerializer()
        active = 0
        max_active = 0

        async def worker():
            nonlocal active, max_active
            async with serializer.hold_async("k"):
                active += 1
                max_active = max(max_active, active)
                await asyncio.sleep(0.01)
                active -= 1

        await asyncio.gather(*[worker() for _ in range(8)])
        assert max_active == 1

    @pytest.mark.asyncio
    async def test_run_on_executor_preserves_request_trace_context(self):
        """run_on_executor must carry request ContextVars into the worker.

        Regression test (#5089): raw ``loop.run_in_executor`` does not copy
        contextvars, so without an explicit ``copy_context`` the worker thread
        reads the trace id bound by ``request_trace_context()`` as unset.
        """
        serializer = AcquireSerializer()
        try:
            with request_trace_context("trace-5089"):
                seen = await serializer.run_on_executor(get_current_trace_id)
            assert seen == "trace-5089"
        finally:
            serializer.close()


async def _hold_once(serializer, key):
    async with serializer.hold_async(key):
        pass


async def _wait_for_table_empty(serializer, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if len(serializer._table) == 0:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("serializer lock table did not drain")


class TestClose:
    def test_close_rejects_new_holders_and_is_idempotent(self):
        serializer = AcquireSerializer()
        serializer.close()
        serializer.close()
        with pytest.raises(RuntimeError, match="closed"):
            with serializer.hold("k"):
                pass

    @pytest.mark.asyncio
    async def test_close_does_not_invalidate_active_critical_section(self):
        serializer = AcquireSerializer()
        async with serializer.hold_async("k"):
            serializer.close()  # must not raise, must not break exit
        # New holders rejected afterwards:
        with pytest.raises(RuntimeError, match="closed"):
            async with serializer.hold_async("k"):
                pass

    @pytest.mark.asyncio
    async def test_executor_shutdown_between_checkout_and_schedule_reclaims_entry(self):
        serializer = AcquireSerializer()
        serializer._executor.shutdown(wait=False, cancel_futures=True)  # simulates close() landing mid-window
        with pytest.raises(RuntimeError, match="closed"):
            async with serializer.hold_async("k"):
                pass
        assert len(serializer._table) == 0

    @pytest.mark.asyncio
    async def test_close_reports_closed_to_queued_waiter(self):
        """A waiter whose queued acquire is cancelled by close() must see
        RuntimeError("closed"), not a spurious CancelledError (#4741)."""
        serializer = AcquireSerializer(max_workers=1)
        blocker = threading.Event()
        with serializer.hold("k"):  # uncontended acquire, safe on the loop
            # Occupy the single worker so the waiter's acquire future stays
            # queued (pending) and is cancelled by close()'s cancel_futures.
            occupied = asyncio.get_running_loop().run_in_executor(serializer.executor, blocker.wait, 5)
            waiter = asyncio.create_task(_hold_once(serializer, "k"))
            await asyncio.sleep(0.1)  # let the waiter check out and queue its acquire
            serializer.close()
            with pytest.raises(RuntimeError, match="closed"):
                await waiter
            blocker.set()
            await occupied
        assert len(serializer._table) == 0

    @pytest.mark.asyncio
    async def test_close_reclaims_caller_cancelled_queued_waiter(self):
        serializer = AcquireSerializer(max_workers=1)
        blocker = threading.Event()
        occupied = asyncio.get_running_loop().run_in_executor(serializer.executor, blocker.wait, 5)
        waiter = asyncio.create_task(_hold_once(serializer, "k"))
        await asyncio.sleep(0.05)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter

        # The acquire was abandoned by its caller but has not started. close()
        # must not strand its checkout when cancelling the executor queue.
        serializer.close()
        blocker.set()
        await occupied
        await _wait_for_table_empty(serializer)
