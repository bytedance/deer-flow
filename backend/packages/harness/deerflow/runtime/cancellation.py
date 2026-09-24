from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import TypeVar

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


async def _drain_context_exit(awaitable: Awaitable[bool | None]) -> bool | None:
    """Drain an async context exit without hiding a teardown failure.

    If caller cancellation arrives while __aexit__ is running, keep waiting
    through repeated cancellation. A later exit failure replaces/chains the
    cancellation, matching normal context-manager semantics; only a successful
    exit re-raises the caller cancellation.
    """
    task = asyncio.ensure_future(awaitable)
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        while not task.done():
            try:
                await asyncio.wait({task})
            except asyncio.CancelledError:
                continue
        task.result()
        raise


@asynccontextmanager
async def drained_async_context[T](
    manager: AbstractAsyncContextManager[T],
) -> AsyncIterator[T]:
    """Keep an entered async context owned until its exit fully settles."""
    value = await manager.__aenter__()
    try:
        yield value
    except BaseException as exc:
        suppressed = await _drain_context_exit(manager.__aexit__(type(exc), exc, exc.__traceback__))
        if not suppressed:
            raise
    else:
        await _drain_context_exit(manager.__aexit__(None, None, None))
