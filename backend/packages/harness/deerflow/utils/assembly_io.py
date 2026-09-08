"""Dedicated async offload helper for agent/tool assembly work."""

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


_ASSEMBLY_EXECUTOR = ThreadPoolExecutor(max_workers=_default_assembly_workers(), thread_name_prefix="assembly")


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
    loop = asyncio.get_running_loop()
    ctx = contextvars.copy_context()
    call = functools.partial(func, *args, **kwargs)
    return await loop.run_in_executor(_ASSEMBLY_EXECUTOR, ctx.run, call)
