import asyncio
import inspect
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal

from deerflow.config import get_app_config
from deerflow.reflection import resolve_class
from deerflow.sandbox.sandbox import Sandbox


@dataclass(frozen=True, slots=True)
class SandboxReconciliationResult:
    """Exact, non-creating lookup result for durable remote operations."""

    status: Literal["found", "absent", "unknown"]
    sandbox: Sandbox | None = None
    close_after: bool = False

    @classmethod
    def found(cls, sandbox: Sandbox, *, close_after: bool = False) -> "SandboxReconciliationResult":
        return cls(status="found", sandbox=sandbox, close_after=close_after)

    @classmethod
    def absent(cls) -> "SandboxReconciliationResult":
        return cls(status="absent")

    @classmethod
    def unknown(cls) -> "SandboxReconciliationResult":
        return cls(status="unknown")


@dataclass(frozen=True, slots=True)
class SandboxReconciliationIdentity:
    """Backend and immutable instance identity persisted by durable operations."""

    provider_key: str
    backend_namespace: str
    incarnation_id: str


class SandboxProvider(ABC):
    """Abstract base class for sandbox providers"""

    uses_thread_data_mounts: bool = False
    needs_upload_permission_adjustment: bool = True

    @abstractmethod
    def acquire(self, thread_id: str | None = None, *, user_id: str | None = None) -> str:
        """Acquire a sandbox environment and return its ID.

        Returns:
            The ID of the acquired sandbox environment.
        """
        pass

    async def acquire_async(self, thread_id: str | None = None, *, user_id: str | None = None) -> str:
        """Acquire a sandbox without blocking the event loop.

        Most sandbox providers expose a synchronous lifecycle API because local
        Docker/provisioner operations are blocking. Async runtimes should call
        this method so those blocking operations run in a worker thread instead
        of stalling the event loop.
        """
        return await asyncio.to_thread(self.acquire, thread_id, user_id=user_id)

    @abstractmethod
    def get(self, sandbox_id: str) -> Sandbox | None:
        """Get a sandbox environment by ID.

        Args:
            sandbox_id: The ID of the sandbox environment to retain.
        """
        pass

    def reconciliation_provider_key(self) -> str:
        """Return a stable, non-secret provider type key for durable journals."""
        provider_type = type(self)
        return f"{provider_type.__module__}.{provider_type.__qualname__}"

    def prepare_sandbox_reconciliation_identity(
        self,
        sandbox_id: str,
    ) -> SandboxReconciliationIdentity | None:
        """Return a restart-safe identity, or ``None`` to disable durable mutation.

        A provider must override this only when it can distinguish both its
        backing deployment/account and an immutable sandbox incarnation. The
        fail-closed default prevents a deterministic raw ID from being rebound
        to a different backend or replacement instance after restart.
        """
        del sandbox_id
        return None

    def reconnect_sandbox_for_reconciliation(
        self,
        sandbox_id: str,
        *,
        thread_id: str,
        user_id: str | None,
        identity: SandboxReconciliationIdentity,
    ) -> SandboxReconciliationResult:
        """Resolve exactly *sandbox_id* without creating or redirecting it.

        Providers that can discover an old instance or prove it terminally
        absent should override this method. The conservative default always
        remains ``unknown``.
        """
        del sandbox_id, thread_id, user_id, identity
        return SandboxReconciliationResult.unknown()

    @abstractmethod
    def release(self, sandbox_id: str) -> None:
        """Release a sandbox environment.

        Args:
            sandbox_id: The ID of the sandbox environment to destroy.
        """
        pass

    def reset(self) -> None:
        """Clear cached state that survives provider instance replacement.

        Provider overrides can release resources and make the instance unusable.
        """
        pass


_default_sandbox_provider: SandboxProvider | None = None
# Guards every read and write of `_default_sandbox_provider`. The singleton is
# reachable from more than one OS thread (e.g. the main event loop and the Feishu
# channel thread, which runs its own loop), so a bare check-then-create can double
# initialize the provider, and an unsynchronized reset/shutdown racing a get can
# hand a caller `None` or a torn instance. Every access to the global below takes
# this lock, including the read+return in `get_sandbox_provider()`.
#
# The lock guards only the reference swap. Provider callbacks (`__init__`,
# `reset()`, `shutdown()`) and the dynamic import in `resolve_class()` run
# *outside* the lock: they are plugin-supplied (`config.sandbox.use` resolves to
# an arbitrary class) and may be slow or, worse, re-enter these lifecycle
# functions. Holding a non-reentrant `threading.Lock` across them would
# self-deadlock such a provider and would block every concurrent `get()` during a
# slow teardown. Keeping callbacks off the lock avoids both.
_provider_lock = threading.Lock()


