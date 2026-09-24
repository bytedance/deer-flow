"""Regression tests for configurable AIO cached-container health checks."""

import importlib
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

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
