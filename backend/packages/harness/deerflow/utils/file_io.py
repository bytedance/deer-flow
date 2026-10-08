"""Dedicated async offload helper for filesystem work."""

from __future__ import annotations

import asyncio
import atexit
import contextvars
import functools
import logging
import os
import threading
from collections.abc import Callable, Coroutine
from concurrent.futures import ThreadPoolExecutor
from typing import Any

logger = logging.getLogger(__name__)


def _default_file_io_workers() -> int:
    raw = os.getenv("DEER_FLOW_FILE_IO_WORKERS")
    if raw:
        try:
            workers = int(raw)
            if workers > 0:
                return workers
        except ValueError:
            pass
        logger.warning("Invalid DEER_FLOW_FILE_IO_WORKERS value; using default file IO worker count")
    return min(32, (os.cpu_count() or 1) + 4)


_FILE_IO_EXECUTOR = ThreadPoolExecutor(max_workers=_default_file_io_workers(), thread_name_prefix="file-io")

# Marks the threads of ``_FILE_IO_EXECUTOR`` so ``run_file_io`` can detect
# (and run inline on) re-entrant calls.
_FILE_IO_WORKER = threading.local()


def _shutdown_file_io_executor() -> None:
    _FILE_IO_EXECUTOR.shutdown(wait=False, cancel_futures=True)


atexit.register(_shutdown_file_io_executor)


def _worker_call(call: Callable[[], Any]) -> Any:
    """Run *call* inside a file-IO worker, marking the thread as such.

    The marker makes ``run_file_io`` re-entrant: a nested offload issued from
    code already running in a worker (e.g. ``asyncio.run`` inside a worker
    body) runs inline instead of submitting to the same bounded executor,
    which would deadlock once every worker is busy — deterministically so
    with a single configured worker.
    """
    _FILE_IO_WORKER.active = True
    try:
        return call()
    finally:
        _FILE_IO_WORKER.active = False


async def run_file_io[**P, T](func: Callable[P, T], /, *args: P.args, **kwargs: P.kwargs) -> T:
    """Run blocking filesystem-oriented work on the dedicated file IO pool.

    ``asyncio.to_thread`` copies ``ContextVar`` values automatically; raw
    ``loop.run_in_executor`` does not. Copy the current context explicitly so
    user-scoped helpers such as ``get_effective_user_id()`` keep working inside
    the worker thread.

    Re-entrant: called from inside a file-IO worker thread, *func* runs inline
    rather than submitting to the pool again — the pool is bounded, so a
    nested submit can deadlock when every worker is already busy.
    """
    call = functools.partial(func, *args, **kwargs)
    if getattr(_FILE_IO_WORKER, "active", False):
        return call()
    loop = asyncio.get_running_loop()
    ctx = contextvars.copy_context()
    return await loop.run_in_executor(_FILE_IO_EXECUTOR, ctx.run, _worker_call, call)


async def await_drained[T](coro: Coroutine[Any, Any, T]) -> T:
    """Await *coro* to completion even when the caller is cancelled meanwhile.

    A locked database transaction that awaits a filesystem offload must not
    release its row lock over in-flight worker work: cancelling the ``await``
    abandons the offload's thread, not the work, so the lock could unwind
    while the worker is still mutating files (e.g. a cancelled purge rolling
    back and unlocking while its unlink worker is still running — a
    concurrent restore could then validate bytes the abandoned worker is
    about to delete). This shield+drain delivers the cancellation only after
    *coro* has fully finished, so the transaction resolves coherently first.
    The inner outcome is retrieved before re-raising (no "exception never
    retrieved" noise).
    """
    task = asyncio.ensure_future(coro)
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        # Drain: the shielded inner task keeps running; absorb repeated
        # cancellation until it finishes, then let the cancellation through.
        while not task.done():
            try:
                await asyncio.wait({task})
            except asyncio.CancelledError:
                continue
        if not task.cancelled():
            task.exception()
        raise
