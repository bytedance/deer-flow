"""Bounded, process-wide offload for potentially slow context injection."""

from __future__ import annotations

import asyncio
import atexit
import contextvars
import logging
import os
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)


class ContextInjectionBusyError(RuntimeError):
    """All context workers are occupied; no additional work was submitted."""


def _default_context_workers() -> int:
    raw = os.getenv("DEER_FLOW_CONTEXT_WORKERS")
    if raw:
        try:
            workers = int(raw)
            if workers > 0:
                return workers
        except ValueError:
            pass
        logger.warning("Invalid DEER_FLOW_CONTEXT_WORKERS value; using default context worker count")
    return 4


class _ContextInjectionPool:
    """Bound unfinished submissions across all event loops in this process."""

    def __init__(self, max_workers: int):
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="context-injection")
        self._slots = threading.BoundedSemaphore(max_workers)

    async def run[**P, T](self, func: Callable[P, T], /, *args: P.args, **kwargs: P.kwargs) -> T:
        loop = asyncio.get_running_loop()
        # Never wait for admission on a worker or accumulate an unbounded queue.
        # A threading primitive also shares the limit with subagent/embedded loops.
        if not self._slots.acquire(blocking=False):
            raise ContextInjectionBusyError("Context injection pool saturated")
        try:
            context = contextvars.copy_context()
            future = self._executor.submit(context.run, func, *args, **kwargs)
        except BaseException:
            self._slots.release()
            raise

        # Own capacity through the concurrent future, not the awaiter: cancelling
        # a running submission does not stop its thread. This callback also runs
        # when queued work is cancelled, or the submitting event loop has closed.
        future.add_done_callback(lambda _future: self._slots.release())
        return await asyncio.wrap_future(future, loop=loop)

    def shutdown(self, *, wait: bool = False) -> None:
        # Running synchronous calls still require their own downstream deadlines.
        self._executor.shutdown(wait=wait, cancel_futures=True)


_CONTEXT_POOL = _ContextInjectionPool(_default_context_workers())
atexit.register(_CONTEXT_POOL.shutdown)


async def run_context_injection[**P, T](func: Callable[P, T], /, *args: P.args, **kwargs: P.kwargs) -> T:
    """Preserve request context while isolating memory/date injection work."""
    return await _CONTEXT_POOL.run(func, *args, **kwargs)
