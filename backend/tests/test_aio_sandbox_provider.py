"""Tests for AioSandboxProvider mount helpers."""

import asyncio
import contextlib
import hashlib
import importlib
import os
import stat
import threading
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import httpx
import pytest
from _windows_acl_helpers import _windows_acl_owner_sid, _windows_acl_sids
from pydantic import ValidationError

from deerflow.config.paths import Paths, join_host_path
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.runtime.user_context import reset_current_user, set_current_user
from deerflow.sandbox.acquire_serialization import AcquireSerializer

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

    loaded = provider._load_config()

    assert loaded["thread_data_mounts"] is expected
    assert loaded["skills_container_path"] == "/mnt/skills"
    assert loaded["max_shell_sessions"] is None
    assert "MAX_SHELL_SESSIONS" not in loaded["environment"]


def test_load_config_snapshots_custom_skills_container_path(monkeypatch):
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    sandbox_config = SandboxConfig(
        use="deerflow.community.aio_sandbox:AioSandboxProvider",
    )
    app_config = SimpleNamespace(
        sandbox=sandbox_config,
        stream_bridge=None,
        skills=SimpleNamespace(container_path="/custom-skills"),
    )
    monkeypatch.setattr(aio_mod, "get_app_config", lambda: app_config)
    provider = aio_mod.AioSandboxProvider.__new__(aio_mod.AioSandboxProvider)

    assert provider._load_config()["skills_container_path"] == "/custom-skills"


def test_load_config_wires_bash_command_timeout_to_aio_default(monkeypatch):
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    sandbox_config = SandboxConfig(
        use="deerflow.community.aio_sandbox:AioSandboxProvider",
        bash_command_timeout=42.5,
    )
    app_config = SimpleNamespace(sandbox=sandbox_config, stream_bridge=None)
    monkeypatch.setattr(aio_mod, "get_app_config", lambda: app_config)
    provider = aio_mod.AioSandboxProvider.__new__(aio_mod.AioSandboxProvider)

    assert provider._load_config()["command_timeout"] == 42.5


@pytest.mark.parametrize("invalid_timeout", [float("nan"), float("inf"), float("-inf"), 0, -1])
def test_positive_float_rejects_non_positive_or_non_finite_values(invalid_timeout):
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")

    with pytest.raises(ValueError, match="sandbox.bash_command_timeout must be positive"):
        aio_mod.AioSandboxProvider._positive_float("bash_command_timeout", invalid_timeout, 600)


def test_positive_float_accepts_fractional_value():
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")

    assert aio_mod.AioSandboxProvider._positive_float("bash_command_timeout", 42.5, 600) == 42.5


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_bash_command_timeout_rejects_non_finite_values(value):
    with pytest.raises(ValidationError):
        SandboxConfig(bash_command_timeout=value)


def test_register_created_sandbox_forwards_configured_command_timeout(tmp_path):
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    provider = _make_provider(tmp_path)
    provider._config["command_timeout"] = 42
    provider._warm_pool = {}
    provider._sandbox_infos = {}
    provider._thread_sandboxes = {}
    provider._last_activity = {}
    provider._publish_ownership = MagicMock()
    info = aio_mod.SandboxInfo(sandbox_id="sandbox-timeout", sandbox_url="http://sandbox")

    with patch.object(aio_mod, "AioSandbox") as sandbox_cls:
        provider._register_created_sandbox("thread-timeout", "sandbox-timeout", info, user_id="user-timeout")

    sandbox_cls.assert_called_once_with(
        id="sandbox-timeout",
        base_url="http://sandbox",
        request_headers=info.request_headers,
        default_command_timeout=42,
        lark_cli_broker=False,
    )


def test_load_config_sizes_aio_shell_capacity_for_subagent_runtime(monkeypatch):
    """Twelve subagents must not exceed AIO 1.11's ten-session default."""
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    sandbox_config = SandboxConfig(
        use="deerflow.community.aio_sandbox:AioSandboxProvider",
    )
    app_config = SimpleNamespace(
        sandbox=sandbox_config,
        stream_bridge=None,
        subagent_runtime=SimpleNamespace(max_running=12),
    )
    monkeypatch.setattr(aio_mod, "get_app_config", lambda: app_config)
    provider = aio_mod.AioSandboxProvider.__new__(aio_mod.AioSandboxProvider)

    loaded = provider._load_config()

    assert loaded["max_shell_sessions"] == 13
    assert loaded["environment"]["MAX_SHELL_SESSIONS"] == str(loaded["max_shell_sessions"])


@pytest.mark.parametrize("remote", [False, True], ids=["docker", "provisioner"])
@pytest.mark.parametrize("persisted_capacity", [4, 9, 13])
def test_backend_checks_runtime_minimum_without_overriding_image_default(monkeypatch, remote, persisted_capacity):
    """Removing a four-session override must not reuse it for eight subagents."""
    from deerflow.community.aio_sandbox import aio_sandbox_provider as aio_mod
    from deerflow.community.aio_sandbox import local_backend as local_mod
    from deerflow.community.aio_sandbox import remote_backend as remote_mod

    app_config = SimpleNamespace(
        sandbox=SandboxConfig(
            use="deerflow.community.aio_sandbox:AioSandboxProvider",
            container_prefix="sandbox",
            provisioner_url="http://provisioner:8002" if remote else None,
            environment={"MAX_SHELL_SESSIONS": "4"},
        ),
        stream_bridge=None,
        subagent_runtime=SimpleNamespace(max_running=3),
    )
    monkeypatch.setattr(aio_mod, "get_app_config", lambda: app_config)
    provider = aio_mod.AioSandboxProvider.__new__(aio_mod.AioSandboxProvider)
    assert provider._load_config()["max_shell_sessions"] == 4
    app_config.subagent_runtime.max_running = 8
    app_config.sandbox.environment = {}
    provider._config = provider._load_config()
    assert provider._config["max_shell_sessions"] is None
    assert "MAX_SHELL_SESSIONS" not in provider._config["environment"]
    monkeypatch.setattr(local_mod.LocalContainerBackend, "_detect_runtime", lambda _self: "docker")
    backend = provider._create_backend()
    if remote:
        payload = {"sandbox_id": "example", "sandbox_url": "http://sandbox:8080", "max_shell_sessions": persisted_capacity}

        def get(url, **_kwargs):
            data = {"sandboxes": [payload]} if url.endswith("/api/sandboxes") else payload
            return SimpleNamespace(status_code=200, raise_for_status=lambda: None, json=lambda: data)

        monkeypatch.setattr(remote_mod.requests, "get", get)
    else:
        monkeypatch.setattr(backend, "_is_container_running", lambda _name: True)
        monkeypatch.setattr(local_mod, "wait_for_sandbox_ready", lambda *_a, **_kw: True)
        monkeypatch.setattr(local_mod.subprocess, "run", lambda *_a, **_kw: SimpleNamespace(returncode=0, stdout="sandbox-example\n"))
        inspection = local_mod._ContainerInspection(
            created_at=1.0,
            host_port=18080,
            image="sandbox:latest",
            networks=frozenset({"bridge"}),
            labels={"deerflow.role": "sandbox", "deerflow.sandbox_id": "example", "deerflow.network_mode": "open"},
            max_shell_sessions=persisted_capacity,
        )
        monkeypatch.setattr(backend, "_batch_inspect", lambda *_a, **_kw: {"sandbox-example": inspection})

    discovered = backend.discover("example")
    assert discovered is not None
    assert discovered.requires_replacement is (persisted_capacity < 9)
    listed = backend.list_running()
    assert len(listed) == 1
    assert listed[0].requires_replacement is (persisted_capacity < 9)


def test_load_config_rejects_shell_capacity_below_subagent_runtime(monkeypatch):
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    sandbox_config = SandboxConfig(
        use="deerflow.community.aio_sandbox:AioSandboxProvider",
        environment={"MAX_SHELL_SESSIONS": "12"},
    )
    app_config = SimpleNamespace(
        sandbox=sandbox_config,
        stream_bridge=None,
        subagent_runtime=SimpleNamespace(max_running=12),
    )
    monkeypatch.setattr(aio_mod, "get_app_config", lambda: app_config)
    provider = aio_mod.AioSandboxProvider.__new__(aio_mod.AioSandboxProvider)

    with pytest.raises(ValueError, match=r"at least subagent_runtime\.max_running \+ 1"):
        provider._load_config()


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
    from deerflow.community.aio_sandbox.quarantine import SandboxQuarantine
    from deerflow.config.sandbox_config import SandboxOwnershipConfig

    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    with patch.object(aio_mod.AioSandboxProvider, "_start_idle_checker"):
        provider = aio_mod.AioSandboxProvider.__new__(aio_mod.AioSandboxProvider)
        provider._config = {"command_timeout": 600.0, "idle_timeout": 600, "replicas": 3}
        provider._backend = SimpleNamespace()
        provider._quarantine = SandboxQuarantine(tmp_path / "quarantine", "test")
        provider._sandboxes = {}
        provider._active_sandbox_identity = {}
        provider._warm_pool_identity = {}
        provider._local_teardown = set()
        provider._unowned_since = {}
        provider._acquire_epoch = {}
        provider._acquire_epoch_counter = 0
        provider._acquire_inflight = {}
        provider._acquire_serializer = AcquireSerializer(thread_name_prefix="aio-sandbox-lock-wait")
        provider._acquire_worker_executor = aio_mod.ThreadPoolExecutor(thread_name_prefix="aio-sandbox-owned-worker-test")
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
    config_dir = tmp_path / "users" / "alice" / "integrations" / "lark-cli" / "config"
    locks_dir = config_dir / "locks"
    data_dir = tmp_path / "users" / "alice" / "integrations" / "lark-cli" / "data"
    if os.name == "nt":
        # NTFS cannot represent POSIX modes; the contract the credential-tree
        # hardener establishes on Windows is an owner-only inheritable DACL.
        owner_sid = _windows_acl_owner_sid(config_dir)
        for hardened in (config_dir, locks_dir, data_dir):
            assert _windows_acl_sids(hardened) == {owner_sid}
    else:
        assert stat.S_IMODE(config_dir.stat().st_mode) == 0o700
        assert stat.S_IMODE(locks_dir.stat().st_mode) == 0o700
        assert stat.S_IMODE(data_dir.stat().st_mode) == 0o700
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
    provider._config["skills_container_path"] = config.skills.container_path
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
        "/mnt/skills/public",
        "/mnt/skills/custom",
        "/mnt/skills/legacy",
        "/mnt/skills/integrations",
        lark_cli.LARK_CLI_SANDBOX_CONFIG_DIR,
        lark_cli.LARK_CLI_SANDBOX_LOCKS_DIR,
        lark_cli.LARK_CLI_SANDBOX_DATA_DIR,
        lark_cli.LARK_CLI_SANDBOX_RUNTIME_DIR,
    }


def test_thread_skill_projection_mounts_all_categories(
    tmp_path,
    monkeypatch,
):
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    paths = Paths(base_dir=tmp_path / "home")
    projection_root = paths.thread_skills_view_dir(
        "thread-policy",
        user_id="alice",
    )
    for category in ("public", "custom", "legacy", "integrations"):
        (projection_root / category).mkdir(parents=True, exist_ok=True)
    config = SimpleNamespace(skills=SimpleNamespace(container_path="/mnt/skills"))
    monkeypatch.setattr(aio_mod, "get_app_config", lambda: config)
    monkeypatch.setattr(aio_mod, "get_paths", lambda: paths)

    mounts = aio_mod.AioSandboxProvider._get_skills_mounts(
        "thread-policy",
        user_id="alice",
    )

    assert {container_path: host_path for host_path, container_path, _ in mounts} == {f"/mnt/skills/{category}": str(projection_root / category) for category in ("public", "custom", "legacy", "integrations")}
    assert all(read_only for _host, _container, read_only in mounts)


def test_thread_skill_projection_uses_distinct_sandbox_identity(
    tmp_path,
    monkeypatch,
):
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    paths = Paths(base_dir=tmp_path / "home")
    monkeypatch.setattr(aio_mod, "get_paths", lambda: paths)
    monkeypatch.setattr(
        aio_mod,
        "get_app_config",
        lambda: SimpleNamespace(skills=SimpleNamespace(container_path="/mnt/skills")),
    )
    provider = _make_provider(tmp_path)

    shared_id = provider._sandbox_id_for_thread("thread-policy", "alice")
    paths.thread_skills_view_dir(
        "thread-policy",
        user_id="alice",
    ).mkdir(parents=True)
    policy_id = provider._sandbox_id_for_thread("thread-policy", "alice")

    assert policy_id != shared_id
    assert policy_id == provider._sandbox_id_for_thread("thread-policy", "alice")
    assert policy_id != provider._deterministic_sandbox_id(
        "thread-policy:agent-skills-v1",
        "alice",
    )


def test_policy_scoped_sandbox_identity_changes_with_skills_container_root(
    tmp_path,
    monkeypatch,
):
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    paths = Paths(base_dir=tmp_path / "home")
    paths.thread_skills_view_dir(
        "thread-policy",
        user_id="alice",
    ).mkdir(parents=True)
    monkeypatch.setattr(aio_mod, "get_paths", lambda: paths)
    config = SimpleNamespace(skills=SimpleNamespace(container_path="/mnt/skills"))
    monkeypatch.setattr(aio_mod, "get_app_config", lambda: config)
    provider = _make_provider(tmp_path)

    default_root_id = provider._sandbox_id_for_thread(
        "thread-policy",
        "alice",
    )
    config.skills.container_path = "/custom-skills"
    provider._config["skills_container_path"] = config.skills.container_path
    custom_root_id = provider._sandbox_id_for_thread(
        "thread-policy",
        "alice",
    )

    assert custom_root_id != default_root_id


