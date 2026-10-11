from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field

import pytest

from deerflow.sandbox.exceptions import SandboxNotFoundError
from deerflow.sandbox.lease import (
    SandboxLeaseManager,
    discard_sandbox_lease_manager,
    get_sandbox_lease_manager,
)
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

    def get_scoped(self, sandbox_id, *, thread_id, user_id):
        del thread_id, user_id
        return self.get(sandbox_id)

    def release(self, sandbox_id):
        self.release_calls.append(sandbox_id)


@dataclass
class _UnhashableLeaseProvider(SandboxProvider):
    """Valid value-comparable provider whose instances are not hashable."""

    marker: str = "same"
    sandbox: _LeaseSandbox = field(default_factory=lambda: _LeaseSandbox("shared"), compare=False)
    release_calls: list[str] = field(default_factory=list, compare=False)

    def acquire(self, thread_id=None, *, user_id=None):
        return self.sandbox.id

    def get(self, sandbox_id):
        return self.sandbox if sandbox_id == self.sandbox.id else None

    def get_scoped(self, sandbox_id, *, thread_id, user_id):
        del thread_id, user_id
        return self.get(sandbox_id)

    def release(self, sandbox_id):
        self.release_calls.append(sandbox_id)


def test_manager_registry_supports_unhashable_provider() -> None:
    provider = _UnhashableLeaseProvider()
    assert provider.__hash__ is None

    try:
        manager = get_sandbox_lease_manager(provider)
        assert get_sandbox_lease_manager(provider) is manager
    finally:
        discard_sandbox_lease_manager(provider)


def test_manager_registry_distinguishes_equal_provider_instances_by_identity() -> None:
    first = _UnhashableLeaseProvider()
    second = _UnhashableLeaseProvider()
    assert first == second
    assert first is not second

    try:
        first_manager = get_sandbox_lease_manager(first)
        second_manager = get_sandbox_lease_manager(second)

        assert first_manager is not second_manager
        first_manager.retain("first-owner", "shared", thread_id="thread-1", user_id="user-1")
        second_manager.retain("second-owner", "shared", thread_id="thread-1", user_id="user-1")
        assert first_manager.binding_for("second-owner") is None
        assert second_manager.binding_for("first-owner") is None

        discard_sandbox_lease_manager(first)
        assert get_sandbox_lease_manager(second) is second_manager
    finally:
        discard_sandbox_lease_manager(first)
        discard_sandbox_lease_manager(second)


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


def test_idle_teardown_reservation_excludes_live_holders_and_fork_retention() -> None:
    provider = _LeaseProvider()
    manager = SandboxLeaseManager(provider)
    try:
        manager.retain("parent", "shared", thread_id="parent-thread", user_id="user")
        with manager.reserve_idle_teardown("shared") as reserved:
            assert reserved is False
        manager.release("parent")

        with manager.reserve_idle_teardown("shared") as reserved:
            assert reserved is True
            with manager.reserve_idle_teardown("shared") as nested:
                assert nested is True
            errors: list[Exception] = []

            def retain_fork():
                try:
                    manager.retain("fork", "shared", thread_id="fork-thread", user_id="user", release_on_last=False)
                except Exception as error:
                    errors.append(error)

            borrower = threading.Thread(target=retain_fork)
            borrower.start()
            borrower.join(timeout=5)
            assert not borrower.is_alive()
            assert len(errors) == 1 and "teardown" in str(errors[0])
            assert manager.binding_for("fork") is None
        manager.retain("fork", "shared", thread_id="fork-thread", user_id="user", release_on_last=False)
        assert manager.binding_for("fork") == "shared"
    finally:
        manager.close()


def test_failed_rebind_to_teardown_keeps_the_previous_execution_binding() -> None:
    manager = SandboxLeaseManager(_LeaseProvider())
    try:
        manager.retain("owner", "previous", thread_id="thread", user_id="user")
        with manager.reserve_idle_teardown("shared") as reserved:
            assert reserved is True
            with pytest.raises(RuntimeError, match="teardown"):
                manager.retain("owner", "shared", thread_id="thread", user_id="user")
            assert manager.binding_for("owner") == "previous"
    finally:
        manager.close()


