"""Tests for AioSandboxProvider mount helpers."""

import asyncio
import contextlib
import hashlib
import importlib
import stat
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from deerflow.config.paths import Paths, join_host_path
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.runtime.user_context import reset_current_user, set_current_user

_LEGACY_COLLIDING_IDENTITIES = (
    ("user-9721", "thread-9721"),
    ("user-94361", "thread-94361"),
)

# ── thread-data mount configuration ─────────────────────────────────────────


@pytest.mark.parametrize(
    ("sandbox_overrides", "expected"),
    [
        ({}, None),
        ({"thread_data_mounts": True}, True),
        ({"thread_data_mounts": False}, False),
    ],
)
def test_load_config_preserves_thread_data_mounts_override(sandbox_overrides, expected, monkeypatch):
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    sandbox_config = SandboxConfig(
        use="deerflow.community.aio_sandbox:AioSandboxProvider",
        **sandbox_overrides,
    )
    app_config = SimpleNamespace(sandbox=sandbox_config, stream_bridge=None)
    monkeypatch.setattr(aio_mod, "get_app_config", lambda: app_config)
    provider = aio_mod.AioSandboxProvider.__new__(aio_mod.AioSandboxProvider)

    assert provider._load_config()["thread_data_mounts"] is expected


@pytest.mark.parametrize(
    ("backend_is_local", "override", "expected"),
    [
        (True, None, True),
        (False, None, False),
        (True, False, False),
        (False, True, True),
    ],
)
def test_thread_data_mounts_override_precedes_backend_detection(backend_is_local, override, expected):
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    provider = aio_mod.AioSandboxProvider.__new__(aio_mod.AioSandboxProvider)
    provider._config = {} if override is None else {"thread_data_mounts": override}
    provider._backend = object.__new__(aio_mod.LocalContainerBackend) if backend_is_local else object()

    assert provider.uses_thread_data_mounts is expected


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
    """Build a minimal AioSandboxProvider instance without starting the idle checker.

    ``tmp_path`` is accepted and ignored: ownership no longer lives on disk. Each
    provider gets its own in-process ownership store, so it owns every sandbox it
    tracks — cross-instance behaviour is covered in
    ``test_sandbox_orphan_reconciliation.py`` (shared store) and
    ``test_sandbox_ownership_store.py`` (store contract).
    """
    from deerflow.community.aio_sandbox.ownership.memory import MemoryOwnershipStore
    from deerflow.config.sandbox_config import SandboxOwnershipConfig

    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    with patch.object(aio_mod.AioSandboxProvider, "_start_idle_checker"):
        provider = aio_mod.AioSandboxProvider.__new__(aio_mod.AioSandboxProvider)
        provider._config = {"idle_timeout": 600, "replicas": 3}
        provider._sandboxes = {}
        provider._active_sandbox_identity = {}
        provider._warm_pool_identity = {}
        provider._local_teardown = set()
        provider._acquire_epoch = {}
        provider._acquire_epoch_counter = 0
        provider._acquire_inflight = {}
        provider._lock = MagicMock()
        provider._idle_checker_stop = MagicMock()
        provider._renewal_stop = MagicMock()
        provider._renewal_thread = None
        provider._owner_id = "test-worker"
        provider._ownership_config = SandboxOwnershipConfig()
        provider._ownership = MemoryOwnershipStore(owner_id="test-worker", ttl_seconds=600)
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


def test_get_thread_mounts_uses_explicit_user_id(tmp_path, monkeypatch):
    """Channel runs must mount the same user bucket used for artifact delivery."""
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    monkeypatch.setattr(aio_mod, "get_paths", lambda: Paths(base_dir=tmp_path))
    monkeypatch.setattr(aio_mod, "get_effective_user_id", lambda: "default")

    mounts = aio_mod.AioSandboxProvider._get_thread_mounts("thread-4", user_id="ou-user")
    container_paths = {container_path: host_path for host_path, container_path, _ in mounts}

    assert container_paths["/mnt/user-data/workspace"] == str(tmp_path / "users" / "ou-user" / "threads" / "thread-4" / "user-data" / "workspace")
    assert container_paths["/mnt/user-data/uploads"] == str(tmp_path / "users" / "ou-user" / "threads" / "thread-4" / "user-data" / "uploads")
    assert container_paths["/mnt/user-data/outputs"] == str(tmp_path / "users" / "ou-user" / "threads" / "thread-4" / "user-data" / "outputs")


def test_get_lark_cli_runtime_mounts_uses_user_auth_dirs(tmp_path, monkeypatch):
    """Sandbox lark-cli commands must read the same auth dirs as Settings."""
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    lark_cli = importlib.import_module("deerflow.integrations.lark_cli")
    monkeypatch.setattr(aio_mod, "get_paths", lambda: Paths(base_dir=tmp_path))
    monkeypatch.setattr(aio_mod, "get_effective_user_id", lambda: "default")
    runtime_dir = tmp_path / "integrations" / "lark-cli" / "sandbox-cli"
    runtime_dir.mkdir(parents=True)

    mounts = aio_mod.AioSandboxProvider._get_lark_cli_runtime_mounts(user_id="alice")
    mount_order = [container_path for _host_path, container_path, _read_only in mounts]
    container_paths = {container_path: (host_path, read_only) for host_path, container_path, read_only in mounts}

    assert container_paths[lark_cli.LARK_CLI_SANDBOX_CONFIG_DIR] == (
        str(tmp_path / "users" / "alice" / "integrations" / "lark-cli" / "config"),
        True,
    )
    assert container_paths[f"{lark_cli.LARK_CLI_SANDBOX_CONFIG_DIR}/locks"] == (
        str(tmp_path / "users" / "alice" / "integrations" / "lark-cli" / "config" / "locks"),
        False,
    )
    assert mount_order.index(lark_cli.LARK_CLI_SANDBOX_CONFIG_DIR) < mount_order.index(lark_cli.LARK_CLI_SANDBOX_LOCKS_DIR)
    assert container_paths[lark_cli.LARK_CLI_SANDBOX_DATA_DIR] == (
        str(tmp_path / "users" / "alice" / "integrations" / "lark-cli" / "data"),
        False,
    )
    assert stat.S_IMODE((tmp_path / "users" / "alice" / "integrations" / "lark-cli" / "config").stat().st_mode) == 0o700
    assert stat.S_IMODE((tmp_path / "users" / "alice" / "integrations" / "lark-cli" / "config" / "locks").stat().st_mode) == 0o700
    assert stat.S_IMODE((tmp_path / "users" / "alice" / "integrations" / "lark-cli" / "data").stat().st_mode) == 0o700
    assert container_paths["/mnt/integrations/lark-cli/runtime"] == (
        str(runtime_dir),
        True,
    )


