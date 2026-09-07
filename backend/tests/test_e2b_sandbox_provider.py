"""Unit tests for ``E2BSandboxProvider`` and its companion ``E2BSandbox``."""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import json
import os
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from deerflow.community.e2b_sandbox.capacity import (
    CapacityBackendError,
    ReserveStatus,
)
from deerflow.community.e2b_sandbox.e2b_sandbox_provider import MountUploadResult
from deerflow.config.paths import Paths
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.sandbox.acquire_serialization import AcquireSerializer
from deerflow.sandbox.exceptions import SandboxCapacityExceededError

# ──────────────────────────────────────────────────────────────────────────────
# Fakes for the e2b SDK
# ──────────────────────────────────────────────────────────────────────────────


class FakeCommandsAPI:
    """Stand-in for ``client.commands``."""

    GONE = "__GONE__"
    NOT_FOUND_MSG = "The sandbox was not found: This error is likely due to sandbox timeout."

    def __init__(self, responses: list[Any] | None = None) -> None:
        self.calls: list[str] = []
        self._responses = list(responses or [])

    def _next(self) -> Any:
        if not self._responses:
            return SimpleNamespace(stdout="BOOTSTRAP_OK", stderr="", exit_code=0)
        head = self._responses.pop(0)
        return head

    def run(self, cmd: str, envs: dict[str, str] | None = None, **kwargs) -> SimpleNamespace:
        self.calls.append(cmd)
        self.envs = getattr(self, "envs", [])
        self.envs.append(envs)
        head = self._next()
        if head == self.GONE:
            raise RuntimeError(self.NOT_FOUND_MSG)
        if callable(head):
            return head(cmd)
        if isinstance(head, SimpleNamespace):
            return head
        return SimpleNamespace(stdout=str(head), stderr="", exit_code=0)


class _FakeFileStream:
    """Minimal stand-in for ``e2b.FileStreamReader``.

    Yields fixed-size chunks and tracks whether ``close()`` was invoked so
    tests can assert we release the connection on both success and abort.
    """

    def __init__(self, data: bytes, *, chunk_size: int = 4096) -> None:
        self._data = bytes(data)
        self._chunk_size = max(1, int(chunk_size))
        self._offset = 0
        self.closed = False

    def __iter__(self):
        return self

    def __next__(self) -> bytes:
        if self.closed or self._offset >= len(self._data):
            raise StopIteration
        end = min(self._offset + self._chunk_size, len(self._data))
        chunk = self._data[self._offset : end]
        self._offset = end
        return chunk

    def close(self) -> None:
        self.closed = True

    def __enter__(self) -> _FakeFileStream:
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()


class FakeFilesAPI:
    def __init__(
        self,
        store: dict[str, bytes] | None = None,
        *,
        stream_chunk_size: int = 4096,
    ) -> None:
        self.store = dict(store or {})
        self.read_calls: list[tuple[str, str | None]] = []
        self.write_calls: list[tuple[str, bytes]] = []
        self.write_streamed: list[bool] = []
        self.streams: list[_FakeFileStream] = []
        self._stream_chunk_size = stream_chunk_size

    def read(self, path: str, *, format: str | None = None):
        self.read_calls.append((path, format))
        if path not in self.store:
            raise FileNotFoundError(path)
        data = self.store[path]
        if format == "bytes":
            return data
        if format == "stream":
            stream = _FakeFileStream(data, chunk_size=self._stream_chunk_size)
            self.streams.append(stream)
            return stream
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            return data

    def write(self, path: str, content: Any) -> None:
        is_stream = hasattr(content, "read")
        data = content.read() if is_stream else content
        self.write_streamed.append(is_stream)
        self.write_calls.append((path, data))
        self.store[path] = data


class FakeClient:
    """Lightweight ``e2b.Sandbox`` substitute used by the provider tests."""

    def __init__(
        self,
        sandbox_id: str = "fake-sb-1",
        *,
        commands: FakeCommandsAPI | None = None,
        files: FakeFilesAPI | None = None,
    ) -> None:
        self.sandbox_id = sandbox_id
        self.commands = commands or FakeCommandsAPI()
        self.files = files or FakeFilesAPI()
        self.timeouts_set: list[int] = []
        self.killed = False
        self.closed = False

    def set_timeout(self, seconds: int) -> None:
        self.timeouts_set.append(int(seconds))

    def kill(self) -> None:
        self.killed = True

    def close(self) -> None:
        self.closed = True


class FakeSandboxClass:
    """Stand-in for ``e2b_code_interpreter.Sandbox`` (the class itself)."""

    def __init__(self) -> None:
        self.create_calls: list[dict[str, Any]] = []
        self.connect_calls: list[tuple[str, dict[str, Any]]] = []
        self.list_calls: list[dict[str, Any]] = []
        self.create_factory = lambda **kw: FakeClient(sandbox_id=f"created-{len(self.create_calls)}")
        self.connect_factory = lambda sid, **kw: FakeClient(sandbox_id=sid)
        self.list_return: Any = []

    def create(self, **kwargs: Any) -> FakeClient:
        self.create_calls.append(kwargs)
        return self.create_factory(**kwargs)

    def connect(self, sandbox_id: str, **kwargs: Any) -> FakeClient:
        self.connect_calls.append((sandbox_id, kwargs))
        return self.connect_factory(sandbox_id, **kwargs)

    def list(self, **kwargs: Any) -> Any:
        self.list_calls.append(kwargs)
        return self.list_return


class FakeOwnershipStore:
    """Shared lease state with per-provider identities for reconciliation tests."""

    supports_cross_process = True

    def __init__(
        self,
        leases: dict[str, tuple[str, str]],
        *,
        owner_id: str,
        lock: threading.Lock | None = None,
    ) -> None:
        self._leases = leases
        self._lock = lock or threading.Lock()
        self.owner_id = owner_id

    def take(self, sandbox_id: str) -> bool:
        with self._lock:
            current = self._leases.get(sandbox_id)
            if current is not None and current[1] == "del":
                return False
            self._leases[sandbox_id] = (self.owner_id, "own")
            return True

    def claim(self, sandbox_id: str, *, for_destroy: bool = False) -> bool:
        with self._lock:
            current = self._leases.get(sandbox_id)
            if current is not None and current[0] != self.owner_id:
                return False
            if current is not None and current[1] == "del" and not for_destroy:
                return False
            self._leases[sandbox_id] = (self.owner_id, "del" if for_destroy else "own")
            return True

    def renew(self, sandbox_id: str):
        from deerflow.community.aio_sandbox.ownership import RenewOutcome

        with self._lock:
            current = self._leases.get(sandbox_id)
            if current is None:
                return RenewOutcome.LAPSED
            if current == (self.owner_id, "own"):
                return RenewOutcome.RENEWED
            return RenewOutcome.LOST

    def release(self, sandbox_id: str) -> None:
        with self._lock:
            if self._leases.get(sandbox_id, (None,))[0] == self.owner_id:
                self._leases.pop(sandbox_id, None)

    def owner(self, sandbox_id: str) -> str | None:
        with self._lock:
            current = self._leases.get(sandbox_id)
            return current[0] if current is not None else None

    def close(self) -> None:
        return None


def _make_provider(
    *,
    replicas: int = 3,
    idle_timeout: int = 1800,
    overflow_policy: str = "wait",
    acquire_timeout: int = 30,
    burst_limit: int = 0,
    skills_container_path: str = "/mnt/skills",
) -> Any:
    """Build a ``E2BSandboxProvider`` instance bypassing ``__init__``."""
    mod = importlib.import_module("deerflow.community.e2b_sandbox.e2b_sandbox_provider")
    provider = mod.E2BSandboxProvider.__new__(mod.E2BSandboxProvider)
    provider._lock = threading.Lock()
    provider._sandboxes = {}
    provider._thread_sandboxes = {}
    provider._acquire_serializer = AcquireSerializer(thread_name_prefix="e2b-sandbox-lock-wait")
    provider._mount_results = {}
    provider._warm_pool = OrderedDict()
    provider._eviction_tombstones = set()
    provider._evictions_in_progress = set()
    provider._remote_ops_in_progress = set()
    provider._unowned_remote_ops_in_progress = set()
    provider._reserved_slots = 0
    provider._transitioning_slots = 0
    provider._capacity_cond = threading.Condition(provider._lock)
    provider._shutdown_called = False
    provider._owner_id = "owner-a"
    provider._ownership = FakeOwnershipStore({}, owner_id=provider._owner_id)
    provider._ownership_config = SimpleNamespace(
        renewal_interval_seconds=60.0,
        ttl_multiplier=4.0,
        key_prefix="deerflow:test",
    )
    provider._deployment_capacity = None
    provider._owned_sandbox_ids = set()
    provider._acquire_inflight = set()
    provider._orphan_first_seen = {}
    provider._maintenance_stop = threading.Event()
    provider._lease_thread = None
    provider._reconcile_thread = None
    provider._config = {
        "api_key": "test-key",
        "template": "code-interpreter-v1",
        "domain": None,
        "home_dir": "/home/user",
        "skills_container_path": skills_container_path,
        "idle_timeout": idle_timeout,
        "replicas": replicas,
        "overflow_policy": overflow_policy,
        "acquire_timeout": acquire_timeout,
        "burst_limit": burst_limit,
        "mounts": [],
        "environment": {},
        "reconciliation_interval_seconds": 60.0,
        "reconciliation_grace_seconds": 30.0,
        "reconciliation_orphan_ttl_seconds": 3600.0,
        "reconciliation_max_pages": 10,
        "reconciliation_max_items": 100,
        "reconciliation_max_seconds": 10.0,
    }
    return provider


def _install_shared_deployment_capacity(
    *providers,
    reserve_results: list[ReserveStatus] | None = None,
) -> MagicMock:
    store = MagicMock()
    store.key = "deerflow:test:e2b-capacity"
    store.revision.return_value = 0
    store.reserve.return_value = ReserveStatus.GRANTED
    store.reconcile.return_value = True
    if reserve_results is not None:
        store.reserve.side_effect = reserve_results
    for provider in providers:
        provider._deployment_capacity = store
    return store


def _install_fake_sdk(monkeypatch, provider) -> FakeSandboxClass:
    fake_cls = FakeSandboxClass()
    monkeypatch.setattr(provider, "_get_sandbox_cls", lambda: fake_cls)
    return fake_cls


def _write_skill(root: Path, name: str) -> None:
    target = root / name / "SKILL.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f"---\nname: {name}\ndescription: test\n---\n", encoding="utf-8")


def test_apply_mounts_uploads_only_enabled_skill_projection(monkeypatch, tmp_path):
    from deerflow.config.extensions_config import ExtensionsConfig, SkillStateConfig

    mod = importlib.import_module("deerflow.community.e2b_sandbox.e2b_sandbox_provider")
    paths = Paths(base_dir=tmp_path)
    skills_root = tmp_path / "skills"
    _write_skill(skills_root / "public", "enabled-skill")
    _write_skill(skills_root / "public", "disabled-skill")
    (skills_root / "custom").mkdir()
    _write_skill(paths.integration_skills_dir() / "lark-cli", "enabled-integration")
    _write_skill(paths.integration_skills_dir() / "lark-cli", "disabled-integration")
    user_skills_root = paths.user_skills_dir("user-1")
    user_skills_root.mkdir(parents=True, exist_ok=True)
    (user_skills_root / "_skill_states.json").write_text(
        json.dumps({"disabled-integration": {"enabled": False}}),
        encoding="utf-8",
    )
    extensions = ExtensionsConfig(skills={"disabled-skill": SkillStateConfig(enabled=False)})
    config = SimpleNamespace(
        skills=SimpleNamespace(
            get_skills_path=lambda: skills_root,
            container_path="/mnt/skills",
            use="deerflow.skills.storage.local_skill_storage:LocalSkillStorage",
        )
    )
    monkeypatch.setattr(mod, "get_app_config", lambda: config)
    monkeypatch.setattr("deerflow.config.paths.get_paths", lambda: paths)
    monkeypatch.setattr("deerflow.config.extensions_config.ExtensionsConfig.from_file", lambda *_args, **_kwargs: extensions)
    monkeypatch.setattr("deerflow.config.extensions_config.get_extensions_config", lambda: extensions)

    provider = _make_provider()
    client = FakeClient()
    provider._apply_mounts(client, user_id="user-1")

    uploaded_paths = {path for path, _content in client.files.write_calls}
    assert "/mnt/skills/public/enabled-skill/SKILL.md" in uploaded_paths
    assert "/mnt/skills/public/disabled-skill/SKILL.md" not in uploaded_paths
    assert "/mnt/skills/integrations/lark-cli/enabled-integration/SKILL.md" in uploaded_paths
    assert "/mnt/skills/integrations/lark-cli/disabled-integration/SKILL.md" not in uploaded_paths


def test_policy_scoped_thread_skips_shared_projection_during_create(
    monkeypatch,
    tmp_path,
):
    paths = Paths(base_dir=tmp_path)
    paths.thread_skills_view_dir("thread-1", user_id="user-1").mkdir(parents=True)
    monkeypatch.setattr("deerflow.config.paths.get_paths", lambda: paths)

    provider = _make_provider()

    assert provider._skill_projection_mounts("user-1", "thread-1") == []


def test_sync_agent_skills_rebuilds_managed_remote_tree_despite_matching_legacy_marker(
    monkeypatch,
    tmp_path,
):
    from deerflow.skills.projection import SkillProjectionPaths

    mod = importlib.import_module("deerflow.community.e2b_sandbox.e2b_sandbox_provider")
    root = tmp_path / "skills-view"
    projection = SkillProjectionPaths(
        public=root / "public",
        custom=root / "custom",
        legacy=root / "legacy",
        integrations=root / "integrations",
    )
    for category in (
        projection.public,
        projection.custom,
        projection.legacy,
        projection.integrations,
    ):
        category.mkdir(parents=True, exist_ok=True)
    _write_skill(projection.public, "allowed-skill")
    manifest_path = root / ".projection-manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "version": 1,
                "source_signature": "source-a",
                "view_signature": "view-a",
            }
        ),
        encoding="utf-8",
    )
    legacy_signature = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    monkeypatch.setattr(
        mod,
        "get_app_config",
        lambda: SimpleNamespace(skills=SimpleNamespace(container_path="/mnt/skills")),
    )

    files = FakeFilesAPI(
        {
            "/mnt/skills/public/excluded-skill/SKILL.md": b"excluded",
            "/mnt/skills/.deerflow-projection-signature": legacy_signature.encode(),
            "/mnt/skills/unmanaged.txt": b"keep",
        }
    )

    def reset_remote_tree(command: str):
        assert "sudo rm -rf -- /mnt/skills;" not in command
        assert "sudo chown -R" not in command
        assert "if [ -L /mnt/skills ]" in command
        managed_paths = (
            "/mnt/skills/public",
            "/mnt/skills/custom",
            "/mnt/skills/legacy",
            "/mnt/skills/integrations",
            "/mnt/skills/.deerflow-projection-signature",
        )
        for managed_path in managed_paths:
            assert managed_path in command
        for path in list(files.store):
            if any(path == managed_path or path.startswith(f"{managed_path}/") for managed_path in managed_paths):
                files.store.pop(path)
        return SimpleNamespace(
            stdout="SKILLS_RESET_OK\n",
            stderr="",
            exit_code=0,
        )

    chmod_ok = SimpleNamespace(stdout="", stderr="", exit_code=0)
    commands = FakeCommandsAPI([reset_remote_tree, chmod_ok, reset_remote_tree, chmod_ok])
    client = FakeClient(sandbox_id="sandbox-1", commands=commands, files=files)
    provider = _make_provider()
    provider._sandboxes["sandbox-1"] = mod.E2BSandbox(
        id="sandbox-1",
        client=client,
        home_dir="/home/user",
    )

    provider.sync_agent_skills(
        "sandbox-1",
        thread_id="thread-1",
        user_id="user-1",
        projection=projection,
    )

    assert "/mnt/skills/public/excluded-skill/SKILL.md" not in files.store
    assert files.store["/mnt/skills/public/allowed-skill/SKILL.md"].startswith(b"---")
    assert files.store["/mnt/skills/unmanaged.txt"] == b"keep"
    assert "/mnt/skills/.deerflow-projection-signature" not in files.store
    assert files.read_calls == []
    first_command_count = len(commands.calls)
    first_write_count = len(files.write_calls)

    provider.sync_agent_skills(
        "sandbox-1",
        thread_id="thread-1",
        user_id="user-1",
        projection=projection,
    )

    assert len(commands.calls) == first_command_count * 2
    assert len(files.write_calls) == first_write_count * 2


def test_sync_agent_skills_serializes_reset_and_upload_for_same_thread(
    monkeypatch,
    tmp_path,
):
    from deerflow.skills.projection import SkillProjectionPaths

    mod = importlib.import_module("deerflow.community.e2b_sandbox.e2b_sandbox_provider")
    projections: list[SkillProjectionPaths] = []
    for name in ("policy-a", "policy-b"):
        root = tmp_path / name
        projection = SkillProjectionPaths(
            public=root / "public",
            custom=root / "custom",
            legacy=root / "legacy",
            integrations=root / "integrations",
        )
        for category in (
            projection.public,
            projection.custom,
            projection.legacy,
            projection.integrations,
        ):
            category.mkdir(parents=True)
        projections.append(projection)

    monkeypatch.setattr(
        mod,
        "get_app_config",
        lambda: SimpleNamespace(skills=SimpleNamespace(container_path="/mnt/skills")),
    )

    first_upload_started = threading.Event()
    allow_first_upload_to_finish = threading.Event()
    second_sync_started = threading.Event()
    second_reset_started = threading.Event()
    reset_count = 0
    reset_count_lock = threading.Lock()

    def reset_remote_tree(_command: str):
        nonlocal reset_count
        with reset_count_lock:
            reset_count += 1
            current_reset = reset_count
        if current_reset == 2:
            second_reset_started.set()
        return SimpleNamespace(stdout="SKILLS_RESET_OK\n", stderr="", exit_code=0)

    commands = FakeCommandsAPI([reset_remote_tree, reset_remote_tree])
    client = FakeClient(sandbox_id="sandbox-1", commands=commands)
    provider = _make_provider()
    provider._sandboxes["sandbox-1"] = mod.E2BSandbox(
        id="sandbox-1",
        client=client,
        home_dir="/home/user",
    )

    first_projection_root = projections[0].public.parent

    def blocking_upload(_client, source, _destination, _read_only, *, budget):
        del budget
        if source.parent == first_projection_root and not first_upload_started.is_set():
            first_upload_started.set()
            assert allow_first_upload_to_finish.wait(timeout=5)

    monkeypatch.setattr(provider, "_upload_tree", blocking_upload)
    errors: list[BaseException] = []

    def sync(
        projection: SkillProjectionPaths,
        *,
        started: threading.Event | None = None,
    ) -> None:
        try:
            if started is not None:
                started.set()
            provider.sync_agent_skills(
                "sandbox-1",
                thread_id="thread-1",
                user_id="user-1",
                projection=projection,
            )
        except BaseException as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    first = threading.Thread(target=sync, args=(projections[0],))
    second = threading.Thread(
        target=sync,
        args=(projections[1],),
        kwargs={"started": second_sync_started},
    )
    first.start()
    assert first_upload_started.wait(timeout=5)
    second.start()
    try:
        assert second_sync_started.wait(timeout=5)
        assert not second_reset_started.wait(timeout=0.2)
    finally:
        allow_first_upload_to_finish.set()
        first.join(timeout=5)
        second.join(timeout=5)

    assert not first.is_alive()
    assert not second.is_alive()
    assert errors == []
    assert second_reset_started.is_set()


@pytest.mark.parametrize(
    "container_path",
    [
        "skills",
        "/",
        "//mnt/skills",
        "/mnt//skills",
        "/mnt/skills/.",
        "/mnt/skills/..",
        "/mnt",
        "/mnt/user-data",
        "/mnt/acp-workspace",
        "/home",
        "/home/user",
        "/bin",
        "/boot",
        "/dev",
        "/etc",
        "/etc/deerflow-skills",
        "/lib",
        "/lib32",
        "/lib64",
        "/libx32",
        "/lost+found",
        "/media",
        "/opt",
        "/proc",
        "/root",
        "/run",
        "/sbin",
        "/snap",
        "/srv",
        "/sys",
        "/tmp",
        "/usr",
        "/usr/local/deerflow-skills",
        "/var",
        "/var/lib/deerflow-skills",
    ],
)
def test_sync_agent_skills_rejects_unsafe_reset_roots_before_remote_access(
    tmp_path,
    container_path,
):
    from deerflow.skills.projection import SkillProjectionPaths

    mod = importlib.import_module("deerflow.community.e2b_sandbox.e2b_sandbox_provider")
    root = tmp_path / "skills-view"
    projection = SkillProjectionPaths(
        public=root / "public",
        custom=root / "custom",
        legacy=root / "legacy",
        integrations=root / "integrations",
    )
    client = FakeClient(sandbox_id="sandbox-1")
    provider = _make_provider()
    provider._config["skills_container_path"] = container_path
    provider._sandboxes["sandbox-1"] = mod.E2BSandbox(
        id="sandbox-1",
        client=client,
        home_dir="/home/user",
    )

    with pytest.raises(ValueError, match="safe E2B skills reset target"):
        provider.sync_agent_skills(
            "sandbox-1",
            thread_id="thread-1",
            user_id="user-1",
            projection=projection,
        )

    assert client.files.read_calls == []
    assert client.commands.calls == []


@pytest.mark.parametrize(
    ("container_path", "expected"),
    [
        ("/mnt/skills", "/mnt/skills"),
        ("/mnt/skills/", "/mnt/skills"),
        ("/home/user/skills", "/home/user/skills"),
        ("/custom-skills", "/custom-skills"),
        ("/custom/skills", "/custom/skills"),
    ],
)
def test_validate_skills_reset_root_accepts_isolated_directories(
    container_path,
    expected,
):
    mod = importlib.import_module("deerflow.community.e2b_sandbox.e2b_sandbox_provider")

    assert mod._validate_skills_reset_root(container_path, home_dir="/home/user") == expected


@pytest.mark.parametrize(
    ("home_dir", "container_path"),
    [
        ("/opt/e2b-home", "/opt/e2b-home/skills"),
        ("/tmp/e2b-home", "/tmp/e2b-home/skills"),
    ],
)
def test_validate_skills_reset_root_accepts_isolated_custom_home_subtree(
    home_dir,
    container_path,
):
    mod = importlib.import_module("deerflow.community.e2b_sandbox.e2b_sandbox_provider")

    assert (
        mod._validate_skills_reset_root(
            container_path,
            home_dir=home_dir,
        )
        == container_path
    )


def test_sync_agent_skills_rejects_symlinked_remote_root_before_deleting(
    monkeypatch,
    tmp_path,
):
    from deerflow.skills.projection import SkillProjectionPaths

    mod = importlib.import_module("deerflow.community.e2b_sandbox.e2b_sandbox_provider")
    root = tmp_path / "skills-view"
    projection = SkillProjectionPaths(
        public=root / "public",
        custom=root / "custom",
        legacy=root / "legacy",
        integrations=root / "integrations",
    )
    for category in (
        projection.public,
        projection.custom,
        projection.legacy,
        projection.integrations,
    ):
        category.mkdir(parents=True, exist_ok=True)
    manifest_path = root / ".projection-manifest.json"
    manifest_path.write_text("{}", encoding="utf-8")
    legacy_signature = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    monkeypatch.setattr(
        mod,
        "get_app_config",
        lambda: SimpleNamespace(skills=SimpleNamespace(container_path="/mnt/skills")),
    )

    def reject_symlinked_root(command: str):
        assert "if [ -L /mnt/skills ]" in command
        return SimpleNamespace(
            stdout="",
            stderr="Refusing symlinked skills root\n",
            exit_code=2,
        )

    client = FakeClient(
        sandbox_id="sandbox-1",
        commands=FakeCommandsAPI([reject_symlinked_root]),
        files=FakeFilesAPI(
            {
                "/mnt/skills/.deerflow-projection-signature": legacy_signature.encode(),
            }
        ),
    )
    provider = _make_provider()
    provider._sandboxes["sandbox-1"] = mod.E2BSandbox(
        id="sandbox-1",
        client=client,
        home_dir="/home/user",
    )
    monkeypatch.setattr(
        provider,
        "_upload_tree",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("upload must not start after a rejected reset")),
    )

    with pytest.raises(RuntimeError, match="Failed to reset E2B skill projection"):
        provider.sync_agent_skills(
            "sandbox-1",
            thread_id="thread-1",
            user_id="user-1",
            projection=projection,
        )

    assert client.files.read_calls == []
    assert client.files.write_calls == []


