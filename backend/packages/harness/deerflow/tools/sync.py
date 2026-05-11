"""Utilities for invoking async tools from synchronous agent paths."""

import asyncio
import atexit
import concurrent.futures
import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

# Shared thread pool for sync tool invocation in async environments.
_SYNC_TOOL_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=10, thread_name_prefix="tool-sync")

atexit.register(lambda: _SYNC_TOOL_EXECUTOR.shutdown(wait=False))


def make_sync_tool_wrapper(coro: Callable[..., Any], tool_name: str) -> Callable[..., Any]:
    """Build a synchronous wrapper for an asynchronous tool coroutine."""

    def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        try:
            if loop is not None and loop.is_running():
                future = _SYNC_TOOL_EXECUTOR.submit(asyncio.run, coro(*args, **kwargs))
                return future.result()
            return asyncio.run(coro(*args, **kwargs))
        except Exception as e:
            logger.error("Error invoking tool %r via sync wrapper: %s", tool_name, e, exc_info=True)
            raise

    return sync_wrapper