def test_get_user_skill_mounts_mounts_only_global_integrations(tmp_path, monkeypatch):
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    skills_root = tmp_path / "skills"
    (skills_root / "public").mkdir(parents=True)
    config = SimpleNamespace(
        skills=SimpleNamespace(
            get_skills_path=lambda: skills_root,
            container_path="/mnt/skills",
        )
    )
    monkeypatch.setattr(aio_mod, "get_app_config", lambda: config)
    monkeypatch.setattr(aio_mod, "get_paths", lambda: Paths(base_dir=tmp_path / "home"))

    alice = {container: host for host, container, _read_only in aio_mod.AioSandboxProvider._get_user_skill_mounts(user_id="alice")}
    bob = {container: host for host, container, _read_only in aio_mod.AioSandboxProvider._get_user_skill_mounts(user_id="bob")}

    assert set(alice) == {"/mnt/skills/integrations"}
    assert set(bob) == {"/mnt/skills/integrations"}
    assert alice["/mnt/skills/integrations"] != bob["/mnt/skills/integrations"]
    assert alice["/mnt/skills/integrations"] == str(tmp_path / "home" / "users" / "alice" / "skills_view" / "integrations")
    assert bob["/mnt/skills/integrations"] == str(tmp_path / "home" / "users" / "bob" / "skills_view" / "integrations")


def test_get_extra_mounts_provisioner_payload_has_unique_container_paths(tmp_path, monkeypatch, provisioner_module):
    """Full AIO mount composition must not send duplicate paths to provisioner."""
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    lark_cli = importlib.import_module("deerflow.integrations.lark_cli")
    remote_backend = importlib.import_module("deerflow.community.aio_sandbox.remote_backend")
    skills_root = tmp_path / "skills"
    (skills_root / "public").mkdir(parents=True)
    home = tmp_path / "home"
    config = SimpleNamespace(
        skills=SimpleNamespace(
            get_skills_path=lambda: skills_root,
            container_path="/mnt/skills",
        )
    )
    runtime_dir = home / "integrations" / "lark-cli" / "sandbox-cli"
    runtime_dir.mkdir(parents=True)

    monkeypatch.setattr(aio_mod, "get_app_config", lambda: config)
    monkeypatch.setattr(aio_mod, "get_paths", lambda: Paths(base_dir=home))
    monkeypatch.setattr(aio_mod, "get_effective_user_id", lambda: "default")
    monkeypatch.setattr(remote_backend, "user_should_see_legacy_skills", lambda *_args, **_kwargs: False)

    provider = _make_provider(tmp_path)
    mounts = provider._get_extra_mounts("thread-1", user_id="alice")
    container_paths = [container for _host, container, _read_only in mounts]

    assert len(container_paths) == len(set(container_paths))
    assert "/mnt/skills/custom" in container_paths
    assert "/mnt/skills/integrations" in container_paths
    assert lark_cli.LARK_CLI_SANDBOX_CONFIG_DIR in container_paths
    assert lark_cli.LARK_CLI_SANDBOX_LOCKS_DIR in container_paths
    assert lark_cli.LARK_CLI_SANDBOX_DATA_DIR in container_paths
    assert lark_cli.LARK_CLI_SANDBOX_RUNTIME_DIR in container_paths

    payload = remote_backend._provisioner_extra_mounts_payload(mounts)
    payload_paths = [str(item["container_path"]) for item in payload]
    assert len(payload_paths) == len(set(payload_paths))
    assert payload_paths.index(lark_cli.LARK_CLI_SANDBOX_CONFIG_DIR) < payload_paths.index(lark_cli.LARK_CLI_SANDBOX_LOCKS_DIR)

    provisioner_module.DEER_FLOW_HOST_BASE_DIR = str(home)
    validated = provisioner_module._validated_extra_mounts([provisioner_module.ExtraMount(**item) for item in payload])
    validated_paths = [mount.container_path for mount in validated]

    assert len(validated_paths) == len(set(validated_paths))
    assert set(validated_paths) == {
        "/mnt/acp-workspace",
        "/mnt/skills/custom",
        "/mnt/skills/integrations",
        lark_cli.LARK_CLI_SANDBOX_CONFIG_DIR,
        lark_cli.LARK_CLI_SANDBOX_LOCKS_DIR,
        lark_cli.LARK_CLI_SANDBOX_DATA_DIR,
        lark_cli.LARK_CLI_SANDBOX_RUNTIME_DIR,
    }


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


@pytest.mark.anyio
async def test_acquire_async_uses_async_readiness_polling(monkeypatch):
    """AioSandboxProvider async creation must not use sync readiness polling."""
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    provider = _make_provider(None)
    provider._config = {"replicas": 3}
    provider._thread_locks = {}
    provider._warm_pool = {}
    provider._sandbox_infos = {}
    provider._thread_sandboxes = {}
    provider._last_activity = {}
    provider._lock = aio_mod.threading.Lock()
    provider._backend = SimpleNamespace(
        create=MagicMock(return_value=aio_mod.SandboxInfo(sandbox_id="sandbox-async", sandbox_url="http://sandbox")),
        destroy=MagicMock(),
        discover=MagicMock(return_value=None),
    )

    async_readiness_calls: list[tuple[str, int]] = []

    async def fake_wait_for_sandbox_ready_async(sandbox_url: str, timeout: int = 30, poll_interval: float = 1.0) -> bool:
        async_readiness_calls.append((sandbox_url, timeout))
        return True

    monkeypatch.setattr(aio_mod, "wait_for_sandbox_ready_async", fake_wait_for_sandbox_ready_async)
    monkeypatch.setattr(
        aio_mod,
        "wait_for_sandbox_ready",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("sync readiness should not be used")),
    )

    sandbox_id = await provider._create_sandbox_async("thread-async", "sandbox-async", user_id="user-async")

    assert sandbox_id == "sandbox-async"
    assert async_readiness_calls == [("http://sandbox", 60)]
    assert provider._backend.destroy.call_count == 0
    assert provider._thread_sandboxes[("user-async", "thread-async")] == "sandbox-async"