def test_sync_agent_skills_leaves_no_signature_after_upload_failure(
    monkeypatch,
    tmp_path,
):
    from deerflow.skills.projection import SkillProjectionPaths

    mod = importlib.import_module("deerflow.community.e2b_sandbox.e2b_sandbox_provider")
    root = tmp_path / "skills-view"
    projection = SkillProjectionPaths(
        public=root / "public",
        custom=root / "custom",
        legacy=root / "legacy",
        integrations=root / "integrations",
    )
    for category in (
        projection.public,
        projection.custom,
        projection.legacy,
        projection.integrations,
    ):
        category.mkdir(parents=True, exist_ok=True)
    (root / ".projection-manifest.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        mod,
        "get_app_config",
        lambda: SimpleNamespace(skills=SimpleNamespace(container_path="/mnt/skills")),
    )
    commands = FakeCommandsAPI([SimpleNamespace(stdout="SKILLS_RESET_OK\n", stderr="", exit_code=0)])
    client = FakeClient(sandbox_id="sandbox-1", commands=commands)
    provider = _make_provider()
    provider._sandboxes["sandbox-1"] = mod.E2BSandbox(
        id="sandbox-1",
        client=client,
        home_dir="/home/user",
    )
    monkeypatch.setattr(
        provider,
        "_upload_tree",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("upload failed")),
    )

    with pytest.raises(RuntimeError, match="upload failed"):
        provider.sync_agent_skills(
            "sandbox-1",
            thread_id="thread-1",
            user_id="user-1",
            projection=projection,
        )

    assert "/mnt/skills/.deerflow-projection-signature" not in client.files.store


def test_upload_tree_streams_file_contents(tmp_path):
    source = tmp_path / "large.bin"
    source.write_bytes(b"mount content")
    client = FakeClient()

    provider = _make_provider()
    provider._upload_tree(client, source, "/mnt/data", read_only=False)

    assert client.files.write_calls == [("/mnt/data/large.bin", b"mount content")]
    assert client.files.write_streamed == [True]


@pytest.mark.parametrize("replacement_content", [b"123", b"12345"], ids=["smaller", "larger"])
def test_upload_tree_rejects_file_size_changed_after_preflight(monkeypatch, tmp_path, replacement_content):
    source = tmp_path / "small.bin"
    source.write_bytes(b"1234")
    replacement = tmp_path / "replacement.bin"
    replacement.write_bytes(replacement_content)
    original_open = Path.open

    def replace_before_open(path: Path, *args, **kwargs):
        if path == source and replacement.exists():
            os.replace(replacement, source)
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", replace_before_open)
    client = FakeClient()

    provider = _make_provider()
    with pytest.raises(ValueError, match="changed during upload preflight"):
        provider._upload_tree(client, source, "/mnt/data", read_only=False)

    assert client.files.write_calls == []


def test_upload_tree_rejects_oversized_file_before_upload(monkeypatch, tmp_path):
    mod = importlib.import_module("deerflow.community.e2b_sandbox.e2b_sandbox_provider")
    monkeypatch.setattr(mod, "_MAX_MOUNT_FILE_SIZE", 4)
    source = tmp_path / "large.bin"
    source.write_bytes(b"12345")
    client = FakeClient()

    provider = _make_provider()
    with pytest.raises(ValueError, match="exceeds the 4-byte file limit"):
        provider._upload_tree(client, source, "/mnt/data", read_only=False)

    assert client.files.write_calls == []


def test_upload_tree_rejects_oversized_tree_before_upload(monkeypatch, tmp_path):
    mod = importlib.import_module("deerflow.community.e2b_sandbox.e2b_sandbox_provider")
    monkeypatch.setattr(mod, "_MAX_MOUNT_FILE_SIZE", 10)
    monkeypatch.setattr(mod, "_MAX_MOUNT_TOTAL_SIZE", 8)
    source = tmp_path / "mount"
    source.mkdir()
    (source / "first.bin").write_bytes(b"12345")
    (source / "second.bin").write_bytes(b"67890")
    client = FakeClient()

    provider = _make_provider()
    with pytest.raises(ValueError, match="exceeds the 8-byte total limit"):
        provider._upload_tree(client, source, "/mnt/data", read_only=False)

    assert client.files.write_calls == []


def test_upload_tree_rejects_excess_file_count_before_upload(monkeypatch, tmp_path):
    mod = importlib.import_module("deerflow.community.e2b_sandbox.e2b_sandbox_provider")
    monkeypatch.setattr(mod, "_MAX_MOUNT_FILES", 1)
    source = tmp_path / "mount"
    source.mkdir()
    (source / "first.txt").write_text("first", encoding="utf-8")
    (source / "second.txt").write_text("second", encoding="utf-8")
    client = FakeClient()

    provider = _make_provider()
    with pytest.raises(ValueError, match="exceeds the 1-file limit"):
        provider._upload_tree(client, source, "/mnt/data", read_only=False)

    assert client.files.write_calls == []


def test_apply_mounts_continues_after_mount_exceeds_limit(monkeypatch, tmp_path):
    mod = importlib.import_module("deerflow.community.e2b_sandbox.e2b_sandbox_provider")
    monkeypatch.setattr(mod, "_MAX_MOUNT_FILE_SIZE", 4)
    monkeypatch.setattr(mod, "get_app_config", lambda: SimpleNamespace(skills=SimpleNamespace(container_path="/mnt/skills")))
    oversized = tmp_path / "oversized"
    oversized.mkdir()
    (oversized / "large.bin").write_bytes(b"12345")
    valid = tmp_path / "valid"
    valid.mkdir()
    (valid / "small.bin").write_bytes(b"1234")

    provider = _make_provider()
    monkeypatch.setattr(provider, "_skill_projection_mounts", lambda _user_id: [])
    provider._config["mounts"] = [
        SimpleNamespace(host_path=str(oversized), container_path="/mnt/oversized", read_only=False),
        SimpleNamespace(host_path=str(valid), container_path="/mnt/valid", read_only=False),
    ]
    client = FakeClient()

    provider._apply_mounts(client, user_id="user-1")

    assert client.files.write_calls == [("/mnt/valid/small.bin", b"1234")]


def test_apply_mounts_bounds_total_bytes_across_mounts(monkeypatch, tmp_path, caplog):
    mod = importlib.import_module("deerflow.community.e2b_sandbox.e2b_sandbox_provider")
    monkeypatch.setattr(mod, "_MAX_MOUNT_PASS_TOTAL_BYTES", 7)
    monkeypatch.setattr(mod, "get_app_config", lambda: SimpleNamespace(skills=SimpleNamespace(container_path="/mnt/skills")))
    first = tmp_path / "first"
    first.mkdir()
    (first / "first.bin").write_bytes(b"1234")
    second = tmp_path / "second"
    second.mkdir()
    (second / "second.bin").write_bytes(b"5678")

    provider = _make_provider()
    monkeypatch.setattr(provider, "_skill_projection_mounts", lambda _user_id: [])
    provider._config["mounts"] = [
        SimpleNamespace(host_path=str(first), container_path="/mnt/first", read_only=False),
        SimpleNamespace(host_path=str(second), container_path="/mnt/second", read_only=False),
    ]
    client = FakeClient()

    with caplog.at_level("WARNING"):
        provider._apply_mounts(client, user_id="user-1")

    assert client.files.write_calls == [("/mnt/first/first.bin", b"1234")]
    assert "total byte budget 7" in caplog.text
    assert "attempted_files=1" in caplog.text
    assert "attempted_bytes=4" in caplog.text


def test_apply_mounts_bounds_total_files_across_mounts(monkeypatch, tmp_path, caplog):
    mod = importlib.import_module("deerflow.community.e2b_sandbox.e2b_sandbox_provider")
    monkeypatch.setattr(mod, "_MAX_MOUNT_PASS_FILES", 1)
    monkeypatch.setattr(mod, "get_app_config", lambda: SimpleNamespace(skills=SimpleNamespace(container_path="/mnt/skills")))
    first = tmp_path / "first"
    first.mkdir()
    (first / "first.txt").write_text("first", encoding="utf-8")
    second = tmp_path / "second"
    second.mkdir()
    (second / "second.txt").write_text("second", encoding="utf-8")

    provider = _make_provider()
    monkeypatch.setattr(provider, "_skill_projection_mounts", lambda _user_id: [])
    provider._config["mounts"] = [
        SimpleNamespace(host_path=str(first), container_path="/mnt/first", read_only=False),
        SimpleNamespace(host_path=str(second), container_path="/mnt/second", read_only=False),
    ]
    client = FakeClient()

    with caplog.at_level("WARNING"):
        provider._apply_mounts(client, user_id="user-1")

    assert client.files.write_calls == [("/mnt/first/first.txt", b"first")]
    assert "file count cap 1" in caplog.text
    assert "attempted_files=1" in caplog.text


def test_read_only_mount_remains_read_only_when_pass_limit_stops_mid_mount(monkeypatch, tmp_path):
    mod = importlib.import_module("deerflow.community.e2b_sandbox.e2b_sandbox_provider")
    monkeypatch.setattr(mod, "_MAX_MOUNT_PASS_FILES", 1)
    monkeypatch.setattr(
        mod,
        "get_app_config",
        lambda: SimpleNamespace(skills=SimpleNamespace(container_path="/mnt/skills")),
    )
    source = tmp_path / "read-only"
    source.mkdir()
    (source / "first.txt").write_text("first", encoding="utf-8")
    (source / "second.txt").write_text("second", encoding="utf-8")

    provider = _make_provider()
    monkeypatch.setattr(provider, "_skill_projection_mounts", lambda _user_id: [])
    provider._config["mounts"] = [
        SimpleNamespace(host_path=str(source), container_path="/mnt/read-only", read_only=True),
    ]
    client = FakeClient()

    provider._apply_mounts(client, user_id="user-1")

    assert len(client.files.write_calls) == 1
    assert "chmod -R a-w /mnt/read-only" in client.commands.calls


def test_read_only_mount_is_not_chmodded_when_no_upload_starts(monkeypatch, tmp_path):
    mod = importlib.import_module("deerflow.community.e2b_sandbox.e2b_sandbox_provider")
    monkeypatch.setattr(mod, "_MAX_MOUNT_PASS_FILES", 0)
    monkeypatch.setattr(
        mod,
        "get_app_config",
        lambda: SimpleNamespace(skills=SimpleNamespace(container_path="/mnt/skills")),
    )
    source = tmp_path / "read-only"
    source.mkdir()
    (source / "file.txt").write_text("content", encoding="utf-8")
    provider = _make_provider()
    monkeypatch.setattr(provider, "_skill_projection_mounts", lambda _user_id: [])
    provider._config["mounts"] = [
        SimpleNamespace(host_path=str(source), container_path="/mnt/read-only", read_only=True),
    ]
    client = FakeClient()

    provider._apply_mounts(client, user_id="user-1")

    assert client.files.write_calls == []
    assert client.commands.calls == []


def test_failed_write_consumes_aggregate_upload_budget(monkeypatch, tmp_path, caplog):
    mod = importlib.import_module("deerflow.community.e2b_sandbox.e2b_sandbox_provider")
    monkeypatch.setattr(mod, "_MAX_MOUNT_PASS_TOTAL_BYTES", 4)
    monkeypatch.setattr(
        mod,
        "get_app_config",
        lambda: SimpleNamespace(skills=SimpleNamespace(container_path="/mnt/skills")),
    )

    class FailFirstWriteAPI(FakeFilesAPI):
        def write(self, path: str, content: Any) -> None:
            super().write(path, content)
            if len(self.write_calls) == 1:
                raise RuntimeError("response lost after upload")

    first = tmp_path / "first"
    first.mkdir()
    (first / "first.bin").write_bytes(b"1234")
    second = tmp_path / "second"
    second.mkdir()
    (second / "second.bin").write_bytes(b"5")
    provider = _make_provider()
    monkeypatch.setattr(provider, "_skill_projection_mounts", lambda _user_id: [])
    provider._config["mounts"] = [
        SimpleNamespace(host_path=str(first), container_path="/mnt/first", read_only=False),
        SimpleNamespace(host_path=str(second), container_path="/mnt/second", read_only=False),
    ]
    client = FakeClient(files=FailFirstWriteAPI())

    with caplog.at_level("WARNING"):
        provider._apply_mounts(client, user_id="user-1")

    assert client.files.write_calls == [("/mnt/first/first.bin", b"1234")]
    assert "attempted_files=1" in caplog.text
    assert "attempted_bytes=4" in caplog.text
    assert "completed_files=0" in caplog.text
    assert "completed_bytes=0" in caplog.text


def test_apply_mounts_deadline_stops_before_next_file(monkeypatch, tmp_path, caplog):
    mod = importlib.import_module("deerflow.community.e2b_sandbox.e2b_sandbox_provider")
    monkeypatch.setattr(mod, "_MOUNT_PASS_DEADLINE_SECONDS", 1)
    monkeypatch.setattr(mod, "get_app_config", lambda: SimpleNamespace(skills=SimpleNamespace(container_path="/mnt/skills")))
    clock = [0.0]
    monkeypatch.setattr(mod.time, "monotonic", lambda: clock[0])

    class DeadlineFilesAPI(FakeFilesAPI):
        def write(self, path: str, content: Any) -> None:
            super().write(path, content)
            clock[0] = 2.0

    source = tmp_path / "mount"
    source.mkdir()
    (source / "first.txt").write_text("first", encoding="utf-8")
    (source / "second.txt").write_text("second", encoding="utf-8")
    provider = _make_provider()
    monkeypatch.setattr(provider, "_skill_projection_mounts", lambda _user_id: [])
    provider._config["mounts"] = [
        SimpleNamespace(host_path=str(source), container_path="/mnt/data", read_only=False),
    ]
    client = FakeClient(files=DeadlineFilesAPI())

    with caplog.at_level("WARNING"):
        provider._apply_mounts(client, user_id="user-1")

    assert len(client.files.write_calls) == 1
    assert client.files.write_calls[0] in {
        ("/mnt/data/first.txt", b"first"),
        ("/mnt/data/second.txt", b"second"),
    }
    assert "time budget 1s" in caplog.text
    assert "attempted_files=1" in caplog.text


def test_apply_mounts_deadline_stops_directory_preflight(monkeypatch, tmp_path, caplog):
    mod = importlib.import_module("deerflow.community.e2b_sandbox.e2b_sandbox_provider")
    monkeypatch.setattr(mod, "_MOUNT_PASS_DEADLINE_SECONDS", 1)
    monkeypatch.setattr(
        mod,
        "get_app_config",
        lambda: SimpleNamespace(skills=SimpleNamespace(container_path="/mnt/skills")),
    )
    clock = [0.0]
    monkeypatch.setattr(mod.time, "monotonic", lambda: clock[0])
    source = tmp_path / "mount"
    source.mkdir()
    first = source / "first.txt"
    first.write_text("first", encoding="utf-8")
    second = source / "second.txt"
    second.write_text("second", encoding="utf-8")
    original_is_file = Path.is_file
    inspected: list[Path] = []

    def slow_rglob(path: Path, pattern: str):
        assert path == source
        assert pattern == "*"
        yield first
        clock[0] = 2.0
        yield second

    def record_is_file(path: Path) -> bool:
        inspected.append(path)
        return original_is_file(path)

    monkeypatch.setattr(Path, "rglob", slow_rglob)
    monkeypatch.setattr(Path, "is_file", record_is_file)
    provider = _make_provider()
    monkeypatch.setattr(provider, "_skill_projection_mounts", lambda _user_id: [])
    provider._config["mounts"] = [
        SimpleNamespace(host_path=str(source), container_path="/mnt/data", read_only=False),
    ]
    client = FakeClient()

    with caplog.at_level("WARNING"):
        provider._apply_mounts(client, user_id="user-1")

    assert first in inspected
    assert second not in inspected
    assert client.files.write_calls == []
    assert "time budget 1s" in caplog.text


def test_apply_mounts_deadline_stops_before_next_mount_preflight(monkeypatch, tmp_path, caplog):
    mod = importlib.import_module("deerflow.community.e2b_sandbox.e2b_sandbox_provider")
    monkeypatch.setattr(mod, "_MOUNT_PASS_DEADLINE_SECONDS", 1)
    monkeypatch.setattr(
        mod,
        "get_app_config",
        lambda: SimpleNamespace(skills=SimpleNamespace(container_path="/mnt/skills")),
    )
    clock = [0.0]
    monkeypatch.setattr(mod.time, "monotonic", lambda: clock[0])

    class DeadlineFilesAPI(FakeFilesAPI):
        def write(self, path: str, content: Any) -> None:
            super().write(path, content)
            clock[0] = 2.0

    first = tmp_path / "first"
    first.mkdir()
    (first / "first.txt").write_text("first", encoding="utf-8")
    second = tmp_path / "second"
    second.mkdir()
    (second / "second.txt").write_text("second", encoding="utf-8")
    original_is_file = Path.is_file
    inspected: list[Path] = []

    def record_is_file(path: Path) -> bool:
        inspected.append(path)
        return original_is_file(path)

    monkeypatch.setattr(Path, "is_file", record_is_file)
    provider = _make_provider()
    monkeypatch.setattr(provider, "_skill_projection_mounts", lambda _user_id: [])
    provider._config["mounts"] = [
        SimpleNamespace(host_path=str(first), container_path="/mnt/first", read_only=False),
        SimpleNamespace(host_path=str(second), container_path="/mnt/second", read_only=False),
    ]
    client = FakeClient(files=DeadlineFilesAPI())

    with caplog.at_level("WARNING"):
        provider._apply_mounts(client, user_id="user-1")

    assert first in inspected
    assert second not in inspected
    assert client.files.write_calls == [("/mnt/first/first.txt", b"first")]
    assert "time budget 1s" in caplog.text


def test_apply_mounts_deadline_defaults_to_120_when_not_configured(monkeypatch, tmp_path, caplog):
    mod = importlib.import_module("deerflow.community.e2b_sandbox.e2b_sandbox_provider")
    monkeypatch.setattr(
        mod,
        "get_app_config",
        lambda: SimpleNamespace(skills=SimpleNamespace(container_path="/mnt/skills")),
    )
    clock = [0.0]
    monkeypatch.setattr(mod.time, "monotonic", lambda: clock[0])

    class DeadlineFilesAPI(FakeFilesAPI):
        def write(self, path: str, content: Any) -> None:
            super().write(path, content)
            clock[0] = 121.0

    source = tmp_path / "mount"
    source.mkdir()
    (source / "first.txt").write_text("first", encoding="utf-8")
    (source / "second.txt").write_text("second", encoding="utf-8")
    provider = _make_provider()
    assert "mount_upload_deadline_seconds" not in provider._config
    monkeypatch.setattr(provider, "_skill_projection_mounts", lambda _user_id: [])
    provider._config["mounts"] = [
        SimpleNamespace(host_path=str(source), container_path="/mnt/data", read_only=False),
    ]
    client = FakeClient(files=DeadlineFilesAPI())

    with caplog.at_level("WARNING"):
        provider._apply_mounts(client, user_id="user-1")

    assert len(client.files.write_calls) == 1
    assert "time budget 120s" in caplog.text


def test_apply_mounts_deadline_uses_configured_value(monkeypatch, tmp_path, caplog):
    mod = importlib.import_module("deerflow.community.e2b_sandbox.e2b_sandbox_provider")
    monkeypatch.setattr(
        mod,
        "get_app_config",
        lambda: SimpleNamespace(skills=SimpleNamespace(container_path="/mnt/skills")),
    )
    clock = [0.0]
    monkeypatch.setattr(mod.time, "monotonic", lambda: clock[0])

    class DeadlineFilesAPI(FakeFilesAPI):
        def write(self, path: str, content: Any) -> None:
            super().write(path, content)
            clock[0] = 61.0

    source = tmp_path / "mount"
    source.mkdir()
    (source / "first.txt").write_text("first", encoding="utf-8")
    (source / "second.txt").write_text("second", encoding="utf-8")
    provider = _make_provider()
    provider._config["mount_upload_deadline_seconds"] = 60
    monkeypatch.setattr(provider, "_skill_projection_mounts", lambda _user_id: [])
    provider._config["mounts"] = [
        SimpleNamespace(host_path=str(source), container_path="/mnt/data", read_only=False),
    ]
    client = FakeClient(files=DeadlineFilesAPI())

    with caplog.at_level("WARNING"):
        provider._apply_mounts(client, user_id="user-1")

    assert len(client.files.write_calls) == 1
    assert "time budget 60s" in caplog.text


@pytest.mark.parametrize(
    "raw,expected",
    [
        (0, 1),
        (-5, 1),
        (-100, 1),
        (None, 120),
        ("120s", 120),
        ("abc", 120),
        (float("inf"), 120),
    ],
    ids=["zero", "negative", "large_negative", "none", "suffix", "alpha", "infinity"],
)
def test_load_config_clamps_invalid_mount_upload_deadline(monkeypatch, caplog, raw, expected):
    mod = importlib.import_module("deerflow.community.e2b_sandbox.e2b_sandbox_provider")

    class FakeConfig:
        skills = SimpleNamespace(container_path="/mnt/skills")
        sandbox = SimpleNamespace(
            model_extra={"mount_upload_deadline_seconds": raw},
            api_key="test-key",
            template=None,
            image=None,
            domain=None,
            home_dir=None,
            idle_timeout=None,
            replicas=None,
            overflow_policy=None,
            acquire_timeout=None,
            burst_limit=None,
            mounts=[],
            environment=None,
            ownership=None,
            mount_upload_deadline_seconds=raw,
        )

    monkeypatch.setattr(mod, "get_app_config", lambda: FakeConfig())
    provider = mod.E2BSandboxProvider.__new__(mod.E2BSandboxProvider)
    with caplog.at_level("WARNING"):
        config = provider._load_config()
    assert config["mount_upload_deadline_seconds"] == expected
    if raw is None:
        assert "clamping" not in caplog.text
    else:
        assert "mount_upload_deadline_seconds" in caplog.text


def test_load_config_custom_mount_upload_deadline_flows_to_apply_mounts(monkeypatch, tmp_path, caplog):
    mod = importlib.import_module("deerflow.community.e2b_sandbox.e2b_sandbox_provider")
    monkeypatch.setattr(
        mod,
        "get_app_config",
        lambda: SimpleNamespace(skills=SimpleNamespace(container_path="/mnt/skills")),
    )
    clock = [0.0]
    monkeypatch.setattr(mod.time, "monotonic", lambda: clock[0])

    class DeadlineFilesAPI(FakeFilesAPI):
        def write(self, path: str, content: Any) -> None:
            super().write(path, content)
            clock[0] = 61.0

    source = tmp_path / "mount"
    source.mkdir()
    (source / "first.txt").write_text("first", encoding="utf-8")
    (source / "second.txt").write_text("second", encoding="utf-8")

    class FakeConfig:
        sandbox = SimpleNamespace(
            model_extra={"mount_upload_deadline_seconds": 60},
            api_key="test-key",
            template=None,
            image=None,
            domain=None,
            home_dir=None,
            idle_timeout=None,
            replicas=None,
            overflow_policy=None,
            acquire_timeout=None,
            burst_limit=None,
            mounts=[SimpleNamespace(host_path=str(source), container_path="/mnt/data", read_only=False)],
            environment=None,
            ownership=None,
            mount_upload_deadline_seconds=60,
        )
        skills = SimpleNamespace(container_path="/mnt/skills")

    monkeypatch.setattr(mod, "get_app_config", lambda: FakeConfig())
    provider = mod.E2BSandboxProvider.__new__(mod.E2BSandboxProvider)
    provider._config = provider._load_config()
    monkeypatch.setattr(provider, "_skill_projection_mounts", lambda _user_id: [])
    client = FakeClient(files=DeadlineFilesAPI())

    with caplog.at_level("WARNING"):
        provider._apply_mounts(client, user_id="user-1")

    assert provider._config["mount_upload_deadline_seconds"] == 60
    assert len(client.files.write_calls) == 1
    assert "time budget 60s" in caplog.text


