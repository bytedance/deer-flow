from __future__ import annotations

import asyncio
from concurrent.futures import Future

import pytest

from deerflow.extensions.notify import _pending_dispatches, drain_extension_notify_dispatches


@pytest.mark.asyncio
async def test_extension_notify_shutdown_drains_pending_dispatch_across_repeated_cancellation() -> None:
    pending: Future[None] = Future()
    _pending_dispatches.add(pending)
    pending.add_done_callback(_pending_dispatches.discard)

    task = asyncio.create_task(drain_extension_notify_dispatches())
    try:
        await asyncio.sleep(0)
        task.cancel()
        for _ in range(5):
            await asyncio.sleep(0)
        assert not task.done()

        task.cancel()
        for _ in range(5):
            await asyncio.sleep(0)
        assert not task.done()

        pending.set_result(None)
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        if not pending.done():
            pending.set_result(None)
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    assert pending not in _pending_dispatches