@pytest.mark.anyio
async def test_discover_or_create_with_lock_async_offloads_lock_file_open_and_close(tmp_path, monkeypatch):
    """Async lock path must not open or close lock files on the event loop."""
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    provider = _make_provider(tmp_path)
    provider._discover_or_create_with_lock_async = aio_mod.AioSandboxProvider._discover_or_create_with_lock_async.__get__(
        provider,
        aio_mod.AioSandboxProvider,
    )
    provider._thread_locks = {}
    provider._warm_pool = {}
    provider._sandbox_infos = {}
    provider._thread_sandboxes = {("default", "thread-async-lock"): "sandbox-async-lock"}
    provider._sandboxes = {"sandbox-async-lock": aio_mod.AioSandbox(id="sandbox-async-lock", base_url="http://sandbox")}
    provider._last_activity = {}
    provider._lock = aio_mod.threading.Lock()
    provider._backend = SimpleNamespace(discover=MagicMock(return_value=None))

    monkeypatch.setattr(aio_mod, "get_paths", lambda: Paths(base_dir=tmp_path))

    to_thread_calls: list[object] = []

    async def fake_to_thread(func, /, *args, **kwargs):
        to_thread_calls.append(func)
        return func(*args, **kwargs)

    monkeypatch.setattr(aio_mod.asyncio, "to_thread", fake_to_thread)

    sandbox_id = await provider._discover_or_create_with_lock_async("thread-async-lock", "sandbox-async-lock", user_id="default")

    assert sandbox_id == "sandbox-async-lock"
    assert aio_mod._open_lock_file in to_thread_calls
    assert any(getattr(func, "__name__", "") == "close" for func in to_thread_calls)


@pytest.mark.anyio
async def test_acquire_thread_lock_async_uses_dedicated_executor(monkeypatch):
    """Per-thread lock waits should not consume the default asyncio.to_thread pool."""
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    lock = aio_mod.threading.Lock()

    async def fail_to_thread(*_args, **_kwargs):
        raise AssertionError("thread-lock acquisition must not use asyncio.to_thread")

    monkeypatch.setattr(aio_mod.asyncio, "to_thread", fail_to_thread)

    await aio_mod._acquire_thread_lock_async(lock)
    try:
        assert not lock.acquire(blocking=False)
    finally:
        lock.release()


@pytest.mark.anyio
async def test_acquire_async_cancellation_does_not_leak_thread_lock(tmp_path):
    """Cancelled async lock waiters must not leave the per-thread lock held."""
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    provider = _make_provider(tmp_path)
    provider._thread_locks = {}
    provider._warm_pool = {}
    provider._sandbox_infos = {}
    provider._thread_sandboxes = {}
    provider._last_activity = {}
    provider._lock = aio_mod.threading.Lock()

    thread_id = "thread-cancel-lock"
    thread_lock = provider._get_thread_lock(thread_id, "default")
    thread_lock.acquire()

    task = asyncio.create_task(provider.acquire_async(thread_id, user_id="default"))
    await asyncio.sleep(0.05)
    task.cancel()

    try:
        await task
    except asyncio.CancelledError:
        pass

    thread_lock.release()
    deadline = asyncio.get_running_loop().time() + 1
    while asyncio.get_running_loop().time() < deadline:
        acquired = thread_lock.acquire(blocking=False)
        if acquired:
            thread_lock.release()
            return
        await asyncio.sleep(0.01)

    pytest.fail("provider thread lock was leaked after cancelling acquire_async")


@pytest.mark.anyio
async def test_acquire_async_cancelled_waiter_does_not_block_successor(tmp_path, monkeypatch):
    """A cancelled waiter must not prevent the next live waiter from acquiring."""
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    provider = _make_provider(tmp_path)
    provider._thread_locks = {}
    provider._warm_pool = {}
    provider._sandbox_infos = {}
    provider._thread_sandboxes = {}
    provider._last_activity = {}
    provider._lock = aio_mod.threading.Lock()

    async def fake_acquire_internal_async(thread_id: str | None, *, user_id: str) -> str:
        assert thread_id == "thread-successor-lock"
        assert user_id == "default"
        await asyncio.sleep(0)
        return "sandbox-successor"

    monkeypatch.setattr(provider, "_acquire_internal_async", fake_acquire_internal_async)

    thread_id = "thread-successor-lock"
    thread_lock = provider._get_thread_lock(thread_id, "default")
    thread_lock.acquire()

    cancelled_waiter = asyncio.create_task(provider.acquire_async(thread_id, user_id="default"))
    await asyncio.sleep(0.05)
    cancelled_waiter.cancel()
    try:
        await cancelled_waiter
    except asyncio.CancelledError:
        pass

    live_waiter = asyncio.create_task(provider.acquire_async(thread_id, user_id="default"))
    thread_lock.release()

    assert await asyncio.wait_for(live_waiter, timeout=1) == "sandbox-successor"

    deadline = asyncio.get_running_loop().time() + 1
    while asyncio.get_running_loop().time() < deadline:
        acquired = thread_lock.acquire(blocking=False)
        if acquired:
            thread_lock.release()
            return
        await asyncio.sleep(0.01)

    pytest.fail("provider thread lock was not released after successor acquire_async")


@pytest.mark.anyio
async def test_acquire_internal_async_offloads_cached_reuse_health_check(tmp_path, monkeypatch):
    """Async cached reuse must keep backend health checks off the event loop."""
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    provider, _sandbox, _ = _make_provider_with_active_sandbox(tmp_path, "sandbox-cached-async")
    provider._thread_sandboxes = {("default", "thread-cached-async"): "sandbox-cached-async"}
    provider._backend.is_alive = MagicMock(return_value=True)

    to_thread_calls: list[tuple[object, tuple[object, ...]]] = []

    async def fake_to_thread(func, /, *args, **kwargs):
        to_thread_calls.append((func, args))
        return func(*args, **kwargs)

    monkeypatch.setattr(aio_mod.asyncio, "to_thread", fake_to_thread)

    sandbox_id = await provider._acquire_internal_async("thread-cached-async", user_id="default")

    assert sandbox_id == "sandbox-cached-async"
    assert to_thread_calls == [
        (provider._ensure_skills_projection, ("default",)),
        (provider._reuse_in_process_sandbox, ("thread-cached-async",)),
    ]


def test_remote_backend_create_forwards_effective_user_id(monkeypatch):
    """Provisioner mode must receive user_id so PVC subPath matches user isolation."""
    remote_mod = importlib.import_module("deerflow.community.aio_sandbox.remote_backend")
    backend = remote_mod.RemoteSandboxBackend("http://provisioner:8002")
    token = set_current_user(SimpleNamespace(id="user-7"))
    posted: dict = {}

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"sandbox_url": "http://sandbox.local"}

    def _post(url, json, timeout, headers=None):  # noqa: A002 - mirrors requests.post kwarg
        posted.update({"url": url, "json": json, "timeout": timeout})
        return _Response()

    monkeypatch.setattr(remote_mod.requests, "post", _post)
    monkeypatch.setattr(remote_mod, "user_should_see_legacy_skills", lambda _user_id: True)

    try:
        backend.create("thread-42", "sandbox-42")
    finally:
        reset_current_user(token)

    assert posted["url"] == "http://provisioner:8002/api/sandboxes"
    assert posted["json"] == {
        "sandbox_id": "sandbox-42",
        "thread_id": "thread-42",
        "user_id": "user-7",
        "include_legacy_skills": True,
        "provision_lark_cli_runtime": False,
        "provision_lark_cli_broker": False,
    }


