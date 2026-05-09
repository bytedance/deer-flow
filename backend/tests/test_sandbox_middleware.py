from __future__ import annotations

import asyncio

import pytest
from langgraph.runtime import Runtime

from deerflow.sandbox.middleware import SandboxMiddleware
from deerflow.sandbox.sandbox import Sandbox
from deerflow.sandbox.sandbox_provider import SandboxProvider, reset_sandbox_provider, set_sandbox_provider


class _SyncProvider(SandboxProvider):
    def __init__(self) -> None:
        self.thread_ids: list[str | None] = []

    def acquire(self, thread_id: str | None = None) -> str:
        self.thread_ids.append(thread_id)
        return "sync-sandbox"

    def get(self, sandbox_id: str) -> Sandbox | None:
        return None

    def release(self, sandbox_id: str) -> None:
        return None


class _AsyncOnlyProvider(SandboxProvider):
    def __init__(self) -> None:
        self.thread_ids: list[str | None] = []

    def acquire(self, thread_id: str | None = None) -> str:
        raise AssertionError("async middleware should not call sync acquire")

    async def acquire_async(self, thread_id: str | None = None) -> str:
        self.thread_ids.append(thread_id)
        return "async-sandbox"

    def get(self, sandbox_id: str) -> Sandbox | None:
        return None

    def release(self, sandbox_id: str) -> None:
        return None


@pytest.mark.anyio
async def test_provider_default_acquire_async_offloads_sync_acquire(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _SyncProvider()
    calls: list[tuple[object, tuple[object, ...]]] = []

    async def fake_to_thread(func, /, *args):
        calls.append((func, args))
        return func(*args)

    monkeypatch.setattr(asyncio, "to_thread", fake_to_thread)

    sandbox_id = await provider.acquire_async("thread-1")

    assert sandbox_id == "sync-sandbox"
    assert provider.thread_ids == ["thread-1"]
    assert calls == [(provider.acquire, ("thread-1",))]


@pytest.mark.anyio
async def test_abefore_agent_uses_async_provider_acquire() -> None:
    provider = _AsyncOnlyProvider()
    set_sandbox_provider(provider)
    try:
        middleware = SandboxMiddleware(lazy_init=False)

        result = await middleware.abefore_agent({}, Runtime(context={"thread_id": "thread-2"}))
    finally:
        reset_sandbox_provider()

    assert result == {"sandbox": {"sandbox_id": "async-sandbox"}}
    assert provider.thread_ids == ["thread-2"]
