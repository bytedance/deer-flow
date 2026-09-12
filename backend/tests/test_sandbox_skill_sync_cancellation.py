from __future__ import annotations

import asyncio
import threading

import pytest
from langgraph.runtime import Runtime

from deerflow.sandbox.middleware import SandboxMiddleware
from deerflow.sandbox.sandbox import Sandbox
from deerflow.sandbox.sandbox_provider import SandboxProvider, reset_sandbox_provider, set_sandbox_provider
from deerflow.sandbox.search import GrepMatch


class _SandboxStub(Sandbox):
    def execute_command(
        self,
        command: str,
        env: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> str:
        del command, env, timeout
        return "OK"

    def read_file(
        self,
        path: str,
        start_line: int | None = None,
        end_line: int | None = None,
    ) -> str:
        del path, start_line, end_line
        return "content"

    def download_file(self, path: str) -> bytes:
        del path
        return b"content"

    def list_dir(self, path: str, max_depth: int = 2) -> list[str]:
        del path, max_depth
        return []

    def write_file(self, path: str, content: str, append: bool = False) -> None:
        del path, content, append

    def glob(
        self,
        path: str,
        pattern: str,
        *,
        include_dirs: bool = False,
        max_results: int = 200,
    ) -> tuple[list[str], bool]:
        del path, pattern, include_dirs, max_results
        return [], False

    def grep(
        self,
        path: str,
        pattern: str,
        *,
        glob: str | None = None,
        literal: bool = False,
        case_sensitive: bool = False,
        max_results: int = 100,
    ) -> tuple[list[GrepMatch], bool]:
        del path, pattern, glob, literal, case_sensitive, max_results
        return [], False

    def update_file(self, path: str, content: bytes) -> None:
        del path, content


class _BlockingSkillSyncProvider(SandboxProvider):
    supports_agent_skill_isolation = True

    def __init__(self) -> None:
        self.sandbox = _SandboxStub("skill-sync-sandbox")
        self.sync_started = threading.Event()
        self.allow_sync_finish = threading.Event()
        self.sync_finished = threading.Event()
        self.release_calls: list[str] = []

    def acquire(self, thread_id: str | None = None, *, user_id: str | None = None) -> str:
        del thread_id, user_id
        return self.sandbox.id

    def get(self, sandbox_id: str) -> Sandbox | None:
        return self.sandbox if sandbox_id == self.sandbox.id else None

    def release(self, sandbox_id: str) -> None:
        self.release_calls.append(sandbox_id)

    def sync_agent_skills(
        self,
        sandbox_id: str,
        *,
        thread_id: str,
        user_id: str,
        projection,
    ) -> None:
        del sandbox_id, thread_id, user_id, projection
        self.sync_started.set()
        assert self.allow_sync_finish.wait(timeout=5), "test did not unblock skill sync"
        self.sync_finished.set()


@pytest.mark.anyio
async def test_cancelled_policy_sync_keeps_lease_until_sync_worker_finishes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _BlockingSkillSyncProvider()
    middleware = SandboxMiddleware(lazy_init=True, available_skills={"allowed"})
    projection = object()
    release_entry_sync_finished: list[bool] = []
    original_release_sandbox_async = middleware._release_sandbox_async

    async def _record_release_entry(sandbox_id: str, *, owner_id: str | None) -> None:
        release_entry_sync_finished.append(provider.sync_finished.is_set())
        await original_release_sandbox_async(sandbox_id, owner_id=owner_id)

    monkeypatch.setattr(
        middleware,
        "_prepare_agent_skill_projection",
        lambda *_args, **_kwargs: projection,
    )
    monkeypatch.setattr(middleware, "_release_sandbox_async", _record_release_entry)
    set_sandbox_provider(provider)
    task = asyncio.create_task(
        middleware.abefore_agent(
            {},
            Runtime(context={"thread_id": "thread-policy", "user_id": "user-policy"}),
        )
    )
    try:
        assert await asyncio.to_thread(provider.sync_started.wait, 2), "skill sync did not start"

        task.cancel()
        await asyncio.sleep(0)

        assert not task.done()
        assert release_entry_sync_finished == []
        assert provider.release_calls == []
        assert not provider.sync_finished.is_set()

        task.cancel()
        await asyncio.sleep(0)

        assert not task.done()
        assert release_entry_sync_finished == []
        assert provider.release_calls == []
        assert not provider.sync_finished.is_set()

        provider.allow_sync_finish.set()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert provider.sync_finished.is_set()
        assert release_entry_sync_finished == [True]
        assert provider.release_calls == [provider.sandbox.id]
    finally:
        provider.allow_sync_finish.set()
        if not task.done():
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        reset_sandbox_provider()
