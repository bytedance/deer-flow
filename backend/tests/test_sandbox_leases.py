from __future__ import annotations

import asyncio
import threading

import pytest

from deerflow.sandbox.lease import SandboxLeaseManager
from deerflow.sandbox.sandbox import Sandbox
from deerflow.sandbox.sandbox_provider import SandboxProvider
from deerflow.sandbox.search import GrepMatch


class _LeaseSandbox(Sandbox):
    def __init__(self, sandbox_id: str):
        super().__init__(sandbox_id)
        self.released_scopes: list[str] = []

    def execute_command(self, command, env=None, timeout=None):
        return command

    def release_command_scope(self, scope_id: str) -> None:
        self.released_scopes.append(scope_id)

    def read_file(self, path, start_line=None, end_line=None):
        return ""

    def download_file(self, path):
        return b""

    def list_dir(self, path, max_depth=2):
        return []

    def write_file(self, path, content, append=False):
        return None

    def glob(self, path, pattern, *, include_dirs=False, max_results=200):
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
        return [], False

    def update_file(self, path, content):
        return None


class _LeaseProvider(SandboxProvider):
    def __init__(self):
        self.sandbox = _LeaseSandbox("shared")
        self.acquire_calls: list[tuple[str | None, str | None]] = []
        self.release_calls: list[str] = []

    def acquire(self, thread_id=None, *, user_id=None):
        self.acquire_calls.append((thread_id, user_id))
        return self.sandbox.id

    def get(self, sandbox_id):
        return self.sandbox if sandbox_id == self.sandbox.id else None

    def release(self, sandbox_id):
        self.release_calls.append(sandbox_id)


def test_last_execution_lease_is_the_only_provider_releaser() -> None:
    provider = _LeaseProvider()
    manager = SandboxLeaseManager(provider)

    for owner_id in ("parent", "child-a", "child-b"):
        manager.retain(
            owner_id,
            "shared",
            thread_id="thread-1",
            user_id="user-1",
        )

    manager.release("child-a")
    manager.release("parent")
    assert provider.release_calls == []

    manager.release("child-b")
    assert provider.release_calls == ["shared"]
    assert provider.sandbox.released_scopes == ["child-a", "parent", "child-b"]


def test_release_is_idempotent_for_executor_finally_safety_net() -> None:
    provider = _LeaseProvider()
    manager = SandboxLeaseManager(provider)
    manager.retain(
        "child",
        "shared",
        thread_id="thread-1",
        user_id="user-1",
    )

    manager.release("child")
    manager.release("child")

    assert provider.release_calls == ["shared"]
    assert provider.sandbox.released_scopes == ["child"]


def test_repeated_acquire_for_same_owner_does_not_reacquire_provider() -> None:
    provider = _LeaseProvider()
    manager = SandboxLeaseManager(provider)

    first = manager.acquire("child", "thread-1", user_id="user-1")
    second = manager.acquire("child", "thread-1", user_id="user-1")

    assert first == second == "shared"
    assert provider.acquire_calls == [("thread-1", "user-1")]


class _BlockingLookupProvider(_LeaseProvider):
    def __init__(self) -> None:
        super().__init__()
        self.lookup_started = threading.Event()
        self.allow_lookup = threading.Event()
        self._block_next_lookup = False
        self._lookup_control = threading.Lock()

    def arm_lookup(self) -> None:
        with self._lookup_control:
            self._block_next_lookup = True

    def get(self, sandbox_id):
        with self._lookup_control:
            block_lookup = self._block_next_lookup
            self._block_next_lookup = False
        if block_lookup:
            self.lookup_started.set()
            assert self.allow_lookup.wait(timeout=1)
        return super().get(sandbox_id)