def test_apply_mounts_deadline_reason_shows_configured_value(monkeypatch, tmp_path, caplog):
    mod = importlib.import_module("deerflow.community.e2b_sandbox.e2b_sandbox_provider")
    monkeypatch.setattr(
        mod,
        "get_app_config",
        lambda: SimpleNamespace(skills=SimpleNamespace(container_path="/mnt/skills")),
    )
    clock = [0.0]
    monkeypatch.setattr(mod.time, "monotonic", lambda: clock[0])

    class DeadlineFilesAPI(FakeFilesAPI):
        def write(self, path: str, content: Any) -> None:
            super().write(path, content)
            clock[0] = 200.0

    source = tmp_path / "mount"
    source.mkdir()
    (source / "first.txt").write_text("first", encoding="utf-8")
    (source / "second.txt").write_text("second", encoding="utf-8")
    provider = _make_provider()
    provider._config["mount_upload_deadline_seconds"] = 180
    monkeypatch.setattr(provider, "_skill_projection_mounts", lambda _user_id: [])
    provider._config["mounts"] = [
        SimpleNamespace(host_path=str(source), container_path="/mnt/data", read_only=False),
    ]
    client = FakeClient(files=DeadlineFilesAPI())

    with caplog.at_level("WARNING"):
        provider._apply_mounts(client, user_id="user-1")

    assert len(client.files.write_calls) == 1
    assert "time budget 180s" in caplog.text
    assert "attempted_files=1" in caplog.text


def test_apply_mounts_returns_result_on_success(monkeypatch, tmp_path):
    source = tmp_path / "mount"
    source.mkdir()
    (source / "first.txt").write_text("first", encoding="utf-8")
    (source / "second.txt").write_text("second", encoding="utf-8")
    provider = _make_provider()
    monkeypatch.setattr(provider, "_skill_projection_mounts", lambda _user_id: [])
    provider._config["mounts"] = [
        SimpleNamespace(host_path=str(source), container_path="/mnt/data", read_only=False),
    ]

    result = provider._apply_mounts(FakeClient(), user_id="user-1")

    assert result.truncated is False
    assert result.reason is None
    assert result.completed_files == 2
    assert result.completed_bytes == 11
    assert result.attempted_files == 2
    assert result.attempted_bytes == 11


def test_apply_mounts_returns_truncated_result_on_deadline(monkeypatch, tmp_path):
    mod = importlib.import_module("deerflow.community.e2b_sandbox.e2b_sandbox_provider")
    clock = [0.0]
    monkeypatch.setattr(mod.time, "monotonic", lambda: clock[0])

    class DeadlineFilesAPI(FakeFilesAPI):
        def write(self, path: str, content: Any) -> None:
            super().write(path, content)
            clock[0] = 2.0

    source = tmp_path / "mount"
    source.mkdir()
    (source / "first.txt").write_text("first", encoding="utf-8")
    (source / "second.txt").write_text("second", encoding="utf-8")
    provider = _make_provider()
    provider._config["mount_upload_deadline_seconds"] = 1
    monkeypatch.setattr(provider, "_skill_projection_mounts", lambda _user_id: [])
    provider._config["mounts"] = [
        SimpleNamespace(host_path=str(source), container_path="/mnt/data", read_only=False),
    ]

    result = provider._apply_mounts(FakeClient(files=DeadlineFilesAPI()), user_id="user-1")

    assert result.truncated is True
    assert result.reason == "time budget 1s"
    assert result.completed_files <= result.attempted_files


def test_apply_mounts_returns_truncated_result_on_file_count(monkeypatch, tmp_path):
    mod = importlib.import_module("deerflow.community.e2b_sandbox.e2b_sandbox_provider")
    monkeypatch.setattr(mod, "_MAX_MOUNT_PASS_FILES", 1)
    first = tmp_path / "first"
    first.mkdir()
    (first / "first.txt").write_text("first", encoding="utf-8")
    second = tmp_path / "second"
    second.mkdir()
    (second / "second.txt").write_text("second", encoding="utf-8")
    provider = _make_provider()
    monkeypatch.setattr(provider, "_skill_projection_mounts", lambda _user_id: [])
    provider._config["mounts"] = [
        SimpleNamespace(host_path=str(first), container_path="/mnt/first", read_only=False),
        SimpleNamespace(host_path=str(second), container_path="/mnt/second", read_only=False),
    ]

    result = provider._apply_mounts(FakeClient(), user_id="user-1")

    assert result.truncated is True
    assert result.reason is not None
    assert "file count cap" in result.reason


def test_apply_mounts_returns_truncated_result_on_byte_budget(monkeypatch, tmp_path):
    mod = importlib.import_module("deerflow.community.e2b_sandbox.e2b_sandbox_provider")
    monkeypatch.setattr(mod, "_MAX_MOUNT_PASS_TOTAL_BYTES", 7)
    first = tmp_path / "first"
    first.mkdir()
    (first / "first.bin").write_bytes(b"1234")
    second = tmp_path / "second"
    second.mkdir()
    (second / "second.bin").write_bytes(b"5678")
    provider = _make_provider()
    monkeypatch.setattr(provider, "_skill_projection_mounts", lambda _user_id: [])
    provider._config["mounts"] = [
        SimpleNamespace(host_path=str(first), container_path="/mnt/first", read_only=False),
        SimpleNamespace(host_path=str(second), container_path="/mnt/second", read_only=False),
    ]

    result = provider._apply_mounts(FakeClient(), user_id="user-1")

    assert result.truncated is True
    assert result.reason is not None
    assert "byte budget" in result.reason


def test_apply_mounts_non_limit_failure_is_not_reported_as_truncation(monkeypatch, tmp_path):
    class FailWriteAPI(FakeFilesAPI):
        def write(self, path: str, content: Any) -> None:
            raise RuntimeError("SDK write failed")

    source = tmp_path / "mount"
    source.mkdir()
    (source / "first.txt").write_text("first", encoding="utf-8")
    provider = _make_provider()
    monkeypatch.setattr(provider, "_skill_projection_mounts", lambda _user_id: [])
    provider._config["mounts"] = [
        SimpleNamespace(host_path=str(source), container_path="/mnt/data", read_only=False),
    ]

    result = provider._apply_mounts(FakeClient(files=FailWriteAPI()), user_id="user-1")

    assert result.truncated is False
    assert result.reason is None


def test_apply_mounts_missing_host_path_is_not_reported_as_truncation(monkeypatch, tmp_path):
    provider = _make_provider()
    monkeypatch.setattr(provider, "_skill_projection_mounts", lambda _user_id: [])
    provider._config["mounts"] = [
        SimpleNamespace(host_path=str(tmp_path / "nonexistent"), container_path="/mnt/data", read_only=False),
    ]

    result = provider._apply_mounts(FakeClient(), user_id="user-1")

    assert result.truncated is False
    assert result.reason is None
    assert result.attempted_files == 0


def test_create_sandbox_stores_mount_result_on_sandbox(monkeypatch):
    provider = _make_provider()
    _install_fake_sdk(monkeypatch, provider)
    monkeypatch.setattr(provider, "_skill_projection_mounts", lambda _user_id, _thread_id=None: [])
    provider._config["mounts"] = []

    sandbox_id = provider._create_sandbox("t1", user_id="u1")
    sandbox = provider.get(sandbox_id)

    assert sandbox is not None
    assert sandbox.mount_upload_result is not None
    assert sandbox.mount_upload_result.truncated is False
    assert sandbox.mount_upload_result.reason is None


def test_mount_result_survives_warm_pool_reclaim(monkeypatch):
    provider = _make_provider()
    _install_fake_sdk(monkeypatch, provider)
    monkeypatch.setattr(provider, "_skill_projection_mounts", lambda _user_id, _thread_id=None: [])
    provider._config["mounts"] = []

    sandbox_id = provider._create_sandbox("t1", user_id="u1")
    sandbox = provider.get(sandbox_id)
    assert sandbox is not None
    original_result = sandbox.mount_upload_result
    assert original_result is not None

    provider.release(sandbox_id)
    reclaimed_id = provider.acquire("t1", user_id="u1")
    reclaimed_sandbox = provider.get(reclaimed_id)

    assert reclaimed_id == sandbox_id
    assert reclaimed_sandbox is not None
    assert reclaimed_sandbox.mount_upload_result == original_result


def test_skill_projection_and_configured_mount_share_upload_budget(monkeypatch, tmp_path):
    mod = importlib.import_module("deerflow.community.e2b_sandbox.e2b_sandbox_provider")
    monkeypatch.setattr(mod, "_MAX_MOUNT_PASS_FILES", 1)
    monkeypatch.setattr(mod, "get_app_config", lambda: SimpleNamespace(skills=SimpleNamespace(container_path="/mnt/skills")))
    projection = tmp_path / "projection"
    projection.mkdir()
    (projection / "SKILL.md").write_text("skill", encoding="utf-8")
    configured = tmp_path / "configured"
    configured.mkdir()
    (configured / "notes.txt").write_text("notes", encoding="utf-8")

    provider = _make_provider()
    monkeypatch.setattr(provider, "_skill_projection_mounts", lambda _user_id: [(projection, "/mnt/skills/public", True)])
    provider._config["mounts"] = [
        SimpleNamespace(host_path=str(configured), container_path="/mnt/configured", read_only=False),
    ]
    client = FakeClient()

    provider._apply_mounts(client, user_id="user-1")

    assert client.files.write_calls == [("/mnt/skills/public/SKILL.md", b"skill")]


def test_upload_tree_logs_upload_summary(caplog, tmp_path):
    source = tmp_path / "mount"
    source.mkdir()
    (source / "first.txt").write_bytes(b"123")
    (source / "second.txt").write_bytes(b"4567")
    client = FakeClient()

    provider = _make_provider()
    with caplog.at_level("INFO"):
        provider._upload_tree(client, source, "/mnt/data", read_only=False)

    assert "source=" in caplog.text
    assert "destination=/mnt/data" in caplog.text
    assert "files=2" in caplog.text
    assert "bytes=7" in caplog.text
    assert "elapsed_ms=" in caplog.text


def test_skill_projection_mounts_swallows_projection_failure(monkeypatch):
    """``_skill_projection_mounts`` must not raise — a projection failure used
    to propagate out of ``_apply_mounts`` before the configured-mounts loop
    ran, dropping the operator's own configured mounts as collateral (#4107
    review)."""
    mod = importlib.import_module("deerflow.community.e2b_sandbox.e2b_sandbox_provider")

    config = SimpleNamespace(skills=SimpleNamespace(container_path="/mnt/skills"))
    monkeypatch.setattr(mod, "get_app_config", lambda: config)
    monkeypatch.setattr(
        "deerflow.skills.projection.ensure_skill_projections",
        lambda storage: (_ for _ in ()).throw(RuntimeError("simulated projection failure")),
    )

    provider = _make_provider()

    assert provider._skill_projection_mounts("user-1") == []


def test_apply_mounts_keeps_configured_mounts_when_projection_fails(monkeypatch, tmp_path):
    """End-to-end: a skills-projection failure must not drop the operator's
    own configured mounts too — the two mount sources are independent."""
    mod = importlib.import_module("deerflow.community.e2b_sandbox.e2b_sandbox_provider")

    host_dir = tmp_path / "operator-mount"
    host_dir.mkdir()
    (host_dir / "notes.txt").write_text("hello", encoding="utf-8")

    config = SimpleNamespace(skills=SimpleNamespace(container_path="/mnt/skills"))
    monkeypatch.setattr(mod, "get_app_config", lambda: config)
    monkeypatch.setattr(
        "deerflow.skills.projection.ensure_skill_projections",
        lambda storage: (_ for _ in ()).throw(RuntimeError("simulated projection failure")),
    )

    provider = _make_provider()
    provider._config["mounts"] = [
        SimpleNamespace(host_path=str(host_dir), container_path="/mnt/operator", read_only=True),
    ]

    client = FakeClient()
    provider._apply_mounts(client, user_id="user-1")

    uploaded_paths = {path for path, _content in client.files.write_calls}
    assert "/mnt/operator/notes.txt" in uploaded_paths


def _make_sandbox(client: FakeClient, *, sandbox_id: str | None = None) -> Any:
    mod = importlib.import_module("deerflow.community.e2b_sandbox.e2b_sandbox")
    return mod.E2BSandbox(
        id=sandbox_id or client.sandbox_id,
        client=client,
        home_dir="/home/user",
    )


def test_thread_key_includes_the_provider_skills_root():
    p = _make_provider()
    assert p._thread_key("t1", "u1") == ("u1", "t1", "/mnt/skills")


def test_sandbox_id_falls_back_when_client_id_is_none():
    client = FakeClient(sandbox_id=None)
    sandbox = _make_sandbox(client, sandbox_id="fallback-id")

    assert sandbox.sandbox_id == "fallback-id"


def test_stable_seed_is_deterministic_and_user_scoped():
    p = _make_provider()
    custom_root = _make_provider(skills_container_path="/custom-skills")
    s_a = p._stable_seed("t1", "u1")
    s_b = p._stable_seed("t1", "u1")
    s_other_user = p._stable_seed("t1", "u2")
    s_other_thread = p._stable_seed("t2", "u1")
    assert s_a == s_b
    assert s_a != s_other_user
    assert s_a != s_other_thread
    assert s_a != custom_root._stable_seed("t1", "u1")


def test_is_sandbox_gone_error_matches_known_signatures():
    mod = importlib.import_module("deerflow.community.e2b_sandbox.e2b_sandbox")
    f = mod._is_sandbox_gone_error
    assert f(RuntimeError("Paused sandbox abcdef not found"))
    assert f(Exception("The sandbox was not found: due to timeout"))
    assert f(Exception("sandbox not found"))
    # Unrelated errors must not flip the dead flag.
    assert not f(Exception("Connection reset by peer"))
    assert not f(ValueError("invalid path"))


def test_execute_command_marks_dead_on_sandbox_gone_error():
    client = FakeClient(commands=FakeCommandsAPI([FakeCommandsAPI.GONE]))
    sb = _make_sandbox(client)
    out = sb.execute_command("echo hi")
    assert "Error: " in out and "sandbox was not found" in out
    assert sb.is_dead is True
    out2 = sb.execute_command("echo again")
    assert "reaped" in out2.lower()
    assert client.commands.calls == ["echo hi"]


def test_execute_command_returns_stdout_on_success():
    client = FakeClient(commands=FakeCommandsAPI([SimpleNamespace(stdout="hello\n", stderr="", exit_code=0)]))
    sb = _make_sandbox(client)
    assert sb.execute_command("printf hello").rstrip() == "hello"
    assert sb.is_dead is False


def test_execute_command_appends_exit_marker_when_failure_has_output():
    """LocalSandbox parity: a nonzero exit must survive in the output text
    even when the command produced output, so evidence consumers (acceptance
    checklist) recover the actual shell status."""
    client = FakeClient(commands=FakeCommandsAPI([SimpleNamespace(stdout="5 passed, 1 error\n", stderr="", exit_code=1)]))
    sb = _make_sandbox(client)
    assert sb.execute_command("make test") == "5 passed, 1 error\n\nExit Code: 1"


def test_execute_command_does_not_mark_dead_on_unrelated_error():

    def boom(_cmd: str, **kwargs) -> Any:
        raise RuntimeError("Connection reset by peer")

    client = FakeClient(commands=FakeCommandsAPI([boom]))
    sb = _make_sandbox(client)
    out = sb.execute_command("echo hi")
    assert "Error" in out
    assert sb.is_dead is False


def test_execute_command_forwards_env_and_timeout_to_commands_run():
    """execute_command(env=..., timeout=...) routes env as ``envs`` and the
    timeout through to ``commands.run`` so request-scoped secrets (#3861) reach
    the e2b subprocess without entering the command string. Regression for the
    signature mismatch that broke bash for every e2b user."""
    commands = MagicMock()
    commands.run.return_value = SimpleNamespace(stdout="ok\n", stderr="", exit_code=0)
    client = FakeClient(commands=commands)
    sb = _make_sandbox(client)

    out = sb.execute_command("echo $TOK", env={"TOK": "secret-v"}, timeout=120)

    assert out.rstrip() == "ok"
    args, kwargs = commands.run.call_args
    assert args == ("echo $TOK",)
    assert kwargs["envs"] == {"TOK": "secret-v"}
    assert kwargs["timeout"] == 120
    # The secret must not be smuggled into the command string.
    assert "secret-v" not in args[0]


def test_execute_command_env_none_passes_no_envs_kwarg():
    """env=None is fully backward-compatible — ``commands.run`` is called with no
    ``envs``/``timeout`` kwargs, so existing (non-secret) callers are unaffected."""
    commands = MagicMock()
    commands.run.return_value = SimpleNamespace(stdout="ok\n", stderr="", exit_code=0)
    client = FakeClient(commands=commands)
    sb = _make_sandbox(client)

    sb.execute_command("echo hi")

    _, kwargs = commands.run.call_args
    assert "envs" not in kwargs
    assert "timeout" not in kwargs


def test_execute_command_forwards_env_as_envs():
    """Per-call ``env`` reaches the e2b SDK as ``envs`` so secrets like
    ``GITHUB_TOKEN`` are scoped to a single command without mutating shared
    state. Mirrors the local/AIO sandboxes' overlay contract.
    """
    client = FakeClient(commands=FakeCommandsAPI([SimpleNamespace(stdout="ok", stderr="", exit_code=0)]))
    sb = _make_sandbox(client)
    sb.execute_command("gh pr create", env={"GH_TOKEN": "tok-123"})
    assert client.commands.envs == [{"GH_TOKEN": "tok-123"}]


def test_execute_command_rejects_invalid_env_key():
    client = FakeClient(commands=FakeCommandsAPI([]))
    sb = _make_sandbox(client)
    with pytest.raises(ValueError, match="extra_env key"):
        sb.execute_command("echo hi", env={"X;rm -rf /;Y": "v"})
    # The SDK was never reached — validation happens before commands.run.
    assert client.commands.calls == []


def test_ping_returns_false_when_sandbox_gone():
    client = FakeClient(commands=FakeCommandsAPI([FakeCommandsAPI.GONE]))
    sb = _make_sandbox(client)
    assert sb.ping() is False
    assert sb.is_dead is True


def test_ping_returns_true_on_unknown_error():
    def boom(_cmd: str) -> Any:
        raise RuntimeError("upstream timeout")

    client = FakeClient(commands=FakeCommandsAPI([boom]))
    sb = _make_sandbox(client)
    assert sb.ping() is True
    assert sb.is_dead is False


def test_client_alive_true_for_healthy_client():
    p = _make_provider()
    client = FakeClient()
    assert p._client_alive(client) is True
    assert client.commands.calls == ["true"]


def test_client_alive_false_when_sandbox_gone():
    p = _make_provider()
    client = FakeClient(commands=FakeCommandsAPI([FakeCommandsAPI.GONE]))
    assert p._client_alive(client) is False


def test_client_alive_treats_unknown_errors_as_alive():
    p = _make_provider()

    def boom(_cmd: str) -> Any:
        raise RuntimeError("flaky network")

    client = FakeClient(commands=FakeCommandsAPI([boom]))
    assert p._client_alive(client) is True


def test_safe_close_client_swallows_close_failures():
    p = _make_provider()

    class BadCloseClient:
        def close(self) -> None:
            raise RuntimeError("boom")

    p._safe_close_client(BadCloseClient())
    p._safe_close_client(None)


def test_kill_and_close_invokes_kill_and_close_in_order():
    p = _make_provider()
    client = FakeClient()
    sb = _make_sandbox(client)
    p._kill_and_close(sb)
    assert client.killed is True


def test_kill_and_close_swallows_kill_exceptions():
    p = _make_provider()
    client = FakeClient()
    sb = _make_sandbox(client)

    def explode():
        raise RuntimeError("already gone")

    client.kill = explode
    p._kill_and_close(sb)
    assert "fake-sb-1" not in p._owned_sandbox_ids
    assert p._ownership.owner("fake-sb-1") is None


def test_kill_and_close_skips_peer_owned_sandbox():
    p = _make_provider()
    client = FakeClient(sandbox_id="peer-owned")
    sandbox = _make_sandbox(client, sandbox_id="peer-owned")
    p._ownership = FakeOwnershipStore(
        {"peer-owned": ("owner-peer", "own")},
        owner_id=p._owner_id,
    )

    p._kill_and_close(sandbox)

    assert client.killed is False
    assert client.closed is True
    assert p._ownership.owner("peer-owned") == "owner-peer"


def test_startup_reconciliation_runs_in_background_without_blocking_caller(monkeypatch):
    p = _make_provider()
    entered = threading.Event()
    release = threading.Event()

    def reconcile():
        entered.set()
        assert release.wait(timeout=2)

    monkeypatch.setattr(p, "_reconcile_remote_sandboxes", reconcile)

    started = time.monotonic()
    p._start_maintenance_threads()
    elapsed = time.monotonic() - started

    assert entered.wait(timeout=1)
    assert elapsed < 0.5

    release.set()
    p._maintenance_stop.set()
    for thread in (p._lease_thread, p._reconcile_thread):
        assert thread is not None
        thread.join(timeout=2)


def test_refresh_owned_leases_reclaims_lapsed_lease():
    p = _make_provider()
    client = FakeClient(sandbox_id="sb-lapsed")
    sandbox = _make_sandbox(client, sandbox_id="sb-lapsed")
    p._sandboxes["sb-lapsed"] = sandbox
    p._thread_sandboxes[p._thread_key("t1", "u1")] = "sb-lapsed"
    p._owned_sandbox_ids.add("sb-lapsed")

    p._refresh_owned_leases()

    assert p._ownership.owner("sb-lapsed") == p._owner_id
    assert p.get("sb-lapsed") is sandbox
    assert client.closed is False


def test_refresh_owned_leases_forgets_peer_owned_sandbox():
    p = _make_provider()
    client = FakeClient(sandbox_id="sb-lost")
    sandbox = _make_sandbox(client, sandbox_id="sb-lost")
    p._sandboxes["sb-lost"] = sandbox
    key = p._thread_key("t1", "u1")
    p._thread_sandboxes[key] = "sb-lost"
    p._owned_sandbox_ids.add("sb-lost")
    p._ownership = FakeOwnershipStore(
        {"sb-lost": ("owner-peer", "own")},
        owner_id=p._owner_id,
    )

    p._refresh_owned_leases()

    assert p.get("sb-lost") is None
    assert key not in p._thread_sandboxes
    assert "sb-lost" not in p._owned_sandbox_ids
    assert client.closed is True


def test_reuse_in_process_sandbox_returns_cached_id_on_healthy_reuse():
    p = _make_provider()
    client = FakeClient()
    sb = _make_sandbox(client, sandbox_id="sb-1")
    p._sandboxes["sb-1"] = sb
    p._thread_sandboxes[p._thread_key("t1", "u1")] = "sb-1"

    sid = p._reuse_in_process_sandbox("t1", user_id="u1")
    assert sid == "sb-1"
    assert client.timeouts_set, "expected set_timeout to be called on reuse"


def test_reuse_in_process_sandbox_evicts_dead_sandbox():
    p = _make_provider()
    client = FakeClient(commands=FakeCommandsAPI([FakeCommandsAPI.GONE]))
    sb = _make_sandbox(client, sandbox_id="sb-dead")
    sb._dead = True
    p._sandboxes["sb-dead"] = sb
    key = p._thread_key("t1", "u1")
    p._thread_sandboxes[key] = "sb-dead"

    sid = p._reuse_in_process_sandbox("t1", user_id="u1")
    assert sid is None
    assert "sb-dead" not in p._sandboxes
    assert key not in p._thread_sandboxes


def test_reuse_in_process_sandbox_evicts_when_ping_fails():
    p = _make_provider()
    client = FakeClient(commands=FakeCommandsAPI([FakeCommandsAPI.GONE]))
    sb = _make_sandbox(client, sandbox_id="sb-stale")
    p._sandboxes["sb-stale"] = sb
    p._thread_sandboxes[p._thread_key("t1", "u1")] = "sb-stale"

    sid = p._reuse_in_process_sandbox("t1", user_id="u1")
    assert sid is None
    assert sb.is_dead is True
    assert "sb-stale" not in p._sandboxes


def test_reuse_in_process_sandbox_cleans_dangling_mapping():
    p = _make_provider()
    key = p._thread_key("t1", "u1")
    p._thread_sandboxes[key] = "ghost"
    sid = p._reuse_in_process_sandbox("t1", user_id="u1")
    assert sid is None
    assert key not in p._thread_sandboxes


def test_reuse_in_process_sandbox_returns_none_when_no_mapping():
    p = _make_provider()
    assert p._reuse_in_process_sandbox("t-x", user_id="u-x") is None


