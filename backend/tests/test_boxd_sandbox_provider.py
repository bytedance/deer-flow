"""Unit tests for the boxd community sandbox provider.

They run without the ``boxd`` SDK installed: a fake client replaces the SDK's
``Boxd`` object and raises errors with the SDK's class names, which is how the
adapter classifies them. Search and command tests run the generated shell
scripts with the local ``bash`` (POSIX only). The live test is
``test_boxd_sandbox_live.py``.
"""

from __future__ import annotations

import asyncio
import errno
import io
import os
import re
import subprocess
import sys
import tarfile
import threading
import types
from pathlib import Path
from typing import Any

import pytest

from deerflow.community.boxd_sandbox.boxd_sandbox import BoxdSandbox
from deerflow.community.boxd_sandbox.boxd_sandbox_provider import BoxdSandboxProvider, _import_client, _ShutdownIncompleteError
from deerflow.config.paths import Paths

posix_only = pytest.mark.skipif(os.name != "posix", reason="runs generated scripts with the local bash")

# ── Fake boxd SDK ────────────────────────────────────────────────────────


class BoxdError(Exception):
    pass


class NotFoundError(BoxdError):
    pass


class ConflictError(BoxdError):
    pass


class MachineFilesystemError(BoxdError, OSError):
    pass


class MachineFileNotFoundError(MachineFilesystemError, NotFoundError, FileNotFoundError):
    pass


class _Result:
    def __init__(self, exit_code: int = 0, stdout: str | bytes = "", stderr: str | bytes = "") -> None:
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr


class _Machine:
    def __init__(self, machine_id: str, name: str) -> None:
        self.id = machine_id
        self.name = name
        self.status = "running"


class _FakeFs:
    _CHUNK = 64

    def __init__(self, client: _FakeClient) -> None:
        self._client = client

    def _files(self, machine_id: str) -> dict[str, bytes]:
        return self._client.files.setdefault(machine_id, {})

    def read_stream(self, machine_id: str, path: str, *, region: str | None = None):
        self._client.check(machine_id)
        files = self._files(machine_id)
        if path not in files:
            raise MachineFileNotFoundError(f"{path}: No such file or directory")
        data = files[path]
        for i in range(0, len(data), self._CHUNK):
            yield data[i : i + self._CHUNK]

    def write(self, machine_id: str, path: str, data: bytes | str, *, region: str | None = None) -> None:
        self._client.check(machine_id)
        if isinstance(data, str):
            data = data.encode()
        elif not isinstance(data, (bytes, bytearray, memoryview)):
            data = b"".join(data)  # an iterable of chunks, like the SDK accepts
        self._files(machine_id)[path] = bytes(data)


class _FakeMachines:
    def __init__(self, client: _FakeClient) -> None:
        self._client = client
        self.fs = _FakeFs(client)

    def create(self, name: str, **kwargs: Any) -> _Machine:
        self._client.create_gate.wait()
        if self._client.create_error is not None and not self._client.create_error_after_create:
            raise self._client.create_error
        machine = _Machine(f"m-{len(self._client.created) + 1}", name)
        machine.labels = dict(kwargs.get("labels") or {})
        self._client.created.append((name, kwargs))
        self._client.machines[machine.id] = machine
        if self._client.create_error is not None:
            raise self._client.create_error
        return machine

    def list(self, *, org=None, labels=None, region=None) -> list[_Machine]:
        return [m for m in self._client.machines.values() if all(m.labels.get(k) == v for k, v in (labels or {}).items())]

    def wait_until_ready(self, machine_id: str, *, timeout: float = 90.0, region: str | None = None) -> _Machine:
        if self._client.ready_error is not None:
            raise self._client.ready_error
        return self._client.machines[machine_id]

    def get(self, machine_id: str, *, region: str | None = None) -> _Machine:
        if machine_id not in self._client.machines:
            raise NotFoundError(f"machine {machine_id} not found")
        return self._client.machines[machine_id]

    def start(self, machine_id: str, *, region: str | None = None) -> None:
        self._client.starts.append(machine_id)
        self._client.machines[machine_id].status = "running"

    def delete(self, machine_id: str, *, region: str | None = None) -> None:
        self._client.delete_calls.append(machine_id)
        if self._client.delete_errors:
            raise self._client.delete_errors.pop(0)
        if machine_id not in self._client.machines:
            raise NotFoundError(f"machine {machine_id} not found")
        del self._client.machines[machine_id]
        self._client.deleted.append(machine_id)

    def exec(self, machine_id: str, command: list[str], *, env=None, timeout=None, encoding="utf-8", region=None) -> _Result:
        self._client.check(machine_id)
        self._client.execs.append({"machine": machine_id, "argv": list(command), "env": dict(env or {}), "timeout": timeout, "encoding": encoding})
        return self._client.handle_exec(machine_id, list(command), env=dict(env or {}), encoding=encoding)


