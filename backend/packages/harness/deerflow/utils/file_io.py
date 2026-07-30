"""Dedicated async offload helper for filesystem work."""

from __future__ import annotations

import asyncio
import atexit
import contextvars
import functools
import logging
import os
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

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


def _shutdown_file_io_executor() -> None:
    _FILE_IO_EXECUTOR.shutdown(wait=False, cancel_futures=True)


atexit.register(_shutdown_file_io_executor)


async def run_file_io[**P, T](func: Callable[P, T], /, *args: P.args, **kwargs: P.kwargs) -> T:
    """Run blocking filesystem-oriented work on the dedicated file IO pool.

    ``asyncio.to_thread`` copies ``ContextVar`` values automatically; raw
    ``loop.run_in_executor`` does not. Copy the current context explicitly so
    user-scoped helpers such as ``get_effective_user_id()`` keep working inside
    the worker thread.
    """
    loop = asyncio.get_running_loop()
    ctx = contextvars.copy_context()
    call = functools.partial(func, *args, **kwargs)
    return await loop.run_in_executor(_FILE_IO_EXECUTOR, ctx.run, call)