def test_reclaim_warm_pool_sandbox_happy_path(monkeypatch):
    p = _make_provider()
    fake_cls = _install_fake_sdk(monkeypatch, p)
    seed = p._stable_seed("t1", "u1")
    p._warm_pool["sb-warm"] = (seed, 12345.0)

    sid = p._reclaim_warm_pool_sandbox("t1", user_id="u1")
    assert sid == "sb-warm"
    assert "sb-warm" in p._sandboxes
    assert p._thread_sandboxes[p._thread_key("t1", "u1")] == "sb-warm"
    assert "sb-warm" not in p._warm_pool
    assert [c[0] for c in fake_cls.connect_calls] == ["sb-warm"]


def test_reclaim_warm_pool_sandbox_drops_dead_entry(monkeypatch):
    p = _make_provider()
    fake_cls = _install_fake_sdk(monkeypatch, p)
    client = FakeClient(
        sandbox_id="sb-zombie",
        commands=FakeCommandsAPI([FakeCommandsAPI.GONE]),
    )
    fake_cls.connect_factory = lambda _sid, **_kw: client
    seed = p._stable_seed("t1", "u1")
    p._warm_pool["sb-zombie"] = (seed, 12345.0)

    sid = p._reclaim_warm_pool_sandbox("t1", user_id="u1")
    assert sid is None
    assert "sb-zombie" not in p._sandboxes
    assert "sb-zombie" not in p._warm_pool
    assert client.closed is True


def test_reclaim_warm_pool_sandbox_handles_reconnect_exception(monkeypatch):
    p = _make_provider()
    fake_cls = _install_fake_sdk(monkeypatch, p)

    def boom(sid, **kw):
        raise RuntimeError("404 Not Found")

    fake_cls.connect_factory = boom
    seed = p._stable_seed("t1", "u1")
    p._warm_pool["sb-broken"] = (seed, 12345.0)

    sid = p._reclaim_warm_pool_sandbox("t1", user_id="u1")
    assert sid is None
    assert "sb-broken" not in p._warm_pool


def test_acquire_discards_warm_sandbox_when_bootstrap_fails(monkeypatch):
    p = _make_provider()
    fake_cls = _install_fake_sdk(monkeypatch, p)
    warm_client = FakeClient(
        sandbox_id="sb-warm",
        commands=FakeCommandsAPI(
            [
                SimpleNamespace(stdout="ok", stderr="", exit_code=0),
                SimpleNamespace(stdout="", stderr="permission denied", exit_code=1),
            ]
        ),
    )
    fresh_client = FakeClient(sandbox_id="sb-fresh")
    fake_cls.connect_factory = lambda _sid, **_kw: warm_client
    fake_cls.create_factory = lambda **_kw: fresh_client
    p._warm_pool["sb-warm"] = (p._stable_seed("t1", "u1"), 12345.0)

    assert p.acquire("t1", user_id="u1") == "sb-fresh"
    assert warm_client.killed is True
    assert warm_client.closed is True
    assert p.get("sb-warm") is None


def test_reclaim_warm_pool_sandbox_returns_none_on_seed_mismatch(monkeypatch):
    p = _make_provider()
    _install_fake_sdk(monkeypatch, p)
    p._warm_pool["sb-other"] = ("some-other-seed", 12345.0)
    assert p._reclaim_warm_pool_sandbox("t1", user_id="u1") is None
    # The unrelated entry must remain untouched.
    assert "sb-other" in p._warm_pool


class _FakePaginator:
    """Mirror of e2b SDK's ``SandboxPaginator``: items via ``next_items``."""

    def __init__(self, pages: list[list[Any]]) -> None:
        self._pages = list(pages)
        self.has_next = bool(self._pages)
        self.calls = 0

    def next_items(self) -> list[Any]:
        self.calls += 1
        if not self._pages:
            self.has_next = False
            return []
        page = self._pages.pop(0)
        self.has_next = bool(self._pages)
        return page


def _info(
    sandbox_id: str,
    user_id: str,
    thread_id: str,
    *,
    skills_container_path: str = "/mnt/skills",
):
    return SimpleNamespace(
        sandbox_id=sandbox_id,
        metadata={
            "deer_flow_provider": "e2b_sandbox_provider",
            "deer_flow_user": user_id,
            "deer_flow_thread": thread_id,
            "deer_flow_skills_root": skills_container_path,
        },
    )


def test_discover_remote_sandbox_rejects_a_different_skills_root(monkeypatch):
    p = _make_provider(skills_container_path="/custom-skills")
    fake_cls = _install_fake_sdk(monkeypatch, p)
    fake_cls.list_return = [_info("sb-old-root", "u1", "t1")]

    assert p._discover_remote_sandbox("t1", user_id="u1") is None
    assert fake_cls.connect_calls == []


def test_create_metadata_records_the_snapshotted_skills_root(monkeypatch):
    provider = _make_provider(skills_container_path="/custom-skills")
    fake_cls = _install_fake_sdk(monkeypatch, provider)

    provider.acquire("t1", user_id="u1")

    assert fake_cls.create_calls[0]["metadata"]["deer_flow_skills_root"] == "/custom-skills"


def test_discover_remote_sandbox_walks_paginator(monkeypatch):
    p = _make_provider()
    fake_cls = _install_fake_sdk(monkeypatch, p)
    fake_cls.list_return = _FakePaginator(
        [
            [_info("sb-other", "u-x", "t-x")],
            [_info("sb-match", "u1", "t1")],
        ]
    )

    sid = p._discover_remote_sandbox("t1", user_id="u1")
    assert sid == "sb-match"
    assert p._thread_sandboxes[p._thread_key("t1", "u1")] == "sb-match"


def test_discover_remote_sandbox_accepts_legacy_list(monkeypatch):
    p = _make_provider()
    fake_cls = _install_fake_sdk(monkeypatch, p)
    fake_cls.list_return = [_info("sb-legacy", "u1", "t1")]

    sid = p._discover_remote_sandbox("t1", user_id="u1")
    assert sid == "sb-legacy"


def test_discover_remote_sandbox_skips_dead_candidate(monkeypatch):
    p = _make_provider()
    fake_cls = _install_fake_sdk(monkeypatch, p)
    fake_cls.list_return = [_info("sb-dead", "u1", "t1")]
    client = FakeClient(
        sandbox_id="sb-dead",
        commands=FakeCommandsAPI([FakeCommandsAPI.GONE]),
    )
    fake_cls.connect_factory = lambda _sid, **_kw: client

    assert p._discover_remote_sandbox("t1", user_id="u1") is None
    assert p._thread_key("t1", "u1") not in p._thread_sandboxes
    assert client.closed is True


def test_discover_remote_sandbox_tries_later_candidate_when_first_is_dead(monkeypatch):
    p = _make_provider()
    fake_cls = _install_fake_sdk(monkeypatch, p)
    fake_cls.list_return = [
        _info("sb-a-dead", "u1", "t1"),
        _info("sb-b-live", "u1", "t1"),
    ]
    dead = FakeClient(
        sandbox_id="sb-a-dead",
        commands=FakeCommandsAPI([FakeCommandsAPI.GONE]),
    )
    live = FakeClient(sandbox_id="sb-b-live")
    fake_cls.connect_factory = lambda sid, **_kw: dead if sid == "sb-a-dead" else live

    assert p._discover_remote_sandbox("t1", user_id="u1") == "sb-b-live"
    assert dead.closed is True
    assert p._thread_sandboxes[p._thread_key("t1", "u1")] == "sb-b-live"
    assert "sb-b-live" in p._owned_sandbox_ids


def test_reconcile_defers_duplicate_with_live_peer_lease(monkeypatch):
    p = _make_provider()
    fake_cls = _install_fake_sdk(monkeypatch, p)
    fake_cls.list_return = [
        _info("sb-canonical", "u1", "t1"),
        _info("sb-duplicate", "u1", "t1"),
    ]
    clients = {
        "sb-canonical": FakeClient(sandbox_id="sb-canonical"),
        "sb-duplicate": FakeClient(sandbox_id="sb-duplicate"),
    }
    fake_cls.connect_factory = lambda sid, **_kw: clients[sid]
    leases = {"sb-duplicate": ("owner-peer", "own")}
    p._ownership = FakeOwnershipStore(leases, owner_id=p._owner_id)
    p._config["reconciliation_grace_seconds"] = 0.0

    stats = p._reconcile_remote_sandboxes(now=time.monotonic())

    assert stats.adopted == 1
    assert stats.deferred == 1
    assert stats.killed == 0
    assert clients["sb-duplicate"].killed is False


def test_reconcile_kills_unowned_duplicate_after_grace(monkeypatch):
    p = _make_provider()
    fake_cls = _install_fake_sdk(monkeypatch, p)
    fake_cls.list_return = [
        _info("sb-canonical", "u1", "t1"),
        _info("sb-duplicate", "u1", "t1"),
    ]
    clients = {
        "sb-canonical": FakeClient(sandbox_id="sb-canonical"),
        "sb-duplicate": FakeClient(sandbox_id="sb-duplicate"),
    }
    fake_cls.connect_factory = lambda sid, **_kw: clients[sid]
    p._config["reconciliation_grace_seconds"] = 5.0

    first = p._reconcile_remote_sandboxes(now=100.0)
    second = p._reconcile_remote_sandboxes(now=106.0)

    assert first.deferred == 1
    assert first.killed == 0
    assert second.killed == 1
    assert clients["sb-duplicate"].killed is True


def test_competing_reconcilers_only_one_kills_duplicate(monkeypatch):
    shared_leases: dict[str, tuple[str, str]] = {}
    shared_lock = threading.Lock()
    providers = [_make_provider(), _make_provider()]
    providers[0]._owner_id = "owner-a"
    providers[1]._owner_id = "owner-b"
    clients = {
        "sb-canonical": FakeClient(sandbox_id="sb-canonical"),
        "sb-duplicate": FakeClient(sandbox_id="sb-duplicate"),
    }
    kill_count = 0

    def kill_duplicate() -> None:
        nonlocal kill_count
        kill_count += 1
        clients["sb-duplicate"].killed = True
        clients["sb-duplicate"].commands._responses.append(FakeCommandsAPI.GONE)

    clients["sb-duplicate"].kill = kill_duplicate

    for provider in providers:
        fake_cls = _install_fake_sdk(monkeypatch, provider)
        fake_cls.list_return = [
            _info("sb-canonical", "u1", "t1"),
            _info("sb-duplicate", "u1", "t1"),
        ]
        fake_cls.connect_factory = lambda sid, **_kw: clients[sid]
        provider._ownership = FakeOwnershipStore(
            shared_leases,
            owner_id=provider._owner_id,
            lock=shared_lock,
        )
        provider._config["reconciliation_grace_seconds"] = 0.0

    results = [provider._reconcile_remote_sandboxes(now=100.0) for provider in providers]

    assert sum(result.killed for result in results) == 1
    assert kill_count == 1


def test_reconcile_honors_item_budget(monkeypatch):
    p = _make_provider()
    fake_cls = _install_fake_sdk(monkeypatch, p)
    fake_cls.list_return = [_info(f"sb-{index}", "u1", f"t-{index}") for index in range(5)]
    p._config["reconciliation_max_items"] = 2

    stats = p._reconcile_remote_sandboxes(now=100.0)

    assert stats.discovered == 2
    assert len(fake_cls.connect_calls) == 2


def test_reconcile_honors_page_budget(monkeypatch):
    p = _make_provider()
    fake_cls = _install_fake_sdk(monkeypatch, p)
    paginator = _FakePaginator(
        [
            [_info("sb-first", "u1", "t1")],
            [_info("sb-never-read", "u2", "t2")],
        ]
    )
    fake_cls.list_return = paginator
    p._config["reconciliation_max_pages"] = 1

    stats = p._reconcile_remote_sandboxes(now=100.0)

    assert stats.discovered == 1
    assert stats.budget_exhausted is True
    assert paginator.calls == 1
    assert [call[0] for call in fake_cls.connect_calls] == ["sb-first"]


def test_reconcile_honors_wall_clock_budget(monkeypatch):
    p = _make_provider()
    fake_cls = _install_fake_sdk(monkeypatch, p)
    fake_cls.list_return = [_info("sb-never-probed", "u1", "t1")]
    p._config["reconciliation_max_seconds"] = 0.5
    provider_mod = importlib.import_module("deerflow.community.e2b_sandbox.e2b_sandbox_provider")
    ticks = iter([0.0, 0.0, 1.0, 1.0])
    monkeypatch.setattr(provider_mod.time, "monotonic", lambda: next(ticks))

    stats = p._reconcile_remote_sandboxes(now=100.0)

    assert stats.budget_exhausted is True
    assert fake_cls.connect_calls == []


def test_reconcile_adopts_canonical_after_restart_loses_local_state(monkeypatch):
    p = _make_provider()
    fake_cls = _install_fake_sdk(monkeypatch, p)
    fake_cls.list_return = [_info("sb-existing", "u1", "t1")]

    stats = p._reconcile_remote_sandboxes(now=100.0)

    assert stats.adopted == 1
    assert p._thread_sandboxes[p._thread_key("t1", "u1")] == "sb-existing"
    assert "sb-existing" in p._owned_sandbox_ids


def test_reconcile_bootstrap_failure_clears_inflight_after_peer_take(monkeypatch):
    p = _make_provider()
    fake_cls = _install_fake_sdk(monkeypatch, p)
    sandbox_id = "sb-racy-bootstrap"
    fake_cls.list_return = [_info(sandbox_id, "u1", "t1")]
    shared_leases: dict[str, tuple[str, str]] = {}
    shared_lock = threading.Lock()
    p._ownership = FakeOwnershipStore(
        shared_leases,
        owner_id=p._owner_id,
        lock=shared_lock,
    )
    peer_ownership = FakeOwnershipStore(
        shared_leases,
        owner_id="owner-peer",
        lock=shared_lock,
    )

    def peer_takes_before_bootstrap_fails(_command: str) -> SimpleNamespace:
        assert peer_ownership.take(sandbox_id) is True
        return SimpleNamespace(stdout="", stderr="permission denied", exit_code=1)

    client = FakeClient(
        sandbox_id=sandbox_id,
        commands=FakeCommandsAPI(
            [
                SimpleNamespace(stdout="ok", stderr="", exit_code=0),
                peer_takes_before_bootstrap_fails,
            ]
        ),
    )
    fake_cls.connect_factory = lambda _sid, **_kw: client

    stats = p._reconcile_remote_sandboxes(now=100.0)

    assert stats.adopted == 0
    assert stats.deferred == 1
    assert sandbox_id not in p._acquire_inflight
    assert sandbox_id not in p._unowned_remote_ops_in_progress
    assert p._reserved_slots == 0
    assert p._ownership.owner(sandbox_id) == "owner-peer"
    assert client.killed is False
    assert client.closed is True


def test_reconcile_kills_metadata_orphan_only_after_ttl(monkeypatch):
    p = _make_provider()
    fake_cls = _install_fake_sdk(monkeypatch, p)
    fake_cls.list_return = [
        SimpleNamespace(
            sandbox_id="sb-orphan",
            metadata={"deer_flow_provider": "e2b_sandbox_provider"},
        )
    ]
    client = FakeClient(sandbox_id="sb-orphan")
    fake_cls.connect_factory = lambda _sid, **_kw: client
    p._config["reconciliation_orphan_ttl_seconds"] = 5.0

    first = p._reconcile_remote_sandboxes(now=100.0)
    second = p._reconcile_remote_sandboxes(now=106.0)

    assert first.deferred == 1
    assert first.killed == 0
    assert second.killed == 1
    assert client.killed is True


def test_reconcile_never_adopts_an_old_skills_root_and_reaps_it_after_grace(
    monkeypatch,
):
    provider = _make_provider(skills_container_path="/custom-skills")
    fake_cls = _install_fake_sdk(monkeypatch, provider)
    fake_cls.list_return = [
        _info(
            "sb-old-root",
            "u1",
            "t1",
            skills_container_path="/mnt/skills",
        )
    ]
    client = FakeClient(sandbox_id="sb-old-root")
    fake_cls.connect_factory = lambda _sid, **_kw: client
    provider._config["reconciliation_grace_seconds"] = 5.0

    first = provider._reconcile_remote_sandboxes(now=100.0)
    second = provider._reconcile_remote_sandboxes(now=106.0)

    assert first.adopted == 0
    assert first.deferred == 1
    assert provider._thread_key("t1", "u1") not in provider._thread_sandboxes
    assert second.killed == 1
    assert client.killed is True


def test_discover_remote_sandbox_discards_candidate_when_bootstrap_fails(monkeypatch):
    p = _make_provider()
    fake_cls = _install_fake_sdk(monkeypatch, p)
    fake_cls.list_return = [_info("sb-broken", "u1", "t1")]
    client = FakeClient(
        sandbox_id="sb-broken",
        commands=FakeCommandsAPI(
            [
                SimpleNamespace(stdout="ok", stderr="", exit_code=0),
                SimpleNamespace(stdout="", stderr="permission denied", exit_code=1),
            ]
        ),
    )
    fake_cls.connect_factory = lambda _sid, **_kw: client

    assert p._discover_remote_sandbox("t1", user_id="u1") is None
    assert client.killed is True
    assert client.closed is True
    assert p._thread_key("t1", "u1") not in p._thread_sandboxes


def test_discovery_claims_ownership_before_bootstrap_cleanup(monkeypatch):
    events: list[str] = []

    class RecordingOwnershipStore(FakeOwnershipStore):
        def take(self, sandbox_id: str) -> bool:
            events.append("take")
            return super().take(sandbox_id)

        def claim(self, sandbox_id: str, *, for_destroy: bool = False) -> bool:
            events.append("claim-destroy" if for_destroy else "claim")
            return super().claim(sandbox_id, for_destroy=for_destroy)

        def release(self, sandbox_id: str) -> None:
            events.append("release")
            super().release(sandbox_id)

    p = _make_provider()
    p._ownership = RecordingOwnershipStore(
        {"sb-broken": ("owner-peer", "own")},
        owner_id=p._owner_id,
    )
    fake_cls = _install_fake_sdk(monkeypatch, p)
    fake_cls.list_return = [_info("sb-broken", "u1", "t1")]
    client = FakeClient(
        sandbox_id="sb-broken",
        commands=FakeCommandsAPI(
            [
                SimpleNamespace(stdout="ok", stderr="", exit_code=0),
                SimpleNamespace(stdout="", stderr="permission denied", exit_code=1),
            ]
        ),
    )
    client.kill = lambda: events.append("kill")
    fake_cls.connect_factory = lambda _sid, **_kw: client

    assert p._discover_remote_sandbox("t1", user_id="u1") is None
    assert events == ["take", "claim-destroy", "kill", "release"]


def test_bootstrap_failure_does_not_kill_without_destroy_lease(monkeypatch):
    p = _make_provider()
    client = FakeClient(
        sandbox_id="sb-peer",
        commands=FakeCommandsAPI([SimpleNamespace(stdout="", stderr="permission denied", exit_code=1)]),
    )
    p._ownership = FakeOwnershipStore(
        {"sb-peer": ("owner-peer", "own")},
        owner_id=p._owner_id,
    )

    error, remote_destroyed = p._bootstrap_or_discard(client, "sb-peer")

    assert error is not None
    assert remote_destroyed is False
    assert client.killed is False
    assert client.closed is True
    assert p._ownership.owner("sb-peer") == "owner-peer"


def test_kill_client_returns_exception_without_raising():
    p = _make_provider()
    store = _install_shared_deployment_capacity(p)
    failed_client = FakeClient()
    error = RuntimeError("already gone")
    failed_client.kill = MagicMock(side_effect=error)

    assert p._kill_client(failed_client) is error
    store.release.assert_not_called()

    client = FakeClient()
    assert p._kill_client(client) is None
    store.release.assert_called_once_with(client.sandbox_id)


def test_kill_client_reports_uncertain_cleanup_without_callable_kill():
    p = _make_provider()

    assert isinstance(p._kill_client(None), RuntimeError)
    assert isinstance(p._kill_client(SimpleNamespace()), RuntimeError)


def test_sandbox_config_validates_e2b_capacity_fields():
    config = SandboxConfig(
        use="deerflow.community.e2b_sandbox:E2BSandboxProvider",
        overflow_policy="burst",
        acquire_timeout=12,
        burst_limit=2,
    )

    assert config.overflow_policy == "burst"
    assert config.acquire_timeout == 12
    assert config.burst_limit == 2

    with pytest.raises(ValidationError):
        SandboxConfig(
            use="deerflow.community.e2b_sandbox:E2BSandboxProvider",
            overflow_policy="invalid",
        )

    with pytest.raises(ValidationError):
        SandboxConfig(
            use="deerflow.community.e2b_sandbox:E2BSandboxProvider",
            acquire_timeout=0,
        )

    with pytest.raises(ValidationError):
        SandboxConfig(
            use="deerflow.community.e2b_sandbox:E2BSandboxProvider",
            burst_limit=-1,
        )

    with pytest.raises(ValidationError):
        SandboxConfig(
            use="deerflow.community.e2b_sandbox:E2BSandboxProvider",
            replicas=0,
        )


def test_e2b_config_accepts_documented_reconciliation_fields(monkeypatch, caplog):
    mod = importlib.import_module("deerflow.community.e2b_sandbox.e2b_sandbox_provider")
    config = SandboxConfig(
        use="deerflow.community.e2b_sandbox:E2BSandboxProvider",
        api_key="test-key",
        reconciliation_interval_seconds=60,
        reconciliation_grace_seconds=120,
        reconciliation_orphan_ttl_seconds=3600,
        reconciliation_max_pages=10,
        reconciliation_max_items=200,
        reconciliation_max_seconds=15,
    )
    provider = mod.E2BSandboxProvider.__new__(mod.E2BSandboxProvider)
    monkeypatch.setattr(
        mod,
        "get_app_config",
        lambda: SimpleNamespace(
            sandbox=config,
            skills=SimpleNamespace(container_path="/mnt/skills"),
        ),
    )

    with caplog.at_level("WARNING"):
        provider._load_config()

    assert "unknown sandbox config fields" not in caplog.text


def test_e2b_config_warns_about_unknown_fields(monkeypatch, caplog):
    mod = importlib.import_module("deerflow.community.e2b_sandbox.e2b_sandbox_provider")
    config = SandboxConfig(
        use="deerflow.community.e2b_sandbox:E2BSandboxProvider",
        api_key="test-key",
        overflo_policy="reject",
    )
    provider = mod.E2BSandboxProvider.__new__(mod.E2BSandboxProvider)
    monkeypatch.setattr(
        mod,
        "get_app_config",
        lambda: SimpleNamespace(
            sandbox=config,
            skills=SimpleNamespace(container_path="/mnt/skills"),
        ),
    )

    with caplog.at_level("WARNING"):
        provider._load_config()

    assert "overflo_policy" in caplog.text


def test_evict_oldest_warm_keeps_slot_when_kill_lookup_raises(monkeypatch):
    p = _make_provider()
    fake_cls = _install_fake_sdk(monkeypatch, p)
    error = RuntimeError("kill unavailable")

    class ClientWithBrokenKill:
        def __init__(self) -> None:
            self.closed = False

        @property
        def kill(self):
            raise error

        def close(self) -> None:
            self.closed = True

    client = ClientWithBrokenKill()
    fake_cls.connect_factory = lambda _sid, **_kw: client
    p._warm_pool["sb-warm"] = ("seed", 12345.0)

    assert p._evict_oldest_warm() is None
    assert client.closed is True
    assert p._eviction_tombstones == {"sb-warm"}
    assert p._transitioning_slots == 1
    assert "sb-warm" not in p._warm_pool
    assert "sb-warm" not in p._owned_sandbox_ids
    assert p._ownership.owner("sb-warm") is None


def test_evict_oldest_warm_defers_peer_owned_sandbox(monkeypatch):
    p = _make_provider()
    fake_cls = _install_fake_sdk(monkeypatch, p)
    p._warm_pool["sb-peer"] = ("seed", 12345.0)
    p._ownership = FakeOwnershipStore(
        {"sb-peer": ("owner-peer", "own")},
        owner_id=p._owner_id,
    )

    assert p._evict_oldest_warm() == "sb-peer"

    assert fake_cls.connect_calls == []
    assert "sb-peer" not in p._warm_pool
    assert p._eviction_tombstones == set()
    assert p._evictions_in_progress == set()
    assert p._transitioning_slots == 0
    assert p._ownership.owner("sb-peer") == "owner-peer"


