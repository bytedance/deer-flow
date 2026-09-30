from __future__ import annotations

import asyncio
import threading

import pytest

from deerflow.sandbox.lease import SandboxLeaseManager
from deerflow.sandbox.sandbox_provider import SandboxProvider


class _BlockingReleaseProvider(SandboxProvider):
    def __init__(self) -> None:
        self._sandboxes: dict[str, object] = {
            "old": object(),
            "new": object(),
        }
        self.release_started = threading.Event()
        self.allow_release = threading.Event()
        self.release_finished = threading.Event()

    def acquire(self, thread_id=None, *, user_id=None) -> str:
        return "new"

    def get(self, sandbox_id):
        return self._sandboxes.get(sandbox_id)

    def release(self, sandbox_id) -> None:
        if sandbox_id == "old":
            self.release_started.set()
            assert self.allow_release.wait(timeout=1)
        self._sandboxes.pop(sandbox_id, None)
        self.release_finished.set()


@pytest.mark.anyio
async def test_cancelled_async_rebind_holds_serializer_until_previous_release_finishes() -> None:
    provider = _BlockingReleaseProvider()
    manager = SandboxLeaseManager(provider)
    manager.retain(
        "owner",
        "old",
        thread_id="thread-1",
        user_id="user-1",
    )

    rebind_task = asyncio.create_task(
        manager.retain_async(
            "owner",
            "new",
            thread_id="thread-1",
            user_id="user-1",
        )
    )
    contender: threading.Thread | None = None

    try:
        assert await asyncio.to_thread(provider.release_started.wait, 1)

        rebind_task.cancel("first cancellation")
        await asyncio.sleep(0)
        rebind_task.cancel("second cancellation")
        await asyncio.sleep(0)

        # Cancelling the awaiter must not release the per-thread serializer
        # while the blocking provider release is still running in its worker.
        assert not rebind_task.done()

        contender_done = threading.Event()

        def retain_next_owner() -> None:
            manager.retain(
                "next",
                "new",
                thread_id="thread-1",
                user_id="user-1",
            )
            contender_done.set()

        contender = threading.Thread(target=retain_next_owner)
        contender.start()
        contender.join(timeout=0.05)
        assert contender.is_alive()
        assert not contender_done.is_set()

        provider.allow_release.set()
        with pytest.raises(asyncio.CancelledError) as exc_info:
            await rebind_task
        assert exc_info.value.args == ("first cancellation",)

        contender.join(timeout=1)
        assert not contender.is_alive()
        assert contender_done.is_set()
        assert provider.release_finished.is_set()
        assert manager.binding_for("owner") == "new"
        assert manager.binding_for("next") == "new"
    finally:
        provider.allow_release.set()
        if contender is not None:
            contender.join(timeout=1)
        if not rebind_task.done():
            rebind_task.cancel()
            try:
                await rebind_task
            except asyncio.CancelledError:
                pass
        manager.close()