def get_sandbox_provider(*, app_config=None, **kwargs) -> SandboxProvider:
    """Get the sandbox provider singleton.

    Returns a cached singleton instance. Use `reset_sandbox_provider()` to clear
    the cache, or `shutdown_sandbox_provider()` to properly shutdown and clear.
    Embedded callers may pass their already-resolved ``app_config`` so cold
    singleton construction uses the same configuration as the caller.

    Returns:
        A sandbox provider instance.
    """
    global _default_sandbox_provider
    # Fast path: a single locked read so a concurrent reset/shutdown can't null
    # the global between the check and the return.
    with _provider_lock:
        if _default_sandbox_provider is not None:
            return _default_sandbox_provider

    # Cold start. Resolve + construct outside the lock: the import and the
    # provider constructor are plugin code and must not run under a non-reentrant
    # lock. The construction may race another caller; we reconcile under the lock.
    config = app_config or get_app_config()
    cls = resolve_class(config.sandbox.use, SandboxProvider)
    provider = cls(**kwargs)

    with _provider_lock:
        if _default_sandbox_provider is None:
            _default_sandbox_provider = provider
            return provider
        # We lost the install race: another thread got there first. `winner` is
        # read under the same lock, so it is always a live instance, never None.
        winner = _default_sandbox_provider

    # Discard the instance we just built (outside the lock). For providers with
    # side-effectful constructors (e.g. AioSandboxProvider starts an idle-checker
    # thread), this tears down the orphan so it does not leak — issue #3721.
    if hasattr(provider, "shutdown"):
        provider.shutdown()
    return winner


def reset_sandbox_provider() -> None:
    """Reset the sandbox provider singleton.

    This clears the cached instance without calling shutdown directly.
    The next call to `get_sandbox_provider()` will create a new instance.
    Useful for testing or when switching configurations.

    Providers can override `reset()` to clear any module-level state they keep
    alive across instances (for example, `LocalSandboxProvider`'s cached
    `LocalSandbox` singleton). Without it, config/mount changes would not take
    effect on the next acquire().

    A provider override can release active sandboxes during reset.
    Otherwise, active sandboxes become orphaned.
    Do not reuse the detached provider after reset.
    Use `shutdown_sandbox_provider()` for proper cleanup.
    """
    global _default_sandbox_provider
    # Detach the reference under the lock, then run the provider's `reset()`
    # callback outside it (see the `_provider_lock` note).
    with _provider_lock:
        provider = _default_sandbox_provider
        _default_sandbox_provider = None
    if provider is not None:
        provider.reset()


def shutdown_sandbox_provider() -> None:
    """Shutdown and reset the sandbox provider.

    This properly shuts down the provider (releasing all sandboxes)
    before clearing the singleton. Call this when the application
    is shutting down or when you need to completely reset the sandbox system.
    """
    global _default_sandbox_provider
    # Detach the reference under the lock, then run the (potentially slow)
    # `shutdown()` callback outside it (see the `_provider_lock` note).
    with _provider_lock:
        provider = _default_sandbox_provider
        _default_sandbox_provider = None
    if provider is not None and hasattr(provider, "shutdown"):
        provider.shutdown()


def set_sandbox_provider(provider: SandboxProvider) -> None:
    """Set a custom sandbox provider instance.

    This allows injecting a custom or mock provider for testing purposes.

    Note: any previously installed provider is replaced but not shut down; the
    caller owns the lifecycle of the instance it is overwriting.

    Args:
        provider: The SandboxProvider instance to use.
    """
    global _default_sandbox_provider
    with _provider_lock:
        _default_sandbox_provider = provider


def sandbox_provider_uses_thread_data_mounts(
    provider: SandboxProvider,
    *,
    refresh: bool = True,
) -> bool:
    """Return one provider mount-mode decision, optionally refreshing it first."""
    # ``MagicMock`` and some proxy providers fabricate arbitrary attributes from
    # ``__getattr__``.  Only opt into the extended contract when the attribute
    # really exists on the instance or its type; otherwise the legacy boolean is
    # the source of truth.
    static_mode_resolver = inspect.getattr_static(provider, "thread_data_mounts_mode", None)
    mode_resolver = getattr(provider, "thread_data_mounts_mode", None) if static_mode_resolver is not None else None
    if callable(mode_resolver):
        return bool(mode_resolver(refresh=refresh))
    if refresh:
        static_refresher = inspect.getattr_static(provider, "refresh_thread_data_mount_capabilities", None)
        refresher = getattr(provider, "refresh_thread_data_mount_capabilities", None) if static_refresher is not None else None
        if callable(refresher):
            refresher()
    return bool(getattr(provider, "uses_thread_data_mounts", False))


def sandbox_provider_sandbox_uses_thread_data_mounts(
    provider: SandboxProvider,
    sandbox_id: str,
) -> bool:
    """Return the immutable mount mode recorded for one acquired sandbox."""
    static_mode_resolver = inspect.getattr_static(provider, "sandbox_uses_thread_data_mounts", None)
    mode_resolver = getattr(provider, "sandbox_uses_thread_data_mounts", None) if static_mode_resolver is not None else None
    if callable(mode_resolver):
        return bool(mode_resolver(sandbox_id))
    return sandbox_provider_uses_thread_data_mounts(provider, refresh=False)


async def sandbox_provider_uses_thread_data_mounts_async(
    provider: SandboxProvider,
    *,
    refresh: bool = True,
) -> bool:
    """Async mount-mode decision that keeps capability probes off the event loop."""
    return await asyncio.to_thread(
        sandbox_provider_uses_thread_data_mounts,
        provider,
        refresh=refresh,
    )