class _FakeClient:
    """In-memory stand-in for ``boxd.Boxd`` with a scripted shell."""

    def __init__(self) -> None:
        self.machines: dict[str, _Machine] = {}
        self.files: dict[str, dict[str, bytes]] = {}
        self.created: list[tuple[str, dict[str, Any]]] = []
        self.delete_calls: list[str] = []
        self.delete_errors: list[Exception] = []
        self.deleted: list[str] = []
        self.starts: list[str] = []
        self.execs: list[dict[str, Any]] = []
        self.create_error: Exception | None = None
        self.create_error_after_create = False
        self.ready_error: Exception | None = None
        self.create_gate = threading.Event()
        self.create_gate.set()
        self.exec_override = None
        self.health_ok = True
        self.bootstrap_exit = 0
        self.local_shell = False
        self.machines_api = _FakeMachines(self)

    def check(self, machine_id: str) -> None:
        machine = self.machines.get(machine_id)
        if machine is None:
            raise NotFoundError(f"machine {machine_id} not found")
        if machine.status == "stopped":
            raise ConflictError(f"VM {machine.name} is stopped")

    def handle_exec(self, machine_id: str, argv: list[str], *, env: dict[str, str], encoding: str) -> _Result:
        if self.exec_override is not None:
            result = self.exec_override(machine_id, argv, env)
            if result is not None:
                return result
        script = argv[-1]
        files = self.files.setdefault(machine_id, {})
        if argv[0] == "head":
            limit, path = int(argv[2]), argv[4]
            if path not in files:
                if any(name.startswith(f"{path}/") for name in files):
                    return _Result(1, b"", f"head: error reading '{path}': Is a directory")
                return _Result(1, b"", f"head: cannot open '{path}' for reading: No such file or directory")
            return _Result(0, files[path][:limit])
        if "BOOTSTRAP_OK" in script:
            return _Result(self.bootstrap_exit, "BOOTSTRAP_OK\n" if self.bootstrap_exit == 0 else "")
        if "UPLOAD_OK" in script:
            return self._extract(files, script)
        if script == "echo ok":
            return _Result(0, "ok\n") if self.health_ok else _Result(1, "", "boom")
        if "-print0" in script and "/mnt/user-data/outputs" in script:
            listing = b"".join(path.encode() + b"\0" for path in sorted(files) if path.startswith("/mnt/user-data/outputs/"))
            return _Result(0, listing if encoding == "buffer" else listing.decode())
        if self.local_shell:
            completed = subprocess.run(argv, env={**os.environ, **env}, capture_output=True, timeout=60)
            if encoding == "buffer":
                return _Result(completed.returncode, completed.stdout, completed.stderr)
            return _Result(completed.returncode, completed.stdout.decode("utf-8", "replace"), completed.stderr.decode("utf-8", "replace"))
        return _Result(0, "")

    @staticmethod
    def _extract(files: dict[str, bytes], script: str) -> _Result:
        match = re.search(r"tar -xzf (\S+) -C (\S+) ", script)
        assert match is not None
        tar_path, dest = match.group(1).strip("'"), match.group(2).strip("'")
        removal = re.search(r"rm -rf -- (.*?);", script)
        if removal:
            for target in removal.group(1).split():
                target = target.strip("'")
                for path in [p for p in files if p.startswith(f"{target}/")]:
                    del files[path]
        with tarfile.open(fileobj=io.BytesIO(files.pop(tar_path)), mode="r:gz") as archive:
            for member in archive.getmembers():
                files[f"{dest}/{member.name}"] = archive.extractfile(member).read()
        return _Result(0, "UPLOAD_OK\n")


def _boxd_class(fake: _FakeClient):
    def factory(*, api_key=None, region=None, timeout=None):
        fake.client_kwargs = {"api_key": api_key, "region": region}
        fake.client_timeout = timeout
        return types.SimpleNamespace(machines=fake.machines_api)

    return factory


def _stub_config(attrs: dict[str, Any] | None = None, *, skills_root: str = "/mnt/skills") -> types.SimpleNamespace:
    values = {"idle_timeout": 0, "boxd_api_key": "test-key", **(attrs or {})}
    return types.SimpleNamespace(sandbox=types.SimpleNamespace(**values), skills=types.SimpleNamespace(container_path=skills_root))


@pytest.fixture
def paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Paths:
    result = Paths(base_dir=tmp_path / "home")
    monkeypatch.setattr("deerflow.config.paths.get_paths", lambda: result)
    return result


@pytest.fixture
def no_skills(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def fail(*args, **kwargs):
        raise RuntimeError("no skills in this test")

    monkeypatch.setattr("deerflow.skills.storage.get_or_new_user_skill_storage", fail)


def _install(monkeypatch: pytest.MonkeyPatch, config: dict[str, Any] | None = None, *, fake: _FakeClient | None = None, skills_root: str = "/mnt/skills") -> tuple[BoxdSandboxProvider, _FakeClient]:
    fake = fake or _FakeClient()
    monkeypatch.setattr("deerflow.community.boxd_sandbox.boxd_sandbox_provider.get_app_config", lambda: _stub_config(config, skills_root=skills_root))
    monkeypatch.setattr("deerflow.community.boxd_sandbox.boxd_sandbox_provider._import_client", lambda: _boxd_class(fake))
    return BoxdSandboxProvider(), fake


@pytest.fixture
def installed(monkeypatch: pytest.MonkeyPatch, paths: Paths, no_skills: None):
    provider, fake = _install(monkeypatch)
    yield provider, fake
    provider.shutdown()


def _box(fake: _FakeClient, *, env: dict[str, str] | None = None, on_terminal_failure=None) -> BoxdSandbox:
    machine = fake.machines_api.create("t")
    return BoxdSandbox("sandbox-id", types.SimpleNamespace(machines=fake.machines_api), machine.id, default_env=env, on_terminal_failure=on_terminal_failure)


# ── SDK import and config ────────────────────────────────────────────────


def test_missing_sdk_has_actionable_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "boxd", None)
    with pytest.raises(ImportError, match=r"deerflow-harness\[boxd\]"):
        _import_client()


def test_package_imports_without_the_sdk() -> None:
    code = "import sys; sys.modules['boxd'] = None; import deerflow.community.boxd_sandbox as m; print(m.BoxdSandboxProvider.__name__)"
    completed = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "BoxdSandboxProvider"


def test_missing_api_key_fails_with_remedy(monkeypatch: pytest.MonkeyPatch, paths: Paths) -> None:
    monkeypatch.delenv("BOXD_API_KEY", raising=False)
    provider, fake = _install(monkeypatch, {"boxd_api_key": None})
    with pytest.raises(ValueError, match="BOXD_API_KEY"):
        provider.acquire("thread", user_id="owner")
    assert fake.created == []


