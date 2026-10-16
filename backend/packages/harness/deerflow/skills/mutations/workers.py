"""Bounded off-loop work. Caller cancellation never releases a worker's locks."""

from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context

from deerflow_extension_api.host_capabilities import HostCapabilityError


class MutationWorkers:
    def __init__(self, *, limit: int = 4):
        self._slots = threading.BoundedSemaphore(limit)
        self._executor = ThreadPoolExecutor(max_workers=limit, thread_name_prefix="skill-mutation")
        self._tasks: set[asyncio.Future] = set()
        self._closed = False

    async def run(self, work):
        if self._closed:
            raise HostCapabilityError("UNAVAILABLE")
        if not self._slots.acquire(blocking=False):
            raise HostCapabilityError("BUSY", retry_after=1)
        cancelled = threading.Event()

        def check():
            # Call during admission/lock retries, never after PREPARED.
            if cancelled.is_set():
                raise HostCapabilityError("CANCELLED")

        def invoke():
            try:
                check()
                return work(check)
            finally:
                self._slots.release()

        context = copy_context()
        try:
            task = asyncio.get_running_loop().run_in_executor(self._executor, context.run, invoke)
        except BaseException:
            self._slots.release()
            raise
        self._tasks.add(task)

        def finished(done):
            self._tasks.discard(done)
            if not done.cancelled():
                done.exception()  # Detached cancellations still consume failures.

        task.add_done_callback(finished)
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    async def close(self):
        from deerflow.utils.file_io import await_drained

        self._closed = True
        if self._tasks:
            await await_drained(asyncio.gather(*tuple(self._tasks), return_exceptions=True))
        # All accepted functions have completed. Signal idle threads to exit
        # without making shutdown depend on the shared default executor.
        self._executor.shutdown(wait=False, cancel_futures=True)
