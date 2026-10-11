from __future__ import annotations

import asyncio
import threading

import pytest
from langgraph.runtime import Runtime

from deerflow.sandbox.middleware import SandboxMiddleware
from deerflow.sandbox.sandbox import Sandbox
from deerflow.sandbox.sandbox_provider import (
    SandboxProvider,
    reset_sandbox_provider,
    set_sandbox_provider,
)


class _BlockingReleaseProvider(SandboxProvider):
    def __init__(self) -> None:
        self.release_started = threading.Event()
        self.allow_release = threading.Event()
        self.released: list[str] = []

    def acquire(self, thread_id: str | None = None, *, user_id: str | None = None) -> str:
        raise AssertionError("acquire is not part of this regression")

    def get(self, sandbox_id: str) -> Sandbox | None:
        return None

    def release(self, sandbox_id: str) -> None:
        self.release_started.set()
        assert self.allow_release.wait(timeout=2)
        self.released.append(sandbox_id)


@pytest.mark.anyio
async def test_aafter_agent_drains_direct_release_across_repeated_cancellation() -> None:
    provider = _BlockingReleaseProvider()
    set_sandbox_provider(provider)
    task: asyncio.Task[dict | None] | None = None
    try:
        task = asyncio.create_task(
            SandboxMiddleware().aafter_agent(
                {"sandbox": {"sandbox_id": "owned-sandbox"}},
                Runtime(context={}),
            )
        )
        assert await asyncio.to_thread(provider.release_started.wait, 2)

        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)

        assert not task.done()
        provider.allow_release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        provider.allow_release.set()
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        reset_sandbox_provider()

    assert provider.released == ["owned-sandbox"]
