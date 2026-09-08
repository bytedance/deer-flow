"""Dedicated async offload helper for agent/tool assembly work."""

from __future__ import annotations

import asyncio
import atexit
import contextvars
import functools
import logging
import os
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)


def _default_assembly_workers() -> int:
    raw = os.getenv("DEER_FLOW_ASSEMBLY_WORKERS")
    if raw:
        try:
            workers = int(raw)
            if workers > 0:
                return workers
        except ValueError:
            pass
        logger.warning("Invalid DEER_FLOW_ASSEMBLY_WORKERS value; using default assembly worker count")
    return 8


_ASSEMBLY_WORKERS = _default_assembly_workers()
_ASSEMBLY_EXECUTOR = ThreadPoolExecutor(max_workers=_ASSEMBLY_WORKERS, thread_name_prefix="assembly")

# Pending (submitted, unfinished) assembly count. Increments on the event loop
# before dispatch and decrements from the future's done callback; guarded for
# multi-loop test environments.
_pending_assemblies = 0
_pending_lock = threading.Lock()
_last_starvation_log = 0.0
_STARVATION_LOG_INTERVAL_SECONDS = 30.0


def _shutdown_assembly_executor() -> None:
    _ASSEMBLY_EXECUTOR.shutdown(wait=False, cancel_futures=True)


atexit.register(_shutdown_assembly_executor)


async def run_assembly[**P, T](func: Callable[P, T], /, *args: P.args, **kwargs: P.kwargs) -> T:
    """Run blocking agent/tool assembly on the dedicated assembly pool.

    Tool and agent assembly re-enters ``get_available_tools()``, which may
    block for the full MCP discovery duration (a slow or hung stdio server
    parks a worker until the MCP timeout). Dispatching those hops onto the
    loop's **default** executor lets a few parked assemblies queue every other
    ``asyncio.to_thread`` / ``run_in_executor(None, ...)`` caller behind them
    and reintroduce a loop-wide stall through a different door; this pool
    keeps the capacity explicit and bounds the blast radius, mirroring
    ``utils/file_io.py`` and ``tools/sync.py``.

    ``asyncio.to_thread`` copies ``ContextVar`` values automatically; raw
    ``loop.run_in_executor`` does not. Copy the current context explicitly so
    agent-assembly helpers such as ``bind_agent_build_extensions`` keep
    working inside the worker thread.
    """
    global _pending_assemblies, _last_starvation_log

    with _pending_lock:
        _pending_assemblies += 1
        pending = _pending_assemblies
        # Saturation is invisible otherwise: workers parked on a hung MCP
        # server leave later assemblies queued indefinitely while the loop
        # stays healthy. Warn at most once per interval while starved.
        warn = pending > _ASSEMBLY_WORKERS and (time.monotonic() - _last_starvation_log) > _STARVATION_LOG_INTERVAL_SECONDS
        if warn:
            _last_starvation_log = time.monotonic()
    if warn:
        logger.warning(
            "Assembly pool saturated: %d pending assemblies on %d workers; agent assembly is starved (likely a hung MCP server)",
            pending,
            _ASSEMBLY_WORKERS,
        )

    loop = asyncio.get_running_loop()
    ctx = contextvars.copy_context()
    call = functools.partial(func, *args, **kwargs)
    future = loop.run_in_executor(_ASSEMBLY_EXECUTOR, ctx.run, call)

    def _release(_done: object) -> None:
        global _pending_assemblies
        with _pending_lock:
            _pending_assemblies -= 1

    future.add_done_callback(_release)
    return await future