def test_remote_backend_create_prefers_explicit_user_id(monkeypatch):
    """Provisioner mode must not fall back to the ambient default for channel runs."""
    remote_mod = importlib.import_module("deerflow.community.aio_sandbox.remote_backend")
    backend = remote_mod.RemoteSandboxBackend("http://provisioner:8002")
    posted: dict = {}

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"sandbox_url": "http://sandbox.local"}

    def _post(url, json, timeout, headers=None):  # noqa: A002 - mirrors requests.post kwarg
        posted.update({"url": url, "json": json, "timeout": timeout})
        return _Response()

    monkeypatch.setattr(remote_mod.requests, "post", _post)
    monkeypatch.setattr(remote_mod, "get_effective_user_id", lambda: "default")
    monkeypatch.setattr(remote_mod, "user_should_see_legacy_skills", lambda _user_id: False)

    backend.create("thread-42", "sandbox-42", user_id="ou-user")

    assert posted["json"]["user_id"] == "ou-user"
    assert posted["json"]["include_legacy_skills"] is False


def test_create_sandbox_requests_runtime_when_lark_installed(tmp_path, monkeypatch):
    """The provider must request lark-cli runtime provisioning when Lark is installed."""
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    provider = _make_provider(tmp_path)
    provider._config = {"replicas": 3}
    provider._thread_locks = {}
    provider._warm_pool = {}
    provider._sandbox_infos = {}
    provider._thread_sandboxes = {}
    provider._last_activity = {}
    provider._lock = aio_mod.threading.Lock()

    captured: dict = {}

    def _create(thread_id, sandbox_id, *, extra_mounts=None, user_id=None, provision_lark_cli_runtime=False, provision_lark_cli_broker=False):
        captured["provision_lark_cli_runtime"] = provision_lark_cli_runtime
        captured["provision_lark_cli_broker"] = provision_lark_cli_broker
        return aio_mod.SandboxInfo(sandbox_id=sandbox_id, sandbox_url="http://sandbox")

    provider._backend = SimpleNamespace(create=_create, destroy=MagicMock(), discover=MagicMock(return_value=None))
    monkeypatch.setattr(aio_mod, "wait_for_sandbox_ready", lambda *_a, **_k: True)
    monkeypatch.setattr(provider, "_get_extra_mounts", lambda *_a, **_k: [])
    monkeypatch.setattr(aio_mod.AioSandboxProvider, "_lark_integration_active", staticmethod(lambda user_id=None: True))
    monkeypatch.setattr(aio_mod.AioSandboxProvider, "_lark_broker_active", staticmethod(lambda user_id=None: False))
    monkeypatch.setattr(provider, "_register_created_sandbox", lambda *a, **k: "sandbox-lark")

    provider._create_sandbox("thread-lark", "sandbox-lark", user_id="alice")
    assert captured["provision_lark_cli_runtime"] is True
    assert captured["provision_lark_cli_broker"] is False


def test_create_sandbox_requests_broker_when_active(tmp_path, monkeypatch):
    """Broker mode (Pattern B) is requested when the provisioner reports it."""
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    provider = _make_provider(tmp_path)
    provider._config = {"replicas": 3}
    provider._thread_locks = {}
    provider._warm_pool = {}
    provider._sandbox_infos = {}
    provider._thread_sandboxes = {}
    provider._last_activity = {}
    provider._lock = aio_mod.threading.Lock()

    captured: dict = {}

    def _create(thread_id, sandbox_id, *, extra_mounts=None, user_id=None, provision_lark_cli_runtime=False, provision_lark_cli_broker=False):
        captured["provision_lark_cli_runtime"] = provision_lark_cli_runtime
        captured["provision_lark_cli_broker"] = provision_lark_cli_broker
        return aio_mod.SandboxInfo(sandbox_id=sandbox_id, sandbox_url="http://sandbox")

    provider._backend = SimpleNamespace(create=_create, destroy=MagicMock(), discover=MagicMock(return_value=None))
    monkeypatch.setattr(aio_mod, "wait_for_sandbox_ready", lambda *_a, **_k: True)
    monkeypatch.setattr(provider, "_get_extra_mounts", lambda *_a, **_k: [])
    monkeypatch.setattr(aio_mod.AioSandboxProvider, "_lark_integration_active", staticmethod(lambda user_id=None: True))
    monkeypatch.setattr(aio_mod.AioSandboxProvider, "_lark_broker_active", staticmethod(lambda user_id=None: True))
    monkeypatch.setattr(provider, "_register_created_sandbox", lambda *a, **k: "sandbox-broker")

    provider._create_sandbox("thread-broker", "sandbox-broker", user_id="alice")
    assert captured["provision_lark_cli_runtime"] is True
    assert captured["provision_lark_cli_broker"] is True


def test_create_sandbox_skips_runtime_when_lark_absent(tmp_path, monkeypatch):
    """No runtime provisioning request when the Lark skill pack is not installed."""
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    provider = _make_provider(tmp_path)
    provider._config = {"replicas": 3}
    provider._thread_locks = {}
    provider._warm_pool = {}
    provider._sandbox_infos = {}
    provider._thread_sandboxes = {}
    provider._last_activity = {}
    provider._lock = aio_mod.threading.Lock()

    captured: dict = {}

    def _create(thread_id, sandbox_id, *, extra_mounts=None, user_id=None, provision_lark_cli_runtime=False, provision_lark_cli_broker=False):
        captured["provision_lark_cli_runtime"] = provision_lark_cli_runtime
        captured["provision_lark_cli_broker"] = provision_lark_cli_broker
        return aio_mod.SandboxInfo(sandbox_id=sandbox_id, sandbox_url="http://sandbox")

    provider._backend = SimpleNamespace(create=_create, destroy=MagicMock(), discover=MagicMock(return_value=None))
    monkeypatch.setattr(aio_mod, "wait_for_sandbox_ready", lambda *_a, **_k: True)
    monkeypatch.setattr(provider, "_get_extra_mounts", lambda *_a, **_k: [])
    monkeypatch.setattr(aio_mod.AioSandboxProvider, "_lark_integration_active", staticmethod(lambda user_id=None: False))
    monkeypatch.setattr(aio_mod.AioSandboxProvider, "_lark_broker_active", staticmethod(lambda user_id=None: False))
    monkeypatch.setattr(provider, "_register_created_sandbox", lambda *a, **k: "sandbox-nolark")

    provider._create_sandbox("thread-nolark", "sandbox-nolark", user_id="alice")
    assert captured["provision_lark_cli_runtime"] is False
    assert captured["provision_lark_cli_broker"] is False


