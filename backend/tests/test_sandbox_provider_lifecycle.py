"""Concurrency regression tests for the sandbox provider singleton lifecycle.

These guard the fix for the unsynchronized check-then-create in
``get_sandbox_provider`` and the unlocked ``reset``/``shutdown``/``set`` paths:
before the lock was added, concurrent cold-start callers could each construct a
separate provider and overwrite the global, and a ``reset``/``shutdown`` racing
a ``get`` could hand a caller ``None`` or a torn-down instance.

Each test resets the process-global singleton on entry and in a ``finally`` on
exit, so tests never leak a provider into one another.
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


class ShutdownSandboxProvider(SlowSandboxProvider):
    """Provider that also exposes ``shutdown``/``reset``, to exercise the paths
    that run a provider callback outside ``_provider_lock``.

    Every constructed instance registers itself in ``registry`` so a test can
    assert which instances were later torn down.
    """

    registry: list["ShutdownSandboxProvider"] = []
    registry_lock = threading.Lock()

    def __init__(self) -> None:
        super().__init__()
        self.shutdown_calls = 0
        self.reset_calls = 0
        with self.registry_lock:
            type(self).registry.append(self)

    def shutdown(self) -> None:
        # A non-trivial teardown: the fix runs this outside the lock, so a
        # concurrent get() must not be blocked or torn by it.
        time.sleep(0.02)
        self.shutdown_calls += 1

    def reset(self) -> None:
        self.reset_calls += 1


class _SandboxConfig:
    use = "SlowSandboxProvider"


class _AppConfig:
    sandbox = _SandboxConfig()


def _patch_provider_resolution(monkeypatch, cls=SlowSandboxProvider) -> None:
    monkeypatch.setattr(sandbox_provider, "get_app_config", lambda: _AppConfig())
    monkeypatch.setattr(sandbox_provider, "resolve_class", lambda *args: cls)


def test_get_sandbox_provider_installs_one_singleton_under_concurrent_access(monkeypatch):
    """Eight threads racing on a cold start must all observe the *same* installed
    instance.

    Construction runs outside ``_provider_lock`` (so plugin ``__init__``/import
    never runs under a non-reentrant lock), so racing callers may each build a
    candidate; the contract is that exactly one is installed and every caller
    sees it. The losers are torn down — see
    ``test_losing_cold_start_racer_shuts_down_its_orphan``.
    """
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
        # Every caller sees the one installed singleton, whichever candidate won.
        assert len({id(provider) for provider in providers}) == 1
        installed = sandbox_provider.get_sandbox_provider()
        assert all(p is installed for p in providers)
    finally:
        sandbox_provider.reset_sandbox_provider()


def test_reset_racing_get_of_live_singleton_never_returns_none_or_torn(monkeypatch):
    """A reset racing concurrent gets of a *live* singleton must never hand back
    ``None`` or a half-built instance: every returned value is a real provider.

    The singleton is populated *before* the barrier so the resetter tears down a
    live instance while the getters read it — the interleaving that the unlocked
    get-read path could turn into a ``None``/torn return.
    """
    sandbox_provider.reset_sandbox_provider()
    SlowSandboxProvider.instances_created = 0
    _patch_provider_resolution(monkeypatch)

    # Populate the singleton up front so the reset races a live instance.
    sandbox_provider.get_sandbox_provider()

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
        # Whatever each getter saw — the original singleton or a freshly rebuilt
        # one after the reset — it must be a real provider, never None and never
        # a partially constructed object.
        assert results, "every getter recorded a result"
        assert all(isinstance(p, SlowSandboxProvider) for p in results)
    finally:
        sandbox_provider.reset_sandbox_provider()


def test_shutdown_racing_get_of_live_singleton_never_returns_none_or_torn(monkeypatch):
    """Same guarantee as the reset case, for ``shutdown_sandbox_provider()``.

    Uses a provider with a real (non-trivial) ``shutdown()`` so the teardown
    runs outside the lock while getters read the global concurrently.
    """
    sandbox_provider.reset_sandbox_provider()
    SlowSandboxProvider.instances_created = 0
    _patch_provider_resolution(monkeypatch, cls=ShutdownSandboxProvider)

    sandbox_provider.get_sandbox_provider()  # live singleton before the race

    results: list[object] = []
    results_lock = threading.Lock()
    barrier = threading.Barrier(5)

    def getter() -> None:
        barrier.wait()
        provider = sandbox_provider.get_sandbox_provider()
        with results_lock:
            results.append(provider)

    def shutter() -> None:
        barrier.wait()
        sandbox_provider.shutdown_sandbox_provider()

    threads = [threading.Thread(target=getter) for _ in range(4)]
    threads.append(threading.Thread(target=shutter))
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    try:
        assert results
        assert all(isinstance(p, ShutdownSandboxProvider) for p in results)
    finally:
        sandbox_provider.reset_sandbox_provider()


def test_set_racing_get_never_returns_none_or_torn(monkeypatch):
    """``set_sandbox_provider()`` racing concurrent gets must never expose a
    ``None`` global: every getter sees a fully constructed provider."""
    sandbox_provider.reset_sandbox_provider()
    SlowSandboxProvider.instances_created = 0
    _patch_provider_resolution(monkeypatch)

    sandbox_provider.get_sandbox_provider()  # live singleton before the race
    injected = SlowSandboxProvider()

    results: list[object] = []
    results_lock = threading.Lock()
    barrier = threading.Barrier(5)

    def getter() -> None:
        barrier.wait()
        provider = sandbox_provider.get_sandbox_provider()
        with results_lock:
            results.append(provider)

    def setter() -> None:
        barrier.wait()
        sandbox_provider.set_sandbox_provider(injected)

    threads = [threading.Thread(target=getter) for _ in range(4)]
    threads.append(threading.Thread(target=setter))
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    try:
        assert results
        assert all(isinstance(p, SlowSandboxProvider) for p in results)
    finally:
        sandbox_provider.reset_sandbox_provider()


def test_losing_cold_start_racer_shuts_down_its_orphan(monkeypatch):
    """When two cold-start callers race, the loser must shut down the instance it
    built so a side-effectful constructor (idle-checker thread, etc.) does not
    leak — the core consequence in issue #3721.

    With ``ShutdownSandboxProvider`` every constructed-but-discarded instance has
    its ``shutdown()`` invoked, so exactly ``(constructed - 1)`` of them are torn
    down (the single winner is kept).
    """
    sandbox_provider.reset_sandbox_provider()
    ShutdownSandboxProvider.instances_created = 0
    ShutdownSandboxProvider.registry = []
    _patch_provider_resolution(monkeypatch, cls=ShutdownSandboxProvider)

    n_threads = 8
    providers: list[ShutdownSandboxProvider] = []
    providers_lock = threading.Lock()
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
        winner = sandbox_provider.get_sandbox_provider()
        # Exactly one instance is installed and returned to every caller.
        assert len({id(p) for p in providers}) == 1
        assert all(p is winner for p in providers)
        # The winner is never torn down...
        assert winner.shutdown_calls == 0
        # ...and every loser that was constructed had shutdown() called on it
        # exactly once.
        losers = [inst for inst in ShutdownSandboxProvider.registry if inst is not winner]
        assert len(losers) == ShutdownSandboxProvider.instances_created - 1
        assert all(inst.shutdown_calls == 1 for inst in losers)
    finally:
        sandbox_provider.reset_sandbox_provider()