def test_execution_holder_survives_scope_cleanup_and_new_fork_defers_parking() -> None:
    provider = _LeaseProvider()
    manager = SandboxLeaseManager(provider)
    manager.retain("parent", "shared", thread_id="parent-thread", user_id="user")
    ordinary_cleanup = provider.sandbox.release_command_scope

    def cleanup(scope_id):
        if scope_id == "parent":
            assert manager.binding_for("parent") == "shared"
            with manager.reserve_idle_teardown("shared") as reserved:
                assert reserved is False
            manager.retain("fork", "shared", thread_id="fork-thread", user_id="user", release_on_last=False)
        ordinary_cleanup(scope_id)

    provider.sandbox.release_command_scope = cleanup
    try:
        manager.release("parent")
        assert provider.release_calls == []
        assert manager.binding_for("fork") == "shared"
        manager.release("fork")
        assert provider.release_calls == ["shared"]
        assert provider.sandbox.released_scopes == ["parent", "fork"]
    finally:
        manager.close()


@pytest.mark.parametrize("async_restore", [False, True], ids=["sync", "async"])
def test_late_fork_lookup_cannot_bind_a_client_after_parent_parks_it(async_restore) -> None:
    captured = threading.Event()
    resume = threading.Event()

    class ParkingProvider(_LeaseProvider):
        active = True

        def get(self, sandbox_id):
            client = super().get(sandbox_id) if self.active else None
            if threading.current_thread().name == "late-fork" and not captured.is_set():
                captured.set()
                assert resume.wait(timeout=5)
            return client

        def release(self, sandbox_id):
            super().release(sandbox_id)
            self.active = False

        def acquire(self, thread_id=None, *, user_id=None):
            self.sandbox = _LeaseSandbox("replacement")
            self.active = True
            return super().acquire(thread_id, user_id=user_id)

    provider = ParkingProvider()
    manager = SandboxLeaseManager(provider)
    manager.retain("parent", "shared", thread_id="parent-thread", user_id="user")
    results: list[str] = []
    errors: list[BaseException] = []

    def restore_fork():
        try:
            options = dict(thread_id="fork-thread", user_id="user", release_on_last=False, allow_unscoped_borrow=True)
            result = asyncio.run(manager.reuse_or_acquire_async("fork", "shared", **options)) if async_restore else manager.reuse_or_acquire("fork", "shared", **options)
            results.append(result)
        except BaseException as error:
            errors.append(error)

    fork = threading.Thread(target=restore_fork, name="late-fork")
    fork.start()
    try:
        assert captured.wait(timeout=5)
        manager.release("parent")
        assert provider.release_calls == ["shared"]
        resume.set()
        fork.join(timeout=5)
        assert not fork.is_alive()
        assert errors == []
        assert results == ["replacement"]
        assert manager.binding_for("fork") == "replacement"
        assert provider.get("replacement") is provider.sandbox
        manager.release("fork")
        assert provider.release_calls == ["shared", "replacement"]
    finally:
        resume.set()
        fork.join(timeout=5)
        manager.close()


@pytest.mark.parametrize("async_acquire", [False, True], ids=["sync", "async"])
def test_acquire_does_not_bind_a_client_that_disappeared_before_admission(async_acquire) -> None:
    class MissingClientProvider(_LeaseProvider):
        def get(self, sandbox_id):
            return None

    provider = MissingClientProvider()
    manager = SandboxLeaseManager(provider)
    try:
        with pytest.raises(SandboxNotFoundError, match="Sandbox not found after acquisition"):
            if async_acquire:
                asyncio.run(manager.acquire_async("owner", "thread", user_id="user"))
            else:
                manager.acquire("owner", "thread", user_id="user")
        assert manager.binding_for("owner") is None
        assert provider.release_calls == ["shared"]
    finally:
        manager.close()