# ── Sandbox client teardown (#2872) ──────────────────────────────────────────


def _make_provider_with_active_sandbox(tmp_path, sandbox_id: str):
    """Build a provider with one active sandbox suitable for release/destroy/shutdown tests."""
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    provider = _make_provider(tmp_path)
    provider._lock = aio_mod.threading.Lock()
    provider._warm_pool = {}
    provider._sandbox_infos = {
        sandbox_id: aio_mod.SandboxInfo(sandbox_id=sandbox_id, sandbox_url="http://sandbox-host"),
    }
    provider._thread_sandboxes = {}
    provider._last_activity = {sandbox_id: 0.0}
    provider._local_teardown = set()
    provider._acquire_epoch = {}
    provider._acquire_epoch_counter = 0
    provider._acquire_inflight = {}
    provider._shutdown_called = False
    provider._idle_checker_thread = None
    provider._backend = SimpleNamespace(destroy=MagicMock())

    sandbox = MagicMock()
    sandbox.id = sandbox_id
    sandbox.close = MagicMock()
    provider._sandboxes = {sandbox_id: sandbox}
    return provider, sandbox, aio_mod


def test_release_closes_cached_sandbox_client(tmp_path):
    """release() must close the host-side client owned by the cached AioSandbox (#2872)."""
    provider, sandbox, _ = _make_provider_with_active_sandbox(tmp_path, "sandbox-rel")

    provider.release("sandbox-rel")

    sandbox.close.assert_called_once_with()
    # And the sandbox is parked in the warm pool (container still running).
    assert "sandbox-rel" in provider._warm_pool
    assert "sandbox-rel" not in provider._sandboxes


def test_destroy_closes_cached_sandbox_client(tmp_path):
    """destroy() must close the host-side client before backend container teardown (#2872)."""
    provider, sandbox, _ = _make_provider_with_active_sandbox(tmp_path, "sandbox-destroy")
    backend_destroy = provider._backend.destroy

    provider.destroy("sandbox-destroy")

    sandbox.close.assert_called_once_with()
    backend_destroy.assert_called_once()
    assert "sandbox-destroy" not in provider._sandboxes
    assert "sandbox-destroy" not in provider._sandbox_infos


def test_shutdown_closes_all_active_sandbox_clients(tmp_path):
    """shutdown() must close every cached AioSandbox client during teardown (#2872)."""
    provider, sandbox, _ = _make_provider_with_active_sandbox(tmp_path, "sandbox-shut")

    provider.shutdown()

    sandbox.close.assert_called_once_with()
    provider._backend.destroy.assert_called_once()
    assert provider._sandboxes == {}


def test_release_swallows_close_errors(tmp_path, caplog):
    """A failure inside sandbox.close() must not break provider release()."""
    provider, sandbox, _ = _make_provider_with_active_sandbox(tmp_path, "sandbox-rel-err")
    sandbox.close.side_effect = RuntimeError("boom")

    with caplog.at_level("WARNING"):
        provider.release("sandbox-rel-err")

    assert "Error closing sandbox sandbox-rel-err during release" in caplog.text
    # Still moved to warm pool: client teardown failure must not block lifecycle.
    assert "sandbox-rel-err" in provider._warm_pool


def test_get_uses_in_memory_registry_only(tmp_path):
    """get() must stay event-loop safe by avoiding backend health checks."""
    provider, sandbox, _ = _make_provider_with_active_sandbox(tmp_path, "sandbox-dead")
    provider._backend.is_alive = MagicMock(side_effect=AssertionError("get must not call backend health checks"))

    assert provider.get("sandbox-dead") is sandbox


def test_acquire_drops_dead_cached_sandbox(tmp_path, monkeypatch):
    """acquire() must replace a stale active cache entry after its container dies."""
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    provider, sandbox, _ = _make_provider_with_active_sandbox(tmp_path, "sandbox-dead")
    provider._thread_locks = {}
    provider._thread_sandboxes = {("default", "thread-dead"): "sandbox-dead"}
    provider._config = {"replicas": 3}
    provider._backend.is_alive = MagicMock(return_value=False)
    provider._backend.discover = MagicMock(return_value=None)
    provider._backend.create = MagicMock(
        return_value=aio_mod.SandboxInfo(
            sandbox_id="sandbox-dead",
            sandbox_url="http://fresh-sandbox",
            container_name="deer-flow-sandbox-sandbox-dead",
        )
    )

    monkeypatch.setattr(aio_mod.AioSandboxProvider, "_sandbox_id_for_thread", lambda _self, _thread_id, _user_id: "sandbox-dead")
    monkeypatch.setattr(aio_mod.AioSandboxProvider, "_get_extra_mounts", lambda _self, _thread_id, *, user_id=None: [])
    monkeypatch.setattr(aio_mod, "get_paths", lambda: Paths(base_dir=tmp_path))
    monkeypatch.setattr(aio_mod, "get_effective_user_id", lambda: None)
    monkeypatch.setattr(aio_mod, "wait_for_sandbox_ready", lambda _url, timeout=60: True)

    sandbox_id = provider.acquire("thread-dead", user_id="default")

    assert sandbox_id == "sandbox-dead"
    sandbox.close.assert_called_once_with()
    provider._backend.destroy.assert_called_once()
    provider._backend.create.assert_called_once()
    assert provider._thread_sandboxes[("default", "thread-dead")] == "sandbox-dead"
    assert provider._sandboxes["sandbox-dead"].base_url == "http://fresh-sandbox"


def test_acquire_keeps_cached_sandbox_when_health_check_errors(tmp_path):
    """Transient backend health-check errors must not destroy a tracked sandbox."""
    provider, sandbox, _ = _make_provider_with_active_sandbox(tmp_path, "sandbox-transient")
    provider._thread_locks = {}
    provider._thread_sandboxes = {("default", "thread-transient"): "sandbox-transient"}
    provider._backend.is_alive = MagicMock(side_effect=OSError("docker daemon busy"))

    sandbox_id = provider.acquire("thread-transient", user_id="default")

    assert sandbox_id == "sandbox-transient"
    sandbox.close.assert_not_called()
    provider._backend.destroy.assert_not_called()
    assert provider._sandboxes["sandbox-transient"] is sandbox