def test_shared_sandbox_identity_changes_when_custom_skills_root_changes(
    tmp_path,
    monkeypatch,
):
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    paths = Paths(base_dir=tmp_path / "home")
    monkeypatch.setattr(aio_mod, "get_paths", lambda: paths)
    config = SimpleNamespace(skills=SimpleNamespace(container_path="/custom-skills-a"))
    monkeypatch.setattr(aio_mod, "get_app_config", lambda: config)
    provider = _make_provider(tmp_path)
    provider._config["skills_container_path"] = config.skills.container_path

    first_root_id = provider._sandbox_id_for_thread(
        "thread-shared",
        "alice",
    )
    config.skills.container_path = "/custom-skills-b"
    provider._config["skills_container_path"] = config.skills.container_path
    second_root_id = provider._sandbox_id_for_thread(
        "thread-shared",
        "alice",
    )

    assert second_root_id != first_root_id


@pytest.mark.parametrize("active_holder", [False, True], ids=["idle", "in-use"])
def test_cached_sandbox_is_replaced_when_expected_identity_changes(
    tmp_path,
    monkeypatch,
    active_holder,
):
    from deerflow.sandbox.lease import get_sandbox_lease_manager

    provider, sandbox, aio_mod = _make_provider_with_active_sandbox(tmp_path, "stale-root-id")
    provider._config["skills_container_path"] = "/custom-skills"
    provider._thread_sandboxes = {("alice", "thread-shared"): "stale-root-id"}
    monkeypatch.setattr(
        provider,
        "_sandbox_id_for_thread",
        lambda *_args, **_kwargs: "new-root-id",
    )
    manager = get_sandbox_lease_manager(provider)
    try:
        if active_holder:
            manager.retain("live-run", "stale-root-id", thread_id="thread-shared", user_id="alice")
            with pytest.raises(aio_mod.SandboxPolicyReplacementDeferredError, match="outdated skills identity"):
                provider._reuse_in_process_sandbox("thread-shared", user_id="alice")
            assert provider.get("stale-root-id") is sandbox
            sandbox.close.assert_not_called()
            provider._backend.destroy.assert_not_called()
            manager.release("live-run")
        else:
            info = provider._sandbox_infos["stale-root-id"]
            assert provider._reuse_in_process_sandbox("thread-shared", user_id="alice") is None
            sandbox.close.assert_called_once_with()
            provider._backend.destroy.assert_called_once_with(info)
            assert "stale-root-id" not in provider._sandboxes
            assert ("alice", "thread-shared") not in provider._thread_sandboxes
    finally:
        provider.reset()
        provider._ownership.close()


def test_policy_scoped_create_excludes_local_config_mounts_below_skills_root(
    tmp_path,
    monkeypatch,
):
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    paths = Paths(base_dir=tmp_path / "home")
    paths.thread_skills_view_dir(
        "thread-policy",
        user_id="alice",
    ).mkdir(parents=True)
    monkeypatch.setattr(aio_mod, "get_paths", lambda: paths)
    monkeypatch.setattr(
        aio_mod,
        "get_app_config",
        lambda: SimpleNamespace(skills=SimpleNamespace(container_path="/mnt/skills")),
    )

    provider = _make_provider(tmp_path)
    provider._config = {
        "command_timeout": 600.0,
        "replicas": 3,
        "skills_container_path": "/mnt/skills",
    }
    provider._thread_locks = {}
    provider._warm_pool = {}
    provider._sandbox_infos = {}
    provider._thread_sandboxes = {}
    provider._last_activity = {}
    provider._lock = aio_mod.threading.Lock()
    captured: dict = {}

    backend = object.__new__(aio_mod.LocalContainerBackend)

    def _create(thread_id, sandbox_id, **kwargs):
        captured.update(kwargs)
        return aio_mod.SandboxInfo(
            sandbox_id=sandbox_id,
            sandbox_url="http://sandbox",
        )

    backend.create = _create
    provider._backend = backend
    monkeypatch.setattr(provider, "_managed_image_profile", lambda: None)
    monkeypatch.setattr(aio_mod, "wait_for_sandbox_ready", lambda *_a, **_k: True)
    monkeypatch.setattr(provider, "_get_extra_mounts", lambda *_a, **_k: [])
    monkeypatch.setattr(
        aio_mod.AioSandboxProvider,
        "_lark_integration_active",
        staticmethod(lambda user_id=None: False),
    )
    monkeypatch.setattr(
        aio_mod.AioSandboxProvider,
        "_lark_broker_active",
        staticmethod(lambda user_id=None: False),
    )
    monkeypatch.setattr(
        provider,
        "_register_created_sandbox",
        lambda *a, **k: "sandbox-policy",
    )

    provider._create_sandbox(
        "thread-policy",
        "sandbox-policy",
        user_id="alice",
    )

    assert captured["config_mount_exclusion_root"] == "/mnt/skills"


def test_remote_create_forwards_configured_skills_container_path(
    tmp_path,
    monkeypatch,
):
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    provider = _make_provider(tmp_path)
    provider._config = {
        "command_timeout": 600.0,
        "replicas": 3,
        "skills_container_path": "/custom-skills",
    }
    provider._thread_locks = {}
    provider._warm_pool = {}
    provider._sandbox_infos = {}
    provider._thread_sandboxes = {}
    provider._last_activity = {}
    provider._lock = aio_mod.threading.Lock()
    captured: dict = {}

    backend = aio_mod.RemoteSandboxBackend("http://provisioner:8002")

    def _create(thread_id, sandbox_id, **kwargs):
        captured.update(kwargs)
        return aio_mod.SandboxInfo(
            sandbox_id=sandbox_id,
            sandbox_url="http://sandbox",
        )

    backend.create = _create
    provider._backend = backend
    monkeypatch.setattr(
        aio_mod,
        "get_app_config",
        lambda: SimpleNamespace(skills=SimpleNamespace(container_path="/custom-skills")),
    )
    monkeypatch.setattr(aio_mod, "wait_for_sandbox_ready", lambda *_a, **_k: True)
    monkeypatch.setattr(provider, "_get_extra_mounts", lambda *_a, **_k: [])
    monkeypatch.setattr(
        aio_mod.AioSandboxProvider,
        "_lark_integration_active",
        staticmethod(lambda user_id=None: False),
    )
    monkeypatch.setattr(
        aio_mod.AioSandboxProvider,
        "_lark_broker_active",
        staticmethod(lambda user_id=None: False),
    )
    monkeypatch.setattr(
        provider,
        "_register_created_sandbox",
        lambda *a, **k: "sandbox-custom-root",
    )

    provider._create_sandbox(
        "thread-custom-root",
        "sandbox-custom-root",
        user_id="alice",
    )

    assert captured["skills_container_path"] == "/custom-skills"


@pytest.mark.anyio
async def test_remote_create_async_forwards_configured_skills_container_path(
    tmp_path,
    monkeypatch,
):
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    provider = _make_provider(tmp_path)
    provider._config = {
        "command_timeout": 600.0,
        "replicas": 3,
        "skills_container_path": "/custom-skills",
    }
    provider._thread_locks = {}
    provider._warm_pool = {}
    provider._sandbox_infos = {}
    provider._thread_sandboxes = {}
    provider._last_activity = {}
    provider._lock = aio_mod.threading.Lock()
    captured: dict = {}

    backend = aio_mod.RemoteSandboxBackend("http://provisioner:8002")

    def _create(thread_id, sandbox_id, **kwargs):
        captured.update(kwargs)
        return aio_mod.SandboxInfo(
            sandbox_id=sandbox_id,
            sandbox_url="http://sandbox",
        )

    backend.create = _create
    provider._backend = backend
    monkeypatch.setattr(
        aio_mod,
        "get_app_config",
        lambda: SimpleNamespace(skills=SimpleNamespace(container_path="/custom-skills")),
    )

    async def _ready(*_args, **_kwargs):
        return True

    monkeypatch.setattr(aio_mod, "wait_for_sandbox_ready_async", _ready)
    monkeypatch.setattr(provider, "_get_extra_mounts", lambda *_a, **_k: [])
    monkeypatch.setattr(
        aio_mod.AioSandboxProvider,
        "_lark_integration_active",
        staticmethod(lambda user_id=None: False),
    )
    monkeypatch.setattr(
        aio_mod.AioSandboxProvider,
        "_lark_broker_active",
        staticmethod(lambda user_id=None: False),
    )
    monkeypatch.setattr(
        provider,
        "_register_created_sandbox",
        lambda *a, **k: "sandbox-custom-root",
    )

    await provider._create_sandbox_async(
        "thread-custom-root",
        "sandbox-custom-root",
        user_id="alice",
    )

    assert captured["skills_container_path"] == "/custom-skills"


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
async def test_acquire_async_uses_async_readiness_polling(tmp_path, monkeypatch):
    """AioSandboxProvider async creation must not use sync readiness polling."""
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    provider = _make_provider(tmp_path)
    provider._config = {"command_timeout": 600.0, "replicas": 3}
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
async def test_discover_or_create_with_lock_async_cancellation_aborts_flock_wait(tmp_path, monkeypatch):
    """A cancelled waiter must not park until a peer releases the cross-process flock."""
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    provider = _make_provider(tmp_path)
    provider._discover_or_create_with_lock_async = aio_mod.AioSandboxProvider._discover_or_create_with_lock_async.__get__(
        provider,
        aio_mod.AioSandboxProvider,
    )
    provider._backend = SimpleNamespace(discover=MagicMock(return_value=None))

    peer_lock = threading.Lock()
    peer_lock.acquire()
    attempt_seen = threading.Event()
    closed = threading.Event()

    class TrackedLockFile:
        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

        def close(self):
            self._inner.close()
            closed.set()

    def open_lock_file(lock_path):
        return TrackedLockFile(open(lock_path, "a", encoding="utf-8"))

    def try_lock(_lock_file) -> bool:
        attempt_seen.set()
        return peer_lock.acquire(blocking=False)

    monkeypatch.setattr(aio_mod, "get_paths", lambda: Paths(base_dir=tmp_path))
    monkeypatch.setattr(aio_mod, "_open_lock_file", open_lock_file)
    monkeypatch.setattr(aio_mod, "_try_lock_file_exclusive", try_lock)

    owner = asyncio.create_task(
        provider._discover_or_create_with_lock_async(
            "thread-cancel-flock-wait",
            "sandbox-cancel-flock-wait",
            user_id="default",
        )
    )
    try:
        assert await asyncio.to_thread(attempt_seen.wait, 2)
        owner.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(owner, timeout=0.5)
        assert closed.is_set()
        provider._backend.discover.assert_not_called()
    finally:
        peer_lock.release()
        if not owner.done():
            owner.cancel()
            await asyncio.gather(owner, return_exceptions=True)


@pytest.mark.anyio
async def test_discover_or_create_with_lock_async_cancellation_keeps_file_lock_until_worker_finishes(tmp_path, monkeypatch):
    """Caller cancellation must not release the cross-process lock over an admitted worker."""
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    provider = _make_provider(tmp_path)
    provider._discover_or_create_with_lock_async = aio_mod.AioSandboxProvider._discover_or_create_with_lock_async.__get__(
        provider,
        aio_mod.AioSandboxProvider,
    )
    provider._warm_pool = {}
    provider._sandbox_infos = {}
    provider._thread_sandboxes = {}
    provider._sandboxes = {}
    provider._last_activity = {}
    provider._lock = aio_mod.threading.Lock()

    discover_started = threading.Event()
    allow_discover = threading.Event()
    contender_acquired = threading.Event()
    release_contender = threading.Event()
    cross_process_lock = threading.Lock()

    def blocking_discover(_sandbox_id: str):
        discover_started.set()
        assert allow_discover.wait(timeout=2)
        return None

    create_calls: list[tuple[str | None, str, str | None]] = []

    async def fake_create(thread_id: str | None, sandbox_id: str, *, user_id: str | None = None) -> str:
        create_calls.append((thread_id, sandbox_id, user_id))
        return sandbox_id

    def contend_for_lock() -> None:
        cross_process_lock.acquire()
        try:
            contender_acquired.set()
            assert release_contender.wait(timeout=2)
        finally:
            cross_process_lock.release()

    provider._backend = SimpleNamespace(discover=blocking_discover)
    monkeypatch.setattr(provider, "_create_sandbox_async", fake_create)
    monkeypatch.setattr(aio_mod, "get_paths", lambda: Paths(base_dir=tmp_path))
    monkeypatch.setattr(aio_mod, "_try_lock_file_exclusive", lambda _lock_file: cross_process_lock.acquire(blocking=False))
    monkeypatch.setattr(aio_mod, "_unlock_file", lambda _lock_file: cross_process_lock.release())

    owner = asyncio.create_task(
        provider._discover_or_create_with_lock_async(
            "thread-cancel-flock",
            "sandbox-cancel-flock",
            user_id="default",
        )
    )
    contender = None
    try:
        assert await asyncio.to_thread(discover_started.wait, 2)
        owner.cancel()
        contender = asyncio.create_task(asyncio.to_thread(contend_for_lock))

        await asyncio.sleep(0.05)
        assert not contender_acquired.is_set(), "cross-process lock released while discover worker was still running"

        allow_discover.set()
        with pytest.raises(asyncio.CancelledError):
            await owner

        assert await asyncio.to_thread(contender_acquired.wait, 2)
        assert create_calls == []
    finally:
        allow_discover.set()
        release_contender.set()
        if not owner.done():
            owner.cancel()
            await asyncio.gather(owner, return_exceptions=True)
        if contender is not None:
            await contender


