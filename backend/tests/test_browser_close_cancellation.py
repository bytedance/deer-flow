from __future__ import annotations

import asyncio
from concurrent.futures import Future
from typing import Any, cast

import pytest

from deerflow.community.browser_automation.session import BrowserSession, BrowserSessionManager


class _ControllablePrivateLoop:
    """Model the cancellation boundary between a caller loop and Playwright's loop."""

    def __init__(self) -> None:
        self.cleanup_futures: list[Future[None]] = []
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
        cleanup_future: Future[None] = Future()
        self.cleanup_futures.append(cleanup_future)
        return cleanup_future


def _session(loop: _ControllablePrivateLoop) -> BrowserSession:
    return BrowserSession(
        cast(Any, loop),
        headless=True,
        timeout_ms=1000,
        viewport={"width": 1000, "height": 500},
    )


@pytest.mark.asyncio
async def test_browser_close_caller_cancellation_does_not_cancel_private_cleanup() -> None:
    loop = _ControllablePrivateLoop()
    session = _session(loop)

    close_task = asyncio.create_task(session.close())
    await asyncio.sleep(0)

    close_task.cancel("caller stopped")
    with pytest.raises(asyncio.CancelledError):
        await close_task

    assert not loop.run_cancelled
    assert len(loop.cleanup_futures) == 1
    assert not loop.cleanup_futures[0].cancelled()

    loop.cleanup_futures[0].set_result(None)
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_manager_close_session_cancellation_keeps_detached_cleanup_running() -> None:
    loop = _ControllablePrivateLoop()
    session = _session(loop)
    manager = BrowserSessionManager()
    manager._sessions["thread-a"] = session
    manager._last_used["thread-a"] = 0.0

    close_task = asyncio.create_task(manager.close_session("thread-a"))
    await asyncio.sleep(0)

    assert "thread-a" not in manager._sessions
    assert len(loop.cleanup_futures) == 1

    close_task.cancel("request stopped")
    with pytest.raises(asyncio.CancelledError):
        await close_task

    assert not loop.cleanup_futures[0].cancelled()
    loop.cleanup_futures[0].set_result(None)
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_manager_close_all_submits_every_cleanup_before_cancellable_wait() -> None:
    loop = _ControllablePrivateLoop()
    manager = BrowserSessionManager()
    manager._sessions.update({"thread-a": _session(loop), "thread-b": _session(loop)})
    manager._last_used.update({"thread-a": 0.0, "thread-b": 0.0})

    close_task = asyncio.create_task(manager.close_all_sessions())
    await asyncio.sleep(0)

    assert manager._sessions == {}
    assert len(loop.cleanup_futures) == 2

    close_task.cancel("shutdown interrupted")
    with pytest.raises(asyncio.CancelledError):
        await close_task

    assert all(not future.cancelled() for future in loop.cleanup_futures)
    for future in loop.cleanup_futures:
        future.set_result(None)
    await asyncio.sleep(0)
