"""Concurrency regression tests for the sandbox provider singleton lifecycle.

These guard the fix for the unsynchronized check-then-create in
``get_sandbox_provider`` and the unlocked ``reset``/``shutdown``/``set`` paths:
before the lock was added, concurrent cold-start callers could each construct a
separate provider and overwrite the global, and a ``reset``/``shutdown`` racing
an in-flight create could clear or tear down an instance mid-construction.
"""

import threading
import time

import deerflow.sandbox.sandbox_provider as sandbox_provider
from deerflow.sandbox.sandbox import Sandbox
from deerflow.sandbox.sandbox_provider import SandboxProvider


class SlowSandboxProvider(SandboxProvider):
    """Provider whose constructor is slow, to widen the check-then-create gap."""

    instances_created = 0
    instances_lock = threading.Lock()

    def __init__(self) -> None:
        time.sleep(0.05)
        with self.instances_lock:
            type(self).instances_created += 1

    def acquire(self, thread_id: str | None = None) -> str:
        return "sandbox-id"

    def get(self, sandbox_id: str) -> Sandbox | None:
        return None

    def release(self, sandbox_id: str) -> None:
        pass


class _SandboxConfig:
    use = "SlowSandboxProvider"


class _AppConfig:
    sandbox = _SandboxConfig()


def _patch_provider_resolution(monkeypatch) -> None:
    monkeypatch.setattr(sandbox_provider, "get_app_config", lambda: _AppConfig())
    monkeypatch.setattr(sandbox_provider, "resolve_class", lambda *args: SlowSandboxProvider)


def test_get_sandbox_provider_initializes_singleton_once_under_concurrent_access(monkeypatch):
    """Eight threads racing on a cold start must observe exactly one instance."""
    sandbox_provider.reset_sandbox_provider()
    SlowSandboxProvider.instances_created = 0
    _patch_provider_resolution(monkeypatch)

    n_threads = 8
    providers: list[SandboxProvider] = []
    providers_lock = threading.Lock()
    # Barrier makes all threads enter get_sandbox_provider() at the same moment,
    # so the race is triggered deterministically rather than probabilistically.
    barrier = threading.Barrier(n_threads)

    def get_provider() -> None:
        barrier.wait()
        provider = sandbox_provider.get_sandbox_provider()
        with providers_lock:
            providers.append(provider)

    threads = [threading.Thread(target=get_provider) for _ in range(n_threads)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    try:
        assert len({id(provider) for provider in providers}) == 1
        assert SlowSandboxProvider.instances_created == 1
    finally:
        sandbox_provider.reset_sandbox_provider()


def test_reset_racing_get_does_not_tear_down_returned_instance(monkeypatch):
    """A reset racing concurrent gets must never hand back a half-built or stale
    singleton: every returned instance must be a fully constructed provider."""
    sandbox_provider.reset_sandbox_provider()
    SlowSandboxProvider.instances_created = 0
    _patch_provider_resolution(monkeypatch)

    results: list[object] = []
    results_lock = threading.Lock()
    barrier = threading.Barrier(5)

    def getter() -> None:
        barrier.wait()
        provider = sandbox_provider.get_sandbox_provider()
        with results_lock:
            results.append(provider)

    def resetter() -> None:
        barrier.wait()
        sandbox_provider.reset_sandbox_provider()

    threads = [threading.Thread(target=getter) for _ in range(4)]
    threads.append(threading.Thread(target=resetter))
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    try:
        # Whatever each getter saw, it must be a real provider instance, never
        # None and never a partially constructed object.
        assert all(isinstance(p, SlowSandboxProvider) for p in results)
    finally:
        sandbox_provider.reset_sandbox_provider()
