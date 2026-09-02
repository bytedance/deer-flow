"""Execution-scoped leases for process-local sandbox use.

Provider ownership stores answer which Gateway instance may reap a remote
sandbox.  This module answers a different question: which concurrently running
agent executions inside one Gateway are still using the provider's active
client.  The last execution lease is the only one allowed to call
``SandboxProvider.release``.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from deerflow.sandbox.acquire_serialization import AcquireSerializer

if TYPE_CHECKING:
    from deerflow.sandbox.sandbox_provider import SandboxProvider

logger = logging.getLogger(__name__)


SANDBOX_LEASE_OWNER_CONTEXT_KEY = "sandbox_lease_owner_id"
SANDBOX_COMMAND_SCOPE_CONTEXT_KEY = "sandbox_command_scope_id"
SANDBOX_SERVER_OWNED_CONTEXT_KEYS = frozenset(
    {
        SANDBOX_LEASE_OWNER_CONTEXT_KEY,
        SANDBOX_COMMAND_SCOPE_CONTEXT_KEY,
    }
)


async def _drain_task_after_cancellation[T](task: asyncio.Task[T]) -> T:
    """Wait for ``task`` even if the current task is cancelled again.

    Lifecycle reconciliation must keep its serializer until provider work has
    finished. Repeated cancellation is therefore remembered by the caller but
    cannot propagate into the reconciliation task or interrupt this drain.
    """
    while True:
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            if task.done():
                return task.result()


async def run_sync_lifecycle_operation[T](func: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
    """Run blocking client work without letting cancellation outlive it.

    ``asyncio.to_thread`` cannot stop its worker when the awaiting task is
    cancelled. Sandbox cleanup must therefore wait for the worker before an
    outer execution/request fence is allowed to release its client holder.
    Repeated cancellation is remembered and propagated only after the worker
    has terminated; a late worker failure is logged without replacing the
    caller's cancellation.
    """
    operation_task = asyncio.create_task(asyncio.to_thread(func, *args, **kwargs))
    try:
        return await asyncio.shield(operation_task)
    except asyncio.CancelledError as cancellation:
        try:
            await _drain_task_after_cancellation(operation_task)
        except Exception:
            logger.warning(
                "Cancelled sandbox client operation failed while draining",
                exc_info=True,
            )
        raise cancellation


@dataclass(slots=True)
class SandboxClientLease:
    """One bounded caller's process-local hold on a sandbox client."""

    sandbox: object | None
    sandbox_id: str
    owner_id: str | None
    provider: SandboxProvider

    async def release(self) -> None:
        """Drop this holder after its final sandbox operation has drained."""
        if self.owner_id is None:
            return
        owner_id = self.owner_id
        self.owner_id = None
        await get_sandbox_lease_manager(self.provider).release_async(owner_id)

    async def run_sync[T](self, func: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
        """Run one blocking client operation inside this lease boundary."""
        return await run_sync_lifecycle_operation(func, *args, **kwargs)


async def acquire_sandbox_client_lease(
    provider: SandboxProvider,
    thread_id: str,
    *,
    user_id: str,
    owner_prefix: str,
    release_on_last: bool = True,
) -> SandboxClientLease:
    """Acquire a unique holder and resolve its process-local client.

    This is the non-HTTP counterpart of Gateway request leases. Callers must
    keep the returned object through their last sandbox operation and release
    it in ``finally``. ``release_on_last=False`` is appropriate for upload
    synchronization: the upload fences a concurrent run but does not itself
    request that the warm sandbox be parked.
    """
    owner_id = f"{owner_prefix}:{uuid.uuid4()}"
    manager = get_sandbox_lease_manager(provider)
    sandbox_id = await manager.acquire_async(
        owner_id,
        thread_id,
        user_id=user_id,
        release_on_last=release_on_last,
    )
    try:
        sandbox = provider.get(sandbox_id)
    except BaseException:
        await manager.release_async(owner_id)
        raise
    return SandboxClientLease(
        sandbox=sandbox,
        sandbox_id=sandbox_id,
        owner_id=owner_id,
        provider=provider,
    )


@dataclass(frozen=True)
class _LeaseBinding:
    sandbox_id: str
    thread_key: tuple[str, str]
    release_on_last: bool = True


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
        self._release_pending_by_sandbox: set[str] = set()

    @staticmethod
    def _thread_key(thread_id: str, user_id: str) -> tuple[str, str]:
        return user_id, thread_id

    def _remove_binding_locked(
        self,
        owner_id: str,
        *,
        request_release: bool = True,
    ) -> tuple[_LeaseBinding | None, bool]:
        binding = self._bindings_by_owner.pop(owner_id, None)
        if binding is None:
            return None, False
        if request_release and binding.release_on_last:
            # Closing responsibility belongs to the sandbox lifecycle, not to
            # whichever holder happens to finish last. A normal owner may
            # leave while a fork/upload borrower is still using the client;
            # remember its close request until every holder is gone.
            self._release_pending_by_sandbox.add(binding.sandbox_id)
        owners = self._owners_by_sandbox.get(binding.sandbox_id)
        if owners is None:
            release_provider = binding.sandbox_id in self._release_pending_by_sandbox
            self._release_pending_by_sandbox.discard(binding.sandbox_id)
            return binding, release_provider
        owners.discard(owner_id)
        if owners:
            return binding, False
        self._owners_by_sandbox.pop(binding.sandbox_id, None)
        release_provider = binding.sandbox_id in self._release_pending_by_sandbox
        self._release_pending_by_sandbox.discard(binding.sandbox_id)
        return binding, release_provider

    def _bind_locked(
        self,
        owner_id: str,
        sandbox_id: str,
        key: tuple[str, str],
        *,
        release_on_last: bool,
    ) -> tuple[_LeaseBinding | None, bool]:
        existing = self._bindings_by_owner.get(owner_id)
        if existing is not None and existing.thread_key != key:
            raise RuntimeError(f"Sandbox lease owner {owner_id!r} cannot move between thread identities")
        if existing is not None and existing.sandbox_id == sandbox_id:
            # Ownership is monotonic for one execution. A normal owner may
            # later encounter a fork-restored view, but must not lose its
            # responsibility to park the provider. A borrowed owner can be
            # upgraded when it later performs a normal acquisition.
            if release_on_last and not existing.release_on_last:
                self._bindings_by_owner[owner_id] = _LeaseBinding(
                    sandbox_id=sandbox_id,
                    thread_key=key,
                    release_on_last=True,
                )
            return None, False

        release_previous = False
        previous: _LeaseBinding | None = None
        if existing is not None:
            previous, release_previous = self._remove_binding_locked(owner_id)

        self._bindings_by_owner[owner_id] = _LeaseBinding(
            sandbox_id=sandbox_id,
            thread_key=key,
            release_on_last=release_on_last,
        )
        self._owners_by_sandbox.setdefault(sandbox_id, set()).add(owner_id)

        return previous, release_previous

    def _release_unbound_acquire(self, sandbox_id: str) -> None:
        """Undo a cancelled acquire when no admitted execution uses its result.

        The caller must still hold the serializer for the originating thread
        key.  That makes the owner check and provider release one transition:
        another execution for the same thread cannot bind the sandbox between
        them.
        """
        with self._metadata_lock:
            has_owners = bool(self._owners_by_sandbox.get(sandbox_id))
        if not has_owners:
            self._provider.release(sandbox_id)

    def _active_owner_binding(
        self,
        owner_id: str,
        key: tuple[str, str],
        *,
        release_on_last: bool,
    ) -> str | None:
        """Return one live owner binding while the caller holds ``key``.

        Middleware may retain a checkpointed id before the provider discovers
        that its local client is gone. Treat that owner binding as stale so a
        later acquire rebuilds it instead of preserving an unusable id.
        """
        with self._metadata_lock:
            existing = self._bindings_by_owner.get(owner_id)
        if existing is None:
            return None
        if existing.thread_key != key:
            raise RuntimeError(f"Sandbox lease owner {owner_id!r} cannot move between thread identities")
        if self._provider.get(existing.sandbox_id) is not None:
            if release_on_last and not existing.release_on_last:
                with self._metadata_lock:
                    if self._bindings_by_owner.get(owner_id) == existing:
                        self._bindings_by_owner[owner_id] = _LeaseBinding(
                            sandbox_id=existing.sandbox_id,
                            thread_key=existing.thread_key,
                            release_on_last=True,
                        )
            return existing.sandbox_id

        with self._metadata_lock:
            if self._bindings_by_owner.get(owner_id) == existing:
                self._remove_binding_locked(owner_id, request_release=False)
        return None

    def _acquire_and_bind(
        self,
        owner_id: str,
        thread_id: str,
        user_id: str,
        key: tuple[str, str],
        *,
        release_on_last: bool,
    ) -> str:
        sandbox_id = self._provider.acquire(thread_id, user_id=user_id)
        with self._metadata_lock:
            previous, release_previous = self._bind_locked(
                owner_id,
                sandbox_id,
                key,
                release_on_last=release_on_last,
            )
        if release_previous and previous is not None:
            self._provider.release(previous.sandbox_id)
        return sandbox_id

    async def _acquire_and_bind_async(
        self,
        owner_id: str,
        thread_id: str,
        user_id: str,
        key: tuple[str, str],
        *,
        release_on_last: bool,
    ) -> str:
        acquire_task = asyncio.create_task(self._provider.acquire_async(thread_id, user_id=user_id))
        try:
            sandbox_id = await asyncio.shield(acquire_task)
        except asyncio.CancelledError as cancellation:
            # Provider implementations commonly offload container startup to a
            # worker thread, which cannot be stopped by cancelling the awaiter.
            # Reconcile the result before relinquishing the serializer.
            try:
                sandbox_id = await _drain_task_after_cancellation(acquire_task)
            except Exception:
                logger.warning(
                    "Cancelled sandbox acquire failed during reconciliation",
                    exc_info=True,
                )
                raise cancellation
            rollback_task = asyncio.create_task(
                asyncio.to_thread(
                    self._release_unbound_acquire,
                    sandbox_id,
                )
            )
            try:
                await _drain_task_after_cancellation(rollback_task)
            except Exception:
                logger.warning(
                    "Cancelled sandbox acquire rollback failed during reconciliation",
                    exc_info=True,
                )
            raise cancellation
        with self._metadata_lock:
            previous, release_previous = self._bind_locked(
                owner_id,
                sandbox_id,
                key,
                release_on_last=release_on_last,
            )
        if release_previous and previous is not None:
            await asyncio.to_thread(
                self._provider.release,
                previous.sandbox_id,
            )
        return sandbox_id

    def retain(
        self,
        owner_id: str,
        sandbox_id: str,
        *,
        thread_id: str,
        user_id: str,
        release_on_last: bool = True,
    ) -> None:
        """Attach an execution to an inherited or checkpointed sandbox id.

        ``release_on_last=False`` is for a borrower: it fences the client and
        owns command-scope cleanup without requesting a park itself. A normal
        owner's earlier park request can still be deferred until it drains.
        """
        key = self._thread_key(thread_id, user_id)
        with self._serializer.hold(key):
            with self._metadata_lock:
                previous, release_previous = self._bind_locked(
                    owner_id,
                    sandbox_id,
                    key,
                    release_on_last=release_on_last,
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
        release_on_last: bool = True,
    ) -> None:
        """Async attach without blocking the event loop on a lifecycle lock."""
        key = self._thread_key(thread_id, user_id)
        async with self._serializer.hold_async(key):
            with self._metadata_lock:
                previous, release_previous = self._bind_locked(
                    owner_id,
                    sandbox_id,
                    key,
                    release_on_last=release_on_last,
                )
            if release_previous and previous is not None:
                await asyncio.to_thread(
                    self._provider.release,
                    previous.sandbox_id,
                )

    def acquire(
        self,
        owner_id: str,
        thread_id: str,
        *,
        user_id: str,
        release_on_last: bool = True,
    ) -> str:
        """Acquire and bind a sandbox, idempotently for one execution owner."""
        key = self._thread_key(thread_id, user_id)
        with self._serializer.hold(key):
            existing_sandbox_id = self._active_owner_binding(
                owner_id,
                key,
                release_on_last=release_on_last,
            )
            if existing_sandbox_id is not None:
                return existing_sandbox_id
            return self._acquire_and_bind(
                owner_id,
                thread_id,
                user_id,
                key,
                release_on_last=release_on_last,
            )

    def reuse_or_acquire(
        self,
        owner_id: str,
        sandbox_id: str,
        *,
        thread_id: str,
        user_id: str,
        release_on_last: bool = True,
        acquire_release_on_last: bool = True,
    ) -> str:
        """Atomically retain a live persisted sandbox or acquire a replacement.

        A fork-restored live client is borrowed with ``release_on_last=False``;
        if that persisted client is gone, its freshly acquired replacement is
        owned normally unless ``acquire_release_on_last`` is also disabled.
        """
        key = self._thread_key(thread_id, user_id)
        with self._serializer.hold(key):
            existing_sandbox_id = self._active_owner_binding(
                owner_id,
                key,
                release_on_last=release_on_last,
            )
            if existing_sandbox_id is not None:
                return existing_sandbox_id

            if self._provider.get(sandbox_id) is not None:
                with self._metadata_lock:
                    previous, release_previous = self._bind_locked(
                        owner_id,
                        sandbox_id,
                        key,
                        release_on_last=release_on_last,
                    )
                if release_previous and previous is not None:
                    self._provider.release(previous.sandbox_id)
                return sandbox_id

            return self._acquire_and_bind(
                owner_id,
                thread_id,
                user_id,
                key,
                release_on_last=acquire_release_on_last,
            )

    async def acquire_async(
        self,
        owner_id: str,
        thread_id: str,
        *,
        user_id: str,
        release_on_last: bool = True,
    ) -> str:
        """Async acquire while preserving the provider's own async hook."""
        key = self._thread_key(thread_id, user_id)
        async with self._serializer.hold_async(key):
            existing_sandbox_id = self._active_owner_binding(
                owner_id,
                key,
                release_on_last=release_on_last,
            )
            if existing_sandbox_id is not None:
                return existing_sandbox_id
            return await self._acquire_and_bind_async(
                owner_id,
                thread_id,
                user_id,
                key,
                release_on_last=release_on_last,
            )

    async def reuse_or_acquire_async(
        self,
        owner_id: str,
        sandbox_id: str,
        *,
        thread_id: str,
        user_id: str,
        release_on_last: bool = True,
        acquire_release_on_last: bool = True,
    ) -> str:
        """Async atomic retain-or-replace transition for a persisted sandbox."""
        key = self._thread_key(thread_id, user_id)
        async with self._serializer.hold_async(key):
            existing_sandbox_id = self._active_owner_binding(
                owner_id,
                key,
                release_on_last=release_on_last,
            )
            if existing_sandbox_id is not None:
                return existing_sandbox_id

            if self._provider.get(sandbox_id) is not None:
                with self._metadata_lock:
                    previous, release_previous = self._bind_locked(
                        owner_id,
                        sandbox_id,
                        key,
                        release_on_last=release_on_last,
                    )
                if release_previous and previous is not None:
                    await asyncio.to_thread(
                        self._provider.release,
                        previous.sandbox_id,
                    )
                return sandbox_id

            return await self._acquire_and_bind_async(
                owner_id,
                thread_id,
                user_id,
                key,
                release_on_last=acquire_release_on_last,
            )

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
                await _drain_task_after_cancellation(release_task)
            except Exception:
                logger.warning(
                    "Cancelled sandbox release failed during reconciliation",
                    exc_info=True,
                )
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
_managers: dict[int, tuple[SandboxProvider, SandboxLeaseManager]] = {}


def get_sandbox_lease_manager(provider: SandboxProvider) -> SandboxLeaseManager:
    """Return the process-local lease manager for this provider object.

    Provider implementations are not required to be hashable, and distinct
    instances that compare equal must not share lifecycle state. Keep a strong
    identity entry until the provider is explicitly detached; the manager
    already owns the provider strongly, so a weak-key registry would not make
    the lifecycle shorter.
    """
    provider_id = id(provider)
    with _manager_lock:
        entry = _managers.get(provider_id)
        if entry is not None and entry[0] is provider:
            return entry[1]
        manager = SandboxLeaseManager(provider)
        _managers[provider_id] = (provider, manager)
        return manager


def discard_sandbox_lease_manager(provider: SandboxProvider) -> None:
    """Forget lease metadata when a provider singleton is detached."""
    provider_id = id(provider)
    with _manager_lock:
        entry = _managers.get(provider_id)
        if entry is None or entry[0] is not provider:
            manager = None
        else:
            _, manager = _managers.pop(provider_id)
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


def _sandbox_execution_lease(context: Any) -> tuple[str, str] | None:
    """Return a bound execution lease without initializing a provider."""
    owner_id = sandbox_lease_owner(context)
    if owner_id is None or not isinstance(context, dict):
        return None
    sandbox_id = context.get("sandbox_id")
    if not isinstance(sandbox_id, str) or not sandbox_id:
        return None
    return owner_id, sandbox_id


def release_sandbox_execution_lease(context: Any) -> None:
    """Release a lead/embedded execution lease at its outer lifecycle fence."""
    lease = _sandbox_execution_lease(context)
    if lease is None:
        return

    # Import lazily so runs that never touch a sandbox do not initialize the
    # provider during terminal cleanup.
    from deerflow.sandbox.sandbox_provider import get_sandbox_provider

    owner_id, _sandbox_id = lease
    provider = get_sandbox_provider()
    get_sandbox_lease_manager(provider).release(owner_id)


async def release_sandbox_execution_lease_async(context: Any) -> None:
    """Async counterpart to :func:`release_sandbox_execution_lease`."""
    lease = _sandbox_execution_lease(context)
    if lease is None:
        return

    from deerflow.sandbox.sandbox_provider import get_sandbox_provider

    owner_id, _sandbox_id = lease
    provider = get_sandbox_provider()
    await get_sandbox_lease_manager(provider).release_async(owner_id)