def test_drop_unhealthy_sandbox_skips_recreated_entry(tmp_path):
    """A stale health-check result must not delete a newly registered sandbox."""
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    provider = _make_provider(tmp_path)
    provider._lock = aio_mod.threading.Lock()
    provider._warm_pool = {}
    provider._last_activity = {"sandbox-toctou": 1.0}
    provider._thread_sandboxes = {("default", "thread-toctou"): "sandbox-toctou"}
    old_info = aio_mod.SandboxInfo(sandbox_id="sandbox-toctou", sandbox_url="http://old-sandbox")
    new_info = aio_mod.SandboxInfo(sandbox_id="sandbox-toctou", sandbox_url="http://new-sandbox")
    new_sandbox = MagicMock()
    provider._sandbox_infos = {"sandbox-toctou": new_info}
    provider._sandboxes = {"sandbox-toctou": new_sandbox}
    provider._backend = SimpleNamespace(destroy=MagicMock())

    provider._drop_unhealthy_sandbox("sandbox-toctou", "stale health check", expected_info=old_info)

    new_sandbox.close.assert_not_called()
    provider._backend.destroy.assert_not_called()
    assert provider._sandbox_infos["sandbox-toctou"] is new_info
    assert provider._sandboxes["sandbox-toctou"] is new_sandbox
    assert provider._thread_sandboxes == {("default", "thread-toctou"): "sandbox-toctou"}


def test_acquire_skips_dead_warm_pool_sandbox(tmp_path, monkeypatch):
    """acquire() must create a fresh sandbox when the warm-pool entry died."""
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    provider = _make_provider(tmp_path)
    provider._lock = aio_mod.threading.Lock()
    provider._thread_locks = {}
    provider._sandboxes = {}
    provider._sandbox_infos = {}
    provider._thread_sandboxes = {}
    provider._last_activity = {}
    provider._warm_pool = {
        "sandbox-warm-dead": (
            aio_mod.SandboxInfo(
                sandbox_id="sandbox-warm-dead",
                sandbox_url="http://stale-sandbox",
                container_name="deer-flow-sandbox-sandbox-warm-dead",
            ),
            0.0,
        )
    }
    provider._config = {"replicas": 3}
    provider._backend = SimpleNamespace(
        is_alive=MagicMock(return_value=False),
        destroy=MagicMock(),
        discover=MagicMock(return_value=None),
        create=MagicMock(
            return_value=aio_mod.SandboxInfo(
                sandbox_id="sandbox-warm-dead",
                sandbox_url="http://fresh-sandbox",
                container_name="deer-flow-sandbox-sandbox-warm-dead",
            )
        ),
    )

    monkeypatch.setattr(aio_mod.AioSandboxProvider, "_sandbox_id_for_thread", lambda _self, _thread_id, _user_id: "sandbox-warm-dead")
    monkeypatch.setattr(aio_mod.AioSandboxProvider, "_get_extra_mounts", lambda _self, _thread_id, *, user_id=None: [])
    monkeypatch.setattr(aio_mod, "get_paths", lambda: Paths(base_dir=tmp_path))
    monkeypatch.setattr(aio_mod, "get_effective_user_id", lambda: None)
    monkeypatch.setattr(aio_mod, "wait_for_sandbox_ready", lambda _url, timeout=60: True)

    sandbox_id = provider.acquire("thread-warm-dead", user_id="default")

    assert sandbox_id == "sandbox-warm-dead"
    provider._backend.destroy.assert_called_once()
    provider._backend.create.assert_called_once()
    assert provider._warm_pool == {}
    assert provider._thread_sandboxes[("default", "thread-warm-dead")] == "sandbox-warm-dead"
    assert provider._sandboxes["sandbox-warm-dead"].base_url == "http://fresh-sandbox"


def test_destroy_swallows_close_errors_and_still_destroys_backend(tmp_path, caplog):
    """A failure in sandbox.close() must not skip backend container destruction."""
    provider, sandbox, _ = _make_provider_with_active_sandbox(tmp_path, "sandbox-dest-err")
    sandbox.close.side_effect = RuntimeError("boom")

    with caplog.at_level("WARNING"):
        provider.destroy("sandbox-dest-err")

    assert "Error closing sandbox sandbox-dest-err during destroy" in caplog.text
    provider._backend.destroy.assert_called_once()


def test_cleanup_idle_sandboxes_keeps_active_cleanup_and_delegates_warm_expiry(tmp_path):
    """AIO active-idle cleanup must remain local while warm expiry uses the shared lifecycle."""
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    provider = _make_provider(tmp_path)
    provider._lock = aio_mod.threading.Lock()
    provider._sandboxes = {"active-old": MagicMock()}
    provider._sandbox_infos = {
        "active-old": aio_mod.SandboxInfo(sandbox_id="active-old", sandbox_url="http://active-old"),
    }
    provider._thread_sandboxes = {("default", "thread-old"): "active-old"}
    provider._last_activity = {"active-old": 0.0}
    provider._warm_pool = {
        "warm-old": (
            aio_mod.SandboxInfo(sandbox_id="warm-old", sandbox_url="http://warm-old"),
            0.0,
        )
    }

    calls = []
    # The idle path destroys through `_destroy_tracked`, not `destroy()`: its
    # "still idle?" re-check has to run in the same critical section that
    # reserves the teardown, so it is passed down as a predicate. Asserting on
    # `destroy` here would pass vacuously — it is no longer on this path.
    provider._destroy_tracked = MagicMock(side_effect=lambda _sandbox_id, **_kw: calls.append("active"))
    provider._reap_expired_warm = MagicMock(side_effect=lambda _idle_timeout: calls.append("warm"))

    provider._cleanup_idle_sandboxes(1.0)

    assert provider._destroy_tracked.call_count == 1
    assert provider._destroy_tracked.call_args.args == ("active-old",)
    # The gate must actually be a live predicate, not a constant-true placeholder.
    assert provider._destroy_tracked.call_args.kwargs["still_reapable"]() is True
    provider._reap_expired_warm.assert_called_once_with(1.0)
    assert calls == ["active", "warm"]


def test_create_sandbox_evicts_oldest_warm_replica_via_shared_lifecycle(tmp_path, monkeypatch):
    """Replica enforcement must destroy the oldest warm SandboxInfo before creating another."""
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    provider = _make_provider(tmp_path)
    provider._lock = aio_mod.threading.Lock()
    provider._config = {"replicas": 2}
    provider._sandboxes = {}
    provider._sandbox_infos = {}
    provider._thread_sandboxes = {}
    provider._last_activity = {}

    oldest_info = aio_mod.SandboxInfo(sandbox_id="warm-oldest", sandbox_url="http://warm-oldest")
    newest_info = aio_mod.SandboxInfo(sandbox_id="warm-newest", sandbox_url="http://warm-newest")
    created_info = aio_mod.SandboxInfo(sandbox_id="created", sandbox_url="http://created")
    provider._warm_pool = {
        "warm-newest": (newest_info, 20.0),
        "warm-oldest": (oldest_info, 10.0),
    }
    provider._backend = SimpleNamespace(
        create=MagicMock(return_value=created_info),
        destroy=MagicMock(),
    )
    monkeypatch.setattr(aio_mod.AioSandboxProvider, "_get_extra_mounts", lambda _self, _thread_id, *, user_id=None: [])
    monkeypatch.setattr(aio_mod, "wait_for_sandbox_ready", lambda _url, *, timeout=60: True)

    sandbox_id = provider._create_sandbox(None, "created", user_id="default")

    assert sandbox_id == "created"
    provider._backend.destroy.assert_called_once_with(oldest_info)
    assert "warm-oldest" not in provider._warm_pool
    assert provider._warm_pool == {"warm-newest": (newest_info, 20.0)}
    assert provider._sandbox_infos["created"] is created_info