def test_reuse_lookup_and_retain_block_last_owner_release_as_one_transition() -> None:
    provider = _BlockingLookupProvider()
    manager = SandboxLeaseManager(provider)
    manager.retain(
        "previous",
        "shared",
        thread_id="thread-1",
        user_id="user-1",
    )
    provider.arm_lookup()

    reused_ids: list[str] = []
    reuse = manager.reuse_or_acquire
    reuse_thread = threading.Thread(
        target=lambda: reused_ids.append(
            reuse(
                "next",
                "shared",
                thread_id="thread-1",
                user_id="user-1",
            )
        )
    )
    release_thread = threading.Thread(target=manager.release, args=("previous",))

    reuse_thread.start()
    assert provider.lookup_started.wait(timeout=1)
    release_thread.start()
    release_thread.join(timeout=0.05)
    assert release_thread.is_alive()

    provider.allow_lookup.set()
    reuse_thread.join(timeout=1)
    release_thread.join(timeout=1)

    assert not reuse_thread.is_alive()
    assert not release_thread.is_alive()
    assert reused_ids == ["shared"]
    assert manager.binding_for("next") == "shared"
    assert provider.release_calls == []


def test_async_reuse_lookup_and_retain_block_last_owner_release_as_one_transition() -> None:
    provider = _BlockingLookupProvider()
    manager = SandboxLeaseManager(provider)
    manager.retain(
        "previous",
        "shared",
        thread_id="thread-1",
        user_id="user-1",
    )
    provider.arm_lookup()

    reused_ids: list[str] = []
    reuse_async = manager.reuse_or_acquire_async

    def run_async_reuse() -> None:
        reused_ids.append(
            asyncio.run(
                reuse_async(
                    "next",
                    "shared",
                    thread_id="thread-1",
                    user_id="user-1",
                )
            )
        )

    reuse_thread = threading.Thread(target=run_async_reuse)
    release_thread = threading.Thread(target=manager.release, args=("previous",))

    reuse_thread.start()
    assert provider.lookup_started.wait(timeout=1)
    release_thread.start()
    release_thread.join(timeout=0.05)
    assert release_thread.is_alive()

    provider.allow_lookup.set()
    reuse_thread.join(timeout=1)
    release_thread.join(timeout=1)

    assert not reuse_thread.is_alive()
    assert not release_thread.is_alive()
    assert reused_ids == ["shared"]
    assert manager.binding_for("next") == "shared"
    assert provider.release_calls == []


def test_reuse_acquires_fresh_sandbox_for_stale_owner_binding() -> None:
    provider = _LeaseProvider()
    manager = SandboxLeaseManager(provider)
    manager.retain(
        "next",
        "stale",
        thread_id="thread-1",
        user_id="user-1",
    )

    sandbox_id = manager.reuse_or_acquire(
        "next",
        "stale",
        thread_id="thread-1",
        user_id="user-1",
    )

    assert sandbox_id == "shared"
    assert manager.binding_for("next") == "shared"
    assert provider.acquire_calls == [("thread-1", "user-1")]


@pytest.mark.anyio
async def test_async_reuse_acquires_fresh_sandbox_for_stale_owner_binding() -> None:
    provider = _LeaseProvider()
    manager = SandboxLeaseManager(provider)
    manager.retain(
        "next",
        "stale",
        thread_id="thread-1",
        user_id="user-1",
    )

    sandbox_id = await manager.reuse_or_acquire_async(
        "next",
        "stale",
        thread_id="thread-1",
        user_id="user-1",
    )

    assert sandbox_id == "shared"
    assert manager.binding_for("next") == "shared"
    assert provider.acquire_calls == [("thread-1", "user-1")]


@pytest.mark.anyio
async def test_async_lazy_acquires_share_one_release_boundary() -> None:
    provider = _LeaseProvider()
    manager = SandboxLeaseManager(provider)

    await manager.acquire_async("child-a", "thread-1", user_id="user-1")
    await manager.acquire_async("child-b", "thread-1", user_id="user-1")

    await manager.release_async("child-a")
    assert provider.release_calls == []
    await manager.release_async("child-b")
    assert provider.release_calls == ["shared"]


@pytest.mark.anyio
async def test_repeated_async_acquire_for_same_owner_does_not_reacquire_provider() -> None:
    provider = _LeaseProvider()
    manager = SandboxLeaseManager(provider)

    first = await manager.acquire_async("child", "thread-1", user_id="user-1")
    second = await manager.acquire_async("child", "thread-1", user_id="user-1")

    assert first == second == "shared"
    assert provider.acquire_calls == [("thread-1", "user-1")]


