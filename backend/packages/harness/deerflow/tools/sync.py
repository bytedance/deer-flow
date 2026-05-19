"""Utilities for invoking async tools from synchronous agent paths."""

import asyncio
import atexit
import concurrent.futures
import contextvars
import functools
import logging
from collections.abc import Callable
from typing import Any, get_type_hints

from langchain_core.runnables import RunnableConfig

logger = logging.getLogger(__name__)

# Shared thread pool for sync tool invocation in async environments.
_SYNC_TOOL_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=10, thread_name_prefix="tool-sync")

atexit.register(lambda: _SYNC_TOOL_EXECUTOR.shutdown(wait=False))


def _get_runnable_config_param(func: Callable[..., Any]) -> str | None:
    """Return the coroutine parameter that expects LangChain RunnableConfig."""
    if isinstance(func, functools.partial):
        func = func.func

    try:
        type_hints = get_type_hints(func)
    except Exception:
        return None

    for name, type_ in type_hints.items():
        if type_ is RunnableConfig:
            return name
    return None


def make_sync_tool_wrapper(coro: Callable[..., Any], tool_name: str) -> Callable[..., Any]:
    """Build a synchronous wrapper for an asynchronous tool coroutine.

    Args:
        coro: Async callable backing a LangChain tool.
        tool_name: Tool name used in error logs.

    Returns:
        A sync callable suitable for ``BaseTool.func``.

    Notes:
        If ``coro`` declares a ``RunnableConfig`` parameter, this wrapper
        exposes ``config: RunnableConfig`` so LangChain can inject runtime
        config and then forwards it to the coroutine's detected config
        parameter. This covers DeerFlow's current config-sensitive tools, such
        as ``invoke_acp_agent``.

        This wrapper intentionally does not synthesize a dynamic function
        signature. A future async tool with a normal user-facing argument named
        ``config`` and a separate ``RunnableConfig`` parameter named something
        else, such as ``run_config``, may collide with LangChain's injected
        ``config`` argument. Rename that user-facing field or extend this
        helper before using that signature.
    """
    config_param = _get_runnable_config_param(coro)

    def run_coroutine(*args: Any, **kwargs: Any) -> Any:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        try:
            if loop is not None and loop.is_running():
                context = contextvars.copy_context()
                future = _SYNC_TOOL_EXECUTOR.submit(context.run, lambda: asyncio.run(coro(*args, **kwargs)))
                return future.result()
            return asyncio.run(coro(*args, **kwargs))
        except Exception as e:
            logger.error("Error invoking tool %r via sync wrapper: %s", tool_name, e, exc_info=True)
            raise

    if config_param:

        def sync_wrapper(*args: Any, config: RunnableConfig = None, **kwargs: Any) -> Any:
            if config is not None or config_param not in kwargs:
                kwargs[config_param] = config
            return run_coroutine(*args, **kwargs)

        return sync_wrapper

    def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
        return run_coroutine(*args, **kwargs)

    return sync_wrapper
