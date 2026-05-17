"""Tests for AioSandboxProvider helpers and recovery paths."""

import importlib
import threading
from unittest.mock import MagicMock, patch

import pytest
import requests

from deerflow.community.aio_sandbox.sandbox_info import SandboxInfo
from deerflow.config.paths import Paths, join_host_path

# ── ensure_thread_dirs ───────────────────────────────────────────────────────


def test_ensure_thread_dirs_creates_acp_workspace(tmp_path):
    """ACP workspace directory must be created alongside user-data dirs."""
    paths = Paths(base_dir=tmp_path)
    paths.ensure_thread_dirs("thread-1")

    assert (tmp_path / "threads" / "thread-1" / "user-data" / "workspace").exists()
    assert (tmp_path / "threads" / "thread-1" / "user-data" / "uploads").exists()
    assert (tmp_path / "threads" / "thread-1" / "user-data" / "outputs").exists()
    assert (tmp_path / "threads" / "thread-1" / "acp-workspace").exists()


def test_ensure_thread_dirs_acp_workspace_is_world_writable(tmp_path):
    """ACP workspace must be chmod 0o777 so the ACP subprocess can write into it."""
    paths = Paths(base_dir=tmp_path)
    paths.ensure_thread_dirs("thread-2")

    acp_dir = tmp_path / "threads" / "thread-2" / "acp-workspace"
    mode = oct(acp_dir.stat().st_mode & 0o777)
    assert mode == oct(0o777)


def test_host_thread_dir_rejects_invalid_thread_id(tmp_path):
    paths = Paths(base_dir=tmp_path)

    with pytest.raises(ValueError, match="Invalid thread_id"):
        paths.host_thread_dir("../escape")


# ── _get_thread_mounts ───────────────────────────────────────────────────────


def _make_provider(tmp_path):
    """Build a minimal AioSandboxProvider instance without starting the idle checker."""
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    with patch.object(aio_mod.AioSandboxProvider, "_start_idle_checker"):
        provider = aio_mod.AioSandboxProvider.__new__(aio_mod.AioSandboxProvider)
        provider._config = {}
        provider._sandboxes = {}
        provider._sandbox_infos = {}
        provider._thread_sandboxes = {}
        provider._thread_locks = {}
        provider._last_activity = {}
        provider._health_check_cache = {}
        provider._warm_pool = {}
        provider._lock = threading.Lock()
        provider._backend = MagicMock()
        provider._idle_checker_stop = MagicMock()
        provider._idle_checker_thread = None
    return provider


def test_get_thread_mounts_includes_acp_workspace(tmp_path, monkeypatch):
    """_get_thread_mounts must include /mnt/acp-workspace (read-only) for docker sandbox."""
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    monkeypatch.setattr(aio_mod, "get_paths", lambda: Paths(base_dir=tmp_path))
    monkeypatch.setattr(aio_mod, "get_effective_user_id", lambda: None)

    mounts = aio_mod.AioSandboxProvider._get_thread_mounts("thread-3")

    container_paths = {m[1]: (m[0], m[2]) for m in mounts}

    assert "/mnt/acp-workspace" in container_paths, "ACP workspace mount is missing"
    expected_host = str(tmp_path / "threads" / "thread-3" / "acp-workspace")
    actual_host, read_only = container_paths["/mnt/acp-workspace"]
    assert actual_host == expected_host
    assert read_only is True, "ACP workspace should be read-only inside the sandbox"


def test_get_thread_mounts_includes_user_data_dirs(tmp_path, monkeypatch):
    """Baseline: user-data mounts must still be present after the ACP workspace change."""
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    monkeypatch.setattr(aio_mod, "get_paths", lambda: Paths(base_dir=tmp_path))

    mounts = aio_mod.AioSandboxProvider._get_thread_mounts("thread-4")
    container_paths = {m[1] for m in mounts}

    assert "/mnt/user-data/workspace" in container_paths
    assert "/mnt/user-data/uploads" in container_paths
    assert "/mnt/user-data/outputs" in container_paths


def test_join_host_path_preserves_windows_drive_letter_style():
    base = r"C:\Users\demo\deer-flow\backend\.deer-flow"

    joined = join_host_path(base, "threads", "thread-9", "user-data", "outputs")

    assert joined == r"C:\Users\demo\deer-flow\backend\.deer-flow\threads\thread-9\user-data\outputs"


def test_get_thread_mounts_preserves_windows_host_path_style(tmp_path, monkeypatch):
    """Docker bind mount sources must keep Windows-style paths intact."""
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    monkeypatch.setenv("DEER_FLOW_HOST_BASE_DIR", r"C:\Users\demo\deer-flow\backend\.deer-flow")
    monkeypatch.setattr(aio_mod, "get_paths", lambda: Paths(base_dir=tmp_path))
    monkeypatch.setattr(aio_mod, "get_effective_user_id", lambda: None)

    mounts = aio_mod.AioSandboxProvider._get_thread_mounts("thread-10")

    container_paths = {container_path: host_path for host_path, container_path, _ in mounts}

    assert container_paths["/mnt/user-data/workspace"] == r"C:\Users\demo\deer-flow\backend\.deer-flow\threads\thread-10\user-data\workspace"
    assert container_paths["/mnt/user-data/uploads"] == r"C:\Users\demo\deer-flow\backend\.deer-flow\threads\thread-10\user-data\uploads"
    assert container_paths["/mnt/user-data/outputs"] == r"C:\Users\demo\deer-flow\backend\.deer-flow\threads\thread-10\user-data\outputs"
    assert container_paths["/mnt/acp-workspace"] == r"C:\Users\demo\deer-flow\backend\.deer-flow\threads\thread-10\acp-workspace"


