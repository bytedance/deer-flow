"""Tests for sandbox container orphan reconciliation on startup.

Covers:
- SandboxBackend.list_running() default behavior
- LocalContainerBackend.list_running() with mocked docker commands
- LocalContainerBackend._get_container_created_at() timestamp parsing
- AioSandboxProvider._reconcile_orphans() decision logic
- SIGHUP signal handler registration
"""

import importlib
import signal
import threading
import time
from datetime import UTC
from unittest.mock import MagicMock

import pytest

from deerflow.community.aio_sandbox.sandbox_info import SandboxInfo

# ── SandboxBackend.list_running() default ────────────────────────────────────


def test_backend_list_running_default_returns_empty():
    """Base SandboxBackend.list_running() returns empty list (backward compat for RemoteSandboxBackend)."""
    from deerflow.community.aio_sandbox.backend import SandboxBackend

    # Create a concrete subclass with the abstract methods stubbed
    class StubBackend(SandboxBackend):
        def create(self, thread_id, sandbox_id, extra_mounts=None):
            pass

        def destroy(self, info):
            pass

        def is_alive(self, info):
            return False

        def discover(self, sandbox_id):
            return None

    backend = StubBackend()
    assert backend.list_running() == []


# ── LocalContainerBackend.list_running() ─────────────────────────────────────


def _make_local_backend():
    """Create a LocalContainerBackend with minimal config."""
    from deerflow.community.aio_sandbox.local_backend import LocalContainerBackend

    return LocalContainerBackend(
        image="test-image:latest",
        base_port=8080,
        container_prefix="deer-flow-sandbox",
        config_mounts=[],
        environment={},
    )


def test_list_running_returns_containers(monkeypatch):
    """list_running should enumerate containers via docker ps and build SandboxInfo."""
    backend = _make_local_backend()
    monkeypatch.setattr(backend, "_runtime", "docker")

    docker_ps_output = "deer-flow-sandbox-abc12345\ndeer-flow-sandbox-def67890\n"
    port_map = {
        "deer-flow-sandbox-abc12345": 8081,
        "deer-flow-sandbox-def67890": 8082,
    }
    created_map = {
        "deer-flow-sandbox-abc12345": 1000.0,
        "deer-flow-sandbox-def67890": 2000.0,
    }

    import subprocess

    def mock_run(cmd, **kwargs):
        result = MagicMock()
        if cmd[:2] == ["docker", "ps"]:
            result.returncode = 0
            result.stdout = docker_ps_output
        else:
            result.returncode = 1
            result.stdout = ""
        return result

    monkeypatch.setattr(subprocess, "run", mock_run)
    monkeypatch.setattr(backend, "_get_container_port", lambda name: port_map.get(name))
    monkeypatch.setattr(backend, "_get_container_created_at", lambda name: created_map.get(name, 0.0))

    infos = backend.list_running()

    assert len(infos) == 2
    ids = {info.sandbox_id for info in infos}
    assert ids == {"abc12345", "def67890"}
    urls = {info.sandbox_url for info in infos}
    assert "http://localhost:8081" in urls
    assert "http://localhost:8082" in urls


def test_list_running_empty_when_no_containers(monkeypatch):
    """list_running should return empty list when docker ps returns nothing."""
    backend = _make_local_backend()
    monkeypatch.setattr(backend, "_runtime", "docker")

    import subprocess

    def mock_run(cmd, **kwargs):
        result = MagicMock()
        result.returncode = 0
        result.stdout = ""
        return result

    monkeypatch.setattr(subprocess, "run", mock_run)

    assert backend.list_running() == []


def test_list_running_skips_non_matching_names(monkeypatch):
    """list_running should skip containers whose names don't match the prefix pattern."""
    backend = _make_local_backend()
    monkeypatch.setattr(backend, "_runtime", "docker")

    import subprocess

    def mock_run(cmd, **kwargs):
        result = MagicMock()
        if cmd[:2] == ["docker", "ps"]:
            result.returncode = 0
            result.stdout = "deer-flow-sandbox-abc12345\nsome-other-container\n"
        else:
            result.returncode = 1
            result.stdout = ""
        return result

    monkeypatch.setattr(subprocess, "run", mock_run)
    monkeypatch.setattr(backend, "_get_container_port", lambda name: 8081)
    monkeypatch.setattr(backend, "_get_container_created_at", lambda name: 1000.0)

    infos = backend.list_running()
    assert len(infos) == 1
    assert infos[0].sandbox_id == "abc12345"