@pytest.mark.parametrize(
    ("config", "message"),
    [
        ({"region": "mars"}, "sandbox.region"),
        ({"vcpu": 3}, "sandbox.vcpu"),
        ({"vcpu": True}, "sandbox.vcpu"),
        ({"memory": "12G"}, "sandbox.memory"),
        ({"vcpu": 2, "memory": "16G"}, "goes with"),
        ({"environment": {"bad-key": "1"}}, "bad-key"),
        ({"auto_suspend_timeout": -1}, "auto_suspend_timeout"),
        ({"labels": {"team": 1}}, "sandbox.labels"),
        ({"name_prefix": "Deer_"}, "name_prefix"),
        ({"ready_timeout": 0}, "ready_timeout"),
        ({"bash_command_timeout": 0}, "bash_command_timeout"),
    ],
)
def test_invalid_config_fails_at_startup(monkeypatch: pytest.MonkeyPatch, config: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        _install(monkeypatch, config)


@pytest.mark.parametrize("root", ["/", "/etc/skills", "/home/boxd", "/mnt/user-data/skills", "/mnt", "skills", "/mnt//skills"])
def test_unsafe_skills_root_is_rejected(monkeypatch: pytest.MonkeyPatch, root: str) -> None:
    with pytest.raises(ValueError, match="skills"):
        _install(monkeypatch, skills_root=root)


def test_create_is_isolated_labelled_and_sized(monkeypatch: pytest.MonkeyPatch, paths: Paths, no_skills: None) -> None:
    provider, fake = _install(
        monkeypatch,
        {"org": "acme", "region": "fra", "memory": "16G", "from_snapshot": "prepared", "auto_suspend_timeout": 300, "labels": {"team": "research"}},
    )
    try:
        sandbox_id = provider.acquire("thread", user_id="owner")
        name, kwargs = fake.created[0]
        assert kwargs["isolated"] is True
        assert kwargs["org"] == "acme"
        assert kwargs["region"] == "fra"
        assert (kwargs["vcpu"], kwargs["memory"]) == (4, "16G")
        assert kwargs["from_snapshot"] == "prepared"
        assert kwargs["auto_suspend_timeout"] == 300
        generation = kwargs["labels"].pop("deer-flow-generation")
        assert re.fullmatch(r"[0-9a-f]{32}", generation)
        assert kwargs["labels"] == {"team": "research", "deer-flow": "sandbox", "deer-flow-scope": sandbox_id}
        assert re.fullmatch(rf"deer-flow-{sandbox_id}-[0-9a-f]{{6}}", name)
        assert fake.client_kwargs == {"api_key": "test-key", "region": "fra"}
        # Every later call addresses the machine by the id create returned.
        assert {call["machine"] for call in fake.execs} == {"m-1"}
    finally:
        provider.shutdown()


def test_create_that_raises_after_the_machine_exists_deletes_it(installed) -> None:
    provider, fake = installed
    fake.machines_api.create("someone-else", labels={"deer-flow": "sandbox"})  # m-1 must survive: no matching generation
    fake.create_error = BoxdError("deadline exceeded")
    fake.create_error_after_create = True
    with pytest.raises(BoxdError):
        provider.acquire("thread", user_id="owner")
    assert fake.deleted == ["m-2"]
    assert "m-1" in fake.machines


@pytest.mark.parametrize("retry", ["reaper", "shutdown"])
def test_failed_create_delete_remains_tracked_until_retry(installed, retry: str) -> None:
    provider, fake = installed
    fake.machines_api.create("someone-else", labels={"deer-flow": "sandbox"})
    fake.create_error = BoxdError("create response lost")
    fake.create_error_after_create = True
    fake.delete_errors = [BoxdError("temporary delete failure")]
    with pytest.raises(BoxdError, match="create response lost"):
        provider.acquire("thread", user_id="owner")

    assert fake.delete_calls == ["m-2"]
    assert set(fake.machines) == {"m-1", "m-2"}
    assert [box.machine_id for box in provider._pending_closes.values()] == ["m-2"]
    assert provider._sandboxes == {}
    assert provider._warm_pool == {}
    if retry == "reaper":
        provider._cleanup_idle_resources(0)
    else:
        provider.shutdown()
    assert fake.deleted == ["m-2"]
    assert fake.delete_calls == ["m-2", "m-2"]
    assert set(fake.machines) == {"m-1"}
    assert provider._pending_closes == {}


def test_provider_enforces_agent_skill_isolation(installed) -> None:
    provider, _ = installed
    assert provider.supports_agent_skill_isolation is True


def test_each_generation_gets_a_new_machine_name(installed) -> None:
    provider, fake = installed
    sandbox_id = provider.acquire("thread", user_id="owner")
    provider._invalidate_sandbox(sandbox_id, "gone")
    provider.acquire("thread", user_id="owner")
    assert len({name for name, _ in fake.created}) == 2


# ── Acquire, reuse and release ───────────────────────────────────────────


def test_scope_reuse_and_user_thread_isolation(installed) -> None:
    provider, fake = installed
    first = provider.acquire("thread", user_id="alice")
    assert provider.acquire("thread", user_id="alice") == first
    other_user = provider.acquire("thread", user_id="bob")
    other_thread = provider.acquire("other", user_id="alice")
    assert len({first, other_user, other_thread}) == 3
    assert len(fake.created) == 3


def test_release_parks_and_same_scope_reclaims_without_create(installed) -> None:
    provider, fake = installed
    sandbox_id = provider.acquire("thread", user_id="owner")
    provider.release(sandbox_id)
    assert provider.get(sandbox_id) is None
    assert provider.acquire("thread", user_id="owner") == sandbox_id
    assert len(fake.created) == 1


def test_unhealthy_warm_machine_is_deleted_and_replaced(installed) -> None:
    provider, fake = installed
    sandbox_id = provider.acquire("thread", user_id="owner")
    provider.release(sandbox_id)
    fake.health_ok = False
    provider.acquire("thread", user_id="owner")
    assert fake.deleted == ["m-1"]
    assert len(fake.created) == 2


def test_readiness_failure_deletes_machine_by_id(installed) -> None:
    provider, fake = installed
    fake.ready_error = TimeoutError("not ready")
    with pytest.raises(TimeoutError):
        provider.acquire("thread", user_id="owner")
    assert fake.delete_calls == ["m-1"]
    assert fake.machines == {}


def test_bootstrap_failure_deletes_machine(installed) -> None:
    provider, fake = installed
    fake.bootstrap_exit = 1
    with pytest.raises(RuntimeError, match="bootstrap"):
        provider.acquire("thread", user_id="owner")
    assert fake.deleted == ["m-1"]


def test_bootstrap_creates_user_data_and_skills_root(installed) -> None:
    provider, fake = installed
    provider.acquire("thread", user_id="owner")
    script = next(call["argv"][-1] for call in fake.execs if "BOOTSTRAP_OK" in call["argv"][-1])
    for path in ("/mnt/user-data/workspace", "/mnt/user-data/uploads", "/mnt/user-data/outputs", "/mnt/skills"):
        assert path in script
    assert "sudo -n" in script


def test_replica_cap_evicts_oldest_warm_machine(monkeypatch: pytest.MonkeyPatch, paths: Paths, no_skills: None) -> None:
    provider, fake = _install(monkeypatch, {"replicas": 1})
    try:
        provider.release(provider.acquire("one", user_id="owner"))
        provider.acquire("two", user_id="owner")
        assert fake.deleted == ["m-1"]
    finally:
        provider.shutdown()


def test_acquire_without_thread_creates_unscoped_machine(installed) -> None:
    provider, fake = installed
    sandbox_id = provider.acquire()
    assert provider.get(sandbox_id) is not None
    assert len(fake.created) == 1


# ── Thread files and skills ──────────────────────────────────────────────


def test_fresh_machine_restores_thread_files(installed, paths: Paths) -> None:
    provider, fake = installed
    uploads = paths.sandbox_uploads_dir("thread", user_id="owner")
    uploads.mkdir(parents=True)
    (uploads / "data.csv").write_bytes(b"a,b\n")
    outputs = paths.sandbox_outputs_dir("thread", user_id="owner")
    (outputs / "nested").mkdir(parents=True)
    (outputs / "nested" / "report.md").write_text("# report")
    (outputs / "link").symlink_to(uploads / "data.csv")

    provider.acquire("thread", user_id="owner")
    files = fake.files["m-1"]
    assert files["/mnt/user-data/uploads/data.csv"] == b"a,b\n"
    assert files["/mnt/user-data/outputs/nested/report.md"] == b"# report"
    assert "/mnt/user-data/outputs/link" not in files
    assert not any(path.startswith("/tmp/") for path in files)


def test_restore_over_limit_is_partial_and_keeps_machine(installed, paths: Paths, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    provider, fake = installed
    monkeypatch.setattr(BoxdSandboxProvider, "_MAX_UPLOAD_FILES", 1)
    uploads = paths.sandbox_uploads_dir("thread", user_id="owner")
    uploads.mkdir(parents=True)
    (uploads / "a.txt").write_text("a")
    outputs = paths.sandbox_outputs_dir("thread", user_id="owner")
    outputs.mkdir(parents=True)
    (outputs / "big.txt").write_text("b")
    sandbox_id = provider.acquire("thread", user_id="owner")
    files = fake.files["m-1"]
    # Uploads come first; the rest is skipped instead of locking the thread out.
    assert files["/mnt/user-data/uploads/a.txt"] == b"a"
    assert "/mnt/user-data/outputs/big.txt" not in files
    assert provider.get(sandbox_id) is not None
    assert fake.deleted == []
    assert "were not copied" in caplog.text


def test_restore_transfer_failure_discards_machine(installed, paths: Paths) -> None:
    provider, fake = installed
    uploads = paths.sandbox_uploads_dir("thread", user_id="owner")
    uploads.mkdir(parents=True)
    (uploads / "a.txt").write_text("a")
    fake.exec_override = lambda machine_id, argv, env: _Result(2, "", "tar: broken") if "UPLOAD_OK" in argv[-1] else None
    with pytest.raises(RuntimeError, match="upload"):
        provider.acquire("thread", user_id="owner")
    assert fake.deleted == ["m-1"]


def _projection(root: Path, files: dict[str, str]) -> Any:
    categories = {}
    for category in ("public", "custom", "legacy", "integrations"):
        path = root / category
        path.mkdir(parents=True, exist_ok=True)
        categories[category] = path
    for rel, text in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    return types.SimpleNamespace(**categories)


def test_fresh_machine_gets_shared_skills_projection(monkeypatch: pytest.MonkeyPatch, paths: Paths, tmp_path: Path) -> None:
    projection = _projection(tmp_path / "proj", {"public/research/SKILL.md": "# research"})
    monkeypatch.setattr("deerflow.skills.storage.get_or_new_user_skill_storage", lambda user_id, app_config=None: object())
    monkeypatch.setattr("deerflow.skills.projection.ensure_skill_projections", lambda storage: projection)
    provider, fake = _install(monkeypatch)
    try:
        provider.acquire("thread", user_id="owner")
        assert fake.files["m-1"]["/mnt/skills/public/research/SKILL.md"] == b"# research"
    finally:
        provider.shutdown()


def test_policy_scoped_thread_skips_shared_skills(monkeypatch: pytest.MonkeyPatch, paths: Paths, tmp_path: Path) -> None:
    projection = _projection(tmp_path / "proj", {"public/research/SKILL.md": "# research"})
    monkeypatch.setattr("deerflow.skills.storage.get_or_new_user_skill_storage", lambda user_id, app_config=None: object())
    monkeypatch.setattr("deerflow.skills.projection.ensure_skill_projections", lambda storage: projection)
    paths.thread_skills_view_dir("thread", user_id="owner").mkdir(parents=True)
    provider, fake = _install(monkeypatch)
    try:
        provider.acquire("thread", user_id="owner")
        assert not any(path.startswith("/mnt/skills/") for path in fake.files.get("m-1", {}))
    finally:
        provider.shutdown()


def test_sync_agent_skills_replaces_managed_categories(installed, tmp_path: Path) -> None:
    provider, fake = installed
    sandbox_id = provider.acquire("thread", user_id="owner")
    fake.files["m-1"]["/mnt/skills/public/old/SKILL.md"] = b"old"
    fake.files["m-1"]["/mnt/skills/notes.txt"] = b"unmanaged"
    projection = _projection(tmp_path / "proj", {"custom/mine/SKILL.md": "# mine"})
    provider.sync_agent_skills(sandbox_id, thread_id="thread", user_id="owner", projection=projection)
    files = fake.files["m-1"]
    assert files["/mnt/skills/custom/mine/SKILL.md"] == b"# mine"
    assert "/mnt/skills/public/old/SKILL.md" not in files
    assert files["/mnt/skills/notes.txt"] == b"unmanaged"


def test_sync_agent_skills_on_unknown_sandbox_raises(installed, tmp_path: Path) -> None:
    provider, _ = installed
    with pytest.raises(RuntimeError, match="not available"):
        provider.sync_agent_skills("missing", thread_id="thread", user_id="owner", projection=_projection(tmp_path / "p", {}))


# ── Output mirroring ─────────────────────────────────────────────────────


def test_release_mirrors_outputs_to_gateway(installed, paths: Paths) -> None:
    provider, fake = installed
    sandbox_id = provider.acquire("thread", user_id="owner")
    fake.files["m-1"]["/mnt/user-data/outputs/report # 中文.txt"] = b"first"
    fake.files["m-1"]["/mnt/user-data/outputs/charts/a.png"] = b"\x89PNG"
    provider.release(sandbox_id)
    outputs = paths.sandbox_outputs_dir("thread", user_id="owner")
    assert (outputs / "report # 中文.txt").read_bytes() == b"first"
    assert (outputs / "charts" / "a.png").read_bytes() == b"\x89PNG"
    assert not list(outputs.rglob(".boxd-sync-*"))
    # The listing is read as bytes, so file names are never decoded lossily.
    listing = next(call for call in fake.execs if "-print0" in call["argv"][-1])
    assert listing["encoding"] == "buffer"


@pytest.mark.parametrize("first_transfer_fails", [False, True])
def test_output_mirror_passes_remaining_deadline_to_downloads(installed, paths: Paths, monkeypatch: pytest.MonkeyPatch, first_transfer_fails: bool) -> None:
    provider, fake = installed
    sandbox_id = provider.acquire("thread", user_id="owner")
    files = fake.files["m-1"]
    files["/mnt/user-data/outputs/a.txt"] = b"a"
    files["/mnt/user-data/outputs/b.txt"] = b"b"
    outputs = paths.sandbox_outputs_dir("thread", user_id="owner")
    outputs.mkdir(parents=True, exist_ok=True)
    (outputs / "a.txt").write_bytes(b"previous")
    now = [0.0]
    monkeypatch.setattr("deerflow.community.boxd_sandbox.boxd_sandbox_provider.time.monotonic", lambda: now[0])

    def transfer(machine_id, argv, env):
        if "-print0" in argv[-1]:
            now[0] += provider._SYNC_DEADLINE_SECONDS - 1
        elif argv[0] == "head":
            now[0] += 0.75
            if first_transfer_fails and argv[-1].endswith("a.txt"):
                raise BoxdError("temporary download failure")
        return None

    fake.exec_override = transfer
    provider.release(sandbox_id)
    downloads = [call for call in fake.execs if call["argv"][0] == "head"]
    assert [call["timeout"] for call in downloads] == [1.0, 0.25]
    assert (outputs / "a.txt").read_bytes() == (b"previous" if first_transfer_fails else b"a")
    assert (outputs / "b.txt").read_bytes() == b"b"
    assert sandbox_id in provider._warm_pool


def test_expired_output_mirror_starts_no_download(installed, monkeypatch: pytest.MonkeyPatch) -> None:
    provider, fake = installed
    sandbox_id = provider.acquire("thread", user_id="owner")
    fake.files["m-1"]["/mnt/user-data/outputs/a.txt"] = b"a"
    now = [0.0]
    monkeypatch.setattr("deerflow.community.boxd_sandbox.boxd_sandbox_provider.time.monotonic", lambda: now[0])

    def listing(machine_id, argv, env):
        if "-print0" in argv[-1]:
            now[0] += provider._SYNC_DEADLINE_SECONDS
        return None

    fake.exec_override = listing
    provider.release(sandbox_id)
    assert all(call["argv"][0] != "head" for call in fake.execs)
    assert sandbox_id in provider._warm_pool


@pytest.mark.parametrize("stop_during_listing", [False, True])
def test_output_mirror_defers_stopped_machine_recovery(installed, paths: Paths, stop_during_listing: bool) -> None:
    provider, fake = installed
    sandbox_id = provider.acquire("thread", user_id="owner")
    fake.files["m-1"]["/mnt/user-data/outputs/a.txt"] = b"new"
    outputs = paths.sandbox_outputs_dir("thread", user_id="owner")
    outputs.mkdir(parents=True, exist_ok=True)
    (outputs / "a.txt").write_bytes(b"previous")

    def stop(machine_id, argv, env):
        if "-print0" in argv[-1]:
            fake.machines[machine_id].status = "stopped"
        return None

    if stop_during_listing:
        fake.exec_override = stop
    else:
        fake.machines["m-1"].status = "stopped"
    provider.release(sandbox_id)
    assert fake.starts == []
    assert (outputs / "a.txt").read_bytes() == b"previous"
    assert sandbox_id in provider._warm_pool
    fake.exec_override = None
    provider.acquire("thread", user_id="owner")
    assert fake.starts == ["m-1"]


def test_output_mirror_rechecks_deadline_after_local_preflight(installed, monkeypatch: pytest.MonkeyPatch) -> None:
    provider, fake = installed
    sandbox_id = provider.acquire("thread", user_id="owner")
    fake.files["m-1"]["/mnt/user-data/outputs/a.txt"] = b"a"
    now = [0.0]
    monkeypatch.setattr("deerflow.community.boxd_sandbox.boxd_sandbox_provider.time.monotonic", lambda: now[0])
    destination = provider._output_destination

    def preflight(root, remote_path):
        now[0] += provider._SYNC_DEADLINE_SECONDS
        return destination(root, remote_path)

    monkeypatch.setattr(provider, "_output_destination", preflight)
    provider.release(sandbox_id)
    assert all(call["argv"][0] != "head" for call in fake.execs)
    assert sandbox_id in provider._warm_pool


def test_output_sync_skips_ambiguous_and_unsafe_names(installed, paths: Paths) -> None:
    provider, fake = installed
    sandbox_id = provider.acquire("thread", user_id="owner")
    files = fake.files["m-1"]
    files["/mnt/user-data/outputs/Report.txt"] = b"upper"
    files["/mnt/user-data/outputs/report.txt"] = b"lower"
    files["/mnt/user-data/outputs/a:b.txt"] = b"colon"
    files["/mnt/user-data/outputs/ok.txt"] = b"ok"
    provider.release(sandbox_id)
    outputs = paths.sandbox_outputs_dir("thread", user_id="owner")
    assert sorted(p.name for p in outputs.iterdir()) == ["ok.txt"]


def test_output_sync_failure_still_parks_machine(installed, monkeypatch: pytest.MonkeyPatch) -> None:
    provider, _ = installed
    sandbox_id = provider.acquire("thread", user_id="owner")
    monkeypatch.setattr(provider, "_sync_outputs_to_host", lambda *a, **k: (_ for _ in ()).throw(OSError("listing failed")))
    provider.release(sandbox_id)
    assert sandbox_id in provider._warm_pool


def test_invalidated_during_sync_is_not_parked(installed, monkeypatch: pytest.MonkeyPatch) -> None:
    provider, fake = installed
    sandbox_id = provider.acquire("thread", user_id="owner")
    sandbox = provider.get(sandbox_id)

    def invalidate(*args, **kwargs):
        provider._invalidate_sandbox(sandbox_id, "gone", expected_sandbox=sandbox)

    monkeypatch.setattr(provider, "_sync_outputs_to_host", invalidate)
    provider.release(sandbox_id)
    assert sandbox_id not in provider._warm_pool
    assert fake.deleted == ["m-1"]


# ── Adapter: commands ────────────────────────────────────────────────────


def test_env_goes_with_every_exec_not_in_the_command(installed) -> None:
    provider, fake = installed
    fake.local_shell = False
    sandbox = BoxdSandbox("s", types.SimpleNamespace(machines=fake.machines_api), fake.machines_api.create("t").id, default_env={"STATIC": "1", "TOKEN": "old"})
    sandbox.execute_command("echo hi", env={"TOKEN": "secret-value"})
    call = fake.execs[-1]
    assert call["env"] == {"STATIC": "1", "TOKEN": "secret-value"}
    assert "secret-value" not in " ".join(call["argv"])
    assert call["argv"][-3:] == ["bash", "-lc", "echo hi"]


def test_execute_command_rejects_invalid_env_key(installed) -> None:
    _, fake = installed
    with pytest.raises(ValueError):
        _box(fake).execute_command("true", env={"bad-key": "x"})


def test_command_without_timeout_gets_the_configured_deadline(monkeypatch: pytest.MonkeyPatch, paths: Paths, no_skills: None) -> None:
    provider, fake = _install(monkeypatch, {"bash_command_timeout": 42})
    try:
        provider.get(provider.acquire("thread", user_id="owner")).execute_command("true")
        call = fake.execs[-1]
        assert call["argv"][:4] == ["timeout", "-k", "5", "42"]
        assert call["timeout"] is not None
    finally:
        provider.shutdown()


def test_every_sdk_call_has_a_deadline(installed) -> None:
    provider, fake = installed
    sandbox = provider.get(provider.acquire("thread", user_id="owner"))
    sandbox.write_file("/mnt/user-data/workspace/a.txt", "x")
    sandbox.read_file("/mnt/user-data/workspace/a.txt")
    sandbox.download_file("/mnt/user-data/workspace/a.txt")
    sandbox.execute_command("true")
    assert all(call["timeout"] for call in fake.execs)
    assert fake.client_timeout is not None


def test_timeout_runs_inside_the_machine(installed) -> None:
    _, fake = installed
    _box(fake).execute_command("sleep 1", timeout=2.5)
    call = fake.execs[-1]
    assert call["argv"][:4] == ["timeout", "-k", "5", "3"]
    assert call["timeout"] > 3


@posix_only
def test_timed_out_command_keeps_partial_output_and_exit_124(installed) -> None:
    _, fake = installed
    fake.local_shell = True
    output = _box(fake).execute_command("echo before; sleep 30; echo after", timeout=1)
    assert output.startswith("before")
    assert "after" not in output
    assert output.endswith("Exit Code: 124")


@posix_only
def test_exit_code_and_streams_are_reported(installed) -> None:
    _, fake = installed
    fake.local_shell = True
    box = _box(fake)
    assert box.execute_command("echo out; echo err >&2; exit 3") == "out\n\nerr\n\nExit Code: 3"
    assert box.execute_command("exit 2") == "Command exited with code 2\nExit Code: 2"
    assert box.execute_command("true") == "(no output)"


def test_sdk_error_is_returned_as_text(installed) -> None:
    _, fake = installed
    box = _box(fake)
    fake.exec_override = lambda *a: (_ for _ in ()).throw(BoxdError("transport down"))
    assert box.execute_command("echo hi") == "Error: transport down"


def test_stopped_machine_command_is_not_repeated(installed) -> None:
    _, fake = installed
    box = _box(fake)
    fake.machines[box.machine_id].status = "stopped"
    output = box.execute_command("echo hi")
    assert output.startswith("Error:") and "run it again" in output
    assert fake.starts == [box.machine_id]
    # Only the readiness probe ran; the command itself never ran twice.
    assert [call["argv"] for call in fake.execs] == [["true"]]


def test_stopped_machine_file_read_is_repeated_once(installed) -> None:
    _, fake = installed
    box = _box(fake)
    fake.files.setdefault(box.machine_id, {})["/mnt/user-data/workspace/a.txt"] = b"data"
    fake.machines[box.machine_id].status = "stopped"
    assert box.read_file("/mnt/user-data/workspace/a.txt") == "data"
    assert fake.starts == [box.machine_id]
    assert [call["argv"][0] for call in fake.execs] == ["true", "head"]


def test_started_machine_is_probed_before_the_call_repeats(installed, monkeypatch: pytest.MonkeyPatch) -> None:
    _, fake = installed
    box = _box(fake)
    fake.files.setdefault(box.machine_id, {})["/mnt/user-data/workspace/a.txt"] = b"done"
    fake.machines[box.machine_id].status = "stopped"
    monkeypatch.setattr("deerflow.community.boxd_sandbox.boxd_sandbox._START_PROBE_INTERVAL", 0)
    probes = []

    def flaky_probe(machine_id, argv, env):
        if argv == ["true"]:
            probes.append(argv)
            if len(probes) < 3:
                raise BoxdError("not reachable yet")
            return _Result(0)
        return None

    fake.exec_override = flaky_probe
    assert box.read_file("/mnt/user-data/workspace/a.txt") == "done"
    assert len(probes) == 3


def test_other_conflicts_are_not_retried(installed) -> None:
    _, fake = installed
    box = _box(fake)
    calls = []

    def conflict(*args):
        calls.append(args)
        raise ConflictError("machine is busy")

    fake.exec_override = conflict
    assert box.execute_command("echo hi").startswith("Error:")
    assert len(calls) == 1
    assert fake.starts == []


def test_gone_machine_invalidates_sandbox(installed) -> None:
    provider, fake = installed
    sandbox_id = provider.acquire("thread", user_id="owner")
    sandbox = provider.get(sandbox_id)
    del fake.machines["m-1"]
    assert sandbox.execute_command("echo hi").startswith("Error:")
    assert provider.get(sandbox_id) is None
    assert not provider._pending_closes


def test_not_found_from_a_live_machine_does_not_invalidate(installed) -> None:
    provider, fake = installed
    sandbox_id = provider.acquire("thread", user_id="owner")
    sandbox = provider.get(sandbox_id)
    fake.exec_override = lambda *a: (_ for _ in ()).throw(NotFoundError("session not found"))
    assert sandbox.execute_command("echo hi").startswith("Error:")
    assert provider.get(sandbox_id) is sandbox
    assert fake.deleted == []


def test_missing_file_does_not_invalidate_sandbox(installed) -> None:
    provider, _ = installed
    sandbox_id = provider.acquire("thread", user_id="owner")
    sandbox = provider.get(sandbox_id)
    assert sandbox.read_file("/mnt/user-data/workspace/missing.txt").startswith("Error:")
    assert provider.get(sandbox_id) is sandbox


# ── Adapter: files ───────────────────────────────────────────────────────


def test_write_read_append_and_line_ranges(installed) -> None:
    _, fake = installed
    box = _box(fake)
    box.write_file("/mnt/user-data/workspace/a.txt", "one\ntwo\n")
    box.write_file("/mnt/user-data/workspace/a.txt", "three\n", append=True)
    box.write_file("/mnt/user-data/workspace/new.txt", "fresh", append=True)
    assert box.read_file("/mnt/user-data/workspace/a.txt") == "one\ntwo\nthree\n"
    assert box.read_file("/mnt/user-data/workspace/a.txt", start_line=2, end_line=3) == "two\nthree"
    assert box.read_file("/mnt/user-data/workspace/a.txt", start_line=-5, end_line=1) == "one"
    assert box.read_file("/mnt/user-data/workspace/new.txt") == "fresh"
    box.update_file("/mnt/user-data/outputs/b.bin", b"\x00\x01")
    assert fake.files[box.machine_id]["/mnt/user-data/outputs/b.bin"] == b"\x00\x01"


@pytest.mark.parametrize("path", ["/mnt/user-data/../etc/passwd", "relative.txt", ""])
def test_paths_are_guarded(installed, path: str) -> None:
    _, fake = installed
    box = _box(fake)
    assert box.read_file(path).startswith("Error:")
    with pytest.raises((PermissionError, ValueError)):
        box.write_file(path, "x")


def test_download_is_bounded_and_confined(installed) -> None:
    _, fake = installed
    box = _box(fake)
    files = fake.files.setdefault(box.machine_id, {})
    files["/mnt/user-data/outputs/big.bin"] = b"x" * 1000
    files["/etc/passwd"] = b"root"
    assert box.download_file("/mnt/user-data/outputs/big.bin", max_bytes=1000) == b"x" * 1000
    with pytest.raises(OSError) as excinfo:
        box.download_file("/mnt/user-data/outputs/big.bin", max_bytes=999)
    assert excinfo.value.errno == errno.EFBIG
    with pytest.raises(PermissionError):
        box.download_file("/etc/passwd")
    with pytest.raises(FileNotFoundError):
        box.download_file("/mnt/user-data/outputs/missing.bin")


@posix_only
def test_grep_glob_and_list_dir_through_the_shell(installed, tmp_path: Path) -> None:
    _, fake = installed
    fake.local_shell = True
    root = tmp_path / "ws"
    (root / "src").mkdir(parents=True)
    (root / "src" / "report:2026.txt").write_text("alpha\nneedle here\n")
    (root / "src" / "main.py").write_text("needle = 1\n")
    (root / "notes.md").write_text("nothing\n")
    box = _box(fake)

    matches, truncated = box.grep(str(root), "needle")
    assert not truncated
    assert sorted((Path(m.path).name, m.line_number) for m in matches) == [("main.py", 1), ("report:2026.txt", 2)]
    scoped, _ = box.grep(str(root), "needle", glob="src/*.py")
    assert [Path(m.path).name for m in scoped] == ["main.py"]

    found, truncated = box.glob(str(root), "**/*.txt")
    assert [Path(p).name for p in found] == ["report:2026.txt"]
    assert not truncated

    listing = box.list_dir(str(root))
    assert str(root / "src" / "main.py") in listing


# ── Teardown ─────────────────────────────────────────────────────────────


def test_failed_delete_is_retried_by_shutdown(monkeypatch: pytest.MonkeyPatch, paths: Paths, no_skills: None) -> None:
    provider, fake = _install(monkeypatch)
    sandbox_id = provider.acquire("thread", user_id="owner")
    provider.release(sandbox_id)
    fake.delete_errors = [BoxdError("transport down")]
    with pytest.raises(_ShutdownIncompleteError):
        provider.shutdown()
    assert "m-1" in fake.machines
    provider.shutdown()
    assert fake.deleted == ["m-1"]
    provider.shutdown()  # complete: a no-op
    assert fake.delete_calls == ["m-1", "m-1"]


def test_shutdown_deletes_machines_even_when_the_reaper_is_slow(monkeypatch: pytest.MonkeyPatch, paths: Paths, no_skills: None) -> None:
    provider, fake = _install(monkeypatch)
    provider.acquire("thread", user_id="owner")

    def slow_reaper() -> None:
        raise RuntimeError("warm-pool idle checker is still running after stop timeout")

    monkeypatch.setattr(provider, "_stop_idle_checker", slow_reaper)
    with pytest.raises(_ShutdownIncompleteError, match="reaper"):
        provider.shutdown()
    assert fake.deleted == ["m-1"]
    monkeypatch.setattr(provider, "_stop_idle_checker", lambda: None)
    provider.shutdown()


def test_delete_of_gone_machine_counts_as_closed(installed) -> None:
    _, fake = installed
    box = _box(fake)
    del fake.machines[box.machine_id]
    box.close()
    assert box.is_closed


def test_shutdown_deletes_active_and_warm_and_rejects_acquire(monkeypatch: pytest.MonkeyPatch, paths: Paths, no_skills: None) -> None:
    provider, fake = _install(monkeypatch)
    active = provider.acquire("one", user_id="owner")
    provider.release(provider.acquire("two", user_id="owner"))
    provider.shutdown()
    assert sorted(fake.deleted) == ["m-1", "m-2"]
    assert provider.get(active) is None
    with pytest.raises(RuntimeError, match="shutting down"):
        provider.acquire("three", user_id="owner")


def test_reset_parks_active_machines_for_later_cleanup(installed) -> None:
    provider, fake = installed
    sandbox_id = provider.acquire("thread", user_id="owner")
    provider.reset()
    assert provider.get(sandbox_id) is None
    assert sandbox_id in provider._warm_pool
    assert fake.deleted == []


def test_machine_created_after_shutdown_is_deleted(installed) -> None:
    provider, fake = installed
    fake.create_gate.clear()
    errors: list[BaseException] = []

    def acquire() -> None:
        try:
            provider.acquire("thread", user_id="owner")
        except BaseException as e:
            errors.append(e)

    worker = threading.Thread(target=acquire)
    worker.start()
    while not provider._acquires:
        threading.Event().wait(0.01)
    provider._accepting = False
    fake.create_gate.set()
    worker.join(timeout=10)
    assert errors and "retired" in str(errors[0])
    assert fake.deleted == ["m-1"]


def test_cancelled_acquire_releases_its_new_machine(installed) -> None:
    provider, fake = installed
    fake.create_gate.clear()

    async def scenario() -> None:
        task = asyncio.create_task(provider.acquire_async("thread", user_id="owner"))
        while not provider._acquires:
            await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        fake.create_gate.set()
        for _ in range(500):
            if provider._warm_pool:
                return
            await asyncio.sleep(0.01)

    asyncio.run(scenario())
    assert list(provider._warm_pool) == [provider._sandbox_id("thread", "owner")]
    assert provider._sandboxes == {}


def test_cancelled_acquire_does_not_release_a_borrowed_machine(installed) -> None:
    provider, fake = installed
    sandbox_id = provider.acquire("thread", user_id="owner")
    gate = threading.Event()
    original = provider._acquire

    def slow_acquire(thread_id, user_id, ticket=None):
        gate.wait(10)
        return original(thread_id, user_id, ticket)

    provider._acquire = slow_acquire

    async def scenario() -> None:
        task = asyncio.create_task(provider.acquire_async("thread", user_id="owner"))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        gate.set()
        await asyncio.sleep(0.3)

    asyncio.run(scenario())
    assert provider.get(sandbox_id) is not None
    assert provider._warm_pool == {}


def test_two_cancelled_acquires_release_the_machine(installed) -> None:
    provider, fake = installed
    fake.create_gate.clear()

    async def scenario() -> None:
        first = asyncio.create_task(provider.acquire_async("thread", user_id="owner"))
        second = asyncio.create_task(provider.acquire_async("thread", user_id="owner"))
        while not provider._acquires:
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.05)
        first.cancel()
        second.cancel()
        for task in (first, second):
            with pytest.raises(asyncio.CancelledError):
                await task
        fake.create_gate.set()
        for _ in range(500):
            if provider._warm_pool and not provider._acquires:
                return
            await asyncio.sleep(0.01)

    asyncio.run(scenario())
    assert list(provider._warm_pool) == [provider._sandbox_id("thread", "owner")]
    assert provider._sandboxes == {}
    assert len(fake.created) == 1


def test_acquire_async_returns_sandbox_id(installed) -> None:
    provider, _ = installed
    sandbox_id = asyncio.run(provider.acquire_async("thread", user_id="owner"))
    assert provider.get(sandbox_id) is not None


def test_real_sdk_errors_are_classified() -> None:
    errors = pytest.importorskip("boxd.errors")
    from deerflow.community.boxd_sandbox.boxd_sandbox import is_machine_gone_error, is_missing_file_error, is_stopped_machine_error

    missing_file = errors.MachineFileNotFoundError.__new__(errors.MachineFileNotFoundError)
    assert is_missing_file_error(missing_file)
    assert not is_machine_gone_error(missing_file)
    is_dir = errors.MachineIsADirectoryError.__new__(errors.MachineIsADirectoryError)
    assert not is_stopped_machine_error(is_dir)
    assert is_machine_gone_error(errors.NotFoundError.__new__(errors.NotFoundError))
    assert is_stopped_machine_error(errors.ConflictError.__new__(errors.ConflictError))