def test_discover_or_create_only_unlocks_when_lock_succeeds(tmp_path, monkeypatch):
    """Unlock should not run if exclusive locking itself fails."""
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    provider = _make_provider(tmp_path)
    provider._discover_or_create_with_lock = aio_mod.AioSandboxProvider._discover_or_create_with_lock.__get__(
        provider,
        aio_mod.AioSandboxProvider,
    )

    monkeypatch.setattr(aio_mod, "get_paths", lambda: Paths(base_dir=tmp_path))
    monkeypatch.setattr(
        aio_mod,
        "_lock_file_exclusive",
        lambda _lock_file: (_ for _ in ()).throw(RuntimeError("lock failed")),
    )

    unlock_calls: list[object] = []
    monkeypatch.setattr(
        aio_mod,
        "_unlock_file",
        lambda lock_file: unlock_calls.append(lock_file),
    )

    with patch.object(provider, "_create_sandbox", return_value="sandbox-id"):
        with pytest.raises(RuntimeError, match="lock failed"):
            provider._discover_or_create_with_lock("thread-5", "sandbox-5")

    assert unlock_calls == []


def test_get_rediscovers_stale_cached_sandbox(tmp_path, monkeypatch):
    """If the cached sandbox URL is dead, get() should rediscover and refresh it."""
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    provider = _make_provider(tmp_path)

    with patch("deerflow.community.aio_sandbox.aio_sandbox.AioSandboxClient"):
        stale = aio_mod.AioSandbox(id="sandbox-1", base_url="http://stale-host:8080")

    provider._sandboxes["sandbox-1"] = stale
    provider._sandbox_infos["sandbox-1"] = SandboxInfo(
        sandbox_id="sandbox-1",
        sandbox_url="http://stale-host:8080",
        container_name="deer-flow-sandbox-sandbox-1",
    )
    provider._thread_sandboxes["thread-1"] = "sandbox-1"
    provider._last_activity["sandbox-1"] = 1.0

    provider._backend.discover.return_value = SandboxInfo(
        sandbox_id="sandbox-1",
        sandbox_url="http://fresh-host:9090",
        container_name="deer-flow-sandbox-sandbox-1",
    )

    def _raise_connection_error(*args, **kwargs):
        raise requests.exceptions.ConnectionError("Connection refused")

    monkeypatch.setattr(requests, "get", _raise_connection_error)

    refreshed = provider.get("sandbox-1")

    assert refreshed is not None
    assert refreshed is not stale
    assert refreshed.base_url == "http://fresh-host:9090"
    assert provider._sandbox_infos["sandbox-1"].sandbox_url == "http://fresh-host:9090"
    assert provider._thread_sandboxes["thread-1"] == "sandbox-1"


def test_get_throttles_repeated_health_checks_for_healthy_sandbox(tmp_path, monkeypatch):
    """Repeated get() calls within the throttle window should reuse the cached health result."""
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    provider = _make_provider(tmp_path)

    with patch("deerflow.community.aio_sandbox.aio_sandbox.AioSandboxClient"):
        sandbox = aio_mod.AioSandbox(id="sandbox-healthy", base_url="http://healthy-host:8080")

    provider._sandboxes["sandbox-healthy"] = sandbox
    provider._sandbox_infos["sandbox-healthy"] = SandboxInfo(
        sandbox_id="sandbox-healthy",
        sandbox_url="http://healthy-host:8080",
        container_name="deer-flow-sandbox-sandbox-healthy",
    )

    timestamps = iter([100.0, 100.0, 100.2, 100.2])
    monkeypatch.setattr(aio_mod.time, "time", lambda: next(timestamps))

    request_calls = {"count": 0}

    class _Response:
        status_code = 200

    def _healthy_response(*args, **kwargs):
        request_calls["count"] += 1
        return _Response()

    monkeypatch.setattr(requests, "get", _healthy_response)

    assert provider.get("sandbox-healthy") is sandbox
    assert provider.get("sandbox-healthy") is sandbox
    assert request_calls["count"] == 1


def test_get_returns_none_when_cached_sandbox_cannot_be_rediscovered(tmp_path, monkeypatch):
    """If the cached sandbox URL is dead and discover() fails, get() should return None."""
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    provider = _make_provider(tmp_path)

    with patch("deerflow.community.aio_sandbox.aio_sandbox.AioSandboxClient"):
        stale = aio_mod.AioSandbox(id="sandbox-2", base_url="http://dead-host:8080")

    provider._sandboxes["sandbox-2"] = stale
    provider._sandbox_infos["sandbox-2"] = SandboxInfo(
        sandbox_id="sandbox-2",
        sandbox_url="http://dead-host:8080",
        container_name="deer-flow-sandbox-sandbox-2",
    )
    provider._thread_sandboxes["thread-2"] = "sandbox-2"
    provider._last_activity["sandbox-2"] = 1.0
    provider._backend.discover.return_value = None

    def _raise_connection_error(*args, **kwargs):
        raise requests.exceptions.ConnectionError("Connection refused")

    monkeypatch.setattr(requests, "get", _raise_connection_error)

    result = provider.get("sandbox-2")

    assert result is None
    assert "sandbox-2" not in provider._sandboxes
    assert "sandbox-2" not in provider._sandbox_infos
    assert "sandbox-2" not in provider._last_activity
    assert "thread-2" not in provider._thread_sandboxes