@pytest.mark.anyio
async def test_cancelled_async_acquire_releases_unbound_provider_result() -> None:
    acquire_started = asyncio.Event()
    allow_acquire = asyncio.Event()

    class _BlockingAsyncProvider(_LeaseProvider):
        async def acquire_async(self, thread_id=None, *, user_id=None):
            self.acquire_calls.append((thread_id, user_id))
            acquire_started.set()
            await allow_acquire.wait()
            return self.sandbox.id

    provider = _BlockingAsyncProvider()
    manager = SandboxLeaseManager(provider)
    acquire_task = asyncio.create_task(manager.acquire_async("child", "thread-1", user_id="user-1"))
    await acquire_started.wait()

    acquire_task.cancel()
    await asyncio.sleep(0)
    assert not acquire_task.done()

    allow_acquire.set()
    with pytest.raises(asyncio.CancelledError):
        await acquire_task

    assert manager.binding_for("child") is None
    assert provider.release_calls == ["shared"]


@pytest.mark.anyio
async def test_cancelled_async_acquire_keeps_same_thread_serialized_through_reconciliation() -> None:
    acquire_started = asyncio.Event()
    allow_acquire = asyncio.Event()
    release_started = threading.Event()
    allow_release = threading.Event()

    class _BlockingReconciliationProvider(_LeaseProvider):
        async def acquire_async(self, thread_id=None, *, user_id=None):
            self.acquire_calls.append((thread_id, user_id))
            acquire_started.set()
            await allow_acquire.wait()
            return self.sandbox.id

        def release(self, sandbox_id):
            release_started.set()
            allow_release.wait(timeout=1)
            super().release(sandbox_id)

    provider = _BlockingReconciliationProvider()
    manager = SandboxLeaseManager(provider)
    acquire_task = asyncio.create_task(manager.acquire_async("cancelled", "thread-1", user_id="user-1"))
    await acquire_started.wait()

    acquire_task.cancel()
    allow_acquire.set()
    assert await asyncio.to_thread(release_started.wait, 1)

    retain_done = threading.Event()

    def retain_next_owner() -> None:
        manager.retain(
            "next",
            "shared",
            thread_id="thread-1",
            user_id="user-1",
        )
        retain_done.set()

    retain_thread = threading.Thread(target=retain_next_owner)
    retain_thread.start()
    retain_thread.join(timeout=0.05)
    assert retain_thread.is_alive()

    allow_release.set()
    with pytest.raises(asyncio.CancelledError):
        await acquire_task
    retain_thread.join(timeout=1)

    assert not retain_thread.is_alive()
    assert retain_done.is_set()
    assert provider.release_calls == ["shared"]
    assert manager.binding_for("cancelled") is None
    assert manager.binding_for("next") == "shared"


def test_new_acquire_waits_until_last_release_transition_finishes() -> None:
    release_started = threading.Event()
    allow_release = threading.Event()

    class _BlockingReleaseProvider(_LeaseProvider):
        def release(self, sandbox_id):
            release_started.set()
            allow_release.wait(timeout=1)
            super().release(sandbox_id)

    provider = _BlockingReleaseProvider()
    manager = SandboxLeaseManager(provider)
    manager.retain(
        "first",
        "shared",
        thread_id="thread-1",
        user_id="user-1",
    )

    release_thread = threading.Thread(target=manager.release, args=("first",))
    acquire_thread = threading.Thread(
        target=manager.acquire,
        args=("second", "thread-1"),
        kwargs={"user_id": "user-1"},
    )
    release_thread.start()
    assert release_started.wait(timeout=1)
    acquire_thread.start()

    acquire_thread.join(timeout=0.05)
    assert acquire_thread.is_alive()

    allow_release.set()
    release_thread.join(timeout=1)
    acquire_thread.join(timeout=1)
    assert not release_thread.is_alive()
    assert not acquire_thread.is_alive()
    assert provider.release_calls == ["shared"]
    assert manager.binding_for("second") == "shared"