@pytest.mark.anyio
async def test_discover_or_create_with_lock_async_cancellation_drains_create_before_unlock(tmp_path, monkeypatch):
    """Cancellation during create must finish the async lifecycle before releasing the flock."""
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    provider = _make_provider(tmp_path)
    provider._discover_or_create_with_lock_async = aio_mod.AioSandboxProvider._discover_or_create_with_lock_async.__get__(
        provider,
        aio_mod.AioSandboxProvider,
    )
    provider._warm_pool = {}
    provider._sandbox_infos = {}
    provider._thread_sandboxes = {}
    provider._sandboxes = {}
    provider._last_activity = {}
    provider._lock = aio_mod.threading.Lock()

    create_started = asyncio.Event()
    allow_create = asyncio.Event()
    create_finished = asyncio.Event()
    contender_acquired = threading.Event()
    release_contender = threading.Event()
    cross_process_lock = threading.Lock()

    async def fake_create(thread_id: str | None, sandbox_id: str, *, user_id: str | None = None) -> str:
        assert thread_id == "thread-cancel-create"
        assert sandbox_id == "sandbox-cancel-create"
        assert user_id == "default"
        create_started.set()
        await allow_create.wait()
        create_finished.set()
        return sandbox_id

    def contend_for_lock() -> None:
        cross_process_lock.acquire()
        try:
            contender_acquired.set()
            assert release_contender.wait(timeout=2)
        finally:
            cross_process_lock.release()

    provider._backend = SimpleNamespace(discover=MagicMock(return_value=None))
    monkeypatch.setattr(provider, "_create_sandbox_async", fake_create)
    monkeypatch.setattr(aio_mod, "get_paths", lambda: Paths(base_dir=tmp_path))
    monkeypatch.setattr(aio_mod, "_try_lock_file_exclusive", lambda _lock_file: cross_process_lock.acquire(blocking=False))
    monkeypatch.setattr(aio_mod, "_unlock_file", lambda _lock_file: cross_process_lock.release())

    owner = asyncio.create_task(
        provider._discover_or_create_with_lock_async(
            "thread-cancel-create",
            "sandbox-cancel-create",
            user_id="default",
        )
    )
    contender = None
    try:
        await asyncio.wait_for(create_started.wait(), timeout=2)
        owner.cancel()
        contender = asyncio.create_task(asyncio.to_thread(contend_for_lock))

        await asyncio.sleep(0.05)
        assert not contender_acquired.is_set(), "flock released before the async create lifecycle finished"

        allow_create.set()
        with pytest.raises(asyncio.CancelledError):
            await owner

        assert create_finished.is_set()
        assert await asyncio.to_thread(contender_acquired.wait, 2)
    finally:
        allow_create.set()
        release_contender.set()
        if not owner.done():
            owner.cancel()
            await asyncio.gather(owner, return_exceptions=True)
        if contender is not None:
            await contender