def _make_tenant_isolation_provider(tmp_path, monkeypatch):
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    provider = _make_provider(tmp_path)
    provider._lock = aio_mod.threading.Lock()
    provider._sandboxes = {}
    provider._sandbox_infos = {}
    provider._thread_sandboxes = {}
    provider._thread_locks = {}
    provider._last_activity = {}
    provider._warm_pool = {}
    provider._active_sandbox_identity = {}
    provider._warm_pool_identity = {}
    provider._shutdown_called = False
    provider._config = {"replicas": 3, "idle_timeout": 0}

    create_calls = []

    def _create(thread_id, sandbox_id, **kwargs):
        create_calls.append((thread_id, sandbox_id, kwargs.get("user_id")))
        return aio_mod.SandboxInfo(
            sandbox_id=sandbox_id,
            sandbox_url=f"http://sandbox-{len(create_calls)}.local",
            container_name=f"deer-flow-sandbox-{sandbox_id}",
        )

    provider._backend = SimpleNamespace(
        create=MagicMock(side_effect=_create),
        destroy=MagicMock(),
        discover=MagicMock(return_value=None),
        is_alive=MagicMock(return_value=True),
        list_running=MagicMock(return_value=[]),
    )
    provider._claim_ownership = MagicMock(return_value=True)
    provider._held_teardown_lease = lambda _sandbox_id: contextlib.nullcontext()

    monkeypatch.setattr(aio_mod, "get_paths", lambda: Paths(base_dir=tmp_path))
    monkeypatch.setattr(
        aio_mod.AioSandboxProvider,
        "_get_extra_mounts",
        lambda self, thread_id, *, user_id=None: [],
    )
    monkeypatch.setattr(
        aio_mod,
        "wait_for_sandbox_ready",
        lambda _url, timeout=60: True,
    )
    return provider, create_calls, aio_mod


def test_aio_wider_id_separates_known_legacy_collision():
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    identity_a, identity_b = _LEGACY_COLLIDING_IDENTITIES
    user_a, thread_a = identity_a
    user_b, thread_b = identity_b

    old_a = hashlib.sha256(f"{user_a}:{thread_a}".encode()).hexdigest()[:8]
    old_b = hashlib.sha256(f"{user_b}:{thread_b}".encode()).hexdigest()[:8]

    assert old_a == old_b
    assert aio_mod.AioSandboxProvider._deterministic_sandbox_id(
        thread_a,
        user_a,
    ) != aio_mod.AioSandboxProvider._deterministic_sandbox_id(
        thread_b,
        user_b,
    )


def test_aio_forced_collision_never_overwrites_active_tenant(
    tmp_path,
    monkeypatch,
):
    provider, create_calls, aio_mod = _make_tenant_isolation_provider(
        tmp_path,
        monkeypatch,
    )
    monkeypatch.setattr(
        aio_mod.AioSandboxProvider,
        "_deterministic_sandbox_id",
        staticmethod(lambda thread_id, user_id: "deadbeefdeadbeef"),
    )

    sandbox_id = provider.acquire("thread-a", user_id="user-a")
    info_a = provider._sandbox_infos[sandbox_id]
    provider.release(sandbox_id)

    assert sandbox_id in provider._warm_pool

    with pytest.raises(aio_mod.SandboxIdentityCollisionError):
        provider.acquire("thread-b", user_id="user-b")

    assert provider._warm_pool[sandbox_id][0] is info_a
    provider._backend.destroy.assert_not_called()
    assert len(create_calls) == 1
    assert provider.acquire("thread-a", user_id="user-a") == sandbox_id
    assert provider._sandbox_infos[sandbox_id] is info_a


# --- #4248 regression: readiness-timeout destroy ownership ---


def _make_unready_destroy_provider(tmp_path, *, sandbox_id, base_url, monkeypatch, aio_mod):
    """Provider wired so ``_create_sandbox`` reaches the readiness-timeout branch.

    ``wait_for_sandbox_ready`` always returns False; the backend records what the
    destroy path did. Mirrors the fixtures used by the warm-replica eviction
    test, minus the warm pool.
    """
    provider = _make_provider(tmp_path)
    provider._lock = aio_mod.threading.Lock()
    provider._config = {"replicas": 3}
    provider._thread_locks = {}
    provider._warm_pool = {}
    provider._sandbox_infos = {}
    provider._thread_sandboxes = {}
    provider._last_activity = {}
    provider._active_sandbox_identity = {}
    provider._warm_pool_identity = {}
    unready_info = aio_mod.SandboxInfo(sandbox_id=sandbox_id, sandbox_url=base_url)
    provider._backend = SimpleNamespace(
        create=MagicMock(return_value=unready_info),
        destroy=MagicMock(),
    )
    monkeypatch.setattr(
        aio_mod.AioSandboxProvider,
        "_get_extra_mounts",
        lambda _self, _thread_id, *, user_id=None: [],
    )
    return provider, unready_info


def test_create_sandbox_claims_ownership_before_readiness_timeout_destroy(tmp_path, monkeypatch):
    """#4248: a readiness-timeout destroy must run under a `del:` teardown lease.

    Before #4248 the unready container was reaped with a bare ``destroy`` call.
    Ownership is published by ``_register_created_sandbox`` only after the
    readiness gate, so for up to 60s the container ran unowned and a peer could
    adopt it; the subsequent stop landed on whatever turn the peer had handed it.
    """
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    provider, unready_info = _make_unready_destroy_provider(
        tmp_path,
        sandbox_id="unready",
        base_url="http://unready",
        monkeypatch=monkeypatch,
        aio_mod=aio_mod,
    )
    monkeypatch.setattr(aio_mod, "wait_for_sandbox_ready", lambda _url, *, timeout=60: False)

    # The heartbeat releases the teardown lease on exit, so the destroy call is
    # the only place we can observe the `del:` state. Snapshot the lease at
    # the instant destroy runs.
    destroy_snapshots: list = []

    def destroy_spy(info):
        destroy_snapshots.append(provider._ownership._leases.get(info.sandbox_id))

    provider._backend.destroy.side_effect = destroy_spy

    with pytest.raises(RuntimeError, match="failed to become ready"):
        provider._create_sandbox("thread-4248", "unready", user_id="user-4248")

    provider._backend.destroy.assert_called_once_with(unready_info)
    assert destroy_snapshots, "destroy must run inside the held teardown lease"
    lease = destroy_snapshots[0]
    assert lease is not None, "teardown lease must be held while destroy runs"
    assert lease.owner_id == provider._owner_id
    assert lease.destroying is True, "destroy must run under a `del:` teardown lease"


