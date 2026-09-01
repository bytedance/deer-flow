"""Execution-scoped leases for process-local sandbox use.

Provider ownership stores answer which Gateway instance may reap a remote
sandbox.  This module answers a different question: which concurrently running
agent executions inside one Gateway are still using the provider's active
client.  The last execution lease is the only one allowed to call
``SandboxProvider.release``.
"""

from __future__ import annotations

import asyncio
import threading
import uuid
import weakref
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from deerflow.sandbox.acquire_serialization import AcquireSerializer

if TYPE_CHECKING:
    from deerflow.sandbox.sandbox_provider import SandboxProvider


SANDBOX_LEASE_OWNER_CONTEXT_KEY = "sandbox_lease_owner_id"
SANDBOX_COMMAND_SCOPE_CONTEXT_KEY = "sandbox_command_scope_id"


@dataclass(frozen=True)
class _LeaseBinding:
    sandbox_id: str
    thread_key: tuple[str, str]


class SandboxLeaseManager:
    """Coordinate active agent users of one sandbox provider.

    Lifecycle transitions are serialized per user/thread key.  Metadata is
    protected separately so unrelated threads do not block each other's slow
    provider operations.
    """

    def __init__(self, provider: SandboxProvider):
        self._provider = provider
        self._metadata_lock = threading.RLock()
        self._serializer = AcquireSerializer[tuple[str, str]](
            thread_name_prefix="sandbox-execution-lease",
        )
        self._bindings_by_owner: dict[str, _LeaseBinding] = {}
        self._owners_by_sandbox: dict[str, set[str]] = {}

    @staticmethod
    def _thread_key(thread_id: str, user_id: str) -> tuple[str, str]:
        return user_id, thread_id

    def _remove_binding_locked(self, owner_id: str) -> tuple[_LeaseBinding | None, bool]:
        binding = self._bindings_by_owner.pop(owner_id, None)
        if binding is None:
            return None, False
        owners = self._owners_by_sandbox.get(binding.sandbox_id)
        if owners is None:
            return binding, False
        owners.discard(owner_id)
        if owners:
            return binding, False
        self._owners_by_sandbox.pop(binding.sandbox_id, None)
        return binding, True

    def _bind_locked(
        self,
        owner_id: str,
        sandbox_id: str,
        key: tuple[str, str],
    ) -> tuple[_LeaseBinding | None, bool]:
        existing = self._bindings_by_owner.get(owner_id)
        if existing == _LeaseBinding(sandbox_id=sandbox_id, thread_key=key):
            return None, False
        if existing is not None and existing.thread_key != key:
            raise RuntimeError(f"Sandbox lease owner {owner_id!r} cannot move between thread identities")

        release_previous = False
        previous: _LeaseBinding | None = None
        if existing is not None:
            previous, release_previous = self._remove_binding_locked(owner_id)

        self._bindings_by_owner[owner_id] = _LeaseBinding(
            sandbox_id=sandbox_id,
            thread_key=key,
        )
        self._owners_by_sandbox.setdefault(sandbox_id, set()).add(owner_id)

        return previous, release_previous

    def _release_unbound_acquire(self, sandbox_id: str) -> None:
        """Undo a cancelled acquire when no admitted execution uses its result."""
        with self._metadata_lock:
            has_owners = bool(self._owners_by_sandbox.get(sandbox_id))
        if not has_owners:
            self._provider.release(sandbox_id)

    def retain(
        self,
        owner_id: str,
        sandbox_id: str,
        *,
        thread_id: str,
        user_id: str,
    ) -> None:
        """Attach ``owner_id`` to an inherited or checkpointed sandbox id."""
        key = self._thread_key(thread_id, user_id)
        with self._serializer.hold(key):
            with self._metadata_lock:
                previous, release_previous = self._bind_locked(
                    owner_id,
                    sandbox_id,
                    key,
                )
            if release_previous and previous is not None:
                self._provider.release(previous.sandbox_id)

    async def retain_async(
        self,
        owner_id: str,
        sandbox_id: str,
        *,
        thread_id: str,
        user_id: str,
    ) -> None:
        """Async attach without blocking the event loop on a lifecycle lock."""
        key = self._thread_key(thread_id, user_id)
        async with self._serializer.hold_async(key):
            with self._metadata_lock:
                previous, release_previous = self._bind_locked(
                    owner_id,
                    sandbox_id,
                    key,
                )
            if release_previous and previous is not None:
                await asyncio.to_thread(
                    self._provider.release,
                    previous.sandbox_id,
                )

    def acquire(self, owner_id: str, thread_id: str, *, user_id: str) -> str:
        """Acquire and bind a sandbox, idempotently for one execution owner."""
        key = self._thread_key(thread_id, user_id)
        with self._serializer.hold(key):
            with self._metadata_lock:
                existing = self._bindings_by_owner.get(owner_id)
                if existing is not None:
                    if existing.thread_key != key:
                        raise RuntimeError(f"Sandbox lease owner {owner_id!r} cannot move between thread identities")
                    return existing.sandbox_id
            sandbox_id = self._provider.acquire(thread_id, user_id=user_id)
            with self._metadata_lock:
                previous, release_previous = self._bind_locked(
                    owner_id,
                    sandbox_id,
                    key,
                )
            if release_previous and previous is not None:
                self._provider.release(previous.sandbox_id)
            return sandbox_id

    async def acquire_async(self, owner_id: str, thread_id: str, *, user_id: str) -> str:
        """Async acquire while preserving the provider's own async hook."""
        key = self._thread_key(thread_id, user_id)
        async with self._serializer.hold_async(key):
            with self._metadata_lock:
                existing = self._bindings_by_owner.get(owner_id)
                if existing is not None:
                    if existing.thread_key != key:
                        raise RuntimeError(f"Sandbox lease owner {owner_id!r} cannot move between thread identities")
                    return existing.sandbox_id
            acquire_task = asyncio.create_task(self._provider.acquire_async(thread_id, user_id=user_id))
            try:
                sandbox_id = await asyncio.shield(acquire_task)
            except asyncio.CancelledError as cancellation:
                # Provider implementations commonly offload container startup
                # to a worker thread, which cannot be stopped by cancelling the
                # awaiter. Reconcile the eventual result before returning so an
                # unbound active sandbox is never left behind.
                try:
                    sandbox_id = await acquire_task
                except Exception:
                    raise cancellation
                await asyncio.to_thread(
                    self._release_unbound_acquire,
                    sandbox_id,
                )
                raise cancellation
            with self._metadata_lock:
                previous, release_previous = self._bind_locked(
                    owner_id,
                    sandbox_id,
                    key,
                )
            if release_previous and previous is not None:
                await asyncio.to_thread(
                    self._provider.release,
                    previous.sandbox_id,
                )
            return sandbox_id

    def release(self, owner_id: str) -> None:
        """Release one execution and park the sandbox only after the last user."""
        with self._metadata_lock:
            binding = self._bindings_by_owner.get(owner_id)
        if binding is None:
            return

        with self._serializer.hold(binding.thread_key):
            with self._metadata_lock:
                current = self._bindings_by_owner.get(owner_id)
                if current is None:
                    return
                binding, release_provider = self._remove_binding_locked(owner_id)
            assert binding is not None

            try:
                sandbox = self._provider.get(binding.sandbox_id)
                if sandbox is not None:
                    sandbox.release_command_scope(owner_id)
            finally:
                if release_provider:
                    self._provider.release(binding.sandbox_id)

    async def release_async(self, owner_id: str) -> None:
        """Release a lease without blocking the caller's event loop."""
        release_task = asyncio.create_task(asyncio.to_thread(self.release, owner_id))
        try:
            await asyncio.shield(release_task)
        except asyncio.CancelledError as cancellation:
            # Complete lifecycle cleanup before allowing cancellation to leave
            # the agent's finally block.
            try:
                await release_task
            except Exception:
                raise cancellation
            raise cancellation

    def binding_for(self, owner_id: str) -> str | None:
        """Return the sandbox bound to an owner; intended for diagnostics/tests."""
        with self._metadata_lock:
            binding = self._bindings_by_owner.get(owner_id)
            return binding.sandbox_id if binding is not None else None

    def close(self) -> None:
        """Stop accepting new transitions and release serializer workers."""
        self._serializer.close()