def test_evict_oldest_warm_releases_destroy_lease_after_kill_failure(monkeypatch):
    p = _make_provider()
    fake_cls = _install_fake_sdk(monkeypatch, p)
    client = FakeClient(sandbox_id="sb-warm")
    client.kill = MagicMock(side_effect=RuntimeError("transient kill failure"))
    fake_cls.connect_factory = lambda _sid, **_kw: client
    p._warm_pool["sb-warm"] = ("seed", 12345.0)
    p._owned_sandbox_ids.add("sb-warm")
    p._ownership.take("sb-warm")

    assert p._evict_oldest_warm() is None

    assert client.closed is True
    assert "sb-warm" not in p._warm_pool
    assert p._eviction_tombstones == {"sb-warm"}
    assert p._transitioning_slots == 1
    assert "sb-warm" not in p._owned_sandbox_ids
    assert p._ownership.owner("sb-warm") is None


def test_evict_oldest_warm_uses_kill_helper_and_closes_client(monkeypatch):
    p = _make_provider()
    fake_cls = _install_fake_sdk(monkeypatch, p)
    client = FakeClient(sandbox_id="sb-warm")
    fake_cls.connect_factory = lambda _sid, **_kw: client
    p._warm_pool["sb-warm"] = ("seed", 12345.0)
    kill_client = MagicMock(return_value=None)
    p._kill_client = kill_client

    assert p._evict_oldest_warm() == "sb-warm"
    kill_client.assert_called_once_with(client)
    assert client.closed is True


def test_discover_remote_sandbox_returns_none_when_list_raises(monkeypatch):
    p = _make_provider()
    fake_cls = _install_fake_sdk(monkeypatch, p)

    def boom(**kw):
        raise RuntimeError("API unreachable")

    fake_cls.list = boom
    assert p._discover_remote_sandbox("t1", user_id="u1") is None


def test_bootstrap_sandbox_paths_emits_expected_script():
    p = _make_provider()
    client = FakeClient()
    p._bootstrap_sandbox_paths(client)
    assert len(client.commands.calls) == 1
    script = client.commands.calls[0]
    assert "ln -sfn" in script
    assert "/mnt/user-data" in script
    assert "/mnt/acp-workspace" in script
    assert "BOOTSTRAP_OK" in script
    for sub in ("workspace", "uploads", "outputs", "acp-workspace"):
        assert f"/home/user/{sub}" in script


def test_bootstrap_sandbox_paths_raises_on_command_failure():
    p = _make_provider()

    def boom(_cmd: str) -> Any:
        raise RuntimeError("sudo not allowed")

    client = FakeClient(commands=FakeCommandsAPI([boom]))
    with pytest.raises(RuntimeError, match="bootstrap script raised"):
        p._bootstrap_sandbox_paths(client)


def test_acquire_cleans_up_and_fails_when_bootstrap_fails(monkeypatch):
    provider = _make_provider()
    fake_cls = _install_fake_sdk(monkeypatch, provider)
    client = FakeClient(
        sandbox_id="bootstrap-failure",
        commands=FakeCommandsAPI([SimpleNamespace(stdout="", stderr="permission denied", exit_code=1)]),
    )
    fake_cls.create_factory = lambda **kwargs: client

    with pytest.raises(RuntimeError, match="bootstrap") as error:
        provider.acquire("thread-1", user_id="user-1")

    assert error.value.__cause__ is not None
    assert "permission denied" in str(error.value.__cause__)
    assert client.killed is True
    assert client.closed is True
    assert provider.get("bootstrap-failure") is None


def test_acquire_rejects_falsey_bootstrap_error(monkeypatch):
    class FalseyError(RuntimeError):
        def __bool__(self) -> bool:
            return False

    provider = _make_provider()
    fake_cls = _install_fake_sdk(monkeypatch, provider)
    client = FakeClient(sandbox_id="bootstrap-failure")
    error = FalseyError("bootstrap failed")
    fake_cls.create_factory = lambda **kwargs: client
    provider._bootstrap_or_discard = MagicMock(return_value=(error, True))

    with pytest.raises(RuntimeError, match="bootstrap") as caught:
        provider.acquire("thread-1", user_id="user-1")

    assert caught.value.__cause__ is error
    assert provider.get("bootstrap-failure") is None


def test_acquire_closes_client_when_bootstrap_cleanup_kill_fails(monkeypatch):
    provider = _make_provider()
    fake_cls = _install_fake_sdk(monkeypatch, provider)
    client = FakeClient(
        sandbox_id="bootstrap-failure",
        commands=FakeCommandsAPI([SimpleNamespace(stdout="", stderr="permission denied", exit_code=1)]),
    )
    client.kill = MagicMock(side_effect=RuntimeError("sandbox already gone"))
    fake_cls.create_factory = lambda **kwargs: client

    with pytest.raises(RuntimeError, match="bootstrap"):
        provider.acquire("thread-1", user_id="user-1")

    assert client.closed is True


def test_release_unknown_sandbox_id_is_noop():
    p = _make_provider()
    p.release("nonexistent")
    assert p._warm_pool == OrderedDict()


def test_release_dead_sandbox_skips_warm_pool(monkeypatch):
    p = _make_provider()
    client = FakeClient()
    sb = _make_sandbox(client, sandbox_id="sb-dead")
    sb._dead = True
    p._sandboxes["sb-dead"] = sb
    key = p._thread_key("t1", "u1")
    p._thread_sandboxes[key] = "sb-dead"

    p.release("sb-dead")

    assert "sb-dead" not in p._warm_pool, "dead sandbox must not be parked"
    assert "sb-dead" not in p._sandboxes
    assert key not in p._thread_sandboxes
    assert client.killed is True, "release of dead sandbox must kill the remote VM"


def test_release_healthy_sandbox_parks_in_warm_pool(monkeypatch, tmp_path):
    p = _make_provider()
    _setup_paths(monkeypatch, tmp_path)
    cmds = FakeCommandsAPI([SimpleNamespace(stdout="", stderr="", exit_code=0)])
    client = FakeClient(commands=cmds)
    sb = _make_sandbox(client, sandbox_id="sb-warm-1")
    p._sandboxes["sb-warm-1"] = sb
    p._thread_sandboxes[p._thread_key("t1", "u1")] = "sb-warm-1"

    p.release("sb-warm-1")

    assert "sb-warm-1" in p._warm_pool
    seed_in_pool, _ts = p._warm_pool["sb-warm-1"]
    assert seed_in_pool == p._stable_seed("t1", "u1")
    assert client.killed is False
    assert client.timeouts_set


def test_acquire_waits_for_same_thread_release_transition(monkeypatch):
    provider = _make_provider()
    _install_fake_sdk(monkeypatch, provider)
    client = FakeClient(sandbox_id="sb-release-race")
    sandbox = _make_sandbox(client)
    provider._sandboxes[sandbox.id] = sandbox
    provider._thread_sandboxes[provider._thread_key("thread-1", "user-1")] = sandbox.id

    sync_started = threading.Event()
    allow_sync_to_finish = threading.Event()

    def blocking_sync(*_args, **_kwargs) -> None:
        sync_started.set()
        assert allow_sync_to_finish.wait(timeout=2)

    monkeypatch.setattr(provider, "_sync_outputs_to_host", blocking_sync)
    early_discovery = MagicMock(return_value="discovered-too-early")
    early_create = MagicMock(return_value="created-too-early")
    monkeypatch.setattr(provider, "_discover_remote_sandbox", early_discovery)
    monkeypatch.setattr(provider, "_create_sandbox", early_create)

    release_thread = threading.Thread(target=provider.release, args=(sandbox.id,))
    acquired: list[str] = []
    acquire_done = threading.Event()

    def acquire() -> None:
        acquired.append(provider.acquire("thread-1", user_id="user-1"))
        acquire_done.set()

    acquire_thread = threading.Thread(target=acquire)
    release_thread.start()
    assert sync_started.wait(timeout=1)
    acquire_thread.start()

    try:
        assert not acquire_done.wait(timeout=0.1), "acquire must wait while release is syncing outputs"
    finally:
        allow_sync_to_finish.set()
        release_thread.join(timeout=2)
        acquire_thread.join(timeout=2)

    assert not release_thread.is_alive()
    assert not acquire_thread.is_alive()
    assert acquired == [sandbox.id]
    early_discovery.assert_not_called()
    early_create.assert_not_called()


def test_release_skips_warm_pool_when_sync_reveals_dead_vm(monkeypatch, tmp_path):
    p = _make_provider()
    _setup_paths(monkeypatch, tmp_path)
    client = FakeClient(commands=FakeCommandsAPI([FakeCommandsAPI.GONE]))
    sb = _make_sandbox(client, sandbox_id="sb-died-during-sync")
    p._sandboxes["sb-died-during-sync"] = sb
    p._thread_sandboxes[p._thread_key("t1", "u1")] = "sb-died-during-sync"

    p.release("sb-died-during-sync")

    assert sb.is_dead is True
    assert "sb-died-during-sync" not in p._warm_pool
    assert client.killed is True


def test_shutdown_only_kills_sandboxes_owned_by_current_instance(monkeypatch):
    p = _make_provider()
    owned_client = FakeClient(sandbox_id="sb-owned")
    peer_client = FakeClient(sandbox_id="sb-peer")
    p._sandboxes = {
        "sb-owned": _make_sandbox(owned_client),
        "sb-peer": _make_sandbox(peer_client),
    }
    p._owned_sandbox_ids = {"sb-owned"}

    p.shutdown()

    assert owned_client.killed is True
    assert peer_client.killed is False
    assert peer_client.closed is True


def _setup_paths(monkeypatch, tmp_path):
    paths_mod = importlib.import_module("deerflow.config.paths")
    monkeypatch.setattr(paths_mod, "get_paths", lambda: Paths(base_dir=tmp_path), raising=False)


def test_sync_outputs_to_host_writes_new_files(monkeypatch, tmp_path):
    p = _make_provider()
    _setup_paths(monkeypatch, tmp_path)
    listing = "13\t2.000000000\t/home/user/outputs/random.pdf\x00"
    files = FakeFilesAPI(store={"/home/user/outputs/random.pdf": b"%PDF-1.4hello"})
    cmds = FakeCommandsAPI([SimpleNamespace(stdout=listing, stderr="", exit_code=0)])
    client = FakeClient(commands=cmds, files=files)
    sb = _make_sandbox(client, sandbox_id="sb-sync-1")

    p._sync_outputs_to_host(sb, thread_id="t1", user_id="u1")

    expected = Paths(base_dir=tmp_path).thread_dir("t1", user_id="u1") / "user-data" / "outputs" / "random.pdf"
    assert expected.exists()
    assert expected.read_bytes() == b"%PDF-1.4hello"


def test_sync_outputs_to_host_updates_changed_same_size_file(monkeypatch, tmp_path):
    p = _make_provider()
    _setup_paths(monkeypatch, tmp_path)
    out_dir = Paths(base_dir=tmp_path).thread_dir("t1", user_id="u1") / "user-data" / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "random.pdf"
    target.write_bytes(b"%PDF-1.4hello")
    os.utime(target, ns=(1_000_000_000, 1_000_000_000))

    listing = "13\t2.000000000\t/home/user/outputs/random.pdf\x00"
    files = FakeFilesAPI(store={"/home/user/outputs/random.pdf": b"changed-value"})
    cmds = FakeCommandsAPI([SimpleNamespace(stdout=listing, stderr="", exit_code=0)])
    client = FakeClient(commands=cmds, files=files)
    sb = _make_sandbox(client, sandbox_id="sb-sync-2")

    p._sync_outputs_to_host(sb, thread_id="t1", user_id="u1")

    assert files.read_calls, "same-size files must be checked for updates"
    assert target.read_bytes() == b"changed-value"
    assert target.stat().st_mtime_ns == 2_000_000_000


def test_sync_outputs_to_host_skips_file_when_manifest_matches(monkeypatch, tmp_path):
    p = _make_provider()
    _setup_paths(monkeypatch, tmp_path)
    out_dir = Paths(base_dir=tmp_path).thread_dir("t1", user_id="u1") / "user-data" / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "random.pdf"
    target.write_bytes(b"%PDF-1.4hello")
    os.utime(target, ns=(2_000_000_000, 2_000_000_000))

    listing = "13\t2.000000000\t/home/user/outputs/random.pdf\x00"
    files = FakeFilesAPI(store={"/home/user/outputs/random.pdf": b"%PDF-1.4hello"})
    cmds = FakeCommandsAPI(
        [
            SimpleNamespace(stdout=listing, stderr="", exit_code=0),
            SimpleNamespace(stdout=listing, stderr="", exit_code=0),
        ]
    )
    client = FakeClient(commands=cmds, files=files)
    sb = _make_sandbox(client, sandbox_id="sb-sync-unchanged")

    p._sync_outputs_to_host(sb, thread_id="t1", user_id="u1")
    files.read_calls.clear()
    p._sync_outputs_to_host(sb, thread_id="t1", user_id="u1")

    assert files.read_calls == []
    assert target.read_bytes() == b"%PDF-1.4hello"


