from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor


def test_default_executor_saturation_keeps_work_queued():
    async def scenario():
        loop = asyncio.get_running_loop()
        executor = ThreadPoolExecutor(max_workers=1)
        loop.set_default_executor(executor)
        release = threading.Event()
        first_started = asyncio.Event()
        second_started = asyncio.Event()

        def blocker():
            loop.call_soon_threadsafe(first_started.set)
            release.wait()

        try:
            first = asyncio.create_task(asyncio.to_thread(blocker))
            await first_started.wait()

            second = asyncio.create_task(asyncio.to_thread(loop.call_soon_threadsafe, second_started.set))
            await asyncio.sleep(0)
            assert not second_started.is_set()

            release.set()
            await asyncio.gather(first, second)
            assert second_started.is_set()
        finally:
            release.set()
            executor.shutdown(wait=True, cancel_futures=True)

    asyncio.run(scenario())


def test_waiter_timeout_does_not_stop_started_sync_work():
    async def scenario():
        loop = asyncio.get_running_loop()
        executor = ThreadPoolExecutor(max_workers=1)
        loop.set_default_executor(executor)
        release = threading.Event()
        started = asyncio.Event()
        finished = threading.Event()
        sentinel_started = asyncio.Event()

        def blocker():
            loop.call_soon_threadsafe(started.set)
            release.wait()
            finished.set()

        try:
            running = asyncio.create_task(asyncio.to_thread(blocker))
            await started.wait()

            try:
                await asyncio.wait_for(running, timeout=0)
            except TimeoutError:
                pass

            assert running.cancelled()
            assert not finished.is_set()

            sentinel = asyncio.create_task(
                asyncio.to_thread(loop.call_soon_threadsafe, sentinel_started.set)
            )
            await asyncio.sleep(0)
            assert not sentinel_started.is_set()

            release.set()
            await sentinel
            assert finished.is_set()
            assert sentinel_started.is_set()
        finally:
            release.set()
            executor.shutdown(wait=True, cancel_futures=True)

    asyncio.run(scenario())


def test_dedicated_file_io_pool_runs_while_default_executor_is_saturated(monkeypatch):
    async def scenario():
        from deerflow.utils import file_io

        loop = asyncio.get_running_loop()
        default_executor = ThreadPoolExecutor(max_workers=1)
        dedicated_executor = ThreadPoolExecutor(max_workers=1)
        monkeypatch.setattr(file_io, "_FILE_IO_EXECUTOR", dedicated_executor)
        loop.set_default_executor(default_executor)
        release = threading.Event()
        default_started = asyncio.Event()
        dedicated_started = asyncio.Event()

        def default_blocker():
            loop.call_soon_threadsafe(default_started.set)
            release.wait()

        def dedicated_work():
            loop.call_soon_threadsafe(dedicated_started.set)
            return "file-io"

        try:
            default_task = asyncio.create_task(asyncio.to_thread(default_blocker))
            await default_started.wait()

            file_task = asyncio.create_task(file_io.run_file_io(dedicated_work))
            await dedicated_started.wait()
            assert await file_task == "file-io"

            release.set()
            await default_task
        finally:
            release.set()
            dedicated_executor.shutdown(wait=True, cancel_futures=True)
            default_executor.shutdown(wait=True, cancel_futures=True)

    asyncio.run(scenario())