def test_list_running_includes_containers_without_port(monkeypatch):
    """list_running should include containers even without port mappings (for orphan cleanup)."""
    backend = _make_local_backend()
    monkeypatch.setattr(backend, "_runtime", "docker")

    import subprocess

    def mock_run(cmd, **kwargs):
        result = MagicMock()
        if cmd[:2] == ["docker", "ps"]:
            result.returncode = 0
            result.stdout = "deer-flow-sandbox-abc12345\n"
        else:
            result.returncode = 1
            result.stdout = ""
        return result

    monkeypatch.setattr(subprocess, "run", mock_run)
    monkeypatch.setattr(backend, "_get_container_port", lambda name: None)

    infos = backend.list_running()
    assert len(infos) == 1
    assert infos[0].sandbox_id == "abc12345"
    assert infos[0].sandbox_url == ""  # No port → empty URL


def test_list_running_handles_docker_failure(monkeypatch):
    """list_running should return empty list when docker ps fails."""
    backend = _make_local_backend()
    monkeypatch.setattr(backend, "_runtime", "docker")

    import subprocess

    def mock_run(cmd, **kwargs):
        result = MagicMock()
        result.returncode = 1
        result.stdout = ""
        return result

    monkeypatch.setattr(subprocess, "run", mock_run)

    assert backend.list_running() == []


# ── _get_container_created_at() ──────────────────────────────────────────────


def test_get_container_created_at_parses_docker_timestamp(monkeypatch):
    """Should correctly parse Docker's ISO 8601 timestamp with nanoseconds."""
    backend = _make_local_backend()
    monkeypatch.setattr(backend, "_runtime", "docker")

    import subprocess

    def mock_run(cmd, **kwargs):
        result = MagicMock()
        result.returncode = 0
        result.stdout = "2026-04-08T01:22:50.123456789Z\n"
        return result

    monkeypatch.setattr(subprocess, "run", mock_run)

    ts = backend._get_container_created_at("test-container")
    assert ts > 0
    # Verify it's approximately correct (2026-04-08T01:22:50Z)
    from datetime import datetime

    expected = datetime(2026, 4, 8, 1, 22, 50, tzinfo=UTC).timestamp()
    assert abs(ts - expected) < 1.0


def test_get_container_created_at_returns_zero_on_failure(monkeypatch):
    """Should return 0.0 when docker inspect fails."""
    backend = _make_local_backend()
    monkeypatch.setattr(backend, "_runtime", "docker")

    import subprocess

    def mock_run(cmd, **kwargs):
        result = MagicMock()
        result.returncode = 1
        result.stdout = ""
        return result

    monkeypatch.setattr(subprocess, "run", mock_run)

    assert backend._get_container_created_at("bad-container") == 0.0


# ── AioSandboxProvider._reconcile_orphans() ──────────────────────────────────


def _make_provider_for_reconciliation():
    """Build a minimal AioSandboxProvider without triggering __init__ side effects."""
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    provider = aio_mod.AioSandboxProvider.__new__(aio_mod.AioSandboxProvider)
    provider._lock = threading.Lock()
    provider._sandboxes = {}
    provider._sandbox_infos = {}
    provider._thread_sandboxes = {}
    provider._thread_locks = {}
    provider._last_activity = {}
    provider._warm_pool = {}
    provider._shutdown_called = False
    provider._idle_checker_stop = threading.Event()
    provider._idle_checker_thread = None
    provider._config = {
        "idle_timeout": 600,
        "replicas": 3,
    }
    provider._backend = MagicMock()
    return provider


def test_reconcile_destroys_old_containers():
    """Containers older than idle_timeout should be destroyed."""
    provider = _make_provider_for_reconciliation()
    now = time.time()

    old_info = SandboxInfo(
        sandbox_id="old12345",
        sandbox_url="http://localhost:8081",
        container_name="deer-flow-sandbox-old12345",
        created_at=now - 1200,  # 20 minutes old, > 600s idle_timeout
    )
    provider._backend.list_running.return_value = [old_info]

    provider._reconcile_orphans()

    provider._backend.destroy.assert_called_once_with(old_info)
    assert "old12345" not in provider._warm_pool


def test_reconcile_adopts_young_containers():
    """Containers younger than idle_timeout should be adopted into warm pool."""
    provider = _make_provider_for_reconciliation()
    now = time.time()

    young_info = SandboxInfo(
        sandbox_id="young123",
        sandbox_url="http://localhost:8082",
        container_name="deer-flow-sandbox-young123",
        created_at=now - 60,  # 1 minute old, < 600s idle_timeout
    )
    provider._backend.list_running.return_value = [young_info]

    provider._reconcile_orphans()

    provider._backend.destroy.assert_not_called()
    assert "young123" in provider._warm_pool
    adopted_info, release_ts = provider._warm_pool["young123"]
    assert adopted_info.sandbox_id == "young123"


