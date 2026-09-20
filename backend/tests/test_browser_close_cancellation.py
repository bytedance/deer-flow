from __future__ import annotations

import asyncio
from concurrent.futures import Future
from typing import Any, cast

import pytest

import deerflow.community.browser_automation.session as session_module
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


class _FailingPrivateLoop(_ControllablePrivateLoop):
    def __init__(self) -> None:
        super().__init__()
        self.submitted_coro: Any | None = None

    def submit(self, coro: Any) -> Future[None]:
        self.submitted_coro = coro
        raise RuntimeError("private loop closed")


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


def test_submit_close_closes_coroutine_when_submission_fails() -> None:
    loop = _FailingPrivateLoop()
    session = _session(loop)

    with pytest.raises(RuntimeError, match="private loop closed"):
        session._submit_close()

    assert loop.submitted_coro is not None
    assert loop.submitted_coro.cr_frame is None


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


@pytest.mark.asyncio
async def test_manager_close_all_continues_after_sync_submission_failure() -> None:
    failing_loop = _FailingPrivateLoop()
    healthy_loop = _ControllablePrivateLoop()
    manager = BrowserSessionManager()
    manager._sessions.update({"broken": _session(failing_loop), "healthy": _session(healthy_loop)})
    manager._last_used.update({"broken": 0.0, "healthy": 0.0})

    close_task = asyncio.create_task(manager.close_all_sessions())
    await asyncio.sleep(0)

    assert manager._sessions == {}
    assert len(healthy_loop.cleanup_futures) == 1
    assert failing_loop.submitted_coro is not None
    assert failing_loop.submitted_coro.cr_frame is None

    healthy_loop.cleanup_futures[0].set_result(None)
    assert await close_task == 2


@pytest.mark.asyncio
async def test_manager_close_all_consumes_group_failure_after_caller_cancellation(monkeypatch: pytest.MonkeyPatch) -> None:
    loop = _ControllablePrivateLoop()
    manager = BrowserSessionManager()
    manager._sessions["thread-a"] = _session(loop)
    manager._last_used["thread-a"] = 0.0

    original_gather = asyncio.gather
    original_consume = session_module._consume_future_exception
    group_future: asyncio.Future[Any] | None = None
    consumed: list[asyncio.Future[Any]] = []

    def tracking_gather(*aws: Any, **kwargs: Any) -> asyncio.Future[Any]:
        nonlocal group_future
        group_future = cast(asyncio.Future[Any], original_gather(*aws, **kwargs))
        return group_future

    def recording_consume(future: asyncio.Future[Any]) -> None:
        consumed.append(future)
        original_consume(future)

    monkeypatch.setattr(asyncio, "gather", tracking_gather)
    monkeypatch.setattr(session_module, "_consume_future_exception", recording_consume)

    close_task = asyncio.create_task(manager.close_all_sessions())
    await asyncio.sleep(0)
    assert group_future is not None

    close_task.cancel("shutdown interrupted")
    with pytest.raises(asyncio.CancelledError):
        await close_task

    loop.cleanup_futures[0].set_exception(RuntimeError("teardown failed"))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert group_future.done()
    assert group_future in consumed