def test_non_releasing_holder_defers_parent_release_until_its_scope_is_clean() -> None:
    provider = _LeaseProvider()
    manager = SandboxLeaseManager(provider)
    manager.retain(
        "parent",
        "shared",
        thread_id="thread-1",
        user_id="user-1",
    )
    manager.retain(
        "fork-child",
        "shared",
        thread_id="thread-1",
        user_id="user-1",
        release_on_last=False,
    )

    manager.release("parent")
    assert provider.release_calls == []

    manager.release("fork-child")

    assert provider.release_calls == ["shared"]
    assert provider.sandbox.released_scopes == ["parent", "fork-child"]


def test_lone_non_releasing_holder_does_not_park_warm_sandbox() -> None:
    provider = _LeaseProvider()
    manager = SandboxLeaseManager(provider)
    manager.retain(
        "upload",
        "shared",
        thread_id="thread-1",
        user_id="user-1",
        release_on_last=False,
    )

    manager.release("upload")

    assert provider.release_calls == []
    assert provider.sandbox.released_scopes == ["upload"]


def test_normal_acquire_upgrades_existing_non_releasing_holder() -> None:
    provider = _LeaseProvider()
    manager = SandboxLeaseManager(provider)
    manager.retain(
        "child",
        "shared",
        thread_id="thread-1",
        user_id="user-1",
        release_on_last=False,
    )

    sandbox_id = manager.acquire("child", "thread-1", user_id="user-1")
    manager.release("child")

    assert sandbox_id == "shared"
    assert provider.acquire_calls == []
    assert provider.release_calls == ["shared"]


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
async def test_cancelled_acquire_defers_rollback_until_a_fork_borrower_drains() -> None:
    started = asyncio.Event()
    finish = asyncio.Event()

    class BlockingProvider(_LeaseProvider):
        async def acquire_async(self, thread_id=None, *, user_id=None):
            started.set()
            await finish.wait()
            return self.sandbox.id

    provider = BlockingProvider()
    manager = SandboxLeaseManager(provider)
    task = asyncio.create_task(manager.acquire_async("cancelled", "parent-thread", user_id="user"))
    try:
        await started.wait()
        manager.retain("fork", "shared", thread_id="fork-thread", user_id="user", release_on_last=False)
        task.cancel()
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert provider.release_calls == []
        await manager.release_async("fork")
        assert provider.release_calls == ["shared"]
        assert provider.sandbox.released_scopes == ["fork"]
    finally:
        finish.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        manager.close()


@pytest.mark.anyio
async def test_repeated_cancellation_waits_for_provider_acquire_reconciliation() -> None:
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
    acquire_task = asyncio.create_task(manager.acquire_async("cancelled", "thread-1", user_id="user-1"))
    await acquire_started.wait()

    acquire_task.cancel()
    await asyncio.sleep(0)
    acquire_task.cancel()
    await asyncio.sleep(0)

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
    try:
        assert not acquire_task.done()
        retain_thread.join(timeout=0.05)
        assert retain_thread.is_alive()

        allow_acquire.set()
        with pytest.raises(asyncio.CancelledError):
            await acquire_task
        retain_thread.join(timeout=1)

        assert not retain_thread.is_alive()
        assert retain_done.is_set()
        assert provider.release_calls == ["shared"]
        assert manager.binding_for("cancelled") is None
        assert manager.binding_for("next") == "shared"
    finally:
        allow_acquire.set()
        retain_thread.join(timeout=1)
        manager.close()


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
    acquire_task.cancel()
    await asyncio.sleep(0)
    assert not acquire_task.done()

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


