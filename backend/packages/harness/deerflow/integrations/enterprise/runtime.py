"""Gateway-owned scheduler bridge; no harness imports from app."""

import asyncio

from .providers import EnterpriseError

_scheduler = None
_loop = None


def set_scheduler(callback):
    global _scheduler, _loop
    _scheduler = callback
    _loop = asyncio.get_running_loop() if callback is not None else None


async def schedule_message(**kwargs):
    callback, loop = _scheduler, _loop
    if callback is None or loop is None or loop.is_closed():
        raise EnterpriseError("scheduler_unavailable")
    if asyncio.get_running_loop() is loop:
        return await callback(**kwargs)
    return await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(callback(**kwargs), loop))