def test_sync_outputs_to_host_uses_manifest_when_host_mtime_is_rounded(monkeypatch, tmp_path):
    p = _make_provider()
    _setup_paths(monkeypatch, tmp_path)
    paths = Paths(base_dir=tmp_path)
    thread_dir = paths.thread_dir("t1", user_id="u1")
    target = thread_dir / "user-data" / "outputs" / "random.pdf"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"%PDF-1.4hello")
    rounded_host_mtime_ns = 1_720_000_000_123_456_800
    os.utime(target, ns=(rounded_host_mtime_ns, rounded_host_mtime_ns))
    (thread_dir / ".e2b-output-sync.json").write_text(
        json.dumps(
            {
                "version": 1,
                "sandbox_id": "sb-sync-manifest",
                "files": {
                    "outputs/random.pdf": {
                        "remote_size": 13,
                        "remote_mtime_ns": 1_720_000_000_123_456_789,
                        "host_size": 13,
                        "host_mtime_ns": rounded_host_mtime_ns,
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    listing = "13\t1720000000.1234567890\t/home/user/outputs/random.pdf\x00"
    files = FakeFilesAPI(store={"/home/user/outputs/random.pdf": b"%PDF-1.4hello"})
    cmds = FakeCommandsAPI([SimpleNamespace(stdout=listing, stderr="", exit_code=0)])
    client = FakeClient(sandbox_id="sb-sync-manifest", commands=cmds, files=files)
    sb = _make_sandbox(client, sandbox_id="sb-sync-manifest")

    p._sync_outputs_to_host(sb, thread_id="t1", user_id="u1")

    assert files.read_calls == []


def test_sync_outputs_to_host_records_variable_precision_remote_mtime(monkeypatch, tmp_path):
    p = _make_provider()
    _setup_paths(monkeypatch, tmp_path)
    listing = "13\t1720000000.1234567890\t/home/user/outputs/random.pdf\x00"
    files = FakeFilesAPI(store={"/home/user/outputs/random.pdf": b"%PDF-1.4hello"})
    cmds = FakeCommandsAPI([SimpleNamespace(stdout=listing, stderr="", exit_code=0)])
    client = FakeClient(commands=cmds, files=files)
    sb = _make_sandbox(client, sandbox_id="sb-sync-precision")

    p._sync_outputs_to_host(sb, thread_id="t1", user_id="u1")

    manifest_path = Paths(base_dir=tmp_path).thread_dir("t1", user_id="u1") / ".e2b-output-sync.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["files"]["outputs/random.pdf"]["remote_mtime_ns"] == 1_720_000_000_123_456_789


def test_sync_outputs_to_host_removes_manifest_entries_for_deleted_files(monkeypatch, tmp_path):
    p = _make_provider()
    _setup_paths(monkeypatch, tmp_path)
    paths = Paths(base_dir=tmp_path)
    thread_dir = paths.thread_dir("t1", user_id="u1")
    thread_dir.mkdir(parents=True, exist_ok=True)
    (thread_dir / ".e2b-output-sync.json").write_text(
        json.dumps(
            {
                "version": 1,
                "sandbox_id": "sb-sync-cleanup",
                "files": {
                    "outputs/deleted.txt": {
                        "remote_size": 3,
                        "remote_mtime_ns": 1,
                        "host_size": 3,
                        "host_mtime_ns": 1,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    listing = "5\t1720000000.1234567890\t/home/user/outputs/live.txt\x00"
    files = FakeFilesAPI(store={"/home/user/outputs/live.txt": b"alive"})
    cmds = FakeCommandsAPI([SimpleNamespace(stdout=listing, stderr="", exit_code=0)])
    client = FakeClient(commands=cmds, files=files)
    sb = _make_sandbox(client, sandbox_id="sb-sync-cleanup")

    p._sync_outputs_to_host(sb, thread_id="t1", user_id="u1")

    manifest = json.loads((thread_dir / ".e2b-output-sync.json").read_text(encoding="utf-8"))
    assert set(manifest["files"]) == {"outputs/live.txt"}


def test_sync_outputs_to_host_preserves_trailing_space_in_filename(monkeypatch, tmp_path):
    p = _make_provider()
    _setup_paths(monkeypatch, tmp_path)
    # "report " (trailing space) is a legal Linux filename; the NUL-delimited
    # listing preserves it, but a .strip() on each entry would truncate it.
    listing = "5\t2.000000000\t/home/user/outputs/report \x00"
    files = FakeFilesAPI(store={"/home/user/outputs/report ": b"hello"})
    cmds = FakeCommandsAPI([SimpleNamespace(stdout=listing, stderr="", exit_code=0)])
    client = FakeClient(commands=cmds, files=files)
    sb = _make_sandbox(client, sandbox_id="sb-sync-space")

    p._sync_outputs_to_host(sb, thread_id="t1", user_id="u1")

    expected = Paths(base_dir=tmp_path).thread_dir("t1", user_id="u1") / "user-data" / "outputs" / "report "
    assert expected.exists()
    assert expected.read_bytes() == b"hello"


def test_sync_outputs_to_host_skips_mtime_restoration_on_overflow(monkeypatch, tmp_path):
    p = _make_provider()
    _setup_paths(monkeypatch, tmp_path)
    # os.utime raises OverflowError (not OSError) when the ns value is out of
    # range; the exact threshold is platform-dependent (macOS clamps, Linux
    # raises), so force the failure deterministically and assert the file is
    # still written and the manifest still updated.
    listing = "5\t1720000000.1234567890\t/home/user/outputs/far-future.txt\x00"
    files = FakeFilesAPI(store={"/home/user/outputs/far-future.txt": b"hello"})
    cmds = FakeCommandsAPI([SimpleNamespace(stdout=listing, stderr="", exit_code=0)])
    client = FakeClient(commands=cmds, files=files)
    sb = _make_sandbox(client, sandbox_id="sb-sync-overflow")

    e2b_provider_mod = importlib.import_module("deerflow.community.e2b_sandbox.e2b_sandbox_provider")

    def _raise_overflow(path, times=None, ns=None):
        raise OverflowError("timestamp out of range")

    monkeypatch.setattr(e2b_provider_mod.os, "utime", _raise_overflow)

    p._sync_outputs_to_host(sb, thread_id="t1", user_id="u1")

    paths = Paths(base_dir=tmp_path).thread_dir("t1", user_id="u1")
    target = paths / "user-data" / "outputs" / "far-future.txt"
    assert target.exists()
    assert target.read_bytes() == b"hello"
    manifest = json.loads((paths / ".e2b-output-sync.json").read_text(encoding="utf-8"))
    assert manifest["files"]["outputs/far-future.txt"]["remote_size"] == 5


def test_sync_outputs_to_host_discards_manifest_from_another_sandbox(monkeypatch, tmp_path):
    p = _make_provider()
    _setup_paths(monkeypatch, tmp_path)
    paths = Paths(base_dir=tmp_path)
    thread_dir = paths.thread_dir("t1", user_id="u1")
    target = thread_dir / "user-data" / "outputs" / "random.pdf"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"%PDF-1.4hello")
    remote_mtime_ns = 1_720_000_000_123_456_789
    os.utime(target, ns=(remote_mtime_ns, remote_mtime_ns))
    (thread_dir / ".e2b-output-sync.json").write_text(
        json.dumps(
            {
                "version": 1,
                "sandbox_id": "sb-old",
                "files": {
                    "outputs/random.pdf": {
                        "remote_size": 13,
                        "remote_mtime_ns": remote_mtime_ns,
                        "host_size": 13,
                        "host_mtime_ns": remote_mtime_ns,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    listing = "13\t1720000000.1234567890\t/home/user/outputs/random.pdf\x00"
    files = FakeFilesAPI(store={"/home/user/outputs/random.pdf": b"%PDF-1.4hello"})
    cmds = FakeCommandsAPI([SimpleNamespace(stdout=listing, stderr="", exit_code=0)])
    client = FakeClient(sandbox_id="sb-new", commands=cmds, files=files)
    sb = _make_sandbox(client, sandbox_id="sb-new")

    p._sync_outputs_to_host(sb, thread_id="t1", user_id="u1")

    assert files.read_calls
    manifest = json.loads((thread_dir / ".e2b-output-sync.json").read_text(encoding="utf-8"))
    assert manifest["sandbox_id"] == "sb-new"


def test_sync_outputs_to_host_resets_empty_manifest_for_new_sandbox(monkeypatch, tmp_path):
    p = _make_provider()
    _setup_paths(monkeypatch, tmp_path)
    thread_dir = Paths(base_dir=tmp_path).thread_dir("t1", user_id="u1")
    thread_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = thread_dir / ".e2b-output-sync.json"
    manifest_path.write_text(
        json.dumps(
            {
                "version": 1,
                "sandbox_id": "sb-old",
                "files": {
                    "outputs/stale.txt": {
                        "remote_size": 1,
                        "remote_mtime_ns": 1,
                        "host_size": 1,
                        "host_mtime_ns": 1,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    client = FakeClient(
        sandbox_id="sb-new",
        commands=FakeCommandsAPI([SimpleNamespace(stdout="", stderr="", exit_code=0)]),
    )
    sb = _make_sandbox(client, sandbox_id="sb-new")

    p._sync_outputs_to_host(sb, thread_id="t1", user_id="u1")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest == {"version": 1, "sandbox_id": "sb-new", "files": {}}


def test_sync_outputs_to_host_restores_externally_modified_file(monkeypatch, tmp_path):
    p = _make_provider()
    _setup_paths(monkeypatch, tmp_path)
    listing = "13\t1720000000.1234567890\t/home/user/outputs/random.pdf\x00"
    files = FakeFilesAPI(store={"/home/user/outputs/random.pdf": b"%PDF-1.4hello"})
    cmds = FakeCommandsAPI(
        [
            SimpleNamespace(stdout=listing, stderr="", exit_code=0),
            SimpleNamespace(stdout=listing, stderr="", exit_code=0),
        ]
    )
    client = FakeClient(commands=cmds, files=files)
    sb = _make_sandbox(client, sandbox_id="sb-sync-local-change")

    p._sync_outputs_to_host(sb, thread_id="t1", user_id="u1")
    target = Paths(base_dir=tmp_path).thread_dir("t1", user_id="u1") / "user-data" / "outputs" / "random.pdf"
    target.write_bytes(b"changed-value")
    os.utime(target, ns=(1_720_000_001_000_000_000, 1_720_000_001_000_000_000))

    p._sync_outputs_to_host(sb, thread_id="t1", user_id="u1")

    assert len(files.read_calls) == 2
    assert target.read_bytes() == b"%PDF-1.4hello"


def test_sync_outputs_to_host_marks_dead_on_sandbox_gone(monkeypatch, tmp_path):
    p = _make_provider()
    _setup_paths(monkeypatch, tmp_path)
    cmds = FakeCommandsAPI([FakeCommandsAPI.GONE])
    client = FakeClient(commands=cmds)
    sb = _make_sandbox(client, sandbox_id="sb-sync-dead")

    p._sync_outputs_to_host(sb, thread_id="t1", user_id="u1")

    assert sb.is_dead is True


def test_sync_outputs_to_host_uses_virtual_path_for_download(monkeypatch, tmp_path):
    """`download_file` requires paths under ``/mnt/user-data``; the sync
    helper must translate the physical /home/user/... back to the virtual
    prefix before calling it."""
    p = _make_provider()
    _setup_paths(monkeypatch, tmp_path)

    listing = "5\t2.000000000\t/home/user/outputs/sub/x.txt\x00"
    files = FakeFilesAPI(store={"/home/user/outputs/sub/x.txt": b"hello"})
    cmds = FakeCommandsAPI([SimpleNamespace(stdout=listing, stderr="", exit_code=0)])
    client = FakeClient(commands=cmds, files=files)
    sb = _make_sandbox(client, sandbox_id="sb-sync-3")

    p._sync_outputs_to_host(sb, thread_id="t1", user_id="u1")

    read_paths = [r[0] for r in files.read_calls]
    assert "/home/user/outputs/sub/x.txt" in read_paths


def test_sync_outputs_to_host_is_noop_when_client_closed():
    p = _make_provider()
    sb = _make_sandbox(FakeClient(), sandbox_id="sb-x")
    sb.close()
    p._sync_outputs_to_host(sb, thread_id="t1", user_id="u1")


def test_read_file_supports_bounded_ranges():
    files = FakeFilesAPI(
        store={"/home/user/workspace/range.txt": b"line 1\nline 2\nline 3\nline 4\nline 5"},
    )
    client = FakeClient(files=files)
    sb = _make_sandbox(client, sandbox_id="sb-read-range")

    assert sb.read_file("/mnt/user-data/workspace/range.txt") == "line 1\nline 2\nline 3\nline 4\nline 5"
    assert sb.read_file("/mnt/user-data/workspace/range.txt", start_line=2, end_line=4) == "line 2\nline 3\nline 4"
    assert sb.read_file("/mnt/user-data/workspace/range.txt", start_line=4) == "line 4\nline 5"
    assert sb.read_file("/mnt/user-data/workspace/range.txt", end_line=2) == "line 1\nline 2"

    resolved_path = "/home/user/workspace/range.txt"
    assert all(path == resolved_path for path, _fmt in files.read_calls), files.read_calls


def test_read_file_returns_error_for_missing_file():
    client = FakeClient(files=FakeFilesAPI())
    sb = _make_sandbox(client, sandbox_id="sb-read-missing")

    assert sb.read_file("/mnt/user-data/workspace/missing.txt").startswith("Error:")


def _outputs_dir(tmp_path):
    return Paths(base_dir=tmp_path).thread_dir("t1", user_id="u1") / "user-data" / "outputs"


def test_sync_outputs_to_host_stops_at_file_count_cap(monkeypatch, tmp_path):
    """A pass downloads at most ``_MAX_SYNC_FILES`` artefacts, deferring the rest."""
    p = _make_provider()
    p._MAX_SYNC_FILES = 2
    _setup_paths(monkeypatch, tmp_path)

    names = ["a.txt", "b.txt", "c.txt", "d.txt"]
    listing = "".join(f"5\t2.000000000\t/home/user/outputs/{n}\x00" for n in names)
    files = FakeFilesAPI(store={f"/home/user/outputs/{n}": b"hello" for n in names})
    cmds = FakeCommandsAPI([SimpleNamespace(stdout=listing, stderr="", exit_code=0)])
    sb = _make_sandbox(FakeClient(commands=cmds, files=files), sandbox_id="sb-cap-files")

    p._sync_outputs_to_host(sb, thread_id="t1", user_id="u1")

    out_dir = _outputs_dir(tmp_path)
    written = sorted(f.name for f in out_dir.iterdir()) if out_dir.exists() else []
    assert written == ["a.txt", "b.txt"]
    assert len(files.read_calls) == 2


def test_sync_outputs_to_host_stops_at_total_byte_budget(monkeypatch, tmp_path):
    """A pass stops before the cumulative download exceeds ``_MAX_SYNC_TOTAL_BYTES``."""
    p = _make_provider()
    p._MAX_SYNC_TOTAL_BYTES = 25  # fits two 10-byte files, not a third
    _setup_paths(monkeypatch, tmp_path)

    names = ["a.txt", "b.txt", "c.txt"]
    listing = "".join(f"10\t2.000000000\t/home/user/outputs/{n}\x00" for n in names)
    files = FakeFilesAPI(store={f"/home/user/outputs/{n}": b"0123456789" for n in names})
    cmds = FakeCommandsAPI([SimpleNamespace(stdout=listing, stderr="", exit_code=0)])
    sb = _make_sandbox(FakeClient(commands=cmds, files=files), sandbox_id="sb-cap-bytes")

    p._sync_outputs_to_host(sb, thread_id="t1", user_id="u1")

    out_dir = _outputs_dir(tmp_path)
    written = sorted(f.name for f in out_dir.iterdir()) if out_dir.exists() else []
    assert written == ["a.txt", "b.txt"]
    assert len(files.read_calls) == 2


def test_sync_outputs_to_host_stops_at_deadline(monkeypatch, tmp_path):
    """A zero wall-clock budget aborts the pass before any download."""
    p = _make_provider()
    p._SYNC_DEADLINE_SECONDS = 0  # monotonic() >= deadline on the first entry
    _setup_paths(monkeypatch, tmp_path)

    listing = "5\t2.000000000\t/home/user/outputs/a.txt\x00"
    files = FakeFilesAPI(store={"/home/user/outputs/a.txt": b"hello"})
    cmds = FakeCommandsAPI([SimpleNamespace(stdout=listing, stderr="", exit_code=0)])
    sb = _make_sandbox(FakeClient(commands=cmds, files=files), sandbox_id="sb-cap-deadline")

    p._sync_outputs_to_host(sb, thread_id="t1", user_id="u1")

    out_dir = _outputs_dir(tmp_path)
    assert not out_dir.exists() or list(out_dir.iterdir()) == []
    assert files.read_calls == []


def test_sync_outputs_to_host_truncated_pass_preserves_stale_manifest(monkeypatch, tmp_path):
    """A capped pass must not prune manifest entries it never got to inspect."""
    p = _make_provider()
    p._MAX_SYNC_FILES = 1
    _setup_paths(monkeypatch, tmp_path)
    thread_dir = Paths(base_dir=tmp_path).thread_dir("t1", user_id="u1")
    thread_dir.mkdir(parents=True, exist_ok=True)
    # A prior-sync entry for a file absent from this listing. A complete pass
    # would prune it as deleted; a truncated pass must leave it for next time.
    (thread_dir / ".e2b-output-sync.json").write_text(
        json.dumps(
            {
                "version": 1,
                "sandbox_id": "sb-trunc",
                "files": {"outputs/kept.txt": {"remote_size": 3, "remote_mtime_ns": 1, "host_size": 3, "host_mtime_ns": 1}},
            }
        ),
        encoding="utf-8",
    )
    names = ["a.txt", "b.txt", "c.txt"]
    listing = "".join(f"5\t2.000000000\t/home/user/outputs/{n}\x00" for n in names)
    files = FakeFilesAPI(store={f"/home/user/outputs/{n}": b"hello" for n in names})
    cmds = FakeCommandsAPI([SimpleNamespace(stdout=listing, stderr="", exit_code=0)])
    sb = _make_sandbox(FakeClient(sandbox_id="sb-trunc", commands=cmds, files=files), sandbox_id="sb-trunc")

    p._sync_outputs_to_host(sb, thread_id="t1", user_id="u1")

    manifest = json.loads((thread_dir / ".e2b-output-sync.json").read_text(encoding="utf-8"))
    assert "outputs/kept.txt" in manifest["files"]  # un-reached entry survives
    assert "outputs/a.txt" in manifest["files"]  # the one download is recorded
    assert len(files.read_calls) == 1


def test_sync_outputs_to_host_converges_across_passes(monkeypatch, tmp_path):
    """The deferred tail drains over successive passes without re-downloading
    already-synced files.

    The budget check sits *below* the manifest-skip path, so a file synced in
    an earlier pass is skipped before it can consume the cap on later passes.
    That is what lets ``c``/``d`` finish instead of ``a``/``b`` being re-fetched
    every release forever. A refactor that moved the budget check above the skip
    would still pass the single-pass truncation tests but fail this one.
    """
    p = _make_provider()
    p._MAX_SYNC_FILES = 2
    _setup_paths(monkeypatch, tmp_path)

    names = ["a.txt", "b.txt", "c.txt", "d.txt"]
    listing = "".join(f"5\t2.000000000\t/home/user/outputs/{n}\x00" for n in names)
    files = FakeFilesAPI(store={f"/home/user/outputs/{n}": b"hello" for n in names})
    # One listing per pass; both passes share the same host tree, manifest and
    # files API (so downloads accumulate and the manifest carries over).
    cmds = FakeCommandsAPI(
        [
            SimpleNamespace(stdout=listing, stderr="", exit_code=0),
            SimpleNamespace(stdout=listing, stderr="", exit_code=0),
        ]
    )
    sb = _make_sandbox(FakeClient(commands=cmds, files=files), sandbox_id="sb-converge")
    out_dir = _outputs_dir(tmp_path)

    # Pass 1: the file cap stops the pass after a, b.
    p._sync_outputs_to_host(sb, thread_id="t1", user_id="u1")
    assert sorted(f.name for f in out_dir.iterdir()) == ["a.txt", "b.txt"]
    assert [r[0] for r in files.read_calls] == [
        "/home/user/outputs/a.txt",
        "/home/user/outputs/b.txt",
    ]

    # Pass 2: a, b are manifest hits skipped before the budget check, so the cap
    # is spent draining the deferred tail c, d rather than re-downloading a, b.
    p._sync_outputs_to_host(sb, thread_id="t1", user_id="u1")
    assert sorted(f.name for f in out_dir.iterdir()) == ["a.txt", "b.txt", "c.txt", "d.txt"]
    assert [r[0] for r in files.read_calls] == [
        "/home/user/outputs/a.txt",
        "/home/user/outputs/b.txt",
        "/home/user/outputs/c.txt",
        "/home/user/outputs/d.txt",
    ]


def test_download_file_uses_streaming_read_and_returns_full_bytes():
    payload = b"A" * (128 * 1024)  # 128 KiB — well below the cap.
    files = FakeFilesAPI(store={"/home/user/outputs/small.bin": payload})
    client = FakeClient(files=files)
    sb = _make_sandbox(client, sandbox_id="sb-stream-1")

    data = sb.download_file("/mnt/user-data/outputs/small.bin")

    assert data == payload
    formats_used = [fmt for _p, fmt in files.read_calls]
    assert "stream" in formats_used, f"expected download_file to invoke read(format='stream'), got {formats_used!r}"
    assert files.streams, "download_file must actually consume a stream"
    assert files.streams[-1].closed, "stream must be closed after successful read"


def test_download_file_streaming_raises_efbig_before_full_buffering():
    import errno as _errno

    from deerflow.community.e2b_sandbox import e2b_sandbox as e2b_sb_mod

    cap = e2b_sb_mod._MAX_DOWNLOAD_SIZE

    class _OversizeStream:
        def __init__(self) -> None:
            self.bytes_yielded = 0
            self.closed = False
            self._chunk = b"X" * (1024 * 1024)  # 1 MiB per chunk

        def __iter__(self):
            return self

        def __next__(self) -> bytes:
            if self.closed:
                raise StopIteration
            # Yield up to ``cap + a bit`` — the caller must abort before
            # actually buffering all of that in memory.
            if self.bytes_yielded > cap + 4 * len(self._chunk):
                raise StopIteration
            self.bytes_yielded += len(self._chunk)
            return self._chunk

        def close(self) -> None:
            self.closed = True

    stream = _OversizeStream()

    class _StubFilesAPI:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str | None]] = []

        def read(self, path: str, *, format: str | None = None):
            self.calls.append((path, format))
            assert format == "stream", "provider must request a streamed download"
            return stream

    files = _StubFilesAPI()
    client = FakeClient(files=files)  # type: ignore[arg-type]
    sb = _make_sandbox(client, sandbox_id="sb-stream-oversize")

    try:
        sb.download_file("/mnt/user-data/outputs/huge.bin")
    except OSError as exc:
        assert exc.errno == _errno.EFBIG, f"expected EFBIG, got errno={exc.errno!r} ({exc})"
    else:  # pragma: no cover - defensive
        raise AssertionError("download_file must raise OSError(EFBIG) on oversize stream")

    assert stream.closed is True, "stream must be closed on abort so the pooled connection is released"
    assert stream.bytes_yielded <= cap + 2 * 1024 * 1024, f"aborted too late: yielded={stream.bytes_yielded} vs cap={cap}"


def test_download_file_falls_back_to_buffered_read_for_legacy_sdk():

    class _LegacyFilesAPI:
        def __init__(self, data: bytes) -> None:
            self._data = data
            self.calls: list[tuple[str, str | None]] = []

        def read(self, path: str, *, format: str | None = None):
            self.calls.append((path, format))
            if format == "stream":
                raise TypeError("format='stream' unsupported")
            if format == "bytes":
                return self._data
            return self._data.decode("utf-8", errors="replace")

    files = _LegacyFilesAPI(b"legacy-payload")
    client = FakeClient(files=files)  # type: ignore[arg-type]
    sb = _make_sandbox(client, sandbox_id="sb-legacy")

    data = sb.download_file("/mnt/user-data/outputs/legacy.bin")
    assert data == b"legacy-payload"
    formats_used = [fmt for _p, fmt in files.calls]
    assert formats_used == ["stream", "bytes"], f"expected stream then bytes fallback, got {formats_used!r}"


def test_sync_outputs_to_host_skips_oversize_files(monkeypatch, tmp_path):
    from deerflow.community.e2b_sandbox import e2b_sandbox as e2b_sb_mod

    p = _make_provider()
    _setup_paths(monkeypatch, tmp_path)

    oversize = e2b_sb_mod._MAX_DOWNLOAD_SIZE + 1
    listing = f"{oversize}\t2.000000000\t/home/user/outputs/huge.bin\x00"
    files = FakeFilesAPI()  # no store entry: any read attempt would raise
    cmds = FakeCommandsAPI([SimpleNamespace(stdout=listing, stderr="", exit_code=0)])
    client = FakeClient(commands=cmds, files=files)
    sb = _make_sandbox(client, sandbox_id="sb-sync-oversize")

    p._sync_outputs_to_host(sb, thread_id="t1", user_id="u1")

    assert files.read_calls == [], "oversize files must be skipped without invoking download_file"
    host_target = Paths(base_dir=tmp_path).thread_dir("t1", user_id="u1") / "user-data" / "outputs" / "huge.bin"
    assert not host_target.exists(), "no oversize artefact must be written to host"


# ──────────────────────────────────────────────────────────────────────────────
# grep() directory-scoped glob filtering
#
# Real GNU grep's ``--include=PATTERN`` matches by basename only, at any
# depth -- it cannot express the directory-scoping portion of a pattern like
# ``src/*.js``. These tests can't invoke a real grep binary (the command
# runs remotely inside the e2b VM via the mocked ``client.commands.run``), so
# they instead supply the raw stdout a real broadened ``--include=*.js``
# grep would actually return (matches from every directory, not just the
# intended one) and assert ``E2BSandbox.grep`` narrows it down to the
# caller's real directory scope via ``path_matches`` -- the same helper
# ``glob()`` already uses -- exactly as verified empirically against a real
# GNU grep binary during development of this fix.
# ──────────────────────────────────────────────────────────────────────────────


def test_grep_scoped_glob_excludes_unrelated_directory_matches():
    """Regression: grep(glob="src/*.js") must not leak matches from sibling
    directories that merely share the file extension."""
    raw_stdout = "/home/user/workspace/other_dir/unrelated.js:1:console.log('needle in other_dir');\n/home/user/workspace/src/app.js:1:console.log('needle in src');\n"
    client = FakeClient(commands=FakeCommandsAPI([SimpleNamespace(stdout=raw_stdout, stderr="", exit_code=0)]))
    sb = _make_sandbox(client)

    matches, truncated = sb.grep("/mnt/user-data/workspace", "needle", glob="src/*.js")

    paths = [m.path for m in matches]
    assert paths == ["/home/user/workspace/src/app.js"]
    assert "/home/user/workspace/other_dir/unrelated.js" not in paths
    assert truncated is False


def test_grep_plain_glob_matches_files_in_any_directory():
    """No regression: a plain non-scoped glob (no ``/`` in the pattern) must
    keep matching files at any depth, same as before the directory-scoping
    fix."""
    raw_stdout = "/home/user/workspace/other_dir/deep/mod.py:1:needle in a deeply nested file\n/home/user/workspace/src/app.py:1:needle in a python file too\n"
    client = FakeClient(commands=FakeCommandsAPI([SimpleNamespace(stdout=raw_stdout, stderr="", exit_code=0)]))
    sb = _make_sandbox(client)

    matches, truncated = sb.grep("/mnt/user-data/workspace", "needle", glob="*.py")

    paths = {m.path for m in matches}
    assert paths == {
        "/home/user/workspace/other_dir/deep/mod.py",
        "/home/user/workspace/src/app.py",
    }
    assert truncated is False


def test_grep_scoped_glob_still_passes_coarse_include_flag():
    """The coarse ``--include=<basename>`` pre-filter is kept as a perf
    optimization (it narrows what grep has to search) even though it can't
    express directory scoping by itself -- the real scoping enforcement
    happens in the post-filter, not by dropping ``--include``."""
    client = FakeClient(commands=FakeCommandsAPI([SimpleNamespace(stdout="", stderr="", exit_code=0)]))
    sb = _make_sandbox(client)

    sb.grep("/mnt/user-data/workspace", "needle", glob="src/*.js")

    assert any("--include=*.js" in cmd for cmd in client.commands.calls)


def test_grep_without_glob_is_unaffected():
    """No regression: omitting ``glob`` entirely must return every match
    with no path-based post-filtering."""
    raw_stdout = "/home/user/workspace/anywhere/file.txt:3:needle here\n"
    client = FakeClient(commands=FakeCommandsAPI([SimpleNamespace(stdout=raw_stdout, stderr="", exit_code=0)]))
    sb = _make_sandbox(client)

    matches, truncated = sb.grep("/mnt/user-data/workspace", "needle")

    assert [m.path for m in matches] == ["/home/user/workspace/anywhere/file.txt"]
    assert truncated is False


def test_grep_single_file_path_with_matching_glob():
    """A basename glob must also apply when the search root is one file."""
    raw_stdout = "/home/user/uploads/report.md:2:needle here\n"
    client = FakeClient(commands=FakeCommandsAPI([SimpleNamespace(stdout=raw_stdout, stderr="", exit_code=0)]))
    sb = _make_sandbox(client)

    matches, truncated = sb.grep("/mnt/user-data/uploads/report.md", "needle", glob="*.md")

    assert [m.path for m in matches] == ["/home/user/uploads/report.md"]
    assert truncated is False


# Capacity enforcement tests (#4339)


def test_deployment_capacity_reserves_commits_and_rejects_globally(monkeypatch) -> None:
    gateway_a = _make_provider(replicas=1, overflow_policy="reject")
    gateway_b = _make_provider(replicas=1, overflow_policy="reject")
    store = _install_shared_deployment_capacity(
        gateway_a,
        gateway_b,
        reserve_results=[ReserveStatus.GRANTED, ReserveStatus.FULL],
    )
    sdk_a = _install_fake_sdk(monkeypatch, gateway_a)
    sdk_b = FakeSandboxClass()
    monkeypatch.setattr(gateway_b, "_get_sandbox_cls", lambda: sdk_b)

    sandbox_id = gateway_a.acquire("thread-a", user_id="user-a")
    with pytest.raises(SandboxCapacityExceededError):
        gateway_b.acquire("thread-b", user_id="user-b")

    metadata = sdk_a.create_calls[0]["metadata"]
    assert metadata["deer_flow_capacity_ledger"] == store.key
    assert metadata["deer_flow_capacity_reservation"]
    store.track.assert_called_once_with(
        sandbox_id,
        reservation_token=metadata["deer_flow_capacity_reservation"],
    )
    assert len(sdk_a.create_calls) == 1
    assert sdk_b.create_calls == []
    assert store.reserve.call_count == 2


def test_ambiguous_create_failure_retains_deployment_reservation(monkeypatch) -> None:
    provider = _make_provider(replicas=1, overflow_policy="reject")
    store = _install_shared_deployment_capacity(provider)
    sdk = _install_fake_sdk(monkeypatch, provider)
    sdk.create_factory = lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("control-plane timeout"))

    with pytest.raises(RuntimeError, match="control-plane timeout"):
        provider.acquire("thread-a", user_id="user-a")

    assert provider._reserved_slots == 0
    store.reserve.assert_called_once()
    store.track.assert_not_called()
    store.release.assert_not_called()


def test_discovery_uses_sdk_query_and_tracks_without_reserving(monkeypatch) -> None:
    provider = _make_provider(replicas=1, overflow_policy="reject")
    store = _install_shared_deployment_capacity(provider)
    sdk = _install_fake_sdk(monkeypatch, provider)
    entry = SimpleNamespace(
        sandbox_id="sandbox-existing",
        metadata={
            "deer_flow_provider": "e2b_sandbox_provider",
            "deer_flow_user": "user-a",
            "deer_flow_thread": "thread-a",
            "deer_flow_skills_root": "/mnt/skills",
            "deer_flow_capacity_ledger": store.key,
        },
    )
    expected_query = {
        key: entry.metadata[key]
        for key in (
            "deer_flow_provider",
            "deer_flow_user",
            "deer_flow_thread",
            "deer_flow_skills_root",
        )
    }
    sdk.list_return = SimpleNamespace(
        has_next=False,
        next_items=lambda: [entry] if sdk.list_calls[-1]["query"].metadata == expected_query else [],
    )
    assert provider.acquire("thread-a", user_id="user-a") == entry.sandbox_id
    assert sdk.create_calls == []
    store.reserve.assert_not_called()
    store.track.assert_called_once_with(entry.sandbox_id, reservation_token=None)


def test_reconciliation_repairs_crash_and_uses_safe_reservation_age(monkeypatch) -> None:
    provider = _make_provider(replicas=1, overflow_policy="reject")
    provider._ownership_config.renewal_interval_seconds = 1.0
    provider._ownership_config.ttl_multiplier = 2.0
    provider._config["reconciliation_grace_seconds"] = 0.0
    store = _install_shared_deployment_capacity(provider)
    sdk = _install_fake_sdk(monkeypatch, provider)
    sdk.list_return = [
        {
            "sandbox_id": "sandbox-existing",
            "metadata": {
                "deer_flow_provider": "e2b_sandbox_provider",
                "deer_flow_capacity_ledger": store.key,
                "deer_flow_capacity_reservation": "reservation-crashed",
            },
        },
        {
            "sandbox_id": "sandbox-other-deployment",
            "metadata": {
                "deer_flow_provider": "e2b_sandbox_provider",
                "deer_flow_capacity_ledger": "deerflow:other:e2b-capacity",
            },
        },
    ]

    stats = provider._reconcile_remote_sandboxes(now=100.0)
    args = store.reconcile.call_args.kwargs
    assert stats.discovered == 1
    assert args["remote_sandboxes"] == {"sandbox-existing": "reservation-crashed"}
    assert args["complete"] is True
    assert args["reservation_max_age_ms"] == 120_000


def test_failed_inventory_and_redis_error_both_prevent_create(monkeypatch) -> None:
    provider = _make_provider(replicas=1, overflow_policy="reject")
    store = _install_shared_deployment_capacity(
        provider,
        reserve_results=[ReserveStatus.NOT_READY],
    )
    sdk = _install_fake_sdk(monkeypatch, provider)
    sdk.list = MagicMock(side_effect=RuntimeError("E2B unavailable"))

    provider._reconcile_remote_sandboxes(now=100.0)

    reconcile_args = store.reconcile.call_args.kwargs
    assert reconcile_args["complete"] is False
    assert reconcile_args["remote_sandboxes"] == {}
    with pytest.raises(SandboxCapacityExceededError):
        provider._create_sandbox("thread-a", user_id="user-a")
    store.reserve.side_effect = CapacityBackendError("Redis unavailable")
    with pytest.raises(SandboxCapacityExceededError) as error:
        provider._create_sandbox("thread-a", user_id="user-a")

    assert error.value.reason == "capacity_backend"
    assert sdk.create_calls == []
    assert provider._reserved_slots == 0


def test_capacity_reject_policy_raises_when_full(monkeypatch):
    """With overflow_policy='reject' and replicas=1, a second acquire raises
    SandboxCapacityExceededError instead of creating an unbounded sandbox."""
    p = _make_provider(replicas=1, overflow_policy="reject")
    fake_cls = _install_fake_sdk(monkeypatch, p)

    sid1 = p.acquire("t1", user_id="u1")
    assert sid1 is not None
    assert len(p._sandboxes) == 1

    with pytest.raises(SandboxCapacityExceededError) as exc_info:
        p.acquire("t2", user_id="u2")
    assert exc_info.value.replicas == 1
    assert exc_info.value.retry_after_seconds > 0
    assert exc_info.value.details["code"] == "SANDBOX_CAPACITY_EXCEEDED"
    assert exc_info.value.details["retryable"] is True
    assert len(fake_cls.create_calls) == 1  # no second create


def test_capacity_reject_frees_slot_on_release(monkeypatch):
    """Releasing a sandbox frees a capacity slot so the next acquire succeeds."""
    p = _make_provider(replicas=1, overflow_policy="reject")
    _install_fake_sdk(monkeypatch, p)

    sid1 = p.acquire("t1", user_id="u1")
    p.release(sid1)

    sid2 = p.acquire("t2", user_id="u2")
    assert sid2 is not None
    assert sid2 != sid1


def test_capacity_reject_evicts_other_thread_warm_entry_before_create(monkeypatch):
    """Reject policy can evict one warm VM before it rejects new capacity."""
    p = _make_provider(replicas=3, overflow_policy="reject")
    store = _install_shared_deployment_capacity(
        p,
        reserve_results=[ReserveStatus.GRANTED, ReserveStatus.FULL, ReserveStatus.GRANTED],
    )
    fake_cls = _install_fake_sdk(monkeypatch, p)

    sid1 = p.acquire("t1", user_id="u1")
    p.release(sid1)
    assert len(p._warm_pool) == 1

    sid2 = p.acquire("t2", user_id="u2")

    assert sid2 != sid1
    assert len(p._warm_pool) == 0
    assert len(fake_cls.create_calls) == 2
    store.release.assert_called_once_with(sid1)


def test_capacity_wait_policy_times_out(monkeypatch):
    """With overflow_policy='wait' and a short timeout, the provider raises
    SandboxCapacityExceededError when no slot frees up."""
    p = _make_provider(replicas=1, overflow_policy="wait", acquire_timeout=1)
    _install_fake_sdk(monkeypatch, p)

    p.acquire("t1", user_id="u1")

    with pytest.raises(SandboxCapacityExceededError) as exc_info:
        p.acquire("t2", user_id="u2")
    assert "Timed out" in str(exc_info.value)


def test_capacity_wait_policy_succeeds_when_slot_freed(monkeypatch):
    """A blocked waiter proceeds once a slot is freed by another thread."""
    p = _make_provider(replicas=1, overflow_policy="wait", acquire_timeout=10)
    _install_fake_sdk(monkeypatch, p)

    sid1 = p.acquire("t1", user_id="u1")

    results: list[str | Exception] = []
    barrier = threading.Barrier(2, timeout=5)
    acquired = threading.Event()

    def waiter() -> None:
        barrier.wait()
        try:
            results.append(p.acquire("t2", user_id="u2"))
        except Exception as e:
            results.append(e)
        acquired.set()

    t = threading.Thread(target=waiter)
    t.start()
    barrier.wait()

    # Give the waiter a moment to block on the condition.
    time.sleep(0.2)

    p.release(sid1)
    t.join(timeout=5)

    assert not t.is_alive(), "waiter thread must complete"
    assert len(results) == 1
    assert isinstance(results[0], str)


def test_capacity_burst_policy_allows_limited_overflow(monkeypatch):
    """With overflow_policy='burst' and burst_limit=2, the provider allows
    up to replicas + burst_limit sandboxes."""
    p = _make_provider(replicas=1, overflow_policy="burst", burst_limit=2)
    _install_fake_sdk(monkeypatch, p)

    sids = []
    for i in range(3):  # replicas(1) + burst(2) = 3
        sids.append(p.acquire(f"t{i}", user_id=f"u{i}"))
    assert len(sids) == 3
    assert len(p._sandboxes) == 3

    with pytest.raises(SandboxCapacityExceededError):
        p.acquire("t-extra", user_id="u-extra")


@pytest.mark.parametrize("overflow_policy", ["reject", "wait"])
def test_non_burst_policy_ignores_burst_limit(monkeypatch, overflow_policy):
    """Only the burst policy can use slots above the replica limit."""
    p = _make_provider(
        replicas=1,
        overflow_policy=overflow_policy,
        acquire_timeout=1,
        burst_limit=2,
    )
    fake_cls = _install_fake_sdk(monkeypatch, p)

    p.acquire("t1", user_id="u1")

    with pytest.raises(SandboxCapacityExceededError):
        p.acquire("t2", user_id="u2")

    assert len(fake_cls.create_calls) == 1


def test_capacity_burst_with_zero_limit_falls_back_to_reject(monkeypatch):
    """overflow_policy='burst' with burst_limit=0 is treated as 'reject'."""
    p = _make_provider(replicas=1, overflow_policy="burst", burst_limit=0)
    _install_fake_sdk(monkeypatch, p)

    p.acquire("t1", user_id="u1")

    with pytest.raises(SandboxCapacityExceededError):
        p.acquire("t2", user_id="u2")


def test_capacity_release_on_create_failure(monkeypatch):
    """A failed create releases the reserved slot so capacity is not leaked."""
    p = _make_provider(replicas=1, overflow_policy="reject")
    fake_cls = _install_fake_sdk(monkeypatch, p)

    call_count = 0

    def flaky_create(**kw):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("API down")
        return FakeClient(sandbox_id=f"sb-{call_count}")

    fake_cls.create_factory = flaky_create

    with pytest.raises(RuntimeError, match="API down"):
        p.acquire("t1", user_id="u1")

    assert p._reserved_slots == 0
    sid = p.acquire("t1", user_id="u1")
    assert sid is not None


def test_capacity_release_on_bootstrap_failure(monkeypatch):
    """A failed bootstrap releases the reserved slot."""
    p = _make_provider(replicas=1, overflow_policy="reject")
    fake_cls = _install_fake_sdk(monkeypatch, p)

    call_count = 0

    def flaky_create(**kw):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return FakeClient(
                sandbox_id="sb-broken",
                commands=FakeCommandsAPI([SimpleNamespace(stdout="", stderr="fail", exit_code=1)]),
            )
        return FakeClient(sandbox_id=f"sb-ok-{call_count}")

    fake_cls.create_factory = flaky_create

    with pytest.raises(RuntimeError, match="bootstrap"):
        p.acquire("t1", user_id="u1")

    assert p._reserved_slots == 0
    sid = p.acquire("t1", user_id="u1")
    assert sid is not None


def test_capacity_reject_policy_does_not_leak_reserved_slots(monkeypatch):
    """Repeated reject failures must not accumulate reserved slots."""
    p = _make_provider(replicas=1, overflow_policy="reject")
    _install_fake_sdk(monkeypatch, p)

    p.acquire("t1", user_id="u1")

    for _ in range(5):
        with pytest.raises(SandboxCapacityExceededError):
            p.acquire("t-extra", user_id="u-extra")
        assert p._reserved_slots == 0


def test_capacity_keeps_slot_when_warm_eviction_reconnect_fails(monkeypatch):
    """An uncertain warm eviction must not make room for a new VM."""
    p = _make_provider(replicas=1, overflow_policy="reject")
    fake_cls = _install_fake_sdk(monkeypatch, p)
    fake_cls.connect_factory = lambda _sid, **_kw: (_ for _ in ()).throw(RuntimeError("gone"))

    sid1 = p.acquire("t1", user_id="u1")
    p.release(sid1)
    assert len(p._warm_pool) == 1
    assert len(p._sandboxes) == 0

    with pytest.raises(SandboxCapacityExceededError):
        p.acquire("t2", user_id="u2")

    assert len(fake_cls.create_calls) == 1
    assert "sb-1" not in p._warm_pool
    assert p._transitioning_slots == 1


def test_capacity_keeps_slot_when_warm_reclaim_reconnect_fails(monkeypatch):
    """An uncertain warm reclaim must not make room for a new VM."""
    p = _make_provider(replicas=1, overflow_policy="reject")
    fake_cls = _install_fake_sdk(monkeypatch, p)
    sid = p.acquire("t1", user_id="u1")
    p.release(sid)
    fake_cls.connect_factory = lambda _sid, **_kw: (_ for _ in ()).throw(RuntimeError("network down"))

    with pytest.raises(SandboxCapacityExceededError):
        p.acquire("t1", user_id="u1")

    assert len(fake_cls.create_calls) == 1
    assert p._eviction_tombstones == {sid}
    assert p._reserved_slots == 0
    assert p._transitioning_slots == 1

    destroy_client = FakeClient(sandbox_id=sid)
    fake_cls.connect_factory = lambda _sid, **_kw: destroy_client
    assert p.acquire("t2", user_id="u2") != sid
    assert destroy_client.killed
    assert p._transitioning_slots == 0


def test_shutdown_during_reclaim_reconnect_failure_tracks_vm(monkeypatch):
    """Shutdown must see a warm VM while reclaim reconnects."""
    p = _make_provider()
    fake_cls = _install_fake_sdk(monkeypatch, p)
    sid = p.acquire("t1", user_id="u1")
    p.release(sid)

    reconnect_started = threading.Event()
    allow_failure = threading.Event()
    shutdown_client = FakeClient(sandbox_id=sid)
    calls = 0

    def reconnect(_sid, **_kw):
        nonlocal calls
        calls += 1
        if calls == 1:
            reconnect_started.set()
            assert allow_failure.wait(timeout=2)
            raise RuntimeError("network down")
        return shutdown_client

    fake_cls.connect_factory = reconnect
    result: list[str | None] = []
    reclaim = threading.Thread(
        target=lambda: result.append(p._reclaim_warm_pool_sandbox("t1", user_id="u1")),
    )
    reclaim.start()
    assert reconnect_started.wait(timeout=1)

    p.shutdown()
    allow_failure.set()
    reclaim.join(timeout=5)

    assert result == [None]
    assert shutdown_client.killed
    assert p._warm_pool == {}
    assert p._eviction_tombstones == set()
    assert p._remote_ops_in_progress == set()


def test_capacity_keeps_slot_when_warm_reclaim_bootstrap_kill_fails(monkeypatch):
    """An uncertain reclaim cleanup must not make room for a new VM."""
    p = _make_provider(replicas=1, overflow_policy="reject")
    fake_cls = _install_fake_sdk(monkeypatch, p)
    sid = p.acquire("t1", user_id="u1")
    p.release(sid)
    reconnect_client = FakeClient(
        sandbox_id=sid,
        commands=FakeCommandsAPI(
            [
                SimpleNamespace(stdout="ok", stderr="", exit_code=0),
                SimpleNamespace(stdout="", stderr="bootstrap failed", exit_code=1),
            ]
        ),
    )
    reconnect_client.kill = MagicMock(side_effect=RuntimeError("kill failed"))
    fake_cls.connect_factory = lambda _sid, **_kw: reconnect_client

    with pytest.raises(SandboxCapacityExceededError):
        p.acquire("t1", user_id="u1")

    assert len(fake_cls.create_calls) == 1
    assert p._eviction_tombstones == {sid}
    assert p._reserved_slots == 0
    assert p._transitioning_slots == 1


def test_capacity_keeps_slot_when_create_bootstrap_kill_fails(monkeypatch):
    """An uncertain create cleanup must not make room for a new VM."""
    p = _make_provider(replicas=1, overflow_policy="reject")
    fake_cls = _install_fake_sdk(monkeypatch, p)
    client = FakeClient(
        sandbox_id="bootstrap-uncertain",
        commands=FakeCommandsAPI([SimpleNamespace(stdout="", stderr="bootstrap failed", exit_code=1)]),
    )
    client.kill = MagicMock(side_effect=RuntimeError("kill failed"))
    fake_cls.create_factory = lambda **_kw: client

    with pytest.raises(RuntimeError, match="bootstrap"):
        p.acquire("t1", user_id="u1")

    fake_cls.connect_factory = lambda _sid, **_kw: (_ for _ in ()).throw(RuntimeError("network down"))
    with pytest.raises(SandboxCapacityExceededError):
        p.acquire("t2", user_id="u2")

    assert len(fake_cls.create_calls) == 1
    assert p._eviction_tombstones == {client.sandbox_id}
    assert p._reserved_slots == 0
    assert p._transitioning_slots == 1

    destroy_client = FakeClient(sandbox_id=client.sandbox_id)
    fake_cls.connect_factory = lambda _sid, **_kw: destroy_client
    fake_cls.create_factory = lambda **_kw: FakeClient(sandbox_id="bootstrap-replacement")
    assert p.acquire("t2", user_id="u2") != client.sandbox_id
    assert destroy_client.killed
    assert p._transitioning_slots == 0


def test_shutdown_during_create_bootstrap_kill_failure_tracks_vm(monkeypatch):
    """Shutdown must see a created VM while bootstrap is in progress."""
    p = _make_provider()
    fake_cls = _install_fake_sdk(monkeypatch, p)
    client = FakeClient(sandbox_id="create-bootstrap-race")
    client.kill = MagicMock(side_effect=RuntimeError("kill failed"))
    fake_cls.create_factory = lambda **_kw: client
    shutdown_client = FakeClient(sandbox_id=client.sandbox_id)
    fake_cls.connect_factory = lambda _sid, **_kw: shutdown_client
    bootstrap_started = threading.Event()
    allow_failure = threading.Event()

    def slow_bootstrap(_client):
        bootstrap_started.set()
        assert allow_failure.wait(timeout=2)
        raise RuntimeError("bootstrap failed")

    monkeypatch.setattr(p, "_bootstrap_sandbox_paths", slow_bootstrap)
    result: list[Exception] = []

    def create():
        try:
            p.acquire("t1", user_id="u1")
        except Exception as error:
            result.append(error)

    create_thread = threading.Thread(target=create)
    create_thread.start()
    assert bootstrap_started.wait(timeout=1)

    p.shutdown()
    allow_failure.set()
    create_thread.join(timeout=5)

    assert len(result) == 1
    assert shutdown_client.killed
    assert p._eviction_tombstones == set()
    assert p._remote_ops_in_progress == set()


def test_capacity_keeps_slot_when_warm_eviction_kill_fails(monkeypatch):
    """An uncertain kill must not make room for a new VM."""
    p = _make_provider(replicas=1, overflow_policy="reject")
    fake_cls = _install_fake_sdk(monkeypatch, p)
    reconnect_client = FakeClient(sandbox_id="created-1")

    def fail_kill():
        raise RuntimeError("control plane unavailable")

    reconnect_client.kill = fail_kill
    fake_cls.connect_factory = lambda _sid, **_kw: reconnect_client

    sid1 = p.acquire("t1", user_id="u1")
    p.release(sid1)

    with pytest.raises(SandboxCapacityExceededError):
        p.acquire("t2", user_id="u2")

    assert len(fake_cls.create_calls) == 1
    assert reconnect_client.closed


def test_capacity_retries_tombstone_until_warm_vm_is_destroyed(monkeypatch):
    """A later confirmed eviction can release the retained capacity slot."""
    p = _make_provider(replicas=1, overflow_policy="reject")
    fake_cls = _install_fake_sdk(monkeypatch, p)

    sid1 = p.acquire("t1", user_id="u1")
    p.release(sid1)
    fake_cls.connect_factory = lambda _sid, **_kw: (_ for _ in ()).throw(RuntimeError("network down"))

    with pytest.raises(SandboxCapacityExceededError):
        p.acquire("t2", user_id="u2")

    reconnect_client = FakeClient(sandbox_id=sid1)
    fake_cls.connect_factory = lambda _sid, **_kw: reconnect_client
    sid2 = p.acquire("t2", user_id="u2")

    assert sid2 != sid1
    assert reconnect_client.killed
    assert p._eviction_tombstones == set()
    assert p._transitioning_slots == 0


def test_tombstone_eviction_has_one_retry_owner(monkeypatch):
    """Only one thread can retry a tombstone at a time."""
    p = _make_provider()
    _install_fake_sdk(monkeypatch, p)
    p._eviction_tombstones = {"a", "b"}
    p._transitioning_slots = 2
    p._evictions_in_progress = {"b"}

    reconnect_started = threading.Event()
    allow_reconnect = threading.Event()

    def slow_reconnect(_cls, sandbox_id):
        assert sandbox_id == "a"
        reconnect_started.set()
        assert allow_reconnect.wait(timeout=2)
        return None

    monkeypatch.setattr(p, "_reconnect_live_client", slow_reconnect)
    first = threading.Thread(target=p._evict_oldest_warm)
    first.start()
    assert reconnect_started.wait(timeout=1)

    assert p._evict_oldest_warm() is None
    allow_reconnect.set()
    first.join(timeout=5)

    assert p._eviction_tombstones == {"b"}
    assert p._transitioning_slots == 1


def test_shutdown_during_initial_eviction_reconnect_failure_tracks_vm(monkeypatch):
    """Shutdown must destroy a VM while its first eviction reconnects."""
    p = _make_provider()
    fake_cls = _install_fake_sdk(monkeypatch, p)
    p._warm_pool["warm-1"] = ("seed", time.time())

    reconnect_started = threading.Event()
    allow_failure = threading.Event()
    shutdown_client = FakeClient(sandbox_id="warm-1")
    calls = 0

    def reconnect(_sid, **_kw):
        nonlocal calls
        calls += 1
        if calls == 1:
            reconnect_started.set()
            assert allow_failure.wait(timeout=2)
            raise RuntimeError("network down")
        return shutdown_client

    fake_cls.connect_factory = reconnect
    eviction = threading.Thread(target=p._evict_oldest_warm)
    eviction.start()
    assert reconnect_started.wait(timeout=1)

    p.shutdown()
    allow_failure.set()
    eviction.join(timeout=5)

    assert shutdown_client.killed
    assert p._warm_pool == {}
    assert p._eviction_tombstones == set()
    assert p._evictions_in_progress == set()


def test_capacity_reset_uses_destructive_shutdown_semantics(monkeypatch):
    """reset() destroys tracked E2B resources and ends the provider."""
    p = _make_provider(replicas=1, overflow_policy="wait", acquire_timeout=30)
    fake_cls = _install_fake_sdk(monkeypatch, p)
    client = FakeClient(sandbox_id="active")
    fake_cls.create_factory = lambda **_kwargs: client
    p.acquire("t1", user_id="u1")

    p._reserved_slots = 3
    p.reset()
    assert p._reserved_slots == 0
    assert p._shutdown_called
    assert client.killed
    assert client.closed


def test_capacity_reset_wakes_waiter_with_shutdown_error(monkeypatch):
    p = _make_provider(replicas=1, overflow_policy="wait", acquire_timeout=30)
    _install_fake_sdk(monkeypatch, p)
    p.acquire("t1", user_id="u1")
    result: list[Exception] = []
    started = threading.Event()

    def wait_for_capacity():
        started.set()
        try:
            p.acquire("t2", user_id="u2")
        except Exception as error:
            result.append(error)

    waiter = threading.Thread(target=wait_for_capacity)
    waiter.start()
    assert started.wait(timeout=1)
    time.sleep(0.1)

    p.reset()
    waiter.join(timeout=0.5)

    assert not waiter.is_alive()
    assert len(result) == 1
    assert isinstance(result[0], SandboxCapacityExceededError)
    assert result[0].reason == "shutdown"


def test_capacity_default_config_values():
    """Default config values are backward-compatible."""
    p = _make_provider()
    assert p._config["overflow_policy"] == "wait"
    assert p._config["acquire_timeout"] == 30
    assert p._config["burst_limit"] == 0


@pytest.mark.anyio
async def test_e2b_acquire_async_uses_dedicated_executor(monkeypatch):
    p = _make_provider(replicas=1, overflow_policy="reject")
    fake_cls = _install_fake_sdk(monkeypatch, p)
    p._acquire_executor = ThreadPoolExecutor(
        max_workers=1,
        thread_name_prefix="e2b-sandbox-acquire",
    )
    thread_names: list[str] = []

    def create_client(**_kwargs):
        thread_names.append(threading.current_thread().name)
        return FakeClient(sandbox_id="async-e2b")

    async def fail_to_thread(*_args, **_kwargs):
        raise AssertionError("E2B acquire must not use the default asyncio executor")

    fake_cls.create_factory = create_client
    monkeypatch.setattr(asyncio, "to_thread", fail_to_thread)

    try:
        sandbox_id = await p.acquire_async("t1", user_id="u1")
    finally:
        p.shutdown()
        p._acquire_executor.shutdown(wait=True, cancel_futures=True)

    assert sandbox_id == "async-e2b"
    assert thread_names == ["e2b-sandbox-acquire_0"]


# ── Race-condition regression tests ──────────────────────────────────────


def test_capacity_release_holds_slot_during_transition(monkeypatch):
    """replicas=1. T1 releases sb1 (slow sync). T2 acquires → reject."""
    p = _make_provider(replicas=1, overflow_policy="reject")
    _install_fake_sdk(monkeypatch, p)

    sid1 = p.acquire("t1", user_id="u1")

    sync_started = threading.Event()
    allow_sync = threading.Event()

    def slow_sync(*_args, **_kwargs):
        sync_started.set()
        assert allow_sync.wait(timeout=2)

    monkeypatch.setattr(p, "_sync_outputs_to_host", slow_sync)

    result: list[str | Exception] = []

    def do_acquire():
        try:
            result.append(p.acquire("t2", user_id="u2"))
        except Exception as e:
            result.append(e)

    release_thread = threading.Thread(target=p.release, args=(sid1,))
    release_thread.start()
    assert sync_started.wait(timeout=1), "release must enter sync"

    t = threading.Thread(target=do_acquire)
    t.start()
    t.join(timeout=2)

    allow_sync.set()
    release_thread.join(timeout=2)

    assert isinstance(result[0], SandboxCapacityExceededError), f"expected reject, got {result[0]!r}"
    assert len(p._sandboxes) + len(p._warm_pool) <= p._capacity_limit()


def test_capacity_reclaim_holds_slot_during_transition(monkeypatch):
    """replicas=1. T1 reclaims warm sb (slow reconnect). T2 acquires → reject."""
    p = _make_provider(replicas=1, overflow_policy="reject")
    fake_cls = _install_fake_sdk(monkeypatch, p)

    sid1 = p.acquire("t1", user_id="u1")
    p.release(sid1)

    reconnect_started = threading.Event()
    allow_reconnect = threading.Event()
    original_connect = fake_cls.connect_factory

    def slow_connect(sid, **kw):
        reconnect_started.set()
        assert allow_reconnect.wait(timeout=2)
        return original_connect(sid, **kw)

    fake_cls.connect_factory = slow_connect

    result: list[str | Exception] = []

    def do_acquire():
        try:
            result.append(p.acquire("t2", user_id="u2"))
        except Exception as e:
            result.append(e)

    reclaim_thread = threading.Thread(target=p._reclaim_warm_pool_sandbox, args=("t1",), kwargs={"user_id": "u1"})
    reclaim_thread.start()
    assert reconnect_started.wait(timeout=1), "reclaim must enter reconnect"

    t = threading.Thread(target=do_acquire)
    t.start()
    t.join(timeout=2)

    allow_reconnect.set()
    reclaim_thread.join(timeout=2)

    assert isinstance(result[0], SandboxCapacityExceededError), f"expected reject during reclaim, got {result[0]!r}"


def test_capacity_shutdown_wakes_waiter_with_error(monkeypatch):
    """Waiter blocked on capacity must raise on shutdown, not create VM."""
    p = _make_provider(replicas=1, overflow_policy="wait", acquire_timeout=30)
    fake_cls = _install_fake_sdk(monkeypatch, p)

    p.acquire("t1", user_id="u1")

    result: list[Exception | None] = []
    started = threading.Event()

    def waiter():
        started.set()
        try:
            p.acquire("t2", user_id="u2")
        except Exception as e:
            result.append(e)

    t = threading.Thread(target=waiter)
    t.start()
    assert started.wait(timeout=1)

    time.sleep(0.2)
    p.shutdown()
    t.join(timeout=5)

    assert len(result) == 1
    assert isinstance(result[0], SandboxCapacityExceededError)
    assert "shutting down" in str(result[0]).lower()
    assert len(fake_cls.create_calls) == 1


def test_capacity_create_aborted_by_shutdown_kills_vm(monkeypatch):
    """shutdown after create() but before commit: kill VM, raise error."""
    p = _make_provider(replicas=2, overflow_policy="reject")
    fake_cls = _install_fake_sdk(monkeypatch, p)

    created_client: FakeClient | None = None
    create_returned = threading.Event()
    allow_commit = threading.Event()

    def intercept_create(**kw):
        nonlocal created_client
        c = FakeClient(sandbox_id="sb-shutdown-race")
        created_client = c
        create_returned.set()
        assert allow_commit.wait(timeout=2)
        return c

    fake_cls.create_factory = intercept_create

    result: list[str | Exception] = []

    def do_acquire():
        try:
            result.append(p.acquire("t1", user_id="u1"))
        except Exception as e:
            result.append(e)

    t = threading.Thread(target=do_acquire)
    t.start()
    assert create_returned.wait(timeout=1)

    p.shutdown()
    allow_commit.set()
    t.join(timeout=5)

    assert len(result) == 1
    assert isinstance(result[0], SandboxCapacityExceededError)
    assert created_client is not None
    assert created_client.killed, "VM must be killed when shutdown aborts create"


def test_capacity_create_aborted_by_shutdown_retries_failed_kill(monkeypatch):
    """A transient kill failure must not orphan a VM created during shutdown."""
    p = _make_provider(replicas=2, overflow_policy="reject")
    fake_cls = _install_fake_sdk(monkeypatch, p)
    created_client = FakeClient(sandbox_id="sb-shutdown-retry")
    created_client.kill = MagicMock(side_effect=RuntimeError("control plane unavailable"))
    retry_client = FakeClient(sandbox_id=created_client.sandbox_id)
    fake_cls.connect_factory = lambda _sid, **_kwargs: retry_client
    create_returned = threading.Event()
    allow_create_return = threading.Event()

    def intercept_create(**_kwargs):
        create_returned.set()
        assert allow_create_return.wait(timeout=2)
        return created_client

    fake_cls.create_factory = intercept_create
    result: list[Exception] = []

    def do_acquire():
        try:
            p.acquire("t1", user_id="u1")
        except Exception as error:
            result.append(error)

    acquire_thread = threading.Thread(target=do_acquire)
    acquire_thread.start()
    assert create_returned.wait(timeout=1)

    p.shutdown()
    allow_create_return.set()
    acquire_thread.join(timeout=5)

    assert len(result) == 1
    assert isinstance(result[0], SandboxCapacityExceededError)
    assert retry_client.killed
    assert retry_client.closed


def test_capacity_create_aborted_by_shutdown_tracks_uncertain_cleanup(monkeypatch):
    """A persistent cleanup failure must keep the remote VM ID visible."""
    p = _make_provider(replicas=2, overflow_policy="reject")
    fake_cls = _install_fake_sdk(monkeypatch, p)
    created_client = FakeClient(sandbox_id="sb-shutdown-uncertain")
    created_client.kill = MagicMock(side_effect=RuntimeError("control plane unavailable"))
    fake_cls.connect_factory = lambda _sid, **_kwargs: (_ for _ in ()).throw(RuntimeError("network unavailable"))
    create_returned = threading.Event()
    allow_create_return = threading.Event()

    def intercept_create(**_kwargs):
        create_returned.set()
        assert allow_create_return.wait(timeout=2)
        return created_client

    fake_cls.create_factory = intercept_create
    result: list[Exception] = []

    def do_acquire():
        try:
            p.acquire("t1", user_id="u1")
        except Exception as error:
            result.append(error)

    acquire_thread = threading.Thread(target=do_acquire)
    acquire_thread.start()
    assert create_returned.wait(timeout=1)

    p.shutdown()
    allow_create_return.set()
    acquire_thread.join(timeout=5)

    assert len(result) == 1
    assert "could not confirm cleanup" in str(result[0])
    assert p._remote_ops_in_progress == {created_client.sandbox_id}


def test_capacity_concurrent_different_threads_only_one_creates(monkeypatch):
    """replicas=1. Two threads for different users/threads → exactly 1 create."""
    p = _make_provider(replicas=1, overflow_policy="reject")
    fake_cls = _install_fake_sdk(monkeypatch, p)

    create_count = 0
    create_lock = threading.Lock()
    create_started = threading.Event()
    allow_first_create = threading.Event()

    def counted_create(**kw):
        nonlocal create_count
        with create_lock:
            create_count += 1
            if create_count == 1:
                create_started.set()
                assert allow_first_create.wait(timeout=2)
        return FakeClient(sandbox_id=f"sb-{create_count}")

    fake_cls.create_factory = counted_create

    results: list[str | Exception] = []
    barrier = threading.Barrier(2, timeout=5)

    def worker_a():
        barrier.wait()
        try:
            results.append(p.acquire("t-a", user_id="u-a"))
        except Exception as e:
            results.append(e)

    def worker_b():
        barrier.wait()
        time.sleep(0.1)
        try:
            results.append(p.acquire("t-b", user_id="u-b"))
        except Exception as e:
            results.append(e)

    ta = threading.Thread(target=worker_a)
    tb = threading.Thread(target=worker_b)
    ta.start()
    tb.start()
    assert create_started.wait(timeout=2)

    tb.join(timeout=5)
    allow_first_create.set()
    ta.join(timeout=5)

    assert create_count == 1, f"expected 1 create, got {create_count}"
    assert len(results) == 2
    sids = [r for r in results if isinstance(r, str)]
    errs = [r for r in results if isinstance(r, Exception)]
    assert len(sids) == 1, f"expected 1 successful acquire, got {len(sids)}"
    assert len(errs) == 1
    assert isinstance(errs[0], SandboxCapacityExceededError)


def test_shutdown_during_release_does_not_repopulate_warm_pool(monkeypatch):
    """release in flight when shutdown fires must kill the VM, not park it."""
    p = _make_provider(replicas=2, overflow_policy="reject")
    fake_cls = _install_fake_sdk(monkeypatch, p)
    client = FakeClient(sandbox_id="sb-release-shutdown")
    fake_cls.create_factory = lambda **_kw: client

    sid1 = p.acquire("t1", user_id="u1")

    sync_entered = threading.Event()
    allow_sync = threading.Event()

    def slow_sync(*_args, **_kwargs):
        sync_entered.set()
        assert allow_sync.wait(timeout=2)

    monkeypatch.setattr(p, "_sync_outputs_to_host", slow_sync)

    release_done = threading.Event()

    def do_release():
        p.release(sid1)
        release_done.set()

    t = threading.Thread(target=do_release)
    t.start()
    assert sync_entered.wait(timeout=1)

    p.shutdown()
    allow_sync.set()
    t.join(timeout=5)

    assert release_done.is_set()
    assert sid1 not in p._warm_pool, "must not park in warm pool after shutdown"
    assert client.killed, "release must kill its saved client after shutdown"


def test_shutdown_during_release_close_kills_published_warm_vm(monkeypatch):
    """Shutdown must find a released VM before its client transport closes."""
    p = _make_provider(replicas=2, overflow_policy="reject")
    fake_cls = _install_fake_sdk(monkeypatch, p)
    client = FakeClient(sandbox_id="sb-release-close-race")
    fake_cls.create_factory = lambda **_kw: client
    sid = p.acquire("t1", user_id="u1")

    close_started = threading.Event()
    allow_close = threading.Event()

    def slow_close():
        client.closed = True
        close_started.set()
        assert allow_close.wait(timeout=2)

    def fail_kill_after_close():
        if client.closed:
            raise RuntimeError("transport closed")
        client.killed = True

    client.close = slow_close
    client.kill = fail_kill_after_close
    shutdown_client = FakeClient(sandbox_id=sid)
    fake_cls.connect_factory = lambda _sid, **_kw: shutdown_client

    release_thread = threading.Thread(target=p.release, args=(sid,))
    release_thread.start()
    assert close_started.wait(timeout=1)

    shutdown_thread = threading.Thread(target=p.shutdown)
    shutdown_thread.start()
    shutdown_thread.join(timeout=2)
    allow_close.set()
    release_thread.join(timeout=5)

    assert shutdown_client.killed


def test_release_keeps_parked_vm_reclaimable_during_client_close(monkeypatch):
    """A concurrent acquire must not evict a VM because release counts it twice."""
    p = _make_provider(replicas=2, overflow_policy="reject")
    fake_cls = _install_fake_sdk(monkeypatch, p)
    first_client = FakeClient(sandbox_id="sb-first")
    second_client = FakeClient(sandbox_id="sb-second")
    created_clients = iter((first_client, second_client))
    fake_cls.create_factory = lambda **_kwargs: next(created_clients)

    first_sid = p.acquire("t1", user_id="u1")
    close_started = threading.Event()
    allow_close = threading.Event()

    def slow_close():
        close_started.set()
        assert allow_close.wait(timeout=2)
        first_client.closed = True

    first_client.close = slow_close
    release_thread = threading.Thread(target=p.release, args=(first_sid,))
    release_thread.start()
    assert close_started.wait(timeout=1)

    assert p.acquire("t2", user_id="u2") == "sb-second"
    allow_close.set()
    release_thread.join(timeout=5)

    assert p.acquire("t1", user_id="u1") == first_sid


def test_shutdown_during_reclaim_does_not_register_active(monkeypatch):
    """reclaim in flight when shutdown fires must kill the VM, not register."""
    p = _make_provider(replicas=2, overflow_policy="reject")
    fake_cls = _install_fake_sdk(monkeypatch, p)

    sid1 = p.acquire("t1", user_id="u1")
    p.release(sid1)

    reconnect_entered = threading.Event()
    allow_reconnect = threading.Event()
    original_connect = fake_cls.connect_factory

    def slow_connect(sid, **kw):
        reconnect_entered.set()
        assert allow_reconnect.wait(timeout=2)
        return original_connect(sid, **kw)

    fake_cls.connect_factory = slow_connect

    result: list[str | None] = []

    def do_reclaim():
        result.append(p._reclaim_warm_pool_sandbox("t1", user_id="u1"))

    t = threading.Thread(target=do_reclaim)
    t.start()
    assert reconnect_entered.wait(timeout=1)

    p.shutdown()
    allow_reconnect.set()
    t.join(timeout=5)

    assert result == [None], "reclaim must return None after shutdown"
    assert sid1 not in p._sandboxes, "must not register active after shutdown"


def test_shutdown_during_bootstrap_does_not_commit(monkeypatch):
    """create in bootstrap when shutdown fires must kill, not commit."""
    p = _make_provider(replicas=2, overflow_policy="reject")
    fake_cls = _install_fake_sdk(monkeypatch, p)

    client = FakeClient(sandbox_id="sb-bootstrap-shutdown")
    fake_cls.create_factory = lambda **kw: client

    bootstrap_entered = threading.Event()
    allow_bootstrap = threading.Event()

    original_bootstrap = p._bootstrap_sandbox_paths

    def slow_bootstrap(c):
        bootstrap_entered.set()
        assert allow_bootstrap.wait(timeout=2)
        return original_bootstrap(c)

    monkeypatch.setattr(p, "_bootstrap_sandbox_paths", slow_bootstrap)

    result: list[str | Exception] = []

    def do_acquire():
        try:
            result.append(p.acquire("t1", user_id="u1"))
        except Exception as e:
            result.append(e)

    t = threading.Thread(target=do_acquire)
    t.start()
    assert bootstrap_entered.wait(timeout=1)

    p.shutdown()
    allow_bootstrap.set()
    t.join(timeout=5)

    assert len(result) == 1
    assert isinstance(result[0], SandboxCapacityExceededError)
    assert "sb-bootstrap-shutdown" not in p._sandboxes
    assert client.killed, "VM must be killed"


def test_discovery_reports_busy_capacity_without_killing_remote_vm(monkeypatch):
    """Discovery must report a full provider without destroying the remote VM."""
    p = _make_provider(replicas=1, overflow_policy="reject")
    fake_cls = _install_fake_sdk(monkeypatch, p)
    discovered_client = FakeClient(sandbox_id="sb-remote")
    fake_cls.connect_factory = lambda _sid, **_kw: discovered_client
    bootstrap = MagicMock()
    monkeypatch.setattr(p, "_bootstrap_sandbox_paths", bootstrap)

    # Fill the single slot.
    p.acquire("t1", user_id="u1")
    bootstrap.reset_mock()

    # Discovery finds a matching sandbox.
    fake_cls.list_return = [
        SimpleNamespace(
            sandbox_id="sb-remote",
            metadata={
                "deer_flow_provider": "e2b_sandbox_provider",
                "deer_flow_user": "u2",
                "deer_flow_thread": "t2",
                "deer_flow_skills_root": "/mnt/skills",
            },
        )
    ]

    with pytest.raises(SandboxCapacityExceededError):
        p._discover_remote_sandbox("t2", user_id="u2")

    assert "sb-remote" not in p._sandboxes
    bootstrap.assert_not_called()
    assert not discovered_client.killed
    assert discovered_client.closed


def test_discovery_reports_shutdown_without_killing_remote_vm(monkeypatch, caplog):
    p = _make_provider(replicas=1, overflow_policy="reject")
    fake_cls = _install_fake_sdk(monkeypatch, p)
    client = FakeClient(sandbox_id="sb-remote")
    fake_cls.connect_factory = lambda _sid, **_kw: client
    fake_cls.list_return = [
        SimpleNamespace(
            sandbox_id=client.sandbox_id,
            metadata={
                "deer_flow_provider": "e2b_sandbox_provider",
                "deer_flow_user": "u1",
                "deer_flow_thread": "t1",
                "deer_flow_skills_root": "/mnt/skills",
            },
        )
    ]
    p._shutdown_called = True

    with caplog.at_level("INFO"), pytest.raises(SandboxCapacityExceededError) as error:
        p._discover_remote_sandbox("t1", user_id="u1")

    assert error.value.reason == "shutdown"
    assert "shutting down" in caplog.text
    assert "capacity is full" not in caplog.text
    assert not client.killed
    assert client.closed


def test_discovery_bootstrap_kill_failure_retains_reserved_slot(monkeypatch):
    """Discovery keeps capacity when bootstrap cleanup cannot destroy the VM."""
    p = _make_provider(replicas=1, overflow_policy="reject")
    fake_cls = _install_fake_sdk(monkeypatch, p)
    client = FakeClient(
        sandbox_id="discovery-bootstrap-failure",
        commands=FakeCommandsAPI(
            [
                SimpleNamespace(stdout="ok", stderr="", exit_code=0),
                SimpleNamespace(stdout="", stderr="bootstrap failed", exit_code=1),
            ]
        ),
    )
    client.kill = MagicMock(side_effect=RuntimeError("kill failed"))
    fake_cls.connect_factory = lambda _sid, **_kw: client
    fake_cls.list_return = [
        SimpleNamespace(
            sandbox_id=client.sandbox_id,
            metadata={
                "deer_flow_provider": "e2b_sandbox_provider",
                "deer_flow_user": "u1",
                "deer_flow_thread": "t1",
                "deer_flow_skills_root": "/mnt/skills",
            },
        )
    ]

    assert p._discover_remote_sandbox("t1", user_id="u1") is None

    assert p._eviction_tombstones == {client.sandbox_id}
    assert p._reserved_slots == 0
    assert p._transitioning_slots == 1
    assert p._remote_ops_in_progress == set()


def test_shutdown_does_not_retry_kill_for_unowned_discovery_vm(monkeypatch):
    """Shutdown does not claim an unowned discovery VM after cleanup fails."""
    p = _make_provider(replicas=1, overflow_policy="reject")
    fake_cls = _install_fake_sdk(monkeypatch, p)
    client = FakeClient(sandbox_id="discovery-bootstrap-race")
    client.kill = MagicMock(side_effect=RuntimeError("kill failed"))
    shutdown_client = FakeClient(sandbox_id=client.sandbox_id)
    connect_calls = 0

    def reconnect(_sid, **_kw):
        nonlocal connect_calls
        connect_calls += 1
        return client if connect_calls == 1 else shutdown_client

    fake_cls.connect_factory = reconnect
    fake_cls.list_return = [
        SimpleNamespace(
            sandbox_id=client.sandbox_id,
            metadata={
                "deer_flow_provider": "e2b_sandbox_provider",
                "deer_flow_user": "u1",
                "deer_flow_thread": "t1",
                "deer_flow_skills_root": "/mnt/skills",
            },
        )
    ]
    bootstrap_started = threading.Event()
    allow_failure = threading.Event()

    def slow_bootstrap(_client):
        bootstrap_started.set()
        assert allow_failure.wait(timeout=2)
        raise RuntimeError("bootstrap failed")

    monkeypatch.setattr(p, "_bootstrap_sandbox_paths", slow_bootstrap)
    result: list[str | None] = []
    discovery = threading.Thread(
        target=lambda: result.append(p._discover_remote_sandbox("t1", user_id="u1")),
    )
    discovery.start()
    assert bootstrap_started.wait(timeout=1)

    p.shutdown()
    allow_failure.set()
    discovery.join(timeout=5)

    assert result == [None]
    assert not shutdown_client.killed
    assert connect_calls == 1
    assert p._eviction_tombstones == set()
    assert p._remote_ops_in_progress == set()
    assert p._unowned_remote_ops_in_progress == set()


def test_shutdown_during_discovery_does_not_kill_unowned_vm(monkeypatch):
    """Shutdown closes discovery clients without killing unowned remote VMs."""
    p = _make_provider(replicas=1, overflow_policy="reject")
    fake_cls = _install_fake_sdk(monkeypatch, p)
    client = FakeClient(sandbox_id="sb-discovery-shutdown")
    fake_cls.connect_factory = lambda _sid, **_kw: client
    fake_cls.list_return = [
        SimpleNamespace(
            sandbox_id=client.sandbox_id,
            metadata={
                "deer_flow_provider": "e2b_sandbox_provider",
                "deer_flow_user": "u1",
                "deer_flow_thread": "t1",
                "deer_flow_skills_root": "/mnt/skills",
            },
        )
    ]

    reserved = threading.Event()
    allow_commit = threading.Event()
    reserve_capacity = p._reserve_capacity

    def pause_after_reserve(
        thread_id,
        user_id,
        *,
        remote_id=None,
        remote_owned=True,
    ):
        reservation = reserve_capacity(
            thread_id,
            user_id,
            remote_id=remote_id,
            remote_owned=remote_owned,
        )
        reserved.set()
        assert allow_commit.wait(timeout=2)
        return reservation

    monkeypatch.setattr(p, "_reserve_capacity", pause_after_reserve)
    result: list[str | None] = []
    thread = threading.Thread(
        target=lambda: result.append(p._discover_remote_sandbox("t1", user_id="u1")),
    )
    thread.start()
    assert reserved.wait(timeout=1)

    p.shutdown()
    allow_commit.set()
    thread.join(timeout=5)

    assert result == [None]
    assert not client.killed
    assert client.closed
    assert p._sandboxes == {}
    assert p._reserved_slots == 0


def test_stable_seed_matches_shared_identity():
    from deerflow.sandbox.identity import derive_sandbox_scope_token

    provider = _make_provider(skills_container_path="/custom-skills")
    base_scope = derive_sandbox_scope_token(user_id="u-1", thread_id="t-1")
    expected = hashlib.sha256(
        f"{base_scope}\0/custom-skills".encode(),
    ).hexdigest()[:16]

    assert provider._stable_seed("t-1", "u-1") == expected


def test_evict_oldest_warm_cleans_mount_result(monkeypatch):
    provider = _make_provider()
    fake_cls = _install_fake_sdk(monkeypatch, provider)
    client = FakeClient(sandbox_id="sb-warm")
    fake_cls.connect_factory = lambda _sid, **_kw: client
    provider._warm_pool["sb-warm"] = ("seed", 12345.0)
    provider._mount_results["sb-warm"] = MountUploadResult(
        truncated=True,
        reason="byte budget",
        attempted_files=8,
        attempted_bytes=4000,
        completed_files=5,
        completed_bytes=2500,
    )
    provider._kill_client = MagicMock(return_value=None)

    assert provider._evict_oldest_warm() == "sb-warm"
    assert "sb-warm" not in provider._mount_results


def test_reuse_evicts_dead_sandbox_cleans_mount_result():
    provider = _make_provider()
    sandbox = _make_sandbox(FakeClient(), sandbox_id="sb-dead")
    sandbox._dead = True
    provider._sandboxes["sb-dead"] = sandbox
    provider._thread_sandboxes[provider._thread_key("t1", "u1")] = "sb-dead"
    provider._mount_results["sb-dead"] = MountUploadResult(
        truncated=True,
        reason="time budget 120s",
        attempted_files=0,
        attempted_bytes=0,
        completed_files=0,
        completed_bytes=0,
    )

    provider._reuse_in_process_sandbox("t1", user_id="u1")

    assert "sb-dead" not in provider._mount_results


def test_reclaim_warm_pool_cleans_mount_result_on_reconnect_failure(monkeypatch):
    provider = _make_provider()
    fake_cls = _install_fake_sdk(monkeypatch, provider)

    def fail_connect(_sandbox_id, **_kwargs):
        raise RuntimeError("404 Not Found")

    fake_cls.connect_factory = fail_connect
    provider._warm_pool["sb-broken"] = (provider._stable_seed("t1", "u1"), 12345.0)
    provider._mount_results["sb-broken"] = MountUploadResult(
        truncated=False,
        reason=None,
        attempted_files=0,
        attempted_bytes=0,
        completed_files=0,
        completed_bytes=0,
    )

    provider._reclaim_warm_pool_sandbox("t1", user_id="u1")

    assert "sb-broken" not in provider._mount_results


def test_reclaim_warm_pool_cleans_mount_result_on_dead_entry(monkeypatch):
    provider = _make_provider()
    fake_cls = _install_fake_sdk(monkeypatch, provider)
    client = FakeClient(sandbox_id="sb-zombie", commands=FakeCommandsAPI([FakeCommandsAPI.GONE]))
    fake_cls.connect_factory = lambda _sandbox_id, **_kwargs: client
    provider._warm_pool["sb-zombie"] = (provider._stable_seed("t1", "u1"), 12345.0)
    provider._mount_results["sb-zombie"] = MountUploadResult(
        truncated=True,
        reason="file count cap",
        attempted_files=0,
        attempted_bytes=0,
        completed_files=0,
        completed_bytes=0,
    )

    provider._reclaim_warm_pool_sandbox("t1", user_id="u1")

    assert "sb-zombie" not in provider._mount_results


def test_forget_local_sandbox_cleans_mount_result():
    provider = _make_provider()
    provider._sandboxes["sb-peer"] = _make_sandbox(FakeClient(), sandbox_id="sb-peer")
    provider._mount_results["sb-peer"] = MountUploadResult(
        truncated=False,
        reason=None,
        attempted_files=0,
        attempted_bytes=0,
        completed_files=0,
        completed_bytes=0,
    )

    provider._forget_local_sandbox("sb-peer")

    assert "sb-peer" not in provider._mount_results
    assert "sb-peer" not in provider._sandboxes


def test_mount_upload_deadline_none_returns_default():
    mod = importlib.import_module("deerflow.community.e2b_sandbox.e2b_sandbox_provider")

    def option(name, default=None):
        return None if name == "mount_upload_deadline_seconds" else default

    assert mod.E2BSandboxProvider._resolve_mount_upload_deadline(option) == mod._MOUNT_PASS_DEADLINE_SECONDS


def test_mount_upload_result_is_frozen():
    result = MountUploadResult(
        truncated=False,
        reason=None,
        attempted_files=0,
        attempted_bytes=0,
        completed_files=0,
        completed_bytes=0,
    )

    with pytest.raises(FrozenInstanceError):
        result.truncated = True  # type: ignore[misc]


def test_list_dir_preserves_trailing_space_in_filename():
    # "notes.txt " (trailing space) is a legal Linux filename; find prints it
    # verbatim, one entry per line, so a per-line strip() corrupts the name and
    # every follow-up file API call on the listed path misses the real file.
    listing = SimpleNamespace(stdout="/home/user/notes.txt \n/home/user/sub\n", stderr="", exit_code=0)
    client = FakeClient(commands=FakeCommandsAPI([listing]))
    sb = _make_sandbox(client)

    assert sb.list_dir("/home/user") == ["/home/user/notes.txt ", "/home/user/sub"]


def test_glob_preserves_trailing_space_in_filename():
    listing = SimpleNamespace(stdout="/home/user/notes.txt \n", stderr="", exit_code=0)
    client = FakeClient(commands=FakeCommandsAPI([listing]))
    sb = _make_sandbox(client)

    matches, truncated = sb.glob("/home/user", "notes*")

    assert matches == ["/home/user/notes.txt "]
    assert truncated is False
