from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import TypeVar

from deerflow.utils.file_io import await_drained

T = TypeVar("T")


async def wait_for_task_until(  # noqa: UP047
    task: asyncio.Future[T], *, deadline: float
) -> bool:
    """Wait through repeated caller cancellation without cancelling task."""
    loop = asyncio.get_running_loop()
    while not task.done():
        remaining = deadline - loop.time()
        if remaining <= 0:
            return False
        try:
            done, _ = await asyncio.wait({task}, timeout=remaining)
        except asyncio.CancelledError:
            continue
        if task in done:
            return True
    return True


@asynccontextmanager
async def drained_async_context[T](
    manager: AbstractAsyncContextManager[T],
) -> AsyncIterator[T]:
    """Keep an entered async context owned until its exit fully settles."""
    value = await manager.__aenter__()
    try:
        yield value
    except BaseException as exc:
        suppressed = await await_drained(manager.__aexit__(type(exc), exc, exc.__traceback__))
        if not suppressed:
            raise
    else:
        await await_drained(manager.__aexit__(None, None, None))
