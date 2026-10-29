from __future__ import annotations

import asyncio
import threading

import pytest

from deerflow.sandbox.sandbox import Sandbox
from deerflow.sandbox.sandbox_provider import SandboxProvider
from deerflow.sandbox.tools import _rollback_failed_sandbox_lookup_async


class _BlockingRollbackProvider(SandboxProvider):
    def __init__(self) -> None:
        self.started = threading.Event()
        self.allow = threading.Event()
        self.released: list[str] = []

    def acquire(self, thread_id: str | None = None, *, user_id: str | None = None) -> str:
        raise AssertionError("not used")

    def get(self, sandbox_id: str) -> Sandbox | None:
        return None

    def release(self, sandbox_id: str) -> None:
        self.started.set()
        assert self.allow.wait(timeout=2)
        self.released.append(sandbox_id)


@pytest.mark.anyio
async def test_async_rollback_drains_direct_release_across_repeated_cancellation() -> None:
    provider = _BlockingRollbackProvider()
    task = asyncio.create_task(_rollback_failed_sandbox_lookup_async(provider, "rollback-sandbox", None))
    try:
        assert await asyncio.to_thread(provider.started.wait, 2)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()

        provider.allow.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        provider.allow.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    assert provider.released == ["rollback-sandbox"]
