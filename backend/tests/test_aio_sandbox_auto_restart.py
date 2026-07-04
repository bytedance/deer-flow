"""Tests for AioSandboxProvider auto-restart of crashed containers."""

import importlib
import threading
from unittest.mock import MagicMock, patch


def _import_provider():
    return importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")


def _make_provider(*, auto_restart=True, alive=True):
    """Build a minimal AioSandboxProvider with a mock backend.

    Args:
        auto_restart: Value for the auto_restart config key.
        alive: Whether the mock backend reports containers as alive.
    """
    mod = _import_provider()
    with patch.object(mod.AioSandboxProvider, "_start_idle_checker"):
        provider = mod.AioSandboxProvider.__new__(mod.AioSandboxProvider)
        provider._config = {"auto_restart": auto_restart}
        provider._lock = threading.Lock()
        provider._sandboxes = {}
        provider._sandbox_infos = {}
        provider._thread_sandboxes = {}
        provider._thread_locks = {}
        provider._last_activity = {}
        provider._warm_pool = {}
        provider._shutdown_called = False
        provider._idle_checker_stop = threading.Event()

        backend = MagicMock()
        backend.is_alive.return_value = alive
        provider._backend = backend

    return provider, backend


def _seed_sandbox(provider, sandbox_id="dead-beef", thread_id="thread-1"):
    """Insert a sandbox into the provider's caches as if it were acquired."""
    sandbox = MagicMock()
    info = MagicMock()

    provider._sandboxes[sandbox_id] = sandbox
    provider._sandbox_infos[sandbox_id] = info
    provider._last_activity[sandbox_id] = 0.0
    if thread_id:
        provider._thread_sandboxes[thread_id] = sandbox_id

    return sandbox, info


# ── get() returns sandbox when container is alive ──────────────────────────


def test_get_returns_sandbox_when_container_alive():
    """When auto_restart is on and the container is alive, get() returns the sandbox."""
    provider, backend = _make_provider(auto_restart=True, alive=True)
    sandbox, _ = _seed_sandbox(provider)

    result = provider.get("dead-beef")

    assert result is sandbox
    backend.is_alive.assert_called_once()


def test_get_returns_sandbox_when_auto_restart_disabled():
    """When auto_restart is off, get() skips the health check entirely."""
    provider, backend = _make_provider(auto_restart=False)
    sandbox, _ = _seed_sandbox(provider)

    result = provider.get("dead-beef")

    assert result is sandbox
    backend.is_alive.assert_not_called()


# ── get() evicts dead sandbox when auto_restart is on ──────────────────────


def test_get_evicts_dead_sandbox_when_auto_restart_enabled():
    """When the container is dead and auto_restart is on, get() returns None and cleans caches."""
    provider, backend = _make_provider(auto_restart=True, alive=False)
    _, info = _seed_sandbox(provider, sandbox_id="dead-beef", thread_id="thread-1")

    result = provider.get("dead-beef")

    assert result is None
    assert "dead-beef" not in provider._sandboxes
    assert "dead-beef" not in provider._sandbox_infos
    assert "dead-beef" not in provider._last_activity
    assert "thread-1" not in provider._thread_sandboxes
    backend.destroy.assert_called_once_with(info)


def test_get_returns_dead_sandbox_when_auto_restart_disabled():
    """When auto_restart is off, get() returns the cached sandbox even if the container is dead."""
    provider, backend = _make_provider(auto_restart=False, alive=False)
    sandbox, _ = _seed_sandbox(provider)

    result = provider.get("dead-beef")

    assert result is sandbox
    # Caches are untouched
    assert "dead-beef" in provider._sandboxes


def test_get_eviction_cleans_multiple_thread_mappings():
    """A sandbox mapped to multiple thread IDs has all mappings cleaned on eviction."""
    provider, backend = _make_provider(auto_restart=True, alive=False)
    _seed_sandbox(provider, sandbox_id="sid-1", thread_id="t-a")
    # Manually add a second thread mapping to the same sandbox
    provider._thread_sandboxes["t-b"] = "sid-1"

    result = provider.get("sid-1")

    assert result is None
    assert "t-a" not in provider._thread_sandboxes
    assert "t-b" not in provider._thread_sandboxes


# ── get() does not check health for unknown sandbox IDs ────────────────────


def test_get_returns_none_for_unknown_id():
    """If the sandbox_id is not in cache, get() returns None without checking health."""
    provider, backend = _make_provider(auto_restart=True, alive=True)

    result = provider.get("nonexistent")

    assert result is None
    backend.is_alive.assert_not_called()


# ── get() handles missing sandbox_info gracefully ──────────────────────────


def test_get_handles_missing_info_gracefully():
    """If sandbox is cached but info is missing, get() skips the health check."""
    provider, backend = _make_provider(auto_restart=True, alive=False)
    sandbox = MagicMock()
    provider._sandboxes["sid-x"] = sandbox
    provider._sandbox_infos.pop("sid-x", None)  # Ensure no info
    provider._last_activity["sid-x"] = 0.0

    result = provider.get("sid-x")

    # No info → cannot call is_alive → sandbox returned as-is
    assert result is sandbox
    backend.is_alive.assert_not_called()


def test_get_liveness_check_runs_outside_provider_lock():
    """get() should not hold the provider lock while checking backend liveness."""
    provider, backend = _make_provider(auto_restart=True, alive=False)
    _seed_sandbox(provider, sandbox_id="sid-locked", thread_id="thread-1")

    def _assert_lock_not_held(_):
        assert not provider._lock.locked()
        return False

    backend.is_alive.side_effect = _assert_lock_not_held

    assert provider.get("sid-locked") is None


def test_get_still_evicts_when_backend_destroy_fails():
    """Cleanup errors should not keep stale sandbox state in memory."""
    provider, backend = _make_provider(auto_restart=True, alive=False)
    _seed_sandbox(provider, sandbox_id="sid-fail", thread_id="thread-1")
    backend.destroy.side_effect = RuntimeError("boom")

    assert provider.get("sid-fail") is None
    assert "sid-fail" not in provider._sandboxes
    assert "sid-fail" not in provider._sandbox_infos
    assert "thread-1" not in provider._thread_sandboxes
    backend.destroy.assert_called_once()


# ── Integration: eviction clears caches for recreation ─────────────────────


def test_eviction_clears_all_caches_for_recreation():
    """After eviction, all caches are clean so _acquire_internal can recreate.

    This verifies the preconditions for transparent restart: when get() evicts
    a dead sandbox, the next _acquire_internal call will find no cached entry,
    no warm-pool entry, and fall through to _create_sandbox.
    """
    provider, backend = _make_provider(auto_restart=True, alive=False)
    _seed_sandbox(provider, sandbox_id="sid-1", thread_id="thread-1")

    # Before eviction: caches populated
    assert "sid-1" in provider._sandboxes
    assert "sid-1" in provider._sandbox_infos
    assert "thread-1" in provider._thread_sandboxes

    # get() detects the dead container and evicts
    assert provider.get("sid-1") is None

    # After eviction: all caches clean
    assert "sid-1" not in provider._sandboxes
    assert "sid-1" not in provider._sandbox_infos
    assert "thread-1" not in provider._thread_sandboxes
    assert "sid-1" not in provider._warm_pool

    # _acquire_internal for the same thread would find nothing cached
    # and generate the deterministic ID, then discover fails (container
    # is gone), falling through to _create_sandbox — a fresh start.