@pytest.mark.anyio
@pytest.mark.parametrize("blocked_step", ["create", "register"])
async def test_discover_or_create_with_lock_async_cancellation_drains_create_lifecycle_steps(
    blocked_step,
    tmp_path,
    monkeypatch,
):
    """Create/register workers must settle before cancellation releases the flock."""
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    provider = _make_provider(tmp_path)
    provider._discover_or_create_with_lock_async = aio_mod.AioSandboxProvider._discover_or_create_with_lock_async.__get__(
        provider,
        aio_mod.AioSandboxProvider,
    )
    provider._warm_pool = {}
    provider._sandbox_infos = {}
    provider._thread_sandboxes = {}
    provider._sandboxes = {}
    provider._last_activity = {}
    provider._lock = aio_mod.threading.Lock()
    provider._config = {"command_timeout": 600.0, "idle_timeout": 600, "replicas": 3}

    step_started = threading.Event()
    allow_step = threading.Event()
    step_finished = threading.Event()
    register_called = threading.Event()
    contender_acquired = threading.Event()
    release_contender = threading.Event()
    cross_process_lock = threading.Lock()

    info = aio_mod.SandboxInfo(
        sandbox_id="sandbox-cancel-lifecycle",
        sandbox_url="http://sandbox",
    )

    def create(*_args, **_kwargs):
        if blocked_step == "create":
            step_started.set()
            assert allow_step.wait(timeout=2)
            step_finished.set()
        return info

    def register(*_args, **_kwargs):
        register_called.set()
        if blocked_step == "register":
            step_started.set()
            assert allow_step.wait(timeout=2)
            step_finished.set()
        return info.sandbox_id

    async def ready(*_args, **_kwargs):
        return True

    def contend_for_lock() -> None:
        cross_process_lock.acquire()
        try:
            contender_acquired.set()
            assert release_contender.wait(timeout=2)
        finally:
            cross_process_lock.release()

    provider._backend = SimpleNamespace(
        create=create,
        destroy=MagicMock(),
        discover=MagicMock(return_value=None),
    )
    monkeypatch.setattr(provider, "_get_extra_mounts", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(provider, "_lark_integration_active", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(provider, "_lark_broker_active", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(provider, "_local_config_mount_exclusion_root", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(provider, "_replica_count", lambda: (3, 0))
    monkeypatch.setattr(provider, "_register_created_sandbox", register)
    monkeypatch.setattr(aio_mod, "wait_for_sandbox_ready_async", ready)
    monkeypatch.setattr(aio_mod, "get_paths", lambda: Paths(base_dir=tmp_path))
    monkeypatch.setattr(aio_mod, "_try_lock_file_exclusive", lambda _lock_file: cross_process_lock.acquire(blocking=False))
    monkeypatch.setattr(aio_mod, "_unlock_file", lambda _lock_file: cross_process_lock.release())

    owner = asyncio.create_task(
        provider._discover_or_create_with_lock_async(
            "thread-cancel-lifecycle",
            info.sandbox_id,
            user_id="default",
        )
    )
    contender = None
    try:
        assert await asyncio.to_thread(step_started.wait, 2)
        owner.cancel()
        contender = asyncio.create_task(asyncio.to_thread(contend_for_lock))

        await asyncio.sleep(0.05)
        assert not contender_acquired.is_set()

        allow_step.set()
        with pytest.raises(asyncio.CancelledError):
            await owner

        assert step_finished.is_set()
        assert register_called.is_set()
        assert await asyncio.to_thread(contender_acquired.wait, 2)
    finally:
        allow_step.set()
        release_contender.set()
        if not owner.done():
            owner.cancel()
            await asyncio.gather(owner, return_exceptions=True)
        if contender is not None:
            await contender


@pytest.mark.anyio
async def test_acquire_async_lock_wait_uses_dedicated_executor(tmp_path, monkeypatch):
    """Per-thread lock waits should not consume the default asyncio.to_thread pool."""
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    provider = _make_provider(tmp_path)

    async def fail_to_thread(*_args, **_kwargs):
        raise AssertionError("thread-lock acquisition must not use asyncio.to_thread")

    monkeypatch.setattr(aio_mod.asyncio, "to_thread", fail_to_thread)

    async def fake_acquire_internal_async(thread_id: str | None, *, user_id: str) -> str:
        await asyncio.sleep(0)
        return "sandbox-lock-wait"

    monkeypatch.setattr(provider, "_acquire_internal_async", fake_acquire_internal_async)

    thread_id = "thread-lock-wait"
    hold = provider._acquire_serializer.hold(provider._thread_key(thread_id, "default"))
    hold.__enter__()
    try:
        waiter = asyncio.create_task(provider.acquire_async(thread_id, user_id="default"))
        await asyncio.sleep(0.05)
        assert not waiter.done()
    finally:
        hold.__exit__(None, None, None)

    assert await asyncio.wait_for(waiter, timeout=1) == "sandbox-lock-wait"


@pytest.mark.anyio
async def test_acquire_async_cancellation_does_not_leak_thread_lock(tmp_path):
    """Cancelled async lock waiters must not leave the per-thread lock held."""
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    provider = _make_provider(tmp_path)
    provider._warm_pool = {}
    provider._sandbox_infos = {}
    provider._thread_sandboxes = {}
    provider._last_activity = {}
    provider._lock = aio_mod.threading.Lock()

    thread_id = "thread-cancel-lock"
    key = provider._thread_key(thread_id, "default")
    hold = provider._acquire_serializer.hold(key)
    hold.__enter__()

    task = asyncio.create_task(provider.acquire_async(thread_id, user_id="default"))
    await asyncio.sleep(0.05)
    task.cancel()

    try:
        await task
    except asyncio.CancelledError:
        pass

    hold.__exit__(None, None, None)
    deadline = asyncio.get_running_loop().time() + 1
    while asyncio.get_running_loop().time() < deadline:
        if key not in provider._acquire_serializer._table:
            return
        await asyncio.sleep(0.01)

    pytest.fail("provider thread lock was leaked after cancelling acquire_async")


@pytest.mark.anyio
async def test_acquire_async_cancelled_waiter_does_not_block_successor(tmp_path, monkeypatch):
    """A cancelled waiter must not prevent the next live waiter from acquiring."""
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    provider = _make_provider(tmp_path)
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
    key = provider._thread_key(thread_id, "default")
    hold = provider._acquire_serializer.hold(key)
    hold.__enter__()

    cancelled_waiter = asyncio.create_task(provider.acquire_async(thread_id, user_id="default"))
    await asyncio.sleep(0.05)
    cancelled_waiter.cancel()
    try:
        await cancelled_waiter
    except asyncio.CancelledError:
        pass

    live_waiter = asyncio.create_task(provider.acquire_async(thread_id, user_id="default"))
    hold.__exit__(None, None, None)

    assert await asyncio.wait_for(live_waiter, timeout=1) == "sandbox-successor"

    deadline = asyncio.get_running_loop().time() + 1
    while asyncio.get_running_loop().time() < deadline:
        if key not in provider._acquire_serializer._table:
            return
        await asyncio.sleep(0.01)

    pytest.fail("provider thread lock was not released after successor acquire_async")


@pytest.mark.anyio
@pytest.mark.parametrize("blocked_step", ["reuse", "reclaim"])
async def test_acquire_async_cancellation_keeps_serializer_until_started_worker_finishes(
    blocked_step,
    tmp_path,
    monkeypatch,
):
    """A cancelled same-key acquire must not overlap an already-started worker."""
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    provider = _make_provider(tmp_path)
    provider._warm_pool = {}
    provider._sandbox_infos = {}
    provider._thread_sandboxes = {}
    provider._sandboxes = {}
    provider._last_activity = {}
    provider._lock = aio_mod.threading.Lock()

    first_started = threading.Event()
    allow_first_finish = threading.Event()
    successor_started = threading.Event()
    state_lock = threading.Lock()
    active = 0
    max_active = 0
    calls = 0

    monkeypatch.setattr(provider, "_ensure_skills_projection", lambda _user_id: None)

    def blocked_worker(result):
        nonlocal active, max_active, calls
        with state_lock:
            calls += 1
            call_number = calls
            active += 1
            max_active = max(max_active, active)
        try:
            if call_number == 1:
                first_started.set()
                assert allow_first_finish.wait(timeout=2)
            else:
                successor_started.set()
            return result
        finally:
            with state_lock:
                active -= 1

    def reuse(*_args, **_kwargs):
        if blocked_step == "reuse":
            return blocked_worker("sandbox-reused")
        return None

    def reclaim(*_args, **_kwargs):
        if blocked_step == "reclaim":
            return blocked_worker("sandbox-reclaimed")
        raise AssertionError("warm reclaim should not run after cached reuse succeeds")

    monkeypatch.setattr(provider, "_reuse_in_process_sandbox", reuse)
    monkeypatch.setattr(provider, "_reclaim_warm_pool_sandbox", reclaim)

    owner = asyncio.create_task(provider.acquire_async("thread-owned-worker", user_id="default"))
    successor = None
    try:
        assert await asyncio.to_thread(first_started.wait, 2)
        owner.cancel()
        successor = asyncio.create_task(provider.acquire_async("thread-owned-worker", user_id="default"))

        await asyncio.sleep(0.05)
        assert not successor_started.is_set(), "serializer released while cancelled worker was still running"

        allow_first_finish.set()
        with pytest.raises(asyncio.CancelledError):
            await owner

        assert await asyncio.to_thread(successor_started.wait, 2)
        expected = "sandbox-reused" if blocked_step == "reuse" else "sandbox-reclaimed"
        assert await asyncio.wait_for(successor, timeout=1) == expected
        assert max_active == 1
    finally:
        allow_first_finish.set()
        if not owner.done():
            owner.cancel()
            await asyncio.gather(owner, return_exceptions=True)
        if successor is not None and not successor.done():
            successor.cancel()
            await asyncio.gather(successor, return_exceptions=True)
        provider.reset()


@pytest.mark.anyio
async def test_acquire_async_cancellation_cancels_queued_reclaim_before_it_runs(tmp_path, monkeypatch):
    """Cancellation must not force a not-yet-started reclaim to run later."""
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    provider = _make_provider(tmp_path)
    provider._acquire_worker_executor.shutdown(wait=False, cancel_futures=True)
    provider._acquire_worker_executor = aio_mod.ThreadPoolExecutor(
        max_workers=1,
        thread_name_prefix="aio-owned-worker-test",
    )
    provider._warm_pool = {}
    provider._sandbox_infos = {}
    provider._thread_sandboxes = {}
    provider._sandboxes = {}
    provider._last_activity = {}
    provider._lock = aio_mod.threading.Lock()

    blocker_started = threading.Event()
    allow_blocker = threading.Event()
    reclaim_submitted = threading.Event()
    reclaim_calls = 0

    executor = provider._acquire_worker_executor
    original_submit = executor.submit
    submit_count = 0

    def occupy_lifecycle_executor():
        blocker_started.set()
        assert allow_blocker.wait(timeout=2)

    def reuse(*_args, **_kwargs):
        # We are running on the owned-lifecycle executor. Queue the blocker
        # behind this worker before returning None; with max_workers=1 it starts
        # immediately after reuse returns and before the event loop can submit
        # warm reclaim.
        original_submit(occupy_lifecycle_executor)
        return None

    def reclaim(*_args, **_kwargs):
        nonlocal reclaim_calls
        reclaim_calls += 1
        return "sandbox-reclaimed"

    def tracking_submit(*args, **kwargs):
        nonlocal submit_count
        submit_count += 1
        future = original_submit(*args, **kwargs)
        # Submission 1 runs cached reuse; submission 2 is warm reclaim,
        # now queued behind occupy_lifecycle_executor.
        if submit_count == 2:
            reclaim_submitted.set()
        return future

    monkeypatch.setattr(provider, "_ensure_skills_projection", lambda _user_id: None)
    monkeypatch.setattr(provider, "_reuse_in_process_sandbox", reuse)
    monkeypatch.setattr(provider, "_reclaim_warm_pool_sandbox", reclaim)
    monkeypatch.setattr(executor, "submit", tracking_submit)

    owner = asyncio.create_task(provider.acquire_async("thread-queued-reclaim", user_id="default"))
    try:
        assert await asyncio.to_thread(blocker_started.wait, 2)
        assert await asyncio.to_thread(reclaim_submitted.wait, 2)

        owner.cancel()
        with pytest.raises(asyncio.CancelledError):
            await owner

        allow_blocker.set()
        await asyncio.sleep(0.05)
        assert reclaim_calls == 0
    finally:
        allow_blocker.set()
        if not owner.done():
            owner.cancel()
            await asyncio.gather(owner, return_exceptions=True)
        provider._acquire_serializer.close()
        provider._acquire_worker_executor.shutdown(wait=False, cancel_futures=True)


@pytest.mark.anyio
async def test_acquire_async_lock_waiters_do_not_starve_holder_worker(tmp_path, monkeypatch):
    """Lock waiters must not occupy the executor needed by the lock holder."""
    provider = _make_provider(tmp_path)
    provider._acquire_serializer.close()
    provider._acquire_serializer = AcquireSerializer(
        max_workers=2,
        thread_name_prefix="aio-holder-deadlock-test",
    )

    projection_started = threading.Event()
    allow_projection = threading.Event()
    waiter_workers_started = threading.Event()
    count_lock = threading.Lock()
    started_workers = 0
    projection_calls = 0

    executor = provider._acquire_serializer.executor
    original_submit = executor.submit

    def tracking_submit(func, /, *args, **kwargs):
        def tracked():
            nonlocal started_workers
            with count_lock:
                started_workers += 1
                if started_workers >= 3:
                    waiter_workers_started.set()
            return func(*args, **kwargs)

        return original_submit(tracked)

    def ensure_projection(_user_id):
        nonlocal projection_calls
        projection_calls += 1
        if projection_calls == 1:
            projection_started.set()
            assert allow_projection.wait(timeout=2)

    monkeypatch.setattr(executor, "submit", tracking_submit)
    monkeypatch.setattr(provider, "_ensure_skills_projection", ensure_projection)
    monkeypatch.setattr(
        provider,
        "_reuse_in_process_sandbox",
        lambda *_args, **_kwargs: "sandbox-cached",
    )

    owner = asyncio.create_task(provider.acquire_async("thread-holder-deadlock", user_id="default"))
    successors: list[asyncio.Task[str]] = []
    try:
        assert await asyncio.to_thread(projection_started.wait, 2)
        successors = [asyncio.create_task(provider.acquire_async("thread-holder-deadlock", user_id="default")) for _ in range(2)]
        # Submission 1 acquired the holder's key. Submissions 2 and 3 are now
        # both running in the bounded serializer pool, blocked on that same key.
        assert await asyncio.to_thread(waiter_workers_started.wait, 2)

        allow_projection.set()
        assert await asyncio.wait_for(owner, timeout=1) == "sandbox-cached"
        assert await asyncio.wait_for(
            asyncio.gather(*successors),
            timeout=1,
        ) == ["sandbox-cached", "sandbox-cached"]
    finally:
        allow_projection.set()
        if not owner.done():
            owner.cancel()
        for task in successors:
            if not task.done():
                task.cancel()
        await asyncio.gather(owner, *successors, return_exceptions=True)
        provider.reset()


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
        "skills_container_path": "/mnt/skills",
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


def test_remote_backend_forwards_shell_capacity_to_provisioner(monkeypatch):
    remote_mod = importlib.import_module("deerflow.community.aio_sandbox.remote_backend")
    backend = remote_mod.RemoteSandboxBackend(
        "http://provisioner:8002",
        max_shell_sessions=13,
    )
    posted: dict = {}

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"sandbox_url": "http://sandbox.local", "max_shell_sessions": 13}

    def _post(url, json, timeout, headers=None):  # noqa: A002 - mirrors requests.post kwarg
        posted.update({"url": url, "json": json, "timeout": timeout})
        return _Response()

    monkeypatch.setattr(remote_mod.requests, "post", _post)
    monkeypatch.setattr(remote_mod, "user_should_see_legacy_skills", lambda _user_id: False)

    backend.create("thread-42", "sandbox-42", user_id="user-7")

    assert posted["json"]["max_shell_sessions"] == 13


def test_create_sandbox_requests_runtime_when_lark_installed(tmp_path, monkeypatch):
    """The provider must request lark-cli runtime provisioning when Lark is installed."""
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    provider = _make_provider(tmp_path)
    provider._config = {"command_timeout": 600.0, "replicas": 3}
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
    provider._config = {"command_timeout": 600.0, "replicas": 3}
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
    provider._config = {"command_timeout": 600.0, "replicas": 3}
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


@pytest.mark.asyncio
@pytest.mark.parametrize("async_create", [False, True])
async def test_unknown_broker_probe_stops_creation_before_mounts(tmp_path, monkeypatch, async_create):
    from deerflow.integrations import lark_cli

    provider, _, provider_mod = _make_provider_with_active_sandbox(tmp_path, "sandbox-probe")
    monkeypatch.setattr(provider, "_get_extra_mounts", lambda *_args, **_kwargs: [("credentials", "/mnt/integrations/lark-cli/config", True)])
    monkeypatch.setattr(provider_mod.AioSandboxProvider, "_lark_integration_active", staticmethod(lambda *_args: True))
    monkeypatch.setattr(lark_cli, "sandbox_lark_broker_active", MagicMock(side_effect=RuntimeError("Provisioner capability is unknown")))
    provider._backend.create = MagicMock()

    with pytest.raises(RuntimeError, match="capability is unknown"):
        if async_create:
            await provider._create_sandbox_async("thread", "sandbox", user_id="alice")
        else:
            await asyncio.to_thread(provider._create_sandbox, "thread", "sandbox", user_id="alice")
    provider._backend.create.assert_not_called()
    provider.reset()


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
    sandbox.requires_container_recycle = False
    provider._sandboxes = {sandbox_id: sandbox}
    return provider, sandbox, aio_mod


@pytest.fixture()
def failure_recovery_lifecycle(tmp_path, monkeypatch):
    """Keep server-side shell state while release/reclaim replaces SDK clients."""
    from deerflow.community.aio_sandbox import aio_sandbox as sandbox_mod

    provider, _, provider_mod = _make_provider_with_active_sandbox(tmp_path, "sandbox-failure-recovery")
    provider._backend.complete_absent_teardown = MagicMock()
    info = provider._sandbox_infos["sandbox-failure-recovery"]
    info.sandbox_url = "https://sandbox.example.test"
    info.container_id = "container-generation-1"
    shell = MagicMock(spec=["exec_command", "create_session", "cleanup_session"])
    shell.exec_command.return_value = SimpleNamespace(data=SimpleNamespace(output="next-turn", exit_code=0, status="completed"))
    shell.create_session.side_effect = lambda id, **_kwargs: SimpleNamespace(data=SimpleNamespace(session_id=id))
    monkeypatch.setattr(sandbox_mod, "AioSandboxClient", lambda **_kwargs: SimpleNamespace(shell=shell, close=MagicMock()))
    sandbox = sandbox_mod.AioSandbox(id=info.sandbox_id, base_url=info.sandbox_url)
    sandbox.lark_cli_broker = info.lark_cli_broker
    provider._sandboxes[info.sandbox_id] = sandbox
    provider._thread_sandboxes[("alice", "thread-failure-recovery")] = info.sandbox_id
    provider._active_sandbox_identity[info.sandbox_id] = ("alice", "thread-failure-recovery")
    monkeypatch.setattr(provider, "_check_tracked_sandbox_alive", lambda *_args: True)
    monkeypatch.setattr(provider, "_ensure_skills_projection", lambda *_args: None)
    monkeypatch.setattr(provider, "_thread_skill_projection_active", lambda *_args: False)
    monkeypatch.setattr(provider, "_sandbox_id_for_thread", lambda *_args: info.sandbox_id)
    monkeypatch.setattr(provider_mod, "get_paths", lambda: Paths(base_dir=tmp_path / "state"))

    try:
        yield provider, sandbox, shell, info
    finally:
        for active_sandbox in list(provider._sandboxes.values()):
            active_sandbox.close()
        sandbox.close()
        provider.reset()
        provider._ownership.close()


@pytest.mark.parametrize(
    "outcome",
    [
        pytest.param(
            "read_timeout",
            id="transport-timeout",
        ),
        pytest.param(
            "no_change_timeout",
            id="no-change-timeout",
        ),
        pytest.param("hard_timeout", id="confirmed-termination-stays-warm"),
        pytest.param("completed", id="completed-command-stays-warm"),
    ],
)
def test_default_shell_outcome_release_reclaim_preserves_isolation(failure_recovery_lifecycle, outcome):
    """A new client must not revive a fenced implicit session in the same container."""
    provider, sandbox, shell, info = failure_recovery_lifecycle
    ambiguous = outcome in ("read_timeout", "no_change_timeout")
    if outcome == "read_timeout":
        first_response = httpx.ReadTimeout("command response timed out")
    else:
        first_exit_code = {"no_change_timeout": None, "hard_timeout": 124, "completed": 0}[outcome]
        first_response = SimpleNamespace(data=SimpleNamespace(output="first-turn", exit_code=first_exit_code, status=outcome))
    shell.exec_command.side_effect = [first_response, shell.exec_command.return_value]

    first_output = sandbox.execute_command("first-command")
    assert shell.exec_command.call_count == 1, "an ambiguous command must not be replayed"
    assert shell.exec_command.call_args.kwargs.get("id") is None
    if ambiguous:
        assert "outcome is unknown" in first_output.lower()
    elif outcome == "hard_timeout":
        assert "Exit Code: 124" in first_output

    provider.release(info.sandbox_id)
    reclaimed_id = provider._reclaim_warm_pool_sandbox("thread-failure-recovery", info.sandbox_id, user_id="alice")
    if reclaimed_id is not None:
        next_sandbox = provider.get(reclaimed_id)
        assert next_sandbox is not sandbox
        assert next_sandbox.execute_command("next-command") == "next-turn"

    implicit_commands = [call.kwargs["command"] for call in shell.exec_command.call_args_list if call.kwargs.get("id") is None]
    if ambiguous:
        # Either recycle the container or preserve the fence and use a new
        # explicit session. Re-entering the old implicit shell is unsafe.
        assert implicit_commands == ["first-command"], "release/reclaim must not erase the implicit-session fence"
    else:
        assert reclaimed_id == info.sandbox_id
        assert implicit_commands == ["first-command", "next-command"]
        provider._backend.destroy.assert_not_called()


def test_failed_dirty_release_cannot_readopt_same_container(failure_recovery_lifecycle):
    """A failed stop must not make the same server generation safe to acquire."""
    provider, sandbox, shell, info = failure_recovery_lifecycle
    shell.exec_command.side_effect = httpx.ReadTimeout("command response timed out")
    assert "outcome is unknown" in sandbox.execute_command("first-command").lower()
    shell.create_session.side_effect = httpx.ReadTimeout("recovery create response timed out")
    assert "session creation outcome is unknown" in sandbox.execute_command("recovery-command")
    assert sandbox.requires_container_recycle is True
    provider._backend.destroy.side_effect = RuntimeError("container stop failed")
    provider._backend.discover = MagicMock(return_value=info)
    provider._backend.create = MagicMock(side_effect=AssertionError("the quarantined generation is still running"))

    provider.release(info.sandbox_id)
    provider._backend.destroy.assert_called_once_with(info)
    assert info.sandbox_id not in provider._warm_pool

    try:
        acquired_id = provider.acquire("thread-failure-recovery", user_id="alice")
    except RuntimeError as error:
        # Unrelated acquire failures must not masquerade as a quarantine fix.
        message = str(error).lower()
        assert any(reason in message for reason in ("quarantin", "recycl", "incompatible provisioning policy"))
        return

    assert acquired_id != info.sandbox_id, "a failed destroy must not permit discovery to clear the same container's quarantine"


def test_quarantined_generation_stays_fenced_after_provider_restart(failure_recovery_lifecycle, tmp_path):
    provider, sandbox, shell, info = failure_recovery_lifecycle
    shell.exec_command.side_effect = httpx.ReadTimeout("command response timed out")
    sandbox.execute_command("uncertain-command")
    provider._backend.destroy.side_effect = RuntimeError("stop failed")
    provider.release(info.sandbox_id)

    restarted, old_client, _ = _make_provider_with_active_sandbox(tmp_path, info.sandbox_id)
    restarted._sandboxes.clear()
    restarted._sandbox_infos.clear()
    old_client.close()
    restarted._ensure_skills_projection = lambda *_args: None
    restarted._thread_skill_projection_active = lambda *_args: False
    restarted._sandbox_id_for_thread = lambda *_args: info.sandbox_id
    # Fresh metadata intentionally drops all in-memory flags, as discovery does.
    restarted._backend.discover = MagicMock(return_value=type(info).from_dict(info.to_dict()))
    restarted._backend.destroy.side_effect = RuntimeError("stop still failing")
    restarted._backend.create = MagicMock(side_effect=AssertionError("old generation is still running"))
    try:
        with pytest.raises(RuntimeError, match="incompatible provisioning policy"):
            restarted.acquire("thread-failure-recovery", user_id="alice")

        restarted._backend.discover.return_value = type(info)(info.sandbox_id, info.sandbox_url, container_id="container-generation-2")
        assert restarted.acquire("thread-failure-recovery", user_id="alice") == info.sandbox_id
        assert restarted._sandbox_infos[info.sandbox_id].container_id == "container-generation-2"
        restarted._backend.create.assert_not_called()
    finally:
        for active in restarted._sandboxes.values():
            active.close()
        restarted.reset()


def test_failed_quarantine_write_keeps_dirty_container_tracked(failure_recovery_lifecycle, monkeypatch):
    from pathlib import Path

    provider, sandbox, shell, info = failure_recovery_lifecycle
    shell.exec_command.side_effect = httpx.ReadTimeout("command response timed out")
    sandbox.execute_command("uncertain-command")
    original_open = Path.open
    with monkeypatch.context() as patcher:
        patcher.setattr(Path, "open", MagicMock(side_effect=PermissionError("quarantine unavailable")))
        provider.release(info.sandbox_id)
        provider._backend.destroy.assert_not_called()
        assert provider.get(info.sandbox_id) is sandbox
        with pytest.raises(PermissionError):
            provider.destroy(info.sandbox_id)
        assert provider.get(info.sandbox_id) is sandbox
    assert Path.open is original_open
    provider._backend.destroy.side_effect = RuntimeError("stop failed")
    with pytest.raises(RuntimeError, match="stop failed"):
        provider.destroy(info.sandbox_id)
    assert provider._quarantine_store().contains(info)


@pytest.mark.asyncio
@pytest.mark.parametrize("async_acquire", [False, True])
@pytest.mark.parametrize("new_generation", [None, "replacement-generation"])
async def test_unknown_generation_can_be_replaced_after_confirmed_absence(failure_recovery_lifecycle, monkeypatch, async_acquire, new_generation):
    provider, sandbox, shell, info = failure_recovery_lifecycle
    info.container_id = None  # Apple Container discovery / older provisioner.
    shell.exec_command.side_effect = httpx.ReadTimeout("command response timed out")
    sandbox.execute_command("uncertain-command")
    provider.release(info.sandbox_id)
    assert provider._quarantine_store().contains(info)
    fresh = type(info)(info.sandbox_id, info.sandbox_url, container_id=new_generation)
    provider._backend.discover = MagicMock(return_value=None)
    provider._backend.create = MagicMock(return_value=fresh)

    def confirm_absence(_sandbox_id):
        assert provider._ownership.owner(info.sandbox_id) == provider._owner_id
        assert info.sandbox_id in provider._local_teardown
        return True

    provider._backend.is_absent = MagicMock(side_effect=confirm_absence)
    monkeypatch.setattr(provider, "_get_extra_mounts", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(type(provider), "_lark_integration_active", staticmethod(lambda *_args: False))
    monkeypatch.setattr(importlib.import_module(type(provider).__module__), "wait_for_sandbox_ready", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(importlib.import_module(type(provider).__module__), "wait_for_sandbox_ready_async", AsyncMock(return_value=True))

    if async_acquire:
        acquired = await provider.acquire_async("thread-failure-recovery", user_id="alice")
    else:
        acquired = provider.acquire("thread-failure-recovery", user_id="alice")

    assert acquired == info.sandbox_id
    assert provider._sandbox_infos[acquired] is fresh
    assert not provider._quarantine_store().contains(fresh)
    provider._backend.is_absent.assert_called_once_with(info.sandbox_id)


@pytest.mark.parametrize("blocked_by", ["existing-runtime", "probe-error", "peer"])
def test_quarantine_retirement_cannot_bypass_absence_or_ownership(failure_recovery_lifecycle, monkeypatch, blocked_by):
    provider, sandbox, shell, info = failure_recovery_lifecycle
    info.container_id = None
    shell.exec_command.side_effect = httpx.ReadTimeout("command response timed out")
    sandbox.execute_command("uncertain-command")
    provider.release(info.sandbox_id)
    provider._backend.create = MagicMock(side_effect=AssertionError("quarantine must be checked before creation"))
    provider._backend.is_absent = MagicMock(return_value=blocked_by == "peer")
    if blocked_by == "probe-error":
        provider._backend.is_absent.side_effect = RuntimeError("runtime unavailable")
    if blocked_by == "peer":
        monkeypatch.setattr(provider, "_claim_ownership", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(provider, "_get_extra_mounts", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(type(provider), "_lark_integration_active", staticmethod(lambda *_args: False))

    with pytest.raises(RuntimeError):
        provider._create_sandbox("thread-failure-recovery", info.sandbox_id, user_id="alice")

    provider._backend.create.assert_not_called()
    assert provider._quarantine_store().contains(info)
    assert info.sandbox_id not in provider._local_teardown
    if blocked_by == "peer":
        provider._backend.is_absent.assert_not_called()


def _prepare_quarantined_runtime_retry(lifecycle, monkeypatch, current):
    provider, sandbox, shell, old = lifecycle
    shell.exec_command.side_effect = httpx.ReadTimeout("uncertain command")
    sandbox.execute_command("uncertain-command")
    provider._backend.destroy.side_effect = RuntimeError("temporary stop failure")
    provider.release(old.sandbox_id)
    provider._backend.destroy.reset_mock()
    provider._backend.destroy.side_effect = None
    provider._backend.discover = MagicMock(return_value=None)
    provider._backend.inspect_runtime = MagicMock(return_value=current)
    provider._backend.create = MagicMock(return_value=current)
    provider._backend.is_absent = MagicMock(return_value=False)
    monkeypatch.setattr(provider, "_get_extra_mounts", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(type(provider), "_lark_integration_active", staticmethod(lambda *_args: False))
    provider_mod = importlib.import_module(type(provider).__module__)
    monkeypatch.setattr(provider_mod, "wait_for_sandbox_ready", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(provider_mod, "wait_for_sandbox_ready_async", AsyncMock(return_value=True))
    return provider, old


@pytest.mark.asyncio
@pytest.mark.parametrize("async_acquire", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("initially_absent", [False, True], ids=["after-delete", "already-absent"])
@pytest.mark.parametrize("cleanup_failure", [False, True], ids=["complete", "cleanup-failed"])
async def test_absent_teardown_completion_precedes_quarantine_retirement_under_fences(failure_recovery_lifecycle, monkeypatch, async_acquire, initially_absent, cleanup_failure):
    old = failure_recovery_lifecycle[3]
    current = type(old)(old.sandbox_id, "", container_id=old.container_id)
    provider, old = _prepare_quarantined_runtime_retry(failure_recovery_lifecycle, monkeypatch, current)
    fresh = type(old)(old.sandbox_id, old.sandbox_url, container_id="new-generation")
    provider._backend.create.return_value = fresh
    provider._backend.is_absent.side_effect = [True] if initially_absent else [False, True]
    completed = []

    def complete_absent_teardown(sandbox_id):
        assert sandbox_id == old.sandbox_id
        assert provider._backend.is_absent.call_count == (1 if initially_absent else 2)
        lease = provider._ownership._leases[sandbox_id]
        assert lease.owner_id == provider._owner_id and lease.destroying is True
        assert sandbox_id in provider._local_teardown
        assert provider._quarantine_store().contains(old)
        provider._backend.create.assert_not_called()
        completed.append(sandbox_id)
        if cleanup_failure:
            raise RuntimeError("absent runtime cleanup incomplete")

    provider._backend.complete_absent_teardown.side_effect = complete_absent_teardown

    async def acquire():
        if async_acquire:
            return await provider.acquire_async("thread-failure-recovery", user_id="alice")
        return await asyncio.to_thread(provider.acquire, "thread-failure-recovery", user_id="alice")

    if cleanup_failure:
        with pytest.raises(RuntimeError, match="absent runtime cleanup incomplete"):
            await acquire()
        assert provider._quarantine_store().contains(old)
        provider._backend.create.assert_not_called()
    else:
        assert await acquire() == old.sandbox_id
        assert provider._sandbox_infos[old.sandbox_id] is fresh
        assert not provider._quarantine_store().contains(old)
    assert completed == [old.sandbox_id]
    provider._backend.complete_absent_teardown.assert_called_once_with(old.sandbox_id)
    assert old.sandbox_id not in provider._local_teardown


@pytest.mark.asyncio
@pytest.mark.parametrize("async_acquire", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("generation", ["container-generation-1", None], ids=["known-generation", "unknown-generation"])
async def test_quarantined_runtime_without_endpoint_is_deleted_before_replacement(failure_recovery_lifecycle, monkeypatch, async_acquire, generation):
    old = failure_recovery_lifecycle[3]
    current = type(old)(old.sandbox_id, "", container_id=generation)
    provider, old = _prepare_quarantined_runtime_retry(failure_recovery_lifecycle, monkeypatch, current)
    fresh = type(old)(old.sandbox_id, old.sandbox_url, container_id="new-generation")
    provider._backend.create.return_value = fresh
    operations = []

    def confirm_absence(sandbox_id):
        assert sandbox_id == old.sandbox_id
        assert provider._ownership.owner(sandbox_id) == provider._owner_id
        assert sandbox_id in provider._local_teardown
        operations.append("absence")
        return operations.count("absence") == 2

    def inspect_runtime(sandbox_id):
        assert provider._ownership.owner(sandbox_id) == provider._owner_id
        assert sandbox_id in provider._local_teardown
        operations.append("inspect")
        return current

    def destroy(info):
        assert info is current
        # Runtime inspection restores identity, not the original cleanup intent.
        # Force full replacement cleanup even after the deployment switches open.
        assert info.requires_replacement is True
        assert provider._ownership.owner(info.sandbox_id) == provider._owner_id
        assert info.sandbox_id in provider._local_teardown
        operations.append("destroy")

    provider._backend.is_absent.side_effect = confirm_absence
    provider._backend.inspect_runtime.side_effect = inspect_runtime
    provider._backend.destroy.side_effect = destroy

    if async_acquire:
        acquired = await provider.acquire_async("thread-failure-recovery", user_id="alice")
    else:
        acquired = await asyncio.to_thread(provider.acquire, "thread-failure-recovery", user_id="alice")

    assert acquired == old.sandbox_id
    assert operations == ["absence", "inspect", "destroy", "absence"]
    assert provider._sandbox_infos[acquired] is fresh
    assert not provider._quarantine_store().contains(old)


@pytest.mark.asyncio
@pytest.mark.parametrize("blocked_step", ["destroy", "absent-completion"])
async def test_cancelled_quarantine_retry_drains_cleanup_before_releasing_fences(failure_recovery_lifecycle, monkeypatch, blocked_step):
    old = failure_recovery_lifecycle[3]
    current = type(old)(old.sandbox_id, "", container_id=old.container_id)
    provider, old = _prepare_quarantined_runtime_retry(failure_recovery_lifecycle, monkeypatch, current)
    fresh = type(old)(old.sandbox_id, old.sandbox_url, container_id="new-generation")
    provider._backend.create.return_value = fresh
    cleanup_started = threading.Event()
    finish_cleanup = threading.Event()
    cleanup_finished = threading.Event()
    unlocked = threading.Event()
    provider._backend.is_absent.side_effect = [False, True]
    provider_mod = importlib.import_module(type(provider).__module__)
    original_unlock = provider_mod._unlock_file

    def wait_cleanup():
        lease = provider._ownership._leases[old.sandbox_id]
        assert lease.owner_id == provider._owner_id and lease.destroying is True
        assert old.sandbox_id in provider._local_teardown
        assert provider._quarantine_store().contains(old)
        cleanup_started.set()
        assert finish_cleanup.wait(5)
        cleanup_finished.set()

    def destroy(info):
        assert info is current
        assert info.requires_replacement is True
        if blocked_step == "destroy":
            wait_cleanup()

    def complete_absent_teardown(sandbox_id):
        assert sandbox_id == old.sandbox_id
        assert provider._backend.is_absent.call_count == 2
        if blocked_step == "absent-completion":
            wait_cleanup()

    def unlock(lock_file):
        assert cleanup_finished.is_set()
        assert not provider._quarantine_store().contains(old)
        original_unlock(lock_file)
        unlocked.set()

    provider._backend.destroy.side_effect = destroy
    provider._backend.complete_absent_teardown.side_effect = complete_absent_teardown
    monkeypatch.setattr(provider_mod, "_unlock_file", unlock)
    task = asyncio.create_task(provider.acquire_async("thread-failure-recovery", user_id="alice"))
    try:
        assert await asyncio.to_thread(cleanup_started.wait, 5)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        assert not unlocked.is_set()
        assert old.sandbox_id in provider._local_teardown
        assert provider._quarantine_store().contains(old)
        finish_cleanup.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cleanup_finished.is_set() and unlocked.is_set()
        assert old.sandbox_id not in provider._local_teardown
        assert provider._sandbox_infos[old.sandbox_id] is fresh
    finally:
        finish_cleanup.set()
        if not task.done():
            task.cancel()
        with contextlib.suppress(asyncio.CancelledError, RuntimeError):
            await task


@pytest.mark.asyncio
@pytest.mark.parametrize("async_acquire", [False, True], ids=["sync", "async"])
async def test_old_quarantine_does_not_destroy_replacement_when_endpoint_is_missing(failure_recovery_lifecycle, monkeypatch, async_acquire):
    old = failure_recovery_lifecycle[3]
    replacement = type(old)(old.sandbox_id, old.sandbox_url, container_id="new-generation")
    provider, old = _prepare_quarantined_runtime_retry(failure_recovery_lifecycle, monkeypatch, replacement)

    if async_acquire:
        acquired = await provider.acquire_async("thread-failure-recovery", user_id="alice")
    else:
        acquired = await asyncio.to_thread(provider.acquire, "thread-failure-recovery", user_id="alice")

    assert acquired == old.sandbox_id
    provider._backend.destroy.assert_not_called()
    assert provider._sandbox_infos[acquired] is replacement
    # The live replacement proves the fenced old generation is absent, so its
    # stale record is pruned instead of stranding every future create on the
    # inspect-and-defer path. The replacement itself stays unfenced.
    assert not provider._quarantine_store().contains(old)
    assert not provider._quarantine_store().contains(replacement)
    provider._backend.complete_absent_teardown.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("async_acquire", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("final_probe", ["still-present", "unavailable"])
async def test_accepted_delete_keeps_quarantine_until_runtime_disappears(failure_recovery_lifecycle, monkeypatch, async_acquire, final_probe):
    from deerflow.community.aio_sandbox.aio_sandbox_provider import SandboxPolicyReplacementDeferredError

    old = failure_recovery_lifecycle[3]
    current = type(old)(old.sandbox_id, "", container_id=old.container_id)
    provider, old = _prepare_quarantined_runtime_retry(failure_recovery_lifecycle, monkeypatch, current)
    provider._backend.is_absent.return_value = False
    expected_error = SandboxPolicyReplacementDeferredError
    if final_probe == "unavailable":
        expected_error = RuntimeError
        provider._backend.is_absent.side_effect = [False, RuntimeError("final presence probe unavailable")]

    with pytest.raises(expected_error):
        if async_acquire:
            await provider.acquire_async("thread-failure-recovery", user_id="alice")
        else:
            await asyncio.to_thread(provider.acquire, "thread-failure-recovery", user_id="alice")

    provider._backend.destroy.assert_called_once_with(current)
    provider._backend.create.assert_not_called()
    assert provider._quarantine_store().contains(old)
    assert old.sandbox_id not in provider._local_teardown

    fresh = type(old)(old.sandbox_id, old.sandbox_url, container_id="new-generation")
    provider._backend.is_absent.side_effect = None
    provider._backend.is_absent.return_value = True
    provider._backend.create.return_value = fresh
    if async_acquire:
        acquired = await provider.acquire_async("thread-failure-recovery", user_id="alice")
    else:
        acquired = await asyncio.to_thread(provider.acquire, "thread-failure-recovery", user_id="alice")

    assert provider._sandbox_infos[acquired] is fresh
    assert not provider._quarantine_store().contains(old)


@pytest.mark.parametrize("blocked_by", ["presence", "inspection", "storage", "peer", "local-reservation", "mismatched-identity"])
def test_quarantined_runtime_retry_fails_closed_before_destroy(failure_recovery_lifecycle, monkeypatch, blocked_by):
    old = failure_recovery_lifecycle[3]
    current = type(old)(old.sandbox_id, "", container_id=old.container_id)
    provider, old = _prepare_quarantined_runtime_retry(failure_recovery_lifecycle, monkeypatch, current)
    expected_error = RuntimeError
    if blocked_by == "presence":
        provider._backend.is_absent.side_effect = RuntimeError("presence unavailable")
    elif blocked_by == "inspection":
        provider._backend.inspect_runtime.side_effect = RuntimeError("runtime inspection unavailable")
    elif blocked_by == "storage":
        expected_error = PermissionError
        store = provider._quarantine_store()
        original_contains = store.contains

        def contains(info):
            if info is current:
                raise PermissionError("quarantine unavailable")
            return original_contains(info)

        monkeypatch.setattr(store, "contains", contains)
    elif blocked_by == "peer":
        monkeypatch.setattr(provider, "_claim_ownership", lambda *_args, **_kwargs: False)
    elif blocked_by == "local-reservation":
        provider._local_teardown.add(old.sandbox_id)
    elif blocked_by == "mismatched-identity":
        provider._backend.inspect_runtime.return_value = type(old)("another-sandbox", "", container_id=old.container_id)

    with pytest.raises(expected_error):
        provider.acquire("thread-failure-recovery", user_id="alice")

    provider._backend.destroy.assert_not_called()
    provider._backend.create.assert_not_called()
    assert provider._quarantine_store().contains(old)
    provider._backend.complete_absent_teardown.assert_not_called()
    if blocked_by in {"peer", "local-reservation"}:
        provider._backend.is_absent.assert_not_called()
        provider._backend.inspect_runtime.assert_not_called()
    if blocked_by == "local-reservation":
        provider._local_teardown.discard(old.sandbox_id)
    else:
        assert old.sandbox_id not in provider._local_teardown


@pytest.mark.asyncio
@pytest.mark.parametrize("async_acquire", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("blocked_by", ["unowned", "peer-owned", "local-reservation"])
@pytest.mark.parametrize("rejection", ["broker-mode", "missing-capacity", "insufficient-capacity"])
async def test_remote_creation_metadata_rejection_uses_fenced_cleanup(failure_recovery_lifecycle, monkeypatch, async_acquire, blocked_by, rejection):
    import json

    import requests

    from deerflow.community.aio_sandbox import remote_backend as remote_mod

    provider, _, _, old = failure_recovery_lifecycle
    sid = "new-sandbox"
    provider._backend = remote_mod.RemoteSandboxBackend("http://provisioner:8002", max_shell_sessions=None if rejection == "broker-mode" else 13)
    monkeypatch.setattr(provider, "_sandbox_id_for_thread", lambda *_args: sid)
    monkeypatch.setattr(provider, "_get_extra_mounts", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(provider, "_lark_integration_active", lambda *_args: rejection == "broker-mode")
    monkeypatch.setattr(provider, "_lark_broker_active", lambda *_args: rejection == "broker-mode")
    monkeypatch.setattr(remote_mod, "user_should_see_legacy_skills", lambda _uid: False)
    if blocked_by == "peer-owned":
        monkeypatch.setattr(provider, "_claim_ownership", lambda *_args, **_kwargs: False)

    def response(status, payload):
        result = requests.Response()
        result.status_code = status
        result._content = json.dumps(payload).encode()
        return result

    monkeypatch.setattr(requests, "get", lambda *_args, **_kwargs: response(404, {}))
    payload = {"sandbox_url": "http://sandbox", "container_id": "created-pod", "lark_cli_broker": False}
    if rejection == "insufficient-capacity":
        payload["max_shell_sessions"] = 10

    def post(*_args, **_kwargs):
        if blocked_by == "local-reservation":
            provider._local_teardown.add(sid)
        return response(200, payload)

    monkeypatch.setattr(requests, "post", post)
    deleted_under_fence = []

    def delete(*_args, **_kwargs):
        deleted_under_fence.append((provider._ownership.owner(sid), sid in provider._local_teardown))
        return response(200, {})

    monkeypatch.setattr(requests, "delete", delete)

    message = {"broker-mode": "broker mode", "missing-capacity": "version skew", "insufficient-capacity": "insufficient shell-session capacity"}[rejection]
    with pytest.raises(RuntimeError, match=message):
        if async_acquire:
            await provider.acquire_async("new-thread", user_id="alice")
        else:
            await asyncio.to_thread(provider.acquire, "new-thread", user_id="alice")

    assert deleted_under_fence == ([(provider._owner_id, True)] if blocked_by == "unowned" else [])
    assert sid not in provider._sandboxes
    assert old.sandbox_id in provider._sandboxes
    provider._local_teardown.discard(sid)


@pytest.mark.asyncio
async def test_cancelled_remote_creation_drains_metadata_rejection_cleanup(failure_recovery_lifecycle, monkeypatch):
    import json

    import requests

    from deerflow.community.aio_sandbox import remote_backend as remote_mod

    provider = failure_recovery_lifecycle[0]
    sid = "new-sandbox"
    provider._backend = remote_mod.RemoteSandboxBackend("http://provisioner:8002")
    monkeypatch.setattr(provider, "_sandbox_id_for_thread", lambda *_args: sid)
    monkeypatch.setattr(provider, "_get_extra_mounts", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(provider, "_lark_integration_active", lambda *_args: True)
    monkeypatch.setattr(provider, "_lark_broker_active", lambda *_args: True)
    monkeypatch.setattr(remote_mod, "user_should_see_legacy_skills", lambda _uid: False)
    post_started = threading.Event()
    finish_post = threading.Event()
    cleanup_started = threading.Event()
    finish_cleanup = threading.Event()
    cleanup_finished = threading.Event()

    def response(status, payload):
        result = requests.Response()
        result.status_code = status
        result._content = json.dumps(payload).encode()
        return result

    def post(*_args, **_kwargs):
        post_started.set()
        assert finish_post.wait(5)
        return response(200, {"sandbox_url": "http://sandbox", "container_id": "created-pod", "lark_cli_broker": False})

    def delete(*_args, **_kwargs):
        assert provider._ownership.owner(sid) == provider._owner_id
        assert sid in provider._local_teardown
        cleanup_started.set()
        assert finish_cleanup.wait(5)
        cleanup_finished.set()
        return response(200, {})

    monkeypatch.setattr(requests, "get", lambda *_args, **_kwargs: response(404, {}))
    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(requests, "delete", delete)
    task = asyncio.create_task(provider.acquire_async("new-thread", user_id="alice"))
    try:
        assert await asyncio.to_thread(post_started.wait, 5)
        task.cancel()
        finish_post.set()
        assert await asyncio.to_thread(cleanup_started.wait, 5)
        assert not task.done()
        finish_cleanup.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cleanup_finished.is_set()
        assert sid not in provider._local_teardown
        assert sid not in provider._sandboxes
    finally:
        finish_post.set()
        finish_cleanup.set()
        if not task.done():
            task.cancel()
        with contextlib.suppress(asyncio.CancelledError, RuntimeError):
            await task


@pytest.mark.asyncio
@pytest.mark.parametrize("async_acquire", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("error_type", [PermissionError, RuntimeError], ids=["storage-error", "policy-error"])
async def test_discovery_policy_failure_after_publish_closes_client_without_destroy(failure_recovery_lifecycle, monkeypatch, async_acquire, error_type):
    provider, _, _, old = failure_recovery_lifecycle
    discovered = type(old)("discovered-sandbox", "http://sandbox", container_id="discovered-generation")
    provider._backend.discover = MagicMock(return_value=discovered)
    provider._backend.create = MagicMock(side_effect=AssertionError("discovered Pod must not be recreated"))
    monkeypatch.setattr(provider, "_sandbox_id_for_thread", lambda *_args: discovered.sandbox_id)
    monkeypatch.setattr(provider, "_lark_integration_active", lambda *_args: False)
    provider_mod = importlib.import_module(type(provider).__module__)
    client = MagicMock()
    monkeypatch.setattr(provider_mod, "AioSandbox", MagicMock(return_value=client))
    published = False
    original_publish = provider._publish_ownership

    def publish(sandbox_id):
        nonlocal published
        original_publish(sandbox_id)
        published = True

    store = provider._quarantine_store()
    original_contains = store.contains

    def contains(info):
        if published:
            raise error_type("policy check failed after ownership publish")
        return original_contains(info)

    monkeypatch.setattr(provider, "_publish_ownership", publish)
    monkeypatch.setattr(store, "contains", contains)

    with pytest.raises(error_type, match="policy check failed after ownership publish"):
        if async_acquire:
            await provider.acquire_async("new-thread", user_id="alice")
        else:
            await asyncio.to_thread(provider.acquire, "new-thread", user_id="alice")

    client.close.assert_called_once_with()
    provider._backend.destroy.assert_not_called()
    assert discovered.sandbox_id not in provider._sandboxes
    assert old.sandbox_id in provider._sandboxes


@pytest.mark.asyncio
@pytest.mark.parametrize("async_create", [False, True])
@pytest.mark.parametrize("failure", ["probe", "storage", "policy"])
@pytest.mark.parametrize("peer_owned", [False, True])
async def test_post_creation_policy_failure_uses_fenced_rollback(failure_recovery_lifecycle, monkeypatch, async_create, failure, peer_owned):
    provider, _, _, old = failure_recovery_lifecycle
    fresh = type(old)("new-sandbox", "http://fresh", container_id="fresh-generation")
    provider._backend.create = MagicMock(return_value=fresh)
    monkeypatch.setattr(provider, "_get_extra_mounts", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(type(provider), "_lark_integration_active", staticmethod(lambda *_args: False))
    monkeypatch.setattr(importlib.import_module(type(provider).__module__), "wait_for_sandbox_ready", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(importlib.import_module(type(provider).__module__), "wait_for_sandbox_ready_async", AsyncMock(return_value=True))

    def check_policy(info, _user):
        if failure == "policy":
            info.requires_replacement = True
        elif failure == "storage":
            raise PermissionError("quarantine unavailable")
        else:
            raise RuntimeError("capability unknown")

    monkeypatch.setattr(provider, "_check_sandbox_reuse_policy", check_policy)
    if peer_owned:
        monkeypatch.setattr(provider, "_claim_ownership", lambda *_args, **_kwargs: False)

    with pytest.raises((RuntimeError, PermissionError)):
        if async_create:
            await provider._create_sandbox_async("new-thread", fresh.sandbox_id, user_id="alice")
        else:
            provider._create_sandbox("new-thread", fresh.sandbox_id, user_id="alice")

    assert fresh.sandbox_id not in provider._sandbox_infos
    assert fresh.sandbox_id not in provider._local_teardown
    if peer_owned:
        provider._backend.destroy.assert_not_called()
    else:
        provider._backend.destroy.assert_called_once_with(fresh)


@pytest.mark.parametrize("source", ["active", "warm", "discovered"])
@pytest.mark.parametrize("actual_broker", [False, True])
def test_mode_mismatch_refreshes_capabilities_before_replacing_pod(failure_recovery_lifecycle, monkeypatch, source, actual_broker):
    from deerflow.community.aio_sandbox.remote_backend import RemoteSandboxBackend
    from deerflow.config import app_config
    from deerflow.integrations import lark_cli

    provider, sandbox, _, info = failure_recovery_lifecycle
    info.lark_cli_broker = sandbox.lark_cli_broker = actual_broker
    provider._backend = RemoteSandboxBackend("http://provisioner:8002")
    provider._backend.destroy = MagicMock()
    provider._backend.create = MagicMock()
    provider._backend.discover = MagicMock(return_value=info)
    monkeypatch.setattr(type(provider), "_lark_integration_active", staticmethod(lambda *_args: True))
    monkeypatch.setattr(provider, "_check_tracked_sandbox_alive", lambda *_args: True)
    config = SimpleNamespace(sandbox=SimpleNamespace(use="deerflow.community.aio_sandbox:AioSandboxProvider", provisioner_url="http://provisioner:8002"))
    monkeypatch.setattr(app_config, "get_app_config", lambda: config)
    monkeypatch.setattr(lark_cli.sandbox_lark_broker_active, "_cache", {}, raising=False)
    probe = MagicMock(side_effect=[{"lark_cli_broker_image": not actual_broker}, {"lark_cli_broker_image": actual_broker}])
    monkeypatch.setattr(lark_cli, "_probe_provisioner_capabilities", probe)
    assert lark_cli.sandbox_lark_broker_active(config) is not actual_broker
    if source != "active":
        provider.release(info.sandbox_id)
        if source == "discovered":
            provider._warm_pool.clear()

    assert provider.acquire("thread-failure-recovery", user_id="alice") == info.sandbox_id

    assert provider.get(info.sandbox_id).lark_cli_broker is actual_broker
    assert info.requires_replacement is False
    assert probe.call_count == 2
    provider._backend.destroy.assert_not_called()
    provider._backend.create.assert_not_called()


@pytest.mark.parametrize("source", ["active", "warm", "discovered"])
def test_probe_recovery_cannot_readmit_non_broker_generation(failure_recovery_lifecycle, monkeypatch, source):
    """Capability recovery must validate every reuse path before executing."""
    import json

    from deerflow.community.aio_sandbox import aio_sandbox_provider as provider_mod
    from deerflow.community.aio_sandbox import remote_backend as remote_mod
    from deerflow.config import app_config
    from deerflow.integrations import lark_cli

    provider, _, shell, info = failure_recovery_lifecycle
    provider._backend = remote_mod.RemoteSandboxBackend("http://provisioner:8002")
    monkeypatch.setattr(provider_mod.AioSandboxProvider, "_lark_integration_active", staticmethod(lambda *_args: True))
    monkeypatch.setattr(provider, "_get_extra_mounts", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(provider_mod, "wait_for_sandbox_ready", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(remote_mod, "user_should_see_legacy_skills", lambda *_args: False)
    config = SimpleNamespace(sandbox=SimpleNamespace(use="deerflow.community.aio_sandbox:AioSandboxProvider", provisioner_url="http://provisioner:8002"))
    monkeypatch.setattr(app_config, "get_app_config", lambda: config)
    capability = MagicMock()
    capability.__enter__.return_value = capability
    capability.read.return_value = json.dumps({"lark_cli_init_image": True, "lark_cli_broker_image": True}).encode()
    probe = MagicMock(side_effect=[TimeoutError("capability timeout"), capability])
    monkeypatch.setattr(lark_cli.urllib.request, "urlopen", probe)
    monkeypatch.setattr(lark_cli.sandbox_lark_broker_active, "_cache", {}, raising=False)
    clock = SimpleNamespace(now=100.0)
    monkeypatch.setattr(lark_cli, "time", SimpleNamespace(monotonic=lambda: clock.now))
    old_exists = [True]

    def response(payload, status=200):
        return SimpleNamespace(status_code=status, ok=status == 200, json=lambda: payload, raise_for_status=lambda: None)

    def get(*_args, **_kwargs):
        return response({**info.to_dict(), "status": "Running"}, 200 if old_exists[0] else 404)

    def delete(*_args, **_kwargs):
        assert provider._ownership.owner(info.sandbox_id) == provider._owner_id
        old_exists[0] = False
        return response({})

    def post(*_args, **kwargs):
        assert kwargs["json"]["provision_lark_cli_broker"] is True
        return response({"sandbox_url": info.sandbox_url, "lark_cli_broker": True, "container_id": "broker-generation"})

    monkeypatch.setattr(remote_mod.requests, "get", get)
    monkeypatch.setattr(remote_mod.requests, "delete", delete)
    monkeypatch.setattr(remote_mod.requests, "post", post)
    if source != "active":
        provider.release(info.sandbox_id)
        if source == "discovered":
            provider._warm_pool.clear()
    # Probe outage: the attested non-broker generation keeps serving. Its own
    # attestation outranks the unreachable deployment-level probe; execution
    # never ran, so nothing here weakens the credential-placement guarantee.
    assert provider.acquire("thread-failure-recovery", user_id="alice") == info.sandbox_id
    assert provider.get(info.sandbox_id).lark_cli_broker is False
    shell.exec_command.assert_not_called()
    clock.now += lark_cli.LARK_BROKER_MODE_PROBE_RETRY_SECONDS + 1
    # Probe recovered and now requires broker: every reuse path must replace the
    # stale generation instead of readmitting it.
    assert provider.acquire("thread-failure-recovery", user_id="alice") == info.sandbox_id
    assert provider.get(info.sandbox_id).lark_cli_broker is True
    assert provider._sandbox_infos[info.sandbox_id].container_id == "broker-generation"
    shell.exec_command.assert_not_called()
    assert probe.call_count == 2


def test_acquire_recycles_quarantined_cached_sandbox_inline(tmp_path, monkeypatch):
    """A failed release recycle must not wedge the thread: the next acquire destroys the fenced residue."""
    provider, sandbox, aio_mod = _make_provider_with_active_sandbox(tmp_path, "sandbox-q-residue")
    info = provider._sandbox_infos["sandbox-q-residue"]
    info.container_id = "generation-dirty"
    sandbox.requires_container_recycle = True
    provider._thread_sandboxes[("alice", "thread-q")] = "sandbox-q-residue"
    provider._quarantine_store().mark(info)
    provider._backend.discover = MagicMock(return_value=None)
    monkeypatch.setattr(provider, "_sandbox_id_for_thread", lambda *_args: "sandbox-q-residue")
    monkeypatch.setattr(provider, "_ensure_skills_projection", lambda *_args: None)
    monkeypatch.setattr(aio_mod, "get_paths", lambda: Paths(base_dir=tmp_path / "state"))
    monkeypatch.setattr(provider, "_create_sandbox", lambda *_args, **_kwargs: "sandbox-q-residue")

    assert provider.acquire("thread-q", user_id="alice") == "sandbox-q-residue"

    provider._backend.destroy.assert_called_once_with(info)
    assert "sandbox-q-residue" not in provider._sandboxes


def test_pending_create_allows_upload_acquire_without_recycling_live_run(failure_recovery_lifecycle, monkeypatch):
    from deerflow.sandbox.lease import discard_sandbox_lease_manager, get_sandbox_lease_manager

    provider, sandbox, shell, info = failure_recovery_lifecycle
    manager = get_sandbox_lease_manager(provider)
    manager.retain("running-agent", info.sandbox_id, thread_id="thread-failure-recovery", user_id="alice")
    entered, complete = threading.Event(), threading.Event()
    results: list[str] = []

    def create_session(id, **_kwargs):
        entered.set()
        assert complete.wait(timeout=5)
        return SimpleNamespace(data=SimpleNamespace(session_id=id))

    shell.create_session.side_effect = create_session
    runner = threading.Thread(target=lambda: results.append(sandbox.execute_command_in_scope("first", scope_id="running-agent")))
    try:
        runner.start()
        assert entered.wait(timeout=5)
        assert manager.acquire("upload", "thread-failure-recovery", user_id="alice") == info.sandbox_id
        assert provider.get(info.sandbox_id) is sandbox
        provider._backend.destroy.assert_not_called()
        assert not provider._quarantine_store().contains(info)
        complete.set()
        runner.join(timeout=5)
        assert not runner.is_alive()
        assert results == ["next-turn"]
        assert sandbox.execute_command_in_scope("second", scope_id="running-agent") == "next-turn"
        manager.release("upload")
        assert provider.get(info.sandbox_id) is sandbox
        manager.release("running-agent")
        provider._backend.destroy.assert_not_called()
    finally:
        complete.set()
        if runner.ident is not None:
            runner.join(timeout=5)
        discard_sandbox_lease_manager(provider)


def test_uncertain_runtime_preserves_live_holders_until_final_release(failure_recovery_lifecycle):
    from deerflow.sandbox.lease import discard_sandbox_lease_manager, get_sandbox_lease_manager

    provider, sandbox, _, info = failure_recovery_lifecycle
    manager = get_sandbox_lease_manager(provider)
    manager.retain("parent", info.sandbox_id, thread_id="thread-failure-recovery", user_id="alice")
    manager.retain("fork", info.sandbox_id, thread_id="fork-thread", user_id="alice", release_on_last=False)
    sandbox._default_shell_corrupted = True
    try:
        provider.release(info.sandbox_id)
        provider.destroy(info.sandbox_id)
        assert provider.get(info.sandbox_id) is sandbox
        provider._backend.destroy.assert_not_called()
        with pytest.raises(RuntimeError, match="deferred|recycle did not complete"):
            manager.acquire("upload", "thread-failure-recovery", user_id="alice")
        assert manager.binding_for("upload") is None
        provider._backend.destroy.assert_not_called()
        manager.release("parent")
        assert provider.get(info.sandbox_id) is sandbox
        provider._backend.destroy.assert_not_called()
        manager.release("fork")
        provider._backend.destroy.assert_called_once_with(info)
        assert provider.get(info.sandbox_id) is None
        assert provider._quarantine_store().contains(info)
    finally:
        discard_sandbox_lease_manager(provider)


@pytest.mark.parametrize("plane", ["shell", "bash"])
def test_idle_release_quarantines_abandoned_pending_create(failure_recovery_lifecycle, plane):
    provider, sandbox, _, info = failure_recovery_lifecycle
    sandbox._begin_session_creation(plane, "abandoned-session")
    assert sandbox.has_pending_session_creates is True
    assert sandbox.requires_container_recycle is False

    provider.release(info.sandbox_id)

    provider._backend.destroy.assert_called_once_with(info)
    assert provider.get(info.sandbox_id) is None
    assert info.sandbox_id not in provider._warm_pool
    assert provider._quarantine_store().contains(info)


@pytest.mark.asyncio
@pytest.mark.parametrize("async_acquire", [False, True], ids=["sync", "async"])
async def test_lease_acquire_can_replace_its_own_fenced_generation(failure_recovery_lifecycle, async_acquire):
    from deerflow.sandbox.lease import get_sandbox_lease_manager

    provider, sandbox, _, info = failure_recovery_lifecycle
    sandbox._default_shell_corrupted = True
    fresh = type(info)(info.sandbox_id, info.sandbox_url, container_id="container-generation-2", lark_cli_broker=False)
    provider._backend.discover = MagicMock(return_value=fresh)
    manager = get_sandbox_lease_manager(provider)

    if async_acquire:
        acquired = await manager.acquire_async("next-run", "thread-failure-recovery", user_id="alice")
    else:
        acquired = await asyncio.to_thread(manager.acquire, "next-run", "thread-failure-recovery", user_id="alice")

    assert acquired == info.sandbox_id
    assert manager.binding_for("next-run") == info.sandbox_id
    assert provider.get(acquired) is not sandbox
    assert provider._sandbox_infos[acquired].container_id == fresh.container_id
    provider._backend.destroy.assert_called_once_with(info)
    await manager.release_async("next-run")


@pytest.mark.parametrize("blocked_by", ["local", "ownership"])
def test_inline_recycle_reports_a_refused_teardown_as_deferred(failure_recovery_lifecycle, blocked_by, monkeypatch):
    provider, sandbox, _, info = failure_recovery_lifecycle
    sandbox._default_shell_corrupted = True
    if blocked_by == "local":
        provider._local_teardown.add(info.sandbox_id)
    else:
        monkeypatch.setattr(provider, "_claim_ownership", lambda *_args, **_kwargs: False)
    assert provider._recycle_fenced_tracked_sandbox(info.sandbox_id) is False
    assert provider.get(info.sandbox_id) is sandbox
    provider._backend.destroy.assert_not_called()


def test_acquire_recycle_failure_defers_with_quarantine_reason(tmp_path, monkeypatch):
    """When the inline recycle cannot destroy the residue, acquire defers with an accurate reason."""
    provider, sandbox, aio_mod = _make_provider_with_active_sandbox(tmp_path, "sandbox-q-stuck")
    info = provider._sandbox_infos["sandbox-q-stuck"]
    info.container_id = "generation-stuck"
    sandbox.requires_container_recycle = True
    provider._thread_sandboxes[("alice", "thread-stuck")] = "sandbox-q-stuck"
    provider._quarantine_store().mark(info)
    provider._backend.destroy = MagicMock(side_effect=RuntimeError("docker daemon down"))
    monkeypatch.setattr(provider, "_sandbox_id_for_thread", lambda *_args: "sandbox-q-stuck")
    monkeypatch.setattr(provider, "_ensure_skills_projection", lambda *_args: None)

    with pytest.raises(aio_mod.SandboxPolicyReplacementDeferredError, match="quarantined"):
        provider.acquire("thread-stuck", user_id="alice")

    provider._backend.destroy.assert_called_once_with(info)
    assert provider._quarantine_store().contains(info)


@pytest.mark.parametrize("attested", [False, True])
def test_reuse_policy_defers_to_attested_mode_when_probe_unavailable(tmp_path, monkeypatch, attested):
    """A Pod-attested mode outranks an unavailable deployment-level capabilities probe."""
    from deerflow.community.aio_sandbox.remote_backend import RemoteSandboxBackend
    from deerflow.integrations import lark_cli

    provider, _, aio_mod = _make_provider_with_active_sandbox(tmp_path, "sandbox-attested")
    provider._backend = RemoteSandboxBackend("http://provisioner:8002")
    monkeypatch.setattr(aio_mod.AioSandboxProvider, "_lark_integration_active", staticmethod(lambda *_args: True))

    def _probe_unknown(*_args, **_kwargs):
        raise lark_cli.LarkBrokerCapabilityUnknownError("capability is unknown")

    monkeypatch.setattr(aio_mod.AioSandboxProvider, "_lark_broker_active", staticmethod(_probe_unknown))
    info = provider._sandbox_infos["sandbox-attested"]
    info.lark_cli_broker = attested

    provider._check_sandbox_reuse_policy(info, "alice")

    assert info.requires_replacement is False


@pytest.mark.parametrize("source", ["active", "warm", "discovered"])
@pytest.mark.parametrize("required_broker", [False, True])
def test_unattested_broker_mode_refuses_acquire_without_deleting_pod(failure_recovery_lifecycle, monkeypatch, source, required_broker):
    """Version skew must refuse admission while preserving the existing Pod."""
    from deerflow.community.aio_sandbox import remote_backend as remote_mod

    provider, sandbox, _, info = failure_recovery_lifecycle
    info.lark_cli_broker = sandbox.lark_cli_broker = None
    if source != "active":
        provider.release(info.sandbox_id)
        if source == "discovered":
            provider._warm_pool.clear()
            provider._warm_pool_identity.clear()
    backend = remote_mod.RemoteSandboxBackend("http://provisioner:8002")
    backend.discover = MagicMock(return_value=info)
    backend.destroy = MagicMock()
    backend.create = MagicMock(side_effect=AssertionError("must preserve the existing Pod"))
    provider._backend = backend
    monkeypatch.setattr(provider, "_lark_integration_active", lambda *_args: True)
    probe = MagicMock(return_value=required_broker)
    monkeypatch.setattr(provider, "_lark_broker_active", probe)

    with pytest.raises(RuntimeError, match="broker mode is unverified"):
        provider.acquire("thread-failure-recovery", user_id="alice")

    assert info.requires_replacement is False
    backend.destroy.assert_not_called()
    backend.create.assert_not_called()
    probe.assert_not_called()


def test_reuse_policy_stays_fail_closed_for_unattested_mode_when_probe_unavailable(tmp_path, monkeypatch):
    """Without a Pod attestation there is no stronger evidence: probe failure keeps refusing reuse."""
    from deerflow.community.aio_sandbox.remote_backend import RemoteSandboxBackend
    from deerflow.integrations import lark_cli

    provider, _, aio_mod = _make_provider_with_active_sandbox(tmp_path, "sandbox-unattested")
    provider._backend = RemoteSandboxBackend("http://provisioner:8002")
    monkeypatch.setattr(aio_mod.AioSandboxProvider, "_lark_integration_active", staticmethod(lambda *_args: True))

    def _probe_unknown(*_args, **_kwargs):
        raise lark_cli.LarkBrokerCapabilityUnknownError("capability is unknown")

    monkeypatch.setattr(aio_mod.AioSandboxProvider, "_lark_broker_active", staticmethod(_probe_unknown))
    info = provider._sandbox_infos["sandbox-unattested"]
    info.lark_cli_broker = None

    with pytest.raises(aio_mod.SandboxBrokerModeUnverifiedError, match="broker mode is unverified"):
        provider._check_sandbox_reuse_policy(info, "alice")


def test_reused_active_sandbox_requires_matching_releases(tmp_path):
    """The execution lease manager keeps AIO clients active until the final holder exits."""
    from deerflow.sandbox.lease import SandboxLeaseManager

    provider, sandbox, _ = _make_provider_with_active_sandbox(tmp_path, "sandbox-lease")
    manager = SandboxLeaseManager(provider)
    try:
        for owner in ("active-run", "temporary-upload"):
            manager.retain(owner, "sandbox-lease", thread_id="thread-lease", user_id="owner-upload")

        manager.release("temporary-upload")
        assert "sandbox-lease" in provider._sandboxes
        assert "sandbox-lease" not in provider._warm_pool
        sandbox.close.assert_not_called()

        manager.release("active-run")
        assert "sandbox-lease" not in provider._sandboxes
        assert "sandbox-lease" in provider._warm_pool
        sandbox.close.assert_called_once_with()
    finally:
        manager.close()


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


def test_destroy_reports_false_when_teardown_is_deferred(tmp_path):
    """An explicit destroy under an active execution lease must surface the
    deferral instead of letting the caller assume the container is gone."""
    import threading

    from deerflow.sandbox.lease import get_sandbox_lease_manager

    provider, sandbox, _ = _make_provider_with_active_sandbox(tmp_path, "sandbox-destroy-defer")
    manager = get_sandbox_lease_manager(provider)
    # reserve_idle_teardown is re-entrant per worker, so the competing
    # reservation must come from another thread to force the deferral.
    hold = threading.Event()
    release = threading.Event()

    def hold_teardown():
        with manager.reserve_idle_teardown("sandbox-destroy-defer") as reserved:
            assert reserved
            hold.set()
            release.wait(5)

    worker = threading.Thread(target=hold_teardown, daemon=True)
    worker.start()
    assert hold.wait(5)
    try:
        assert provider.destroy("sandbox-destroy-defer") is False
    finally:
        release.set()
        worker.join(5)

    provider._backend.destroy.assert_not_called()
    sandbox.close.assert_not_called()
    assert "sandbox-destroy-defer" in provider._sandboxes
    assert provider.destroy("sandbox-destroy-defer") is True
    provider._backend.destroy.assert_called_once()


def test_shutdown_closes_all_active_sandbox_clients(tmp_path):
    """shutdown() must close every cached AioSandbox client during teardown (#2872)."""
    provider, sandbox, _ = _make_provider_with_active_sandbox(tmp_path, "sandbox-shut")

    provider.shutdown()

    sandbox.close.assert_called_once_with()
    provider._backend.destroy.assert_called_once()
    assert provider._sandboxes == {}


@pytest.mark.asyncio
async def test_reset_closes_acquire_serializer_executor(tmp_path):
    provider = _make_provider(tmp_path)
    async with provider._acquire_serializer.hold_async(("alice", "thread-reset")):
        pass
    worker_threads = tuple(provider._acquire_serializer.executor._threads)
    assert worker_threads

    provider.reset()

    for thread in worker_threads:
        thread.join(timeout=2)
    assert all(not thread.is_alive() for thread in worker_threads)
    with pytest.raises(RuntimeError, match="closed"):
        async with provider._acquire_serializer.hold_async(("alice", "thread-after-reset")):
            pass


def test_release_dirty_sandbox_branches_before_warm_pool(
    tmp_path,
):
    provider, sandbox, _ = _make_provider_with_active_sandbox(
        tmp_path,
        "sandbox-dirty",
    )
    sandbox.requires_container_recycle = True

    observed: dict[str, bool] = {}

    def destroy_tracked(
        sandbox_id,
        *,
        still_reapable,
    ):
        observed["active_before_destroy"] = provider._sandboxes.get(sandbox_id) is sandbox
        observed["warm_before_destroy"] = sandbox_id in provider._warm_pool
        observed["still_reapable"] = still_reapable()

    provider._destroy_tracked = MagicMock(side_effect=destroy_tracked)

    provider.release("sandbox-dirty")

    assert observed == {
        "active_before_destroy": True,
        "warm_before_destroy": False,
        "still_reapable": True,
    }


def test_release_dirty_sandbox_destroys_container_instead_of_warming(
    tmp_path,
):
    provider, sandbox, _ = _make_provider_with_active_sandbox(
        tmp_path,
        "sandbox-dirty-destroy",
    )
    sandbox.requires_container_recycle = True
    info = provider._sandbox_infos["sandbox-dirty-destroy"]

    provider.release("sandbox-dirty-destroy")

    assert "sandbox-dirty-destroy" not in provider._warm_pool
    assert "sandbox-dirty-destroy" not in provider._sandboxes
    assert "sandbox-dirty-destroy" not in provider._sandbox_infos

    sandbox.close.assert_called_once_with()
    provider._backend.destroy.assert_called_once_with(info)


def test_release_dirty_sandbox_destroy_failure_is_logged_without_warming(
    tmp_path,
    caplog,
):
    provider, sandbox, _ = _make_provider_with_active_sandbox(
        tmp_path,
        "sandbox-dirty-fail",
    )
    sandbox.requires_container_recycle = True
    provider._backend.destroy.side_effect = RuntimeError("container stop failed")

    with caplog.at_level("ERROR"):
        provider.release("sandbox-dirty-fail")

    assert "sandbox-dirty-fail" not in provider._warm_pool
    assert "sandbox-dirty-fail" not in provider._sandboxes
    assert "sandbox-dirty-fail" not in provider._sandbox_infos
    assert "Failed to recycle quarantined sandbox sandbox-dirty-fail" in caplog.text
    provider._backend.destroy.assert_called_once()
    sandbox.close.assert_called_once_with()


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
    provider._thread_sandboxes = {("default", "thread-dead"): "sandbox-dead"}
    provider._config = {"command_timeout": 600.0, "replicas": 3}
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
    provider._config = {"command_timeout": 600.0, "replicas": 3}
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


def test_shutdown_keeps_aio_warm_entries_owned_when_idle_checker_stop_times_out(tmp_path):
    """A failed reaper join must leave AIO warm entries available to a retry."""
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    provider = _make_provider(tmp_path)
    provider._lock = aio_mod.threading.Lock()
    provider._shutdown_called = False
    provider._sandboxes = {}
    provider._sandbox_infos = {}
    provider._thread_sandboxes = {}
    provider._last_activity = {}
    warm_info = aio_mod.SandboxInfo(sandbox_id="warm-retry", sandbox_url="http://warm-retry")
    provider._warm_pool = {"warm-retry": (warm_info, 1.0)}
    provider._warm_pool_identity = {"warm-retry": ("default", "thread-retry")}
    provider._stop_idle_checker = MagicMock(side_effect=[RuntimeError("reaper still alive"), None])
    provider._stop_lease_renewal = MagicMock()
    provider._destroy_warm_entry = MagicMock()
    provider._ownership.close = MagicMock()

    with pytest.raises(RuntimeError, match="reaper still alive"):
        provider.shutdown()

    assert provider._shutdown_called is False
    assert provider._warm_pool == {"warm-retry": (warm_info, 1.0)}
    assert provider._warm_pool_identity == {"warm-retry": ("default", "thread-retry")}
    provider._destroy_warm_entry.assert_not_called()

    provider.shutdown()

    provider._destroy_warm_entry.assert_called_once_with(
        "warm-retry",
        warm_info,
        reason="shutdown",
        still_reapable=ANY,
    )
    assert provider._warm_pool == {}
    assert provider._warm_pool_identity == {}


def test_shutdown_keeps_aio_warm_entries_owned_when_lease_renewal_stop_times_out(tmp_path):
    """A live renewal worker must keep AIO ownership attached for shutdown retry."""
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    provider = _make_provider(tmp_path)
    provider._lock = aio_mod.threading.Lock()
    provider._shutdown_called = False
    provider._sandboxes = {}
    provider._sandbox_infos = {}
    provider._thread_sandboxes = {}
    provider._last_activity = {}
    warm_info = aio_mod.SandboxInfo(sandbox_id="warm-renewal-retry", sandbox_url="http://warm-renewal-retry")
    provider._warm_pool = {"warm-renewal-retry": (warm_info, 1.0)}
    provider._warm_pool_identity = {"warm-renewal-retry": ("default", "thread-retry")}
    provider._stop_idle_checker = MagicMock()
    provider._destroy_warm_entry = MagicMock()
    provider._ownership.close = MagicMock()

    renewal_thread = MagicMock()
    renewal_thread.is_alive.side_effect = [True, True, False, False]
    provider._renewal_thread = renewal_thread

    with pytest.raises(RuntimeError, match="lease-renewal thread is still running after stop timeout"):
        provider.shutdown()

    assert provider._shutdown_called is False
    assert provider._warm_pool == {"warm-renewal-retry": (warm_info, 1.0)}
    assert provider._warm_pool_identity == {"warm-renewal-retry": ("default", "thread-retry")}
    renewal_thread.join.assert_called_once_with(timeout=5)
    provider._destroy_warm_entry.assert_not_called()
    provider._ownership.close.assert_not_called()

    provider.shutdown()

    provider._destroy_warm_entry.assert_called_once_with(
        "warm-renewal-retry",
        warm_info,
        reason="shutdown",
        still_reapable=ANY,
    )
    assert provider._warm_pool == {}
    assert provider._warm_pool_identity == {}


def test_signal_handler_forwards_original_signal_when_shutdown_fails(tmp_path, monkeypatch, caplog):
    """A fail-closed shutdown must not swallow or replace the process signal."""
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    provider = _make_provider(tmp_path)
    provider.shutdown = MagicMock(side_effect=RuntimeError("renewal worker still alive"))

    forwarded = MagicMock()
    installed = {}

    def fake_getsignal(signum):
        return forwarded if signum == aio_mod.signal.SIGTERM else aio_mod.signal.SIG_IGN

    def fake_signal(signum, handler):
        installed[signum] = handler

    monkeypatch.setattr(aio_mod.signal, "getsignal", fake_getsignal)
    monkeypatch.setattr(aio_mod.signal, "signal", fake_signal)

    provider._register_signal_handlers()

    with caplog.at_level("ERROR"):
        installed[aio_mod.signal.SIGTERM](aio_mod.signal.SIGTERM, None)

    provider.shutdown.assert_called_once_with()
    forwarded.assert_called_once_with(aio_mod.signal.SIGTERM, None)
    assert "Sandbox shutdown failed while handling signal" in caplog.text


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
    provider._config = {"command_timeout": 600.0, "replicas": 2}
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
    provider._last_activity = {}
    provider._warm_pool = {}
    provider._active_sandbox_identity = {}
    provider._warm_pool_identity = {}
    provider._shutdown_called = False
    provider._config = {"command_timeout": 600.0, "replicas": 3, "idle_timeout": 0}

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
    provider._config = {"command_timeout": 600.0, "replicas": 3}
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


def test_deterministic_sandbox_id_matches_shared_identity():
    from deerflow.sandbox.identity import derive_sandbox_scope_token

    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    assert aio_mod.AioSandboxProvider._deterministic_sandbox_id("t-1", "u-1") == derive_sandbox_scope_token(user_id="u-1", thread_id="t-1")
