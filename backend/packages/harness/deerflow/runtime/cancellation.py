from __future__ import annotations

import asyncio
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