_manager_lock = threading.Lock()
_managers: weakref.WeakKeyDictionary[SandboxProvider, SandboxLeaseManager] = weakref.WeakKeyDictionary()


def get_sandbox_lease_manager(provider: SandboxProvider) -> SandboxLeaseManager:
    """Return the process-local lease manager associated with ``provider``."""
    with _manager_lock:
        manager = _managers.get(provider)
        if manager is None:
            manager = SandboxLeaseManager(provider)
            _managers[provider] = manager
        return manager


def discard_sandbox_lease_manager(provider: SandboxProvider) -> None:
    """Forget lease metadata when a provider singleton is detached."""
    with _manager_lock:
        manager = _managers.pop(provider, None)
    if manager is not None:
        manager.close()


def ensure_sandbox_lease_owner(context: Any) -> str | None:
    """Create one ephemeral owner id in a mutable runtime context."""
    if not isinstance(context, dict):
        return None
    existing = context.get(SANDBOX_LEASE_OWNER_CONTEXT_KEY)
    if isinstance(existing, str) and existing:
        return existing
    owner_id = f"agent:{uuid.uuid4()}"
    context[SANDBOX_LEASE_OWNER_CONTEXT_KEY] = owner_id
    return owner_id


def sandbox_lease_owner(context: Any) -> str | None:
    """Read an execution owner without creating one for direct tool callers."""
    if not isinstance(context, dict):
        return None
    owner_id = context.get(SANDBOX_LEASE_OWNER_CONTEXT_KEY)
    return owner_id if isinstance(owner_id, str) and owner_id else None


def sandbox_command_scope(context: Any) -> str | None:
    """Read the optional shell-session scope carried by subagent execution."""
    if not isinstance(context, dict):
        return None
    scope_id = context.get(SANDBOX_COMMAND_SCOPE_CONTEXT_KEY)
    return scope_id if isinstance(scope_id, str) and scope_id else None