@pytest.mark.anyio
async def test_cancelled_async_acquire_logs_reconciliation_failure(caplog) -> None:
    acquire_started = asyncio.Event()
    allow_acquire_failure = asyncio.Event()

    class _FailingCancelledAcquireProvider(_LeaseProvider):
        async def acquire_async(self, thread_id=None, *, user_id=None):
            self.acquire_calls.append((thread_id, user_id))
            acquire_started.set()
            await allow_acquire_failure.wait()
            raise RuntimeError("provider acquire failed")

    provider = _FailingCancelledAcquireProvider()
    manager = SandboxLeaseManager(provider)
    acquire_task = asyncio.create_task(manager.acquire_async("cancelled", "thread-1", user_id="user-1"))
    await acquire_started.wait()

    with caplog.at_level("WARNING", logger="deerflow.sandbox.lease"):
        acquire_task.cancel()
        allow_acquire_failure.set()
        with pytest.raises(asyncio.CancelledError):
            await acquire_task

    assert "Cancelled sandbox acquire failed during reconciliation" in caplog.text
    assert "provider acquire failed" in caplog.text


@pytest.mark.anyio
async def test_cancelled_async_acquire_preserves_cancellation_when_rollback_fails(caplog) -> None:
    acquire_started = asyncio.Event()
    allow_acquire = asyncio.Event()

    class _FailingRollbackProvider(_LeaseProvider):
        async def acquire_async(self, thread_id=None, *, user_id=None):
            self.acquire_calls.append((thread_id, user_id))
            acquire_started.set()
            await allow_acquire.wait()
            return self.sandbox.id

        def release(self, sandbox_id):
            raise RuntimeError("rollback failed")

    provider = _FailingRollbackProvider()
    manager = SandboxLeaseManager(provider)
    acquire_task = asyncio.create_task(manager.acquire_async("cancelled", "thread-1", user_id="user-1"))
    await acquire_started.wait()

    with caplog.at_level("WARNING", logger="deerflow.sandbox.lease"):
        acquire_task.cancel()
        allow_acquire.set()
        with pytest.raises(asyncio.CancelledError):
            await acquire_task

    assert "Cancelled sandbox acquire rollback failed during reconciliation" in caplog.text
    assert "rollback failed" in caplog.text


@pytest.mark.anyio
async def test_cancelled_async_release_logs_reconciliation_failure(caplog) -> None:
    release_started = threading.Event()
    allow_release_failure = threading.Event()

    class _FailingCancelledReleaseProvider(_LeaseProvider):
        def release(self, sandbox_id):
            release_started.set()
            assert allow_release_failure.wait(timeout=1)
            raise RuntimeError("provider release failed")

    provider = _FailingCancelledReleaseProvider()
    manager = SandboxLeaseManager(provider)
    manager.retain(
        "cancelled",
        "shared",
        thread_id="thread-1",
        user_id="user-1",
    )
    release_task = asyncio.create_task(manager.release_async("cancelled"))
    assert await asyncio.to_thread(release_started.wait, 1)

    with caplog.at_level("WARNING", logger="deerflow.sandbox.lease"):
        release_task.cancel()
        allow_release_failure.set()
        with pytest.raises(asyncio.CancelledError):
            await release_task

    assert "Cancelled sandbox release failed during reconciliation" in caplog.text
    assert "provider release failed" in caplog.text


@pytest.mark.anyio
async def test_repeated_cancellation_waits_for_async_release_reconciliation() -> None:
    release_started = threading.Event()
    allow_release = threading.Event()

    class _BlockingReleaseProvider(_LeaseProvider):
        def release(self, sandbox_id):
            release_started.set()
            assert allow_release.wait(timeout=1)
            super().release(sandbox_id)

    provider = _BlockingReleaseProvider()
    manager = SandboxLeaseManager(provider)
    manager.retain(
        "cancelled",
        "shared",
        thread_id="thread-1",
        user_id="user-1",
    )
    release_task = asyncio.create_task(manager.release_async("cancelled"))
    assert await asyncio.to_thread(release_started.wait, 1)

    for _ in range(3):
        release_task.cancel()
        await asyncio.sleep(0)
    try:
        assert not release_task.done()
        allow_release.set()
        with pytest.raises(asyncio.CancelledError):
            await release_task

        assert manager.binding_for("cancelled") is None
        assert provider.release_calls == ["shared"]
    finally:
        allow_release.set()
        manager.close()


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
