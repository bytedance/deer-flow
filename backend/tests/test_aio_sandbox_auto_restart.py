"""Regression tests for configurable AIO cached-container health checks."""

import importlib
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from test_aio_sandbox_provider import _make_provider_with_active_sandbox

from deerflow.config.sandbox_config import SandboxConfig


@pytest.mark.parametrize("auto_restart", [True, False])
def test_load_config_preserves_auto_restart(auto_restart, monkeypatch):
    module = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    app_config = SimpleNamespace(
        sandbox=SandboxConfig(use="deerflow.community.aio_sandbox:AioSandboxProvider", auto_restart=auto_restart),
        stream_bridge=None,
    )
    monkeypatch.setattr(module, "get_app_config", lambda: app_config)
    provider = module.AioSandboxProvider.__new__(module.AioSandboxProvider)

    assert provider._load_config()["auto_restart"] is auto_restart


@pytest.mark.parametrize(
    ("auto_restart", "alive", "expected_checks", "expected_alive"),
    [(True, True, 1, True), (True, False, 1, False), (False, False, 0, True)],
)
def test_cached_container_health_check_respects_auto_restart(auto_restart, alive, expected_checks, expected_alive):
    module = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    provider = module.AioSandboxProvider.__new__(module.AioSandboxProvider)
    provider._config = {"auto_restart": auto_restart}
    provider._backend = MagicMock()
    provider._backend.is_alive.return_value = alive
    info = MagicMock()

    assert provider._check_tracked_sandbox_alive("sandbox-1", info) is expected_alive
    assert provider._backend.is_alive.call_count == expected_checks


def test_get_remains_in_memory_lookup():
    module = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    provider = module.AioSandboxProvider.__new__(module.AioSandboxProvider)
    provider._lock = threading.Lock()
    sandbox = MagicMock()
    provider._sandboxes = {"sandbox-1": sandbox}
    provider._last_activity = {}
    provider._backend = MagicMock()

    assert provider.get("sandbox-1") is sandbox
    provider._backend.is_alive.assert_not_called()


def test_health_check_evicts_sandbox_that_crashed_between_tool_calls(tmp_path):
    """A container crash between two tool calls must not keep handing out a dead client.

    ``get()``/``get_scoped()`` stay pure in-memory lookups (see
    ``test_get_remains_in_memory_lookup`` / ``test_get_uses_in_memory_registry_only``),
    so the scheduled health worker is what catches a mid-run crash: it must
    evict the cached sandbox so the *next* cache lookup misses and the caller
    falls through to ``acquire()`` for a fresh container.
    """
    provider, sandbox, _ = _make_provider_with_active_sandbox(tmp_path, "sandbox-crashed")
    provider._thread_sandboxes = {("default", "thread-crashed"): "sandbox-crashed"}
    info = provider._sandbox_infos["sandbox-crashed"]

    # First tool call: container is healthy.
    assert provider.get("sandbox-crashed") is sandbox

    # Container crashes mid-run, before the next tool call.
    provider._backend.is_alive = MagicMock(return_value=False)

    provider._health_check_owned_sandboxes()

    sandbox.close.assert_called_once_with()
    provider._backend.destroy.assert_called_once_with(info)
    assert "sandbox-crashed" not in provider._sandboxes
    assert "sandbox-crashed" not in provider._sandbox_infos
    assert ("default", "thread-crashed") not in provider._thread_sandboxes

    # Next tool call's cache lookup must miss instead of returning the dead client.
    assert provider.get("sandbox-crashed") is None


def test_health_check_respects_auto_restart_disabled(tmp_path):
    """With auto_restart disabled, a crashed container must not be evicted."""
    provider, sandbox, _ = _make_provider_with_active_sandbox(tmp_path, "sandbox-crashed-disabled")
    provider._config = {"auto_restart": False}
    provider._backend.is_alive = MagicMock(return_value=False)

    provider._health_check_owned_sandboxes()

    provider._backend.is_alive.assert_not_called()
    provider._backend.destroy.assert_not_called()
    assert provider.get("sandbox-crashed-disabled") is sandbox


def test_slow_health_check_does_not_delay_lease_renewal():
    """A blocked remote probe must not hold up the next ownership renewal."""
    module = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    provider = module.AioSandboxProvider.__new__(module.AioSandboxProvider)
    provider._config = {"auto_restart": True}
    provider._ownership_config = SimpleNamespace(renewal_interval_seconds=0.01, ttl_multiplier=4)
    provider._renewal_stop = threading.Event()
    provider._renewal_thread = None
    provider._health_check_thread = None

    health_started = threading.Event()
    allow_health = threading.Event()
    second_renewal = threading.Event()
    renewals: list[int] = []
    health_checks: list[int] = []

    def renew() -> None:
        renewals.append(1)
        if len(renewals) >= 2:
            second_renewal.set()

    def check_health() -> None:
        health_checks.append(1)
        health_started.set()
        allow_health.wait(timeout=2)

    provider._renew_owned_leases = renew
    provider._health_check_owned_sandboxes = check_health

    provider._start_lease_renewal()
    try:
        assert health_started.wait(timeout=1)
        assert second_renewal.wait(timeout=0.5), "a slow health probe delayed lease renewal"
        assert len(health_checks) == 1, "health checks must not spawn unbounded workers"
    finally:
        allow_health.set()
        provider._stop_lease_renewal()
    assert provider._health_check_thread is not None
    assert not provider._health_check_thread.is_alive()