@pytest.mark.anyio
async def test_create_sandbox_async_claims_ownership_before_readiness_timeout_destroy(tmp_path, monkeypatch):
    """#4248 (async path): same teardown-lease guard on the async readiness branch."""
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    provider, unready_info = _make_unready_destroy_provider(
        tmp_path,
        sandbox_id="unready-async",
        base_url="http://unready-async",
        monkeypatch=monkeypatch,
        aio_mod=aio_mod,
    )

    async def fake_wait_async(_url, *, timeout=60, poll_interval=1.0):
        return False

    monkeypatch.setattr(aio_mod, "wait_for_sandbox_ready_async", fake_wait_async)
    monkeypatch.setattr(
        aio_mod,
        "wait_for_sandbox_ready",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("sync readiness should not be used")),
    )

    destroy_snapshots: list = []

    def destroy_spy(info):
        destroy_snapshots.append(provider._ownership._leases.get(info.sandbox_id))

    provider._backend.destroy.side_effect = destroy_spy

    with pytest.raises(RuntimeError, match="failed to become ready"):
        await provider._create_sandbox_async("thread-4248-async", "unready-async", user_id="user-4248-async")

    provider._backend.destroy.assert_called_once_with(unready_info)
    assert destroy_snapshots, "destroy must run inside the held teardown lease"
    lease = destroy_snapshots[0]
    assert lease is not None
    assert lease.owner_id == provider._owner_id
    assert lease.destroying is True, "destroy must run under a `del:` teardown lease"


def test_create_sandbox_skips_destroy_when_unready_sandbox_owned_by_peer(tmp_path, monkeypatch):
    """#4248 fail-closed: if a peer already owns the unready container, do not stop it.

    The lease refuses our teardown claim, so the container is left for the peer
    to reap via its own reconciliation. Stopping it anyway would be the
    cross-instance kill this guard exists to prevent.
    """
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    provider, unready_info = _make_unready_destroy_provider(
        tmp_path,
        sandbox_id="peer-owned",
        base_url="http://peer-owned",
        monkeypatch=monkeypatch,
        aio_mod=aio_mod,
    )
    monkeypatch.setattr(aio_mod, "wait_for_sandbox_ready", lambda _url, *, timeout=60: False)

    # Every claim refuses: peer holds the lease (or the store cannot answer).
    provider._ownership.claim = lambda _sid, *, for_destroy=False: False

    with pytest.raises(RuntimeError, match="failed to become ready"):
        provider._create_sandbox("thread-peer", "peer-owned", user_id="user-peer")

    provider._backend.destroy.assert_not_called()


def test_reconcile_does_not_adopt_a_container_whose_unready_teardown_is_reserved(tmp_path, monkeypatch):
    """#4248 follow-up: the readiness-timeout destroy must hold the local
    reservation, not just the cross-instance claim.

    The claim succeeds against our own lease by design, so without
    ``_reserve_local_teardown`` there is a window — readiness failed, claim not
    yet written — in which the idle checker's ``_reconcile_orphans`` sees the
    container running, untracked, and past its recovery grace, and adopts it
    into ``_warm_pool``. The claim then still succeeds (the lease is ours) and
    the stop lands on an entry this instance has just adopted, leaving a dead
    warm entry for the next reclaim to hand out. This is the same interleaving
    shape as ``test_reconcile_does_not_adopt_a_container_this_instance_is_tearing_down``
    in ``test_sandbox_orphan_reconciliation.py``.
    """
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    provider, unready_info = _make_unready_destroy_provider(
        tmp_path,
        sandbox_id="unready-race",
        base_url="http://unready-race",
        monkeypatch=monkeypatch,
        aio_mod=aio_mod,
    )
    provider._unowned_since = {}
    provider._backend.list_running = MagicMock(return_value=[unready_info])
    monkeypatch.setattr(aio_mod, "wait_for_sandbox_ready", lambda _url, *, timeout=60: False)

    # Park the destroy thread after it has reserved the local teardown but
    # before the `del:` claim lands — the exact window reconcile would adopt in.
    at_claim, let_claim = threading.Event(), threading.Event()
    real_claim = provider._claim_ownership

    def gated_claim(sandbox_id, *, for_destroy=False):
        if for_destroy:
            at_claim.set()
            assert let_claim.wait(timeout=5)
        return real_claim(sandbox_id, for_destroy=for_destroy)

    provider._claim_ownership = gated_claim
    reaper = threading.Thread(
        target=lambda: provider._destroy_unready_sandbox("unready-race", unready_info),
        daemon=True,
    )
    reaper.start()
    try:
        assert at_claim.wait(timeout=5), "the unready destroy never reached its claim"
        # Reserved locally, still running, untracked, and the `del:` marker is
        # not written yet — exactly the shape reconcile would have adopted
        # before the reservation wrapped this path.
        provider._reconcile_orphans()
        assert "unready-race" not in provider._warm_pool, "reconcile adopted a container this instance is tearing down"
    finally:
        let_claim.set()
        reaper.join(timeout=5)

    # The reservation is released once the stop returns, and the destroy did run.
    provider._backend.destroy.assert_called_once_with(unready_info)
    assert provider._local_teardown == set(), "a teardown reservation outlived the stop it guarded"


def test_reconcile_adopts_unready_container_when_no_teardown_is_in_flight(tmp_path, monkeypatch):
    """Mirror of the interleaving test: with no destroy running, the same
    not-yet-registered container *is* adoptable, so the guard above cannot
    over-block legitimate reconciliation of a container whose creator crashed
    before the readiness gate.
    """
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    provider, unready_info = _make_unready_destroy_provider(
        tmp_path,
        sandbox_id="adoptable",
        base_url="http://adoptable",
        monkeypatch=monkeypatch,
        aio_mod=aio_mod,
    )
    provider._unowned_since = {}
    provider._backend.list_running = MagicMock(return_value=[unready_info])

    provider._reconcile_orphans()

    assert "adoptable" in provider._warm_pool, "reconcile must still adopt a genuinely unowned container"
