from __future__ import annotations

import asyncio
from concurrent.futures import Future
from typing import Any, cast

import pytest

from deerflow.community.browser_automation.session import BrowserSession


class _ControllablePrivateLoop:
    """Model the cancellation boundary between a caller loop and Playwright's loop."""

    def __init__(self) -> None:
        self.cleanup_future: Future[None] = Future()
        self.run_cancelled = False

    async def run(self, coro: Any) -> None:
        # Current main awaits the private-loop proxy directly, so caller
        # cancellation propagates through wrap_future and cancels cleanup.
        coro.close()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            self.run_cancelled = True
            raise

    def submit(self, coro: Any) -> Future[None]:
        # The fixed close path hands cleanup to the private loop and awaits its
        # concurrent future behind a shield. Closing the coroutine here avoids
        # needing Playwright in this focused lifecycle test.
        coro.close()
        return self.cleanup_future


@pytest.mark.asyncio
async def test_browser_close_caller_cancellation_does_not_cancel_private_cleanup() -> None:
    loop = _ControllablePrivateLoop()
    session = BrowserSession(
        cast(Any, loop),
        headless=True,
        timeout_ms=1000,
        viewport={"width": 1000, "height": 500},
    )

    close_task = asyncio.create_task(session.close())
    await asyncio.sleep(0)

    close_task.cancel("caller stopped")
    with pytest.raises(asyncio.CancelledError):
        await close_task

    # Once BrowserSessionManager has removed this session from its registry,
    # the private-loop close is the last owner of the Chromium teardown. Caller
    # cancellation must not cancel that cleanup and orphan the browser process.
    assert not loop.run_cancelled
    assert not loop.cleanup_future.cancelled()

    loop.cleanup_future.set_result(None)
    await asyncio.sleep(0)
