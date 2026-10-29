from __future__ import annotations

import asyncio
import threading
from concurrent.futures import Future

import pytest

import deerflow.extensions.notify as notify_module
from deerflow.extensions.notify import (
    _pending_dispatches,
    dispatch_system_model_observation,
    drain_extension_notify_dispatches,
    reset_extension_notify_loop,
    set_extension_notify_loop,
    suspend_extension_system_observations,
)


@pytest.mark.asyncio
async def test_extension_notify_shutdown_drains_pending_dispatch_across_repeated_cancellation() -> None:
    reset_extension_notify_loop()
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
        reset_extension_notify_loop()

    assert pending not in _pending_dispatches


@pytest.mark.asyncio
async def test_extension_notify_shutdown_drain_is_bounded() -> None:
    reset_extension_notify_loop()
    pending: Future[None] = Future()
    _pending_dispatches.add(pending)
    pending.add_done_callback(_pending_dispatches.discard)

    try:
        await asyncio.wait_for(
            drain_extension_notify_dispatches(timeout=0.01),
            timeout=0.5,
        )
    finally:
        if not pending.done():
            pending.cancel()
        reset_extension_notify_loop()


def test_shutdown_snapshot_includes_dispatch_already_admitted(monkeypatch) -> None:
    """Shutdown must wait for a dispatch that passed admission before suspension."""
    reset_extension_notify_loop()
    submit_entered = threading.Event()
    release_submit = threading.Event()
    suspend_entered = threading.Event()
    dispatch_done = threading.Event()
    drain_done = threading.Event()
    pending: Future[None] = Future()

    class _Loop:
        @staticmethod
        def is_running() -> bool:
            return True

    def _submit(_coro, _loop):
        submit_entered.set()
        if not release_submit.wait(timeout=2):
            raise TimeoutError("test did not release the simulated submission")
        return pending

    original_suspend = suspend_extension_system_observations

    def _tracked_suspend() -> None:
        suspend_entered.set()
        original_suspend()

    monkeypatch.setattr(notify_module.asyncio, "run_coroutine_threadsafe", _submit)
    monkeypatch.setattr(notify_module, "suspend_extension_system_observations", _tracked_suspend)
    set_extension_notify_loop(_Loop())

    async def _observation() -> None:
        return None

    def _dispatch() -> None:
        coro = _observation()
        try:
            accepted = dispatch_system_model_observation(coro, "shutdown-race")
            if accepted:
                # The fake submitter deliberately does not schedule this coroutine.
                coro.close()
        finally:
            dispatch_done.set()

    def _drain() -> None:
        try:
            asyncio.run(drain_extension_notify_dispatches(timeout=1))
        finally:
            drain_done.set()

    dispatcher = threading.Thread(target=_dispatch, daemon=True)
    shutdown = threading.Thread(target=_drain, daemon=True)
    try:
        dispatcher.start()
        assert submit_entered.wait(timeout=1)
        shutdown.start()
        assert suspend_entered.wait(timeout=1)
        assert not drain_done.wait(timeout=0.05), "shutdown returned while an admitted dispatch had not been registered"

        release_submit.set()
        assert dispatch_done.wait(timeout=1)
        assert pending in _pending_dispatches
        pending.set_result(None)
        assert drain_done.wait(timeout=1)
        assert pending not in _pending_dispatches
    finally:
        release_submit.set()
        if not pending.done():
            pending.set_result(None)
        dispatcher.join(timeout=1)
        shutdown.join(timeout=1)
        reset_extension_notify_loop()

    assert not dispatcher.is_alive()
    assert not shutdown.is_alive()