def test_reconcile_mixed_containers():
    """Mix of old and young containers: old destroyed, young adopted."""
    provider = _make_provider_for_reconciliation()
    now = time.time()

    old_info = SandboxInfo(
        sandbox_id="old_one",
        sandbox_url="http://localhost:8081",
        container_name="deer-flow-sandbox-old_one",
        created_at=now - 1200,
    )
    young_info = SandboxInfo(
        sandbox_id="young_one",
        sandbox_url="http://localhost:8082",
        container_name="deer-flow-sandbox-young_one",
        created_at=now - 60,
    )
    provider._backend.list_running.return_value = [old_info, young_info]

    provider._reconcile_orphans()

    provider._backend.destroy.assert_called_once_with(old_info)
    assert "old_one" not in provider._warm_pool
    assert "young_one" in provider._warm_pool


def test_reconcile_skips_already_tracked_containers():
    """Containers already in _sandboxes or _warm_pool should be skipped."""
    provider = _make_provider_for_reconciliation()
    now = time.time()

    existing_info = SandboxInfo(
        sandbox_id="existing1",
        sandbox_url="http://localhost:8081",
        container_name="deer-flow-sandbox-existing1",
        created_at=now - 1200,
    )
    # Pre-populate _sandboxes to simulate already-tracked container
    provider._sandboxes["existing1"] = MagicMock()
    provider._backend.list_running.return_value = [existing_info]

    provider._reconcile_orphans()

    provider._backend.destroy.assert_not_called()


def test_reconcile_handles_backend_failure():
    """Reconciliation should not crash if backend.list_running() fails."""
    provider = _make_provider_for_reconciliation()
    provider._backend.list_running.side_effect = RuntimeError("docker not available")

    # Should not raise
    provider._reconcile_orphans()

    assert provider._warm_pool == {}


def test_reconcile_no_running_containers():
    """Reconciliation with no running containers is a no-op."""
    provider = _make_provider_for_reconciliation()
    provider._backend.list_running.return_value = []

    provider._reconcile_orphans()

    provider._backend.destroy.assert_not_called()
    assert provider._warm_pool == {}


def test_reconcile_handles_destroy_failure():
    """If destroy fails for one container, others should still be processed."""
    provider = _make_provider_for_reconciliation()
    now = time.time()

    info1 = SandboxInfo(sandbox_id="fail_one", sandbox_url="http://localhost:8081", created_at=now - 1200)
    info2 = SandboxInfo(sandbox_id="fail_two", sandbox_url="http://localhost:8082", created_at=now - 1200)

    provider._backend.list_running.return_value = [info1, info2]
    provider._backend.destroy.side_effect = [RuntimeError("docker stop failed"), None]

    provider._reconcile_orphans()

    assert provider._backend.destroy.call_count == 2


def test_reconcile_zero_created_at_treated_as_orphan():
    """Containers with created_at=0 (unknown age) should be treated as infinitely old → destroyed."""
    provider = _make_provider_for_reconciliation()

    info = SandboxInfo(sandbox_id="unknown1", sandbox_url="http://localhost:8081", created_at=0.0)
    provider._backend.list_running.return_value = [info]

    provider._reconcile_orphans()

    provider._backend.destroy.assert_called_once_with(info)


def test_reconcile_idle_timeout_zero_adopts_all():
    """When idle_timeout=0 (disabled), all containers are adopted into warm pool, none destroyed."""
    provider = _make_provider_for_reconciliation()
    provider._config["idle_timeout"] = 0
    now = time.time()

    old_info = SandboxInfo(sandbox_id="old_one", sandbox_url="http://localhost:8081", created_at=now - 7200)
    young_info = SandboxInfo(sandbox_id="young_one", sandbox_url="http://localhost:8082", created_at=now - 60)
    provider._backend.list_running.return_value = [old_info, young_info]

    provider._reconcile_orphans()

    provider._backend.destroy.assert_not_called()
    assert "old_one" in provider._warm_pool
    assert "young_one" in provider._warm_pool


# ── SIGHUP signal handler ───────────────────────────────────────────────────


def test_sighup_handler_registered():
    """SIGHUP handler should be registered on Unix systems."""
    if not hasattr(signal, "SIGHUP"):
        pytest.skip("SIGHUP not available on this platform")

    provider = _make_provider_for_reconciliation()

    # Save original handler
    original_handler = signal.getsignal(signal.SIGHUP)
    try:
        aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
        provider._original_sighup = signal.getsignal(signal.SIGHUP)
        provider._original_sigterm = signal.getsignal(signal.SIGTERM)
        provider._original_sigint = signal.getsignal(signal.SIGINT)
        provider.shutdown = MagicMock()

        aio_mod.AioSandboxProvider._register_signal_handlers(provider)

        # Verify SIGHUP handler is no longer the default
        handler = signal.getsignal(signal.SIGHUP)
        assert handler != signal.SIG_DFL, "SIGHUP handler should be registered"
    finally:
        # Restore original handler
        signal.signal(signal.SIGHUP, original_handler)
