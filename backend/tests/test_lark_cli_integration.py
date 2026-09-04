from __future__ import annotations

import hashlib
import inspect
import io
import json
import multiprocessing
import os
import re
import shutil
import stat
import subprocess
import tarfile
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient

from app.gateway.auth.models import User
from app.gateway.deps import get_config
from app.gateway.routers import integrations as integrations_router
from deerflow.config import paths as paths_module
from deerflow.config.paths import Paths
from deerflow.integrations import lark_cli
from deerflow.sandbox.tools import _lark_cli_env_from_runtime
from deerflow.skills.storage import reset_skill_storage
from deerflow.skills.storage.user_scoped_skill_storage import UserScopedSkillStorage
from deerflow.skills.types import SkillCategory


def _skill_content(name: str) -> str:
    return f"---\nname: {name}\ndescription: {name} integration skill\n---\n\n# {name}\n"


def _make_lark_cli_source_zip(tmp_path: Path, *, omit_skill: str | None = None, renamed_skill: str | None = None) -> Path:
    archive = tmp_path / "lark-cli.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        for skill_name in lark_cli.LARK_SKILL_NAMES:
            if skill_name == omit_skill:
                continue
            declared_name = f"{skill_name}-renamed" if skill_name == renamed_skill else skill_name
            zf.writestr(f"cli-1.0.65/skills/{skill_name}/SKILL.md", _skill_content(declared_name))
            zf.writestr(f"cli-1.0.65/skills/{skill_name}/references/readme.md", f"# {skill_name}\n")
    return archive


def _make_lark_cli_binary_tar(payload: bytes, *, member_name: str = "lark-cli") -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tf:
        info = tarfile.TarInfo(member_name)
        info.mode = 0o755
        info.size = len(payload)
        tf.addfile(info, io.BytesIO(payload))
    return buffer.getvalue()


def _assert_lark_root_missing(user_id: str) -> None:
    root = lark_cli.lark_integration_root(user_id)
    assert not root.exists()


def _config(skills_root: Path):
    return SimpleNamespace(
        skills=SimpleNamespace(
            get_skills_path=lambda: skills_root,
            container_path="/mnt/skills",
            use="deerflow.skills.storage.local_skill_storage:LocalSkillStorage",
        )
    )


def _patch_paths(monkeypatch, base_dir: Path) -> None:
    monkeypatch.setattr(paths_module, "_paths", Paths(base_dir=base_dir))


def _bootstrap_credential_dirs(monkeypatch, tmp_path, *, config: bool = True, data: bool = True):
    """Patch paths and create the per-user config/data dirs; return ``(config_dir, data_dir)``."""
    _patch_paths(monkeypatch, tmp_path / "home")
    config_dir = lark_cli.lark_cli_config_dir("alice")
    data_dir = lark_cli.lark_cli_data_dir("alice")
    if config:
        config_dir.mkdir(parents=True)
    if data:
        data_dir.mkdir(parents=True)
    return config_dir, data_dir


def _windows_acl_env() -> dict[str, str]:
    """Return a PowerShell environment with a clean, ordered ``PSModulePath``.

    The Codex runtime prepends a bundled PowerShell module path that shadows the
    stock ``Microsoft.PowerShell.Security`` module, which makes ``Get-Acl`` fail
    to autoload under ``-NoProfile``. Use the stock Windows PowerShell module path
    so ACL inspection is reliable on any host.
    """
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    modules = f"{system_root}\\system32\\WindowsPowerShell\\v1.0\\Modules;{program_files}\\WindowsPowerShell\\Modules"
    return {**os.environ, "PSModulePath": modules}


def _windows_acl_sids(path: Path) -> set[str]:
    """Return the SIDs granted on *path* (Windows-only, PowerShell resolver).

    ``icacls`` displays localized account names rather than raw SIDs, so we
    translate each ACE IdentityReference back to a SID before asserting.
    """
    cmd = "(Get-Acl -LiteralPath '" + str(path) + "').Access | ForEach-Object { $_.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value }"
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command", cmd],
        capture_output=True,
        text=True,
        check=True,
        env=_windows_acl_env(),
    )
    return {line.strip() for line in out.stdout.splitlines() if line.strip()}


def _windows_acl_protected(path: Path) -> bool:
    """Return whether *path*'s DACL is protected from inheritance (Windows-only)."""
    cmd = "(Get-Acl -LiteralPath '" + str(path) + "').AreAccessRulesProtected"
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command", cmd],
        capture_output=True,
        text=True,
        check=True,
        env=_windows_acl_env(),
    )
    return out.stdout.strip() == "True"


def _windows_acl_owner_sid(path: Path) -> str:
    """Return *path*'s object owner as a raw SID (Windows-only)."""
    cmd = "$acl = Get-Acl -LiteralPath $env:DEER_FLOW_TEST_ACL_PATH; $acl.GetOwner([System.Security.Principal.SecurityIdentifier]).Value"
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command", cmd],
        capture_output=True,
        text=True,
        check=True,
        env={**_windows_acl_env(), "DEER_FLOW_TEST_ACL_PATH": str(path)},
    )
    return out.stdout.strip()


class _FakeWindowsHandle:
    """Real-filesystem-backed stand-in for ``_WindowsTreeHandle`` used by mocks.

    It mirrors the behavior the handle-relative walker relies on (``info``,
    ``set_security``, ``enumerate``, ``open_child``, ``open_or_create_child_dir``,
    ``close``) without touching Win32, so the Windows credential-tree tests still
    run on Linux CI.
    """

    def __init__(
        self,
        path: Path,
        dacl_calls: list[tuple[str, str, bool]],
        *,
        reparse: bool = False,
        apply_fails: bool = False,
        link_count: int = 1,
    ) -> None:
        self.path = path
        self._dacl_calls = dacl_calls
        self._reparse = reparse
        self._apply_fails = apply_fails
        self._link_count = link_count
        self._is_dir = path.is_dir()

    @property
    def info(self):
        return SimpleNamespace(reparse=self._reparse, is_dir=self._is_dir, link_count=self._link_count)

    def set_security(self, owner_sid, *, inheritable_full):
        if self._apply_fails:
            raise RuntimeError("SetSecurityInfo failed")
        self._dacl_calls.append((str(self.path), owner_sid, inheritable_full))

    def enumerate(self):
        if not self._is_dir:
            return iter(())
        try:
            return iter([entry.name for entry in self.path.iterdir()])
        except OSError:
            return iter(())

    def open_child(self, name):
        child = self.path / name
        if child.is_symlink():
            raise ValueError(f"Lark CLI credential path must not be a reparse point: {child}")
        return _FakeWindowsHandle(child, self._dacl_calls, apply_fails=self._apply_fails)

    def open_or_create_child_dir(self, name):
        child = self.path / name
        if child.is_symlink():
            raise ValueError(f"Lark CLI credential path must not be a reparse point: {child}")
        child.mkdir(parents=True, exist_ok=True)
        return _FakeWindowsHandle(child, self._dacl_calls, apply_fails=self._apply_fails)

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def _windows_os_stub() -> SimpleNamespace:
    """Minimal ``os`` stub that forces the Windows code path in unit tests.

    The real ``os`` module is replaced wholesale so ``lark_cli.os.name == "nt"``
    drives the Windows handle-relative walker without touching the host. The
    cross-process hardening lock (``_exclusive_install_lock``) also consults
    ``os.SEEK_END`` when seeking the advisory lock file, so the stub must carry it.
    """
    return SimpleNamespace(name="nt", SEEK_END=os.SEEK_END)


def _patch_windows_hardening(monkeypatch, tmp_path, sid: str = "S-1-5-21-111-222-333-1001"):
    """Set up the Windows path: mock whoami and record handle-bound DACL applies."""
    _patch_paths(monkeypatch, tmp_path / "home")
    monkeypatch.setattr(lark_cli, "os", _windows_os_stub())
    subprocess_calls: list[list[str]] = []
    dacl_calls: list[tuple[str, str, bool]] = []

    def _fake_run(args, **kwargs):
        subprocess_calls.append(list(args))
        if args and args[0] == "whoami":
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout=f'"DOMAIN\\alice","{sid}"\n',
                stderr="",
            )
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(lark_cli.subprocess, "run", _fake_run)

    def _open(path, *, access, reject_reparse=True):
        reparse = path.is_symlink()
        if reparse and reject_reparse:
            raise ValueError(f"Lark CLI credential path must not be a reparse point: {path}")
        return _FakeWindowsHandle(path, dacl_calls, reparse=reparse)

    monkeypatch.setattr(lark_cli, "_open_windows_pinned", _open)

    def _open_or_create(parent, name, *, full_path, access, share):
        child = parent.path / name
        if child.is_symlink():
            raise ValueError(f"Lark CLI credential path must not be a reparse point: {child}")
        child.mkdir(parents=True, exist_ok=True)
        return _FakeWindowsHandle(child, dacl_calls, reparse=child.is_symlink())

    monkeypatch.setattr(lark_cli, "_open_or_create_dir_relative", _open_or_create)
    return subprocess_calls, dacl_calls


def _advance_lark_flow(user_id: str = "alice") -> str:
    with lark_cli._lark_credential_lock(user_id):
        return lark_cli._advance_lark_flow_generation_locked(user_id)


def test_sandbox_lark_cli_env_prepends_managed_linux_runtime() -> None:
    overlay = lark_cli.lark_cli_env_overlay("alice", sandbox_paths=True)

    assert overlay["PATH"].split(":", 1)[0] == "/mnt/integrations/lark-cli/runtime/bin"
    assert overlay["LARKSUITE_CLI_CONFIG_DIR"] == "/mnt/integrations/lark-cli/config"
    assert overlay["LARKSUITE_CLI_DATA_DIR"] == "/mnt/integrations/lark-cli/data"


def test_init_image_launcher_matches_python_constant() -> None:
    """The init image's build script must embed the same launcher as the Gateway.

    Both produce ``bin/lark-cli``; if they drift, the sandbox PATH contract
    breaks for one provisioning mode.
    """
    repo_root = Path(lark_cli.__file__).resolve().parents[5]
    build_script = repo_root / "docker" / "lark-cli-init" / "build-runtime.sh"
    assert build_script.is_file(), f"missing init image build script at {build_script}"
    body = build_script.read_text(encoding="utf-8")
    # The launcher heredoc in the build script must contain the exact script body.
    assert lark_cli.LARK_CLI_SANDBOX_LAUNCHER_SCRIPT.strip() in body


def test_managed_sandbox_runtime_verifies_and_installs_linux_archives(monkeypatch, tmp_path) -> None:
    assert hasattr(lark_cli, "_ensure_managed_sandbox_lark_cli"), "managed sandbox runtime installer is missing"
    _patch_paths(monkeypatch, tmp_path / "home")
    archives = {
        "lark-cli-1.0.65-linux-amd64.tar.gz": _make_lark_cli_binary_tar(b"amd64-binary"),
        "lark-cli-1.0.65-linux-arm64.tar.gz": _make_lark_cli_binary_tar(b"arm64-binary"),
    }
    checksums = "".join(f"{hashlib.sha256(payload).hexdigest()}  {name}\n" for name, payload in archives.items()).encode()
    assets = {"checksums.txt": checksums, **archives}

    monkeypatch.setattr(lark_cli, "_download_lark_release_asset", lambda _version, name, **_kwargs: assets[name])

    runtime = lark_cli._ensure_managed_sandbox_lark_cli("v1.0.65")

    assert (runtime / "linux-amd64" / "lark-cli").read_bytes() == b"amd64-binary"
    assert (runtime / "linux-arm64" / "lark-cli").read_bytes() == b"arm64-binary"
    assert stat.S_IMODE((runtime / "linux-amd64" / "lark-cli").stat().st_mode) == 0o755
    launcher = (runtime / "bin" / "lark-cli").read_text(encoding="utf-8")
    assert "uname -m" in launcher
    assert "x86_64" in launcher and "aarch64" in launcher


def test_managed_sandbox_runtime_rejects_checksum_mismatch(monkeypatch, tmp_path) -> None:
    assert hasattr(lark_cli, "_ensure_managed_sandbox_lark_cli"), "managed sandbox runtime installer is missing"
    _patch_paths(monkeypatch, tmp_path / "home")
    archives = {
        "lark-cli-1.0.65-linux-amd64.tar.gz": _make_lark_cli_binary_tar(b"amd64-binary"),
        "lark-cli-1.0.65-linux-arm64.tar.gz": _make_lark_cli_binary_tar(b"arm64-binary"),
    }
    bad_checksums = "".join(f"{'0' * 64}  {name}\n" for name in archives).encode()
    assets = {"checksums.txt": bad_checksums, **archives}
    monkeypatch.setattr(lark_cli, "_download_lark_release_asset", lambda _version, name, **_kwargs: assets[name])

    with pytest.raises(ValueError, match="checksum"):
        lark_cli._ensure_managed_sandbox_lark_cli("v1.0.65")

    assert not lark_cli.lark_cli_managed_sandbox_dir().exists()


def test_managed_sandbox_runtime_rejects_unsafe_tar_member(monkeypatch, tmp_path) -> None:
    assert hasattr(lark_cli, "_ensure_managed_sandbox_lark_cli"), "managed sandbox runtime installer is missing"
    _patch_paths(monkeypatch, tmp_path / "home")
    unsafe = _make_lark_cli_binary_tar(b"binary", member_name="../lark-cli")
    safe = _make_lark_cli_binary_tar(b"binary")
    archives = {
        "lark-cli-1.0.65-linux-amd64.tar.gz": unsafe,
        "lark-cli-1.0.65-linux-arm64.tar.gz": safe,
    }
    checksums = "".join(f"{hashlib.sha256(payload).hexdigest()}  {name}\n" for name, payload in archives.items()).encode()
    assets = {"checksums.txt": checksums, **archives}
    monkeypatch.setattr(lark_cli, "_download_lark_release_asset", lambda _version, name, **_kwargs: assets[name])

    with pytest.raises(ValueError, match="Unsafe Lark CLI runtime archive member"):
        lark_cli._ensure_managed_sandbox_lark_cli("v1.0.65")


def test_managed_sandbox_runtime_accepts_prestaged_airgapped_tree(monkeypatch, tmp_path) -> None:
    _patch_paths(monkeypatch, tmp_path / "home")
    source = tmp_path / "pre-staged"
    for arch in ("amd64", "arm64"):
        binary = source / f"linux-{arch}" / "lark-cli"
        binary.parent.mkdir(parents=True)
        binary.write_bytes(f"{arch}-binary".encode())
        binary.chmod(0o755)
    launcher = source / "bin" / "lark-cli"
    launcher.parent.mkdir(parents=True)
    launcher.write_text("#!/bin/sh\n", encoding="utf-8")
    launcher.chmod(0o755)
    monkeypatch.setenv(lark_cli.LARK_CLI_SANDBOX_RUNTIME_SOURCE_ENV, str(source))
    monkeypatch.setattr(
        lark_cli,
        "_download_lark_release_asset",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("air-gapped install must not download")),
    )

    runtime = lark_cli._ensure_managed_sandbox_lark_cli("v1.0.65")

    assert (runtime / "linux-amd64" / "lark-cli").read_bytes() == b"amd64-binary"
    assert (runtime / "linux-arm64" / "lark-cli").read_bytes() == b"arm64-binary"


def test_managed_sandbox_runtime_rejects_any_symlink_in_prestaged_tree(monkeypatch, tmp_path) -> None:
    _patch_paths(monkeypatch, tmp_path / "home")
    source = tmp_path / "pre-staged"
    for arch in ("amd64", "arm64"):
        binary = source / f"linux-{arch}" / "lark-cli"
        binary.parent.mkdir(parents=True)
        binary.write_bytes(f"{arch}-binary".encode())
        binary.chmod(0o755)
    launcher = source / "bin" / "lark-cli"
    launcher.parent.mkdir(parents=True)
    launcher.write_text("#!/bin/sh\n", encoding="utf-8")
    launcher.chmod(0o755)
    outside = tmp_path / "outside-secret"
    outside.write_text("must-not-be-copied", encoding="utf-8")
    try:
        (source / "extra-link").symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlinks are not available: {exc}")
    monkeypatch.setenv(lark_cli.LARK_CLI_SANDBOX_RUNTIME_SOURCE_ENV, str(source))

    with pytest.raises(ValueError, match="symlink"):
        lark_cli._ensure_managed_sandbox_lark_cli("v1.0.65")

    assert not lark_cli.lark_cli_managed_sandbox_dir().exists()


def test_managed_sandbox_runtime_rejects_non_executable_prestaged_binary(monkeypatch, tmp_path) -> None:
    _patch_paths(monkeypatch, tmp_path / "home")
    source = tmp_path / "pre-staged"
    for arch in ("amd64", "arm64"):
        binary = source / f"linux-{arch}" / "lark-cli"
        binary.parent.mkdir(parents=True)
        binary.write_bytes(f"{arch}-binary".encode())
        binary.chmod(0o755)
    (source / "linux-arm64" / "lark-cli").chmod(0o644)
    launcher = source / "bin" / "lark-cli"
    launcher.parent.mkdir(parents=True)
    launcher.write_text("#!/bin/sh\n", encoding="utf-8")
    launcher.chmod(0o755)
    monkeypatch.setenv(lark_cli.LARK_CLI_SANDBOX_RUNTIME_SOURCE_ENV, str(source))

    with pytest.raises(ValueError, match="executable"):
        lark_cli._ensure_managed_sandbox_lark_cli("v1.0.65")

    assert not lark_cli.lark_cli_managed_sandbox_dir().exists()


def test_concurrent_managed_sandbox_runtime_installs_serialize_replacement(monkeypatch, tmp_path) -> None:
    _patch_paths(monkeypatch, tmp_path / "home")
    source = tmp_path / "pre-staged"
    for arch in ("amd64", "arm64"):
        binary = source / f"linux-{arch}" / "lark-cli"
        binary.parent.mkdir(parents=True)
        binary.write_bytes(f"{arch}-binary".encode())
        binary.chmod(0o755)
    launcher = source / "bin" / "lark-cli"
    launcher.parent.mkdir(parents=True)
    launcher.write_text("#!/bin/sh\n", encoding="utf-8")
    launcher.chmod(0o755)
    monkeypatch.setenv(lark_cli.LARK_CLI_SANDBOX_RUNTIME_SOURCE_ENV, str(source))

    real_validate = lark_cli._validate_lark_cli_sandbox_runtime
    start = threading.Barrier(2)
    state_lock = threading.Lock()
    active = 0
    max_active = 0

    def _slow_validate(root):
        nonlocal active, max_active
        with state_lock:
            active += 1
            max_active = max(max_active, active)
        try:
            time.sleep(0.15)
            return real_validate(root)
        finally:
            with state_lock:
                active -= 1

    def _install():
        start.wait()
        return lark_cli._ensure_managed_sandbox_lark_cli("v1.0.65")

    monkeypatch.setattr(lark_cli, "_validate_lark_cli_sandbox_runtime", _slow_validate)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [future.result(timeout=5) for future in [pool.submit(_install) for _ in range(2)]]

    assert results[0] == results[1] == lark_cli.lark_cli_managed_sandbox_dir()
    assert max_active == 1
    assert not list(results[0].parent.glob(".replacing-sandbox-cli-*"))


def test_install_lark_integration_installs_one_readonly_pack_for_all_users(monkeypatch, tmp_path):
    reset_skill_storage()
    _patch_paths(monkeypatch, tmp_path / "home")
    skills_root = tmp_path / "skills"
    (skills_root / "public").mkdir(parents=True)
    (skills_root / "custom").mkdir()
    config = _config(skills_root)
    archive = _make_lark_cli_source_zip(tmp_path)

    monkeypatch.setattr(lark_cli, "probe_lark_cli", lambda: lark_cli.LarkCliProbe(available=True, path="/usr/bin/lark-cli", version="v1.0.65"))
    monkeypatch.setattr(lark_cli, "probe_lark_auth", lambda _user_id, **_kwargs: lark_cli.LarkAuthProbe(status="not_configured", message="not configured"))

    result = lark_cli.install_lark_integration("alice", config, source_archive=archive)

    assert result.success is True
    assert "lark-doc" in result.installed_skills
    assert result.status.installed is True
    root = lark_cli.lark_integration_root("alice")
    assert root == lark_cli.lark_integration_root("bob")
    assert root == tmp_path / "home" / "integrations" / "skills" / "lark-cli"
    assert (root / "lark-doc" / "SKILL.md").is_file()
    assert (root / lark_cli.LARK_CLI_MANIFEST_FILE).is_file()
    shared_content = (root / "lark-shared" / "SKILL.md").read_text(encoding="utf-8")
    assert "?settings=integrations" in shared_content
    assert "不要要求用户在终端执行" in shared_content
    assert "Exact OAuth scope" in shared_content

    storage = UserScopedSkillStorage("alice", host_path=str(skills_root), app_config=config)
    skills = storage.load_skills(enabled_only=False)
    lark_doc = next(skill for skill in skills if skill.name == "lark-doc")
    assert lark_doc.category == SkillCategory.INTEGRATION
    assert lark_doc.get_container_file_path("/mnt/skills") == "/mnt/skills/integrations/lark-cli/lark-doc/SKILL.md"
    assert lark_doc.enabled is True

    bob_storage = UserScopedSkillStorage("bob", host_path=str(skills_root), app_config=config)
    bob_lark_doc = next(skill for skill in bob_storage.load_skills(enabled_only=False) if skill.name == "lark-doc")
    assert bob_lark_doc.category == SkillCategory.INTEGRATION
    assert bob_lark_doc.skill_file == root / "lark-doc" / "SKILL.md"
    reset_skill_storage()


def test_aio_install_provisions_matching_linux_sandbox_runtime(monkeypatch, tmp_path) -> None:
    reset_skill_storage()
    _patch_paths(monkeypatch, tmp_path / "home")
    skills_root = tmp_path / "skills"
    (skills_root / "public").mkdir(parents=True)
    (skills_root / "custom").mkdir()
    config = _config(skills_root)
    config.sandbox = SimpleNamespace(use="deerflow.community.aio_sandbox:AioSandboxProvider")
    archive = _make_lark_cli_source_zip(tmp_path)
    provisioned_versions: list[str] = []

    monkeypatch.setattr(lark_cli, "probe_lark_cli", lambda: lark_cli.LarkCliProbe(available=True, path="/usr/bin/lark-cli", version="v1.0.65"))
    monkeypatch.setattr(lark_cli, "probe_lark_auth", lambda _user_id, **_kwargs: lark_cli.LarkAuthProbe(status="not_configured", message="not configured"))
    monkeypatch.setattr(
        lark_cli,
        "_ensure_managed_sandbox_lark_cli",
        lambda version: provisioned_versions.append(version) or lark_cli.lark_cli_managed_sandbox_dir(),
    )

    result = lark_cli.install_lark_integration("alice", config, source_archive=archive)

    assert result.success is True
    assert provisioned_versions == ["v1.0.65"]
    reset_skill_storage()


def test_remote_provisioner_install_skips_gateway_sandbox_runtime(monkeypatch, tmp_path) -> None:
    reset_skill_storage()
    _patch_paths(monkeypatch, tmp_path / "home")
    skills_root = tmp_path / "skills"
    (skills_root / "public").mkdir(parents=True)
    (skills_root / "custom").mkdir()
    config = _config(skills_root)
    config.sandbox = SimpleNamespace(
        use="deerflow.community.aio_sandbox:AioSandboxProvider",
        provisioner_url="http://provisioner:8002",
    )
    archive = _make_lark_cli_source_zip(tmp_path)
    provisioned_versions: list[str] = []

    monkeypatch.setattr(lark_cli, "probe_lark_cli", lambda: lark_cli.LarkCliProbe(available=True, path="/usr/bin/lark-cli", version="v1.0.65"))
    monkeypatch.setattr(lark_cli, "probe_lark_auth", lambda _user_id, **_kwargs: lark_cli.LarkAuthProbe(status="not_configured", message="not configured"))
    monkeypatch.setattr(
        lark_cli,
        "_ensure_managed_sandbox_lark_cli",
        lambda version: provisioned_versions.append(version) or lark_cli.lark_cli_managed_sandbox_dir(),
    )

    result = lark_cli.install_lark_integration("alice", config, source_archive=archive)

    assert result.success is True
    # Remote provisioner mode gets the runtime from an init container, so the
    # Gateway must not download Linux binaries at install time.
    assert provisioned_versions == []
    reset_skill_storage()


def test_status_runtime_mode_none_for_non_aio(monkeypatch, tmp_path) -> None:
    config = _config(tmp_path / "skills")
    config.sandbox = SimpleNamespace(use="deerflow.sandbox.local:LocalSandboxProvider")
    mode, ready, detail = lark_cli._resolve_sandbox_runtime_readiness(config, probe=True)
    assert mode == "none"
    assert ready is False
    assert detail


def test_status_runtime_mode_gateway_download_ready(monkeypatch, tmp_path) -> None:
    _patch_paths(monkeypatch, tmp_path / "home")
    config = _config(tmp_path / "skills")
    config.sandbox = SimpleNamespace(use="deerflow.community.aio_sandbox:AioSandboxProvider")

    # Stage a valid runtime dir so validation passes.
    runtime = lark_cli.lark_cli_managed_sandbox_dir()
    (runtime / "bin").mkdir(parents=True)
    (runtime / "bin" / "lark-cli").write_text("#!/bin/sh\n", encoding="utf-8")
    (runtime / "bin" / "lark-cli").chmod(0o755)
    for arch in lark_cli.LARK_CLI_LINUX_ARCHES:
        (runtime / f"linux-{arch}").mkdir(parents=True)
        target = runtime / f"linux-{arch}" / "lark-cli"
        target.write_bytes(b"\x7fELF")
        target.chmod(0o755)

    mode, ready, detail = lark_cli._resolve_sandbox_runtime_readiness(config, probe=True)
    assert mode == "gateway-download"
    assert ready is True
    assert detail is None


def test_status_runtime_mode_gateway_download_not_ready(monkeypatch, tmp_path) -> None:
    _patch_paths(monkeypatch, tmp_path / "home")
    config = _config(tmp_path / "skills")
    config.sandbox = SimpleNamespace(use="deerflow.community.aio_sandbox:AioSandboxProvider")
    mode, ready, detail = lark_cli._resolve_sandbox_runtime_readiness(config, probe=True)
    assert mode == "gateway-download"
    assert ready is False
    assert detail


def test_status_runtime_mode_init_container_ready(monkeypatch, tmp_path) -> None:
    config = _config(tmp_path / "skills")
    config.sandbox = SimpleNamespace(
        use="deerflow.community.aio_sandbox:AioSandboxProvider",
        provisioner_url="http://provisioner:8002",
    )
    monkeypatch.setattr(lark_cli, "_probe_provisioner_capabilities", lambda _config: {"lark_cli_init_image": True, "lark_cli_broker_image": False})
    mode, ready, detail = lark_cli._resolve_sandbox_runtime_readiness(config, probe=True)
    assert mode == "init-container"
    assert ready is True
    assert detail is None


def test_status_runtime_mode_broker_supersedes_init_container(monkeypatch, tmp_path) -> None:
    config = _config(tmp_path / "skills")
    config.sandbox = SimpleNamespace(
        use="deerflow.community.aio_sandbox:AioSandboxProvider",
        provisioner_url="http://provisioner:8002",
    )
    # Broker (Pattern B) wins even when the init image is also configured.
    monkeypatch.setattr(lark_cli, "_probe_provisioner_capabilities", lambda _config: {"lark_cli_init_image": True, "lark_cli_broker_image": True})
    mode, ready, detail = lark_cli._resolve_sandbox_runtime_readiness(config, probe=True)
    assert mode == "broker"
    assert ready is True
    assert detail is None


def test_status_runtime_mode_init_container_not_configured(monkeypatch, tmp_path) -> None:
    config = _config(tmp_path / "skills")
    config.sandbox = SimpleNamespace(
        use="deerflow.community.aio_sandbox:AioSandboxProvider",
        provisioner_url="http://provisioner:8002",
    )
    monkeypatch.setattr(lark_cli, "_probe_provisioner_capabilities", lambda _config: {"lark_cli_init_image": False, "lark_cli_broker_image": False})
    mode, ready, detail = lark_cli._resolve_sandbox_runtime_readiness(config, probe=True)
    assert mode == "init-container"
    assert ready is False
    assert detail


def test_status_runtime_mode_init_container_unreachable(monkeypatch, tmp_path) -> None:
    config = _config(tmp_path / "skills")
    config.sandbox = SimpleNamespace(
        use="deerflow.community.aio_sandbox:AioSandboxProvider",
        provisioner_url="http://provisioner:8002",
    )
    monkeypatch.setattr(lark_cli, "_probe_provisioner_capabilities", lambda _config: None)
    mode, ready, detail = lark_cli._resolve_sandbox_runtime_readiness(config, probe=True)
    assert mode == "init-container"
    assert ready is False
    assert detail


def test_status_runtime_probe_skipped_when_not_requested(monkeypatch, tmp_path) -> None:
    config = _config(tmp_path / "skills")
    config.sandbox = SimpleNamespace(
        use="deerflow.community.aio_sandbox:AioSandboxProvider",
        provisioner_url="http://provisioner:8002",
    )

    def _fail(_config):  # pragma: no cover - must not be called
        raise AssertionError("provisioner should not be probed when probe=False")

    monkeypatch.setattr(lark_cli, "_probe_provisioner_capabilities", _fail)
    mode, ready, detail = lark_cli._resolve_sandbox_runtime_readiness(config, probe=False)
    assert mode == "init-container"
    assert ready is False
    assert detail is None


def _reset_broker_mode_cache() -> None:
    if hasattr(lark_cli.sandbox_lark_broker_active, "_cache"):
        del lark_cli.sandbox_lark_broker_active._cache


def test_sandbox_lark_broker_active_uses_tight_hot_path_timeout(monkeypatch, tmp_path) -> None:
    """The per-bash-call broker probe must use the tight hot-path timeout, not the
    5s Settings-status budget, so non-broker remote-provisioner users don't pay a
    multi-second latency hit on the first lark-cli call per TTL."""
    _reset_broker_mode_cache()
    config = _config(tmp_path / "skills")
    config.sandbox = SimpleNamespace(
        use="deerflow.community.aio_sandbox:AioSandboxProvider",
        provisioner_url="http://provisioner:8002",
    )
    seen: dict[str, float] = {}

    def _capture(_config, *, timeout):
        seen["timeout"] = timeout
        return {"lark_cli_init_image": False, "lark_cli_broker_image": True}

    monkeypatch.setattr(lark_cli, "_probe_provisioner_capabilities", _capture)
    try:
        assert lark_cli.sandbox_lark_broker_active(config) is True
        assert seen["timeout"] == lark_cli.LARK_BROKER_MODE_PROBE_TIMEOUT_SECONDS
    finally:
        _reset_broker_mode_cache()


def test_sandbox_lark_broker_active_caches_negative_result(monkeypatch, tmp_path) -> None:
    """A non-broker result is cached (longer TTL) so the hot path stops probing."""
    _reset_broker_mode_cache()
    config = _config(tmp_path / "skills")
    config.sandbox = SimpleNamespace(
        use="deerflow.community.aio_sandbox:AioSandboxProvider",
        provisioner_url="http://provisioner:8002",
    )
    calls = {"n": 0}

    def _probe(_config, *, timeout):
        calls["n"] += 1
        return {"lark_cli_init_image": True, "lark_cli_broker_image": False}

    monkeypatch.setattr(lark_cli, "_probe_provisioner_capabilities", _probe)
    try:
        assert lark_cli.sandbox_lark_broker_active(config) is False
        assert lark_cli.sandbox_lark_broker_active(config) is False
        # Second call served from cache — the provisioner is probed only once.
        assert calls["n"] == 1
    finally:
        _reset_broker_mode_cache()


def test_sandbox_lark_broker_active_false_without_remote_provisioner(monkeypatch, tmp_path) -> None:
    """Local AIO (no provisioner URL) never probes and is never broker mode."""
    _reset_broker_mode_cache()
    config = _config(tmp_path / "skills")
    config.sandbox = SimpleNamespace(use="deerflow.community.aio_sandbox:AioSandboxProvider")

    def _fail(_config, *, timeout):  # pragma: no cover - must not be called
        raise AssertionError("no provisioner should be probed without a provisioner_url")

    monkeypatch.setattr(lark_cli, "_probe_provisioner_capabilities", _fail)
    try:
        assert lark_cli.sandbox_lark_broker_active(config) is False
    finally:
        _reset_broker_mode_cache()


def test_install_lark_integration_is_idempotent_across_reinstalls(monkeypatch, tmp_path):
    reset_skill_storage()
    _patch_paths(monkeypatch, tmp_path / "home")
    skills_root = tmp_path / "skills"
    (skills_root / "public").mkdir(parents=True)
    (skills_root / "custom").mkdir()
    config = _config(skills_root)
    archive = _make_lark_cli_source_zip(tmp_path)

    monkeypatch.setattr(lark_cli, "probe_lark_cli", lambda: lark_cli.LarkCliProbe(available=True, path="/usr/bin/lark-cli", version="v1.0.65"))
    monkeypatch.setattr(lark_cli, "probe_lark_auth", lambda _user_id, **_kwargs: lark_cli.LarkAuthProbe(status="not_configured", message="not configured"))

    first = lark_cli.install_lark_integration("alice", config, source_archive=archive)
    root = lark_cli.lark_integration_root("alice")
    # Drop a stray file so the reinstall must replace the whole tree, not merge.
    stray = root / "lark-doc" / "stray.txt"
    stray.write_text("stale", encoding="utf-8")

    second = lark_cli.install_lark_integration("alice", config, source_archive=archive)

    assert first.installed_skills == second.installed_skills
    assert second.status.installed is True
    assert (root / "lark-doc" / "SKILL.md").is_file()
    assert not stray.exists()
    # No leftover backup/staging dirs beside the target after a reinstall.
    parent = root.parent
    leftovers = [p.name for p in parent.iterdir() if p.name not in {lark_cli.INTEGRATION_ID, ".lark-cli.install.lock"}]
    assert leftovers == []
    reset_skill_storage()


@pytest.mark.parametrize("_attempt", range(5))
def test_concurrent_lark_skill_reinstalls_serialize_atomic_replacement(monkeypatch, tmp_path, _attempt) -> None:
    _patch_paths(monkeypatch, tmp_path / "home")
    archive = _make_lark_cli_source_zip(tmp_path)
    real_extract = lark_cli._extract_lark_skills
    start = threading.Barrier(2)
    state_lock = threading.Lock()
    active = 0
    max_active = 0

    def _slow_extract(zf, destination):
        nonlocal active, max_active
        with state_lock:
            active += 1
            max_active = max(max_active, active)
        try:
            time.sleep(0.15)
            return real_extract(zf, destination)
        finally:
            with state_lock:
                active -= 1

    def _install():
        start.wait()
        return lark_cli._install_lark_skills_from_archive("alice", archive, version="v1.0.65")

    monkeypatch.setattr(lark_cli, "_extract_lark_skills", _slow_extract)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(_install) for _ in range(2)]
        results = [future.result(timeout=5) for future in futures]

    assert results[0] == results[1]
    assert max_active == 1
    root = lark_cli.lark_integration_root()
    assert (root / "lark-doc" / "SKILL.md").is_file()
    assert not list(root.parent.glob(".replacing-lark-cli-*"))


@pytest.mark.skipif(
    "fork" not in multiprocessing.get_all_start_methods() or lark_cli.fcntl is None,
    reason="requires POSIX fork and fcntl",
)
def test_concurrent_lark_skill_reinstalls_serialize_across_processes(monkeypatch, tmp_path) -> None:
    _patch_paths(monkeypatch, tmp_path / "home")
    archive = _make_lark_cli_source_zip(tmp_path)
    real_extract = lark_cli._extract_lark_skills
    context = multiprocessing.get_context("fork")
    start = context.Barrier(2)
    active = context.Value("i", 0)
    max_active = context.Value("i", 0)
    results = context.Queue()

    def _slow_extract(zf, destination):
        with active.get_lock(), max_active.get_lock():
            active.value += 1
            max_active.value = max(max_active.value, active.value)
        try:
            time.sleep(0.2)
            return real_extract(zf, destination)
        finally:
            with active.get_lock():
                active.value -= 1

    def _install():
        try:
            start.wait(timeout=5)
            installed, digest = lark_cli._install_lark_skills_from_archive("alice", archive, version="v1.0.65")
            results.put((installed, digest, None))
        except BaseException as exc:  # noqa: BLE001 - propagate child failure
            results.put((None, None, repr(exc)))

    monkeypatch.setattr(lark_cli, "_extract_lark_skills", _slow_extract)
    processes = [context.Process(target=_install) for _ in range(2)]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=10)

    assert [process.exitcode for process in processes] == [0, 0]
    child_results = [results.get(timeout=2) for _ in processes]
    assert all(error is None for _installed, _digest, error in child_results), child_results
    assert child_results[0][:2] == child_results[1][:2]
    assert max_active.value == 1
    assert not list(lark_cli.lark_integration_root().parent.glob(".replacing-lark-cli-*"))


def test_install_lark_integration_succeeds_when_backup_cleanup_fails(monkeypatch, tmp_path):
    reset_skill_storage()
    _patch_paths(monkeypatch, tmp_path / "home")
    skills_root = tmp_path / "skills"
    (skills_root / "public").mkdir(parents=True)
    (skills_root / "custom").mkdir()
    config = _config(skills_root)
    archive = _make_lark_cli_source_zip(tmp_path)

    monkeypatch.setattr(lark_cli, "probe_lark_cli", lambda: lark_cli.LarkCliProbe(available=True, path="/usr/bin/lark-cli", version="v1.0.65"))
    monkeypatch.setattr(lark_cli, "probe_lark_auth", lambda _user_id, **_kwargs: lark_cli.LarkAuthProbe(status="not_configured", message="not configured"))

    # First install lays down the target so the reinstall has a backup to clean.
    lark_cli.install_lark_integration("alice", config, source_archive=archive)

    real_rmtree = shutil.rmtree
    forced_raises = {"count": 0}

    def _rmtree(path, *args, **kwargs):
        # The post-rename backup deletion is best-effort and now passes
        # ignore_errors=True, so a transient FS error there must not flip a
        # successful install into a failure. Force any rmtree that does *not*
        # ignore errors to raise, proving the success path no longer depends on
        # a fragile backup cleanup.
        if kwargs.get("ignore_errors"):
            return real_rmtree(path, *args, **kwargs)
        forced_raises["count"] += 1
        raise OSError("transient FS error during backup cleanup")

    monkeypatch.setattr(lark_cli.shutil, "rmtree", _rmtree)

    result = lark_cli.install_lark_integration("alice", config, source_archive=archive)

    assert result.success is True
    root = lark_cli.lark_integration_root("alice")
    assert (root / "lark-doc" / "SKILL.md").is_file()
    # No non-ignoring rmtree is relied upon on the success path, and no leftover
    # backup dir remains beside the target after the reinstall.
    assert forced_raises["count"] == 0
    leftovers = [p.name for p in root.parent.iterdir() if p.name not in {lark_cli.INTEGRATION_ID, ".lark-cli.install.lock"}]
    assert leftovers == []
    reset_skill_storage()


def test_install_lark_integration_records_content_sha_in_manifest(monkeypatch, tmp_path):
    reset_skill_storage()
    _patch_paths(monkeypatch, tmp_path / "home")
    skills_root = tmp_path / "skills"
    (skills_root / "public").mkdir(parents=True)
    (skills_root / "custom").mkdir()
    config = _config(skills_root)
    archive = _make_lark_cli_source_zip(tmp_path)

    monkeypatch.setattr(lark_cli, "probe_lark_cli", lambda: lark_cli.LarkCliProbe(available=True, path="/usr/bin/lark-cli", version="v1.0.65"))
    monkeypatch.setattr(lark_cli, "probe_lark_auth", lambda _user_id, **_kwargs: lark_cli.LarkAuthProbe(status="not_configured", message="not configured"))

    lark_cli.install_lark_integration("alice", config, source_archive=archive)

    manifest = json.loads((lark_cli.lark_integration_root("alice") / lark_cli.LARK_CLI_MANIFEST_FILE).read_text(encoding="utf-8"))
    assert manifest["version"] == "v1.0.65"
    assert isinstance(manifest["content_sha256"], str)
    assert len(manifest["content_sha256"]) == 64
    reset_skill_storage()


def test_install_lark_integration_reports_content_change_on_reinstall(monkeypatch, tmp_path):
    reset_skill_storage()
    _patch_paths(monkeypatch, tmp_path / "home")
    skills_root = tmp_path / "skills"
    (skills_root / "public").mkdir(parents=True)
    (skills_root / "custom").mkdir()
    config = _config(skills_root)
    archive = _make_lark_cli_source_zip(tmp_path)

    monkeypatch.setattr(lark_cli, "probe_lark_cli", lambda: lark_cli.LarkCliProbe(available=True, path="/usr/bin/lark-cli", version="v1.0.65"))
    monkeypatch.setattr(lark_cli, "probe_lark_auth", lambda _user_id, **_kwargs: lark_cli.LarkAuthProbe(status="not_configured", message="not configured"))

    first = lark_cli.install_lark_integration("alice", config, source_archive=archive)
    assert "content changed" not in first.message

    changed_dir = tmp_path / "changed"
    changed_dir.mkdir()
    changed_archive = _make_lark_cli_source_zip(changed_dir)
    with zipfile.ZipFile(changed_archive, "a") as zf:
        zf.writestr("cli-1.0.65/skills/lark-doc/references/extra.md", "# extra content\n")

    second = lark_cli.install_lark_integration("alice", config, source_archive=changed_archive)
    assert "content changed" in second.message
    reset_skill_storage()


def test_install_lark_integration_rejects_zip_slip_member(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path / "home")
    config = _config(tmp_path / "skills")
    archive = _make_lark_cli_source_zip(tmp_path)
    with zipfile.ZipFile(archive, "a") as zf:
        zf.writestr("../evil.txt", "escape")

    with pytest.raises(ValueError, match="Unsafe Lark CLI archive member"):
        lark_cli.install_lark_integration("alice", config, source_archive=archive)

    _assert_lark_root_missing("alice")


def test_install_lark_integration_rejects_symlink_member(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path / "home")
    config = _config(tmp_path / "skills")
    archive = _make_lark_cli_source_zip(tmp_path)
    link_info = zipfile.ZipInfo("cli-1.0.65/skills/lark-doc/references/link")
    link_info.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(archive, "a") as zf:
        zf.writestr(link_info, "target")

    with pytest.raises(ValueError, match="Unsafe Lark CLI archive member"):
        lark_cli.install_lark_integration("alice", config, source_archive=archive)

    _assert_lark_root_missing("alice")


def test_install_lark_integration_rejects_executable_binary_member(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path / "home")
    config = _config(tmp_path / "skills")
    archive = _make_lark_cli_source_zip(tmp_path)
    with zipfile.ZipFile(archive, "a") as zf:
        zf.writestr("cli-1.0.65/skills/lark-doc/bin/tool", b"\x7fELFbinary")

    with pytest.raises(ValueError, match="executable binary member"):
        lark_cli.install_lark_integration("alice", config, source_archive=archive)

    _assert_lark_root_missing("alice")


def test_install_lark_integration_rejects_oversized_extraction(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path / "home")
    config = _config(tmp_path / "skills")
    archive = _make_lark_cli_source_zip(tmp_path)
    monkeypatch.setattr(lark_cli, "LARK_CLI_MAX_EXTRACTED_BYTES", 128)

    with pytest.raises(ValueError, match="expands to too much data"):
        lark_cli.install_lark_integration("alice", config, source_archive=archive)

    _assert_lark_root_missing("alice")


def test_install_lark_integration_rejects_missing_required_skill(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path / "home")
    config = _config(tmp_path / "skills")
    archive = _make_lark_cli_source_zip(tmp_path, omit_skill="lark-doc")

    with pytest.raises(ValueError, match="missing required skills: lark-doc"):
        lark_cli.install_lark_integration("alice", config, source_archive=archive)

    _assert_lark_root_missing("alice")


def test_install_lark_integration_rejects_renamed_skill_metadata(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path / "home")
    config = _config(tmp_path / "skills")
    archive = _make_lark_cli_source_zip(tmp_path, renamed_skill="lark-doc")

    with pytest.raises(ValueError, match="declares name 'lark-doc-renamed'"):
        lark_cli.install_lark_integration("alice", config, source_archive=archive)

    _assert_lark_root_missing("alice")


def test_fallback_and_docker_lark_cli_versions_match():
    dockerfile = Path(__file__).resolve().parents[1] / "Dockerfile"
    match = re.search(r"^ARG LARK_CLI_NPM_VERSION=(?P<version>\S+)$", dockerfile.read_text(encoding="utf-8"), re.MULTILINE)

    assert match is not None
    assert lark_cli.LARK_CLI_NPM_VERSION == match.group("version")
    assert lark_cli.FALLBACK_LARK_CLI_VERSION == f"v{lark_cli.LARK_CLI_NPM_VERSION}"


def test_resolve_lark_cli_path_prefers_managed_gateway_cli(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path / "home")
    managed_bin = lark_cli.lark_cli_managed_gateway_dir() / "node_modules" / ".bin" / "lark-cli"
    managed_bin.parent.mkdir(parents=True)
    managed_bin.write_text("#!/bin/sh\n", encoding="utf-8")

    monkeypatch.setattr(lark_cli.shutil, "which", lambda _name: "/usr/bin/lark-cli")

    assert lark_cli._resolve_lark_cli_path() == str(managed_bin)


def test_install_managed_gateway_lark_cli_uses_deerflow_prefix(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path / "home")
    captured: dict[str, object] = {}

    monkeypatch.setattr(lark_cli.shutil, "which", lambda name: "/usr/bin/npm" if name == "npm" else None)

    def _run(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        managed_bin = lark_cli.lark_cli_managed_gateway_dir() / "node_modules" / ".bin" / "lark-cli"
        managed_bin.parent.mkdir(parents=True)
        managed_bin.write_text("#!/bin/sh\n", encoding="utf-8")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(lark_cli.subprocess, "run", _run)
    monkeypatch.setattr(lark_cli, "_probe_lark_cli_at_path", lambda path: lark_cli.LarkCliProbe(available=True, path=path, version="lark-cli VERSION 1.2.3"))

    result = lark_cli._install_managed_gateway_lark_cli("v1.2.3")

    assert result.available is True
    assert result.version == "lark-cli VERSION 1.2.3"
    assert captured["args"] == [
        "/usr/bin/npm",
        "install",
        "--prefix",
        str(lark_cli.lark_cli_managed_gateway_dir()),
        "--no-audit",
        "--no-fund",
        "@larksuite/cli@1.2.3",
    ]


def test_install_lark_integration_installs_managed_gateway_cli_before_skill_pack(monkeypatch, tmp_path):
    reset_skill_storage()
    _patch_paths(monkeypatch, tmp_path / "home")
    skills_root = tmp_path / "skills"
    (skills_root / "public").mkdir(parents=True)
    (skills_root / "custom").mkdir()
    config = _config(skills_root)
    archive = _make_lark_cli_source_zip(tmp_path)
    downloaded_versions: list[str] = []

    monkeypatch.setattr(lark_cli, "probe_lark_auth", lambda _user_id, **_kwargs: lark_cli.LarkAuthProbe(status="not_configured", message="not configured"))
    monkeypatch.setattr(lark_cli, "_ensure_managed_gateway_lark_cli", lambda: lark_cli.LarkCliProbe(available=True, path="/managed/bin/lark-cli", version="lark-cli VERSION 9.9.9"))

    def _download(version: str) -> Path:
        downloaded_versions.append(version)
        return archive

    monkeypatch.setattr(lark_cli, "_download_lark_archive", _download)

    result = lark_cli.install_lark_integration("alice", config)

    assert downloaded_versions == ["v9.9.9"]
    assert result.status.manifest_version == "v9.9.9"
    reset_skill_storage()


def test_resolve_latest_lark_cli_version_uses_release_tag(monkeypatch):
    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({"tag_name": "v1.2.3"}).encode("utf-8")

    monkeypatch.setattr(lark_cli.urllib.request, "urlopen", lambda *a, **k: _Resp())
    assert lark_cli._resolve_latest_lark_cli_version() == "v1.2.3"


def test_resolve_latest_lark_cli_version_falls_back_on_error(monkeypatch):
    def _boom(*a, **k):
        raise OSError("network down")

    monkeypatch.setattr(lark_cli.urllib.request, "urlopen", _boom)
    assert lark_cli._resolve_latest_lark_cli_version() == lark_cli.FALLBACK_LARK_CLI_VERSION


def test_lark_archive_url_rejects_invalid_version_tag():
    with pytest.raises(ValueError, match="Invalid Lark CLI version tag"):
        lark_cli._lark_archive_url("v1.2.3/../../evil")


def test_start_lark_auth_returns_browser_url(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path / "home")
    captured: dict[str, object] = {}

    def _run(args, **kwargs):
        captured["args"] = list(args)
        return {
            "verification_url": "https://open.feishu.cn/auth/mock",
            "device_code": "device-code",
            "expires_in": 600,
        }

    monkeypatch.setattr(lark_cli, "_require_lark_cli_path", lambda: "/usr/bin/lark-cli")
    monkeypatch.setattr(
        lark_cli,
        "_run_lark_cli_json",
        lambda args, **kwargs: _run(args, **kwargs),
    )

    result = lark_cli.start_lark_auth("alice", domains=("calendar",), recommend=True)

    assert result.verification_url == "https://open.feishu.cn/auth/mock"
    assert result.device_code == "device-code"
    assert result.generation
    assert json.loads(lark_cli._lark_flow_state_path("alice").read_text(encoding="utf-8")) == {"generation": result.generation}
    assert captured["args"] == [
        "/usr/bin/lark-cli",
        "auth",
        "login",
        "--no-wait",
        "--json",
        "--recommend",
        "--domain",
        "calendar",
    ]


def test_start_lark_auth_uses_minimal_login_by_default(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path / "home")
    captured: dict[str, object] = {}

    def _run(args, **kwargs):
        captured["args"] = list(args)
        return {
            "verification_url": "https://open.feishu.cn/auth/mock",
            "device_code": "device-code",
            "expires_in": 600,
        }

    monkeypatch.setattr(lark_cli, "_require_lark_cli_path", lambda: "/usr/bin/lark-cli")
    monkeypatch.setattr(
        lark_cli,
        "_run_lark_cli_json",
        lambda args, **kwargs: _run(args, **kwargs),
    )

    result = lark_cli.start_lark_auth("alice")

    assert result.verification_url == "https://open.feishu.cn/auth/mock"
    assert captured["args"] == [
        "/usr/bin/lark-cli",
        "auth",
        "login",
        "--no-wait",
        "--json",
    ]


def test_start_lark_auth_reuses_parent_flow_generation(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path / "home")
    generation = _advance_lark_flow()
    monkeypatch.setattr(lark_cli, "_require_lark_cli_path", lambda: "/usr/bin/lark-cli")
    monkeypatch.setattr(
        lark_cli,
        "_run_lark_cli_json",
        lambda *_args, **_kwargs: {
            "verification_url": "https://open.feishu.cn/auth/mock",
            "device_code": "device-code",
        },
    )

    result = lark_cli.start_lark_auth("alice", generation=generation)

    assert result.generation == generation
    assert json.loads(lark_cli._lark_flow_state_path("alice").read_text(encoding="utf-8")) == {"generation": generation}


def test_lark_cli_env_from_runtime_exposes_settings_auth_to_lark_commands(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path / "home")
    runtime = SimpleNamespace(context={"user_id": "alice"})

    env = _lark_cli_env_from_runtime(runtime, "lark-cli auth status --json", sandbox_paths=False)

    assert env is not None
    assert Path(env["LARKSUITE_CLI_CONFIG_DIR"]) == lark_cli.lark_cli_config_dir("alice")
    assert Path(env["LARKSUITE_CLI_DATA_DIR"]) == lark_cli.lark_cli_data_dir("alice")


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits unavailable")
def test_lark_cli_env_hardens_existing_credential_tree(monkeypatch, tmp_path) -> None:
    config_dir, data_dir = _bootstrap_credential_dirs(monkeypatch, tmp_path)
    secret_file = config_dir / "config.json"
    token_file = data_dir / "auth.json"
    secret_file.write_text('{"appSecret":"secret"}', encoding="utf-8")
    token_file.write_text('{"token":"secret"}', encoding="utf-8")
    config_dir.chmod(0o755)
    data_dir.chmod(0o777)
    secret_file.chmod(0o644)
    token_file.chmod(0o666)

    lark_cli.lark_cli_env_overlay("alice")

    assert stat.S_IMODE(config_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE((config_dir / "locks").stat().st_mode) == 0o700
    assert stat.S_IMODE(data_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(secret_file.stat().st_mode) == 0o600
    assert stat.S_IMODE(token_file.stat().st_mode) == 0o600


def test_windows_credential_tree_hardening_applies_single_private_dacl(monkeypatch, tmp_path) -> None:
    """On Windows each credential-tree entry gets exactly one owner-only DACL apply."""
    sid = "S-1-5-21-111-222-333-1001"
    subprocess_calls, dacl_calls = _patch_windows_hardening(monkeypatch, tmp_path, sid)

    config_dir = lark_cli.lark_cli_config_dir("alice")
    data_dir = lark_cli.lark_cli_data_dir("alice")
    credential_root = config_dir.parent
    config_dir.mkdir(parents=True)
    data_dir.mkdir(parents=True)
    secret_file = config_dir / "config.json"
    token_file = data_dir / "auth.json"
    secret_file.write_text('{"appSecret":"secret"}', encoding="utf-8")
    token_file.write_text('{"token":"secret"}', encoding="utf-8")

    lark_cli.ensure_lark_cli_credential_tree("alice")

    # whoami is resolved via the documented command.
    assert [args for args in subprocess_calls if args and args[0] == "whoami"] == [["whoami", "/user", "/fo", "csv", "/nh"]]
    # No shelled icacls path remains.
    assert not any(args and args[0] == "icacls" for args in subprocess_calls)

    expected = {
        str(credential_root): True,
        str(config_dir): True,
        str(config_dir / "locks"): True,
        str(data_dir): True,
        str(secret_file): False,
        str(token_file): False,
    }
    got = {path: inheritable for path, owner_sid, inheritable in dacl_calls if owner_sid == sid}
    assert got == expected
    assert len(dacl_calls) == 6


def test_resolve_current_user_sid_parses_real_whoami_csv_shape(monkeypatch) -> None:
    """`whoami /user` reports 'User Name, SID'; the SID is the *second* CSV field."""
    sid = "S-1-5-21-111-222-333-1001"

    def _fake_run(args, **kwargs):
        assert args[:4] == ["whoami", "/user", "/fo", "csv"]
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=f'"DOMAIN\\alice","{sid}"\n',
            stderr="",
        )

    monkeypatch.setattr(lark_cli.subprocess, "run", _fake_run)

    assert lark_cli._resolve_current_user_sid() == sid


@pytest.mark.parametrize("fail_kind", ["whoami", "dacl"])
def test_windows_credential_tree_raises_on_identity_or_acl_failure(monkeypatch, tmp_path, fail_kind) -> None:
    """Identity or ACL manipulation failures must raise, never be silently ignored."""
    sid = "S-1-5-21-111-222-333-1001"
    _patch_paths(monkeypatch, tmp_path / "home")
    monkeypatch.setattr(lark_cli, "os", _windows_os_stub())

    config_dir = lark_cli.lark_cli_config_dir("alice")
    data_dir = lark_cli.lark_cli_data_dir("alice")
    config_dir.mkdir(parents=True)
    data_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text("x", encoding="utf-8")
    (data_dir / "auth.json").write_text("x", encoding="utf-8")

    def _fake_run(args, **kwargs):
        if args and args[0] == "whoami":
            if fail_kind == "whoami":
                return subprocess.CompletedProcess(args, returncode=1, stdout="", stderr="no user")
            return subprocess.CompletedProcess(args, returncode=0, stdout=f'"DOMAIN\\alice","{sid}"\n', stderr="")
        return subprocess.CompletedProcess(args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(lark_cli.subprocess, "run", _fake_run)

    def _open(path, *, access, reject_reparse=True):
        if path.is_symlink() and reject_reparse:
            raise ValueError(f"Lark CLI credential path must not be a reparse point: {path}")
        return _FakeWindowsHandle(path, [], apply_fails=(fail_kind == "dacl"))

    monkeypatch.setattr(lark_cli, "_open_windows_pinned", _open)

    def _open_or_create(parent, name, *, full_path, access, share):
        child = parent.path / name
        if child.is_symlink():
            raise ValueError(f"Lark CLI credential path must not be a reparse point: {child}")
        child.mkdir(parents=True, exist_ok=True)
        return _FakeWindowsHandle(child, [], apply_fails=(fail_kind == "dacl"))

    monkeypatch.setattr(lark_cli, "_open_or_create_dir_relative", _open_or_create)

    with pytest.raises((RuntimeError, ValueError)):
        lark_cli.ensure_lark_cli_credential_tree("alice")


def test_windows_credential_tree_hardening_issues_single_owner_apply_no_reset_fallback(monkeypatch, tmp_path) -> None:
    """Hardening applies one owner-only DACL per entry; no shelled reset/remove path."""
    sid = "S-1-5-21-111-222-333-1001"
    subprocess_calls, dacl_calls = _patch_windows_hardening(monkeypatch, tmp_path, sid)
    config_dir = lark_cli.lark_cli_config_dir("alice")
    data_dir = lark_cli.lark_cli_data_dir("alice")
    config_dir.mkdir(parents=True)
    data_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text("x", encoding="utf-8")
    (data_dir / "auth.json").write_text("x", encoding="utf-8")

    lark_cli.ensure_lark_cli_credential_tree("alice")

    # No shelled icacls /reset /remove path anywhere.
    assert not any(args and args[0] == "icacls" for args in subprocess_calls)
    # One private-DACL apply per entry, always to the owner SID (never a denylist).
    assert len(dacl_calls) == 6
    assert all(owner_sid == sid for _, owner_sid, _ in dacl_calls)
    assert {path for path, _, _ in dacl_calls} == {
        str(config_dir.parent),
        str(config_dir),
        str(config_dir / "locks"),
        str(data_dir),
        str(config_dir / "config.json"),
        str(data_dir / "auth.json"),
    }


def test_windows_credential_tree_hardening_rejects_reparse_before_descent(monkeypatch, tmp_path) -> None:
    """A symlink/junction inside the tree is rejected before traversal uses it.

    The parent is hardened first through its exclusive handle; that exclusive open
    suppresses propagation of the inheritable ACL into existing unvalidated children.
    Each child is then opened no-follow relative to the parent and a reparse point is
    rejected before its own security descriptor is touched or traversal follows it.
    """
    subprocess_calls, dacl_calls = _patch_windows_hardening(monkeypatch, tmp_path)
    config_dir = lark_cli.lark_cli_config_dir("alice")
    config_dir.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "leak.txt").write_text("secret", encoding="utf-8")
    try:
        (config_dir / "evil").symlink_to(outside)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlinks are not available: {exc}")

    with pytest.raises(ValueError, match="reparse"):
        lark_cli.ensure_lark_cli_credential_tree("alice")

    assert not any(args and args[0] == "icacls" for args in subprocess_calls)
    dacl_paths = [path for path, _, _ in dacl_calls]
    assert dacl_paths, "expected the parent directory to be hardened before the reparse was hit"
    assert str(config_dir / "evil") not in dacl_paths
    assert not any(p.startswith(str(outside)) for p in dacl_paths)
    assert not any(str(outside) in p for p in dacl_paths)


def test_credential_tree_path_kind_classifies_and_rejects(monkeypatch) -> None:
    """The path-kind resolver rejects symlinks and reparse points before descent."""
    monkeypatch.setattr(lark_cli, "os", _windows_os_stub())

    class _FakePath:
        def __init__(self, st_mode: int, st_attrs: int = 0) -> None:
            self._st_mode = st_mode
            self._st_attrs = st_attrs

        def lstat(self):
            return SimpleNamespace(st_mode=self._st_mode, st_file_attributes=self._st_attrs)

    assert lark_cli._credential_tree_path_kind(_FakePath(stat.S_IFDIR)) == "dir"
    assert lark_cli._credential_tree_path_kind(_FakePath(stat.S_IFREG)) == "file"
    with pytest.raises(ValueError, match="symlink"):
        lark_cli._credential_tree_path_kind(_FakePath(stat.S_IFLNK))
    with pytest.raises(ValueError, match="reparse"):
        lark_cli._credential_tree_path_kind(_FakePath(stat.S_IFDIR, stat.FILE_ATTRIBUTE_REPARSE_POINT))
    with pytest.raises(ValueError, match="Unsupported"):
        lark_cli._credential_tree_path_kind(_FakePath(stat.S_IFCHR))


def test_windows_private_descriptor_contract_includes_owner() -> None:
    """The private descriptor must transfer ownership, not only replace the DACL."""
    sid = "S-1-5-21-111-222-333-1001"
    dir_sddl = lark_cli._windows_private_sddl(sid, inheritable_full=True)
    file_sddl = lark_cli._windows_private_sddl(sid, inheritable_full=False)
    assert dir_sddl == f"O:{sid}D:P(A;OICI;FA;;;{sid})"
    assert file_sddl == f"O:{sid}D:P(A;;FA;;;{sid})"

    info = lark_cli._windows_private_security_information()
    assert info & 0x00000001  # OWNER_SECURITY_INFORMATION
    assert info & 0x00000004  # DACL_SECURITY_INFORMATION
    assert info & 0x80000000  # PROTECTED_DACL_SECURITY_INFORMATION


def test_private_lark_temp_dir_hardens_before_yield(monkeypatch, tmp_path) -> None:
    """`_private_lark_temp_dir` establishes owner-only permissions before yielding."""
    applied: list[str] = []
    orig = lark_cli._establish_private_directory_boundary

    def _spy(root):
        applied.append(str(root))
        return orig(root)

    monkeypatch.setattr(lark_cli, "_establish_private_directory_boundary", _spy)
    with lark_cli._private_lark_temp_dir(prefix=".private-test-", dir=tmp_path) as root:
        assert applied == [str(root)]
        assert root.is_dir()


@pytest.mark.skipif(os.name != "nt", reason="requires a real NTFS junction")
def test_windows_credential_tree_rejects_real_junction(monkeypatch, tmp_path) -> None:
    _patch_paths(monkeypatch, tmp_path / "home")
    monkeypatch.setattr(lark_cli, "os", _windows_os_stub())
    config_dir = lark_cli.lark_cli_config_dir("alice")
    config_dir.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "leak.txt").write_text("secret", encoding="utf-8")

    junction = config_dir / "evil"
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
        check=True,
        capture_output=True,
        text=True,
    )

    dacl_paths: list[str] = []
    _orig_set_security = lark_cli._WindowsTreeHandle.set_security

    def _record_security(self, owner_sid, *, inheritable_full):
        dacl_paths.append(str(self.path))
        return _orig_set_security(self, owner_sid, inheritable_full=inheritable_full)

    monkeypatch.setattr(lark_cli._WindowsTreeHandle, "set_security", _record_security)

    try:
        with pytest.raises(ValueError, match="reparse"):
            lark_cli.ensure_lark_cli_credential_tree("alice")
    finally:
        # Remove only the junction itself (not its target) so pytest's recursive
        # temp cleanup does not hit a WinError on the reparse point.
        if junction.exists():
            os.rmdir(junction)

    assert str(junction) not in dacl_paths
    assert not any(str(outside) in p for p in dacl_paths)


@pytest.mark.skipif(os.name != "nt", reason="requires real Windows ACLs")
def test_windows_credential_tree_hardening_removes_arbitrary_existing_explicit_sid(monkeypatch, tmp_path) -> None:
    """A real arbitrary pre-existing explicit SID must not survive hardening.

    Seed an explicit BUILTIN\\Guests (``S-1-5-32-546``) grant, verify it exists,
    run the real Windows hardening path (no mock), then verify the unwanted SID
    is absent while the current process user's SID remains granted.
    """
    _patch_paths(monkeypatch, tmp_path / "home")
    config_dir = lark_cli.lark_cli_config_dir("alice")
    data_dir = lark_cli.lark_cli_data_dir("alice")
    config_dir.mkdir(parents=True)
    data_dir.mkdir(parents=True)
    secret_file = config_dir / "config.json"
    token_file = data_dir / "auth.json"
    secret_file.write_text('{"appSecret":"secret"}', encoding="utf-8")
    token_file.write_text('{"token":"secret"}', encoding="utf-8")

    unwanted_sid = "S-1-5-32-546"  # BUILTIN\Guests
    subprocess.run(
        ["icacls", str(secret_file), "/grant:r", f"*{unwanted_sid}:F"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert unwanted_sid in _windows_acl_sids(secret_file), "seed explicit grant was not applied"

    # Real hardening path: do not mock subprocess here so the actual ACLs change.
    lark_cli.ensure_lark_cli_credential_tree("alice")

    owner_sid = lark_cli._resolve_current_user_sid()
    result_sids = _windows_acl_sids(secret_file)
    assert result_sids == {owner_sid}, "only the owner SID may remain after hardening"
    assert _windows_acl_owner_sid(secret_file) == owner_sid, "object owner must be the Gateway user"


@pytest.mark.skipif(os.name != "nt", reason="requires real Windows ACLs")
def test_windows_credential_tree_final_security_apply_failure_has_no_prior_broadening(monkeypatch, tmp_path) -> None:
    """Failure at the final handle-bound apply seam has no prior /reset or widening step."""
    config_dir, _ = _bootstrap_credential_dirs(monkeypatch, tmp_path, data=False)
    secret_file = config_dir / "config.json"
    secret_file.write_text('{"appSecret":"secret"}', encoding="utf-8")

    lark_cli.ensure_lark_cli_credential_tree("alice")
    owner_sid = lark_cli._resolve_current_user_sid()
    before = _windows_acl_sids(secret_file)
    assert before == {owner_sid}
    assert _windows_acl_protected(secret_file)

    def _boom(handle, owner_sid, *, inheritable_full):
        raise OSError("simulated SetSecurityInfo failure")

    monkeypatch.setattr(lark_cli, "_set_windows_security_info_handle", _boom)
    with pytest.raises((OSError, RuntimeError)):
        lark_cli.ensure_lark_cli_credential_tree("alice")

    after = _windows_acl_sids(secret_file)
    assert after == before
    assert after == {owner_sid}
    assert _windows_acl_owner_sid(secret_file) == owner_sid
    assert _windows_acl_protected(secret_file)


@pytest.mark.skipif(os.name != "nt", reason="requires real Windows ACLs")
def test_validate_lark_app_credentials_establishes_boundary_before_writing(monkeypatch, tmp_path) -> None:
    """The validation temp tree is owner-only before the CLI writes a secret."""
    _patch_paths(monkeypatch, tmp_path / "home")
    owner_sid = lark_cli._resolve_current_user_sid()

    def fake_init(*, app_id, app_secret, brand, env):
        config_dir = Path(env["LARKSUITE_CLI_CONFIG_DIR"])
        data_dir = Path(env["LARKSUITE_CLI_DATA_DIR"])
        temp_root = config_dir.parent
        # The private root is protected; children inherit owner-only.
        assert _windows_acl_protected(temp_root)
        assert _windows_acl_owner_sid(temp_root) == owner_sid
        assert _windows_acl_sids(config_dir) == {owner_sid}
        assert _windows_acl_sids(data_dir) == {owner_sid}
        secret = data_dir / "auth.json"
        secret.write_text('{"token":"secret"}', encoding="utf-8")
        assert secret.exists()
        assert _windows_acl_sids(secret) == {owner_sid}

    monkeypatch.setattr(lark_cli, "_run_lark_config_init", fake_init)
    lark_cli._validate_lark_app_credentials_with_cli(app_id="a", app_secret="s", brand="lark")


@pytest.mark.skipif(os.name != "nt", reason="requires real Windows ACLs")
def test_lark_credential_transaction_establishes_boundary_before_copy(monkeypatch, tmp_path) -> None:
    """The transaction snapshot tree is owner-only before credentials are copied."""
    _patch_paths(monkeypatch, tmp_path / "home")
    owner_sid = lark_cli._resolve_current_user_sid()
    root = lark_cli._lark_cli_credential_root("alice")
    config_dir = root / "config"
    data_dir = root / "data"
    config_dir.mkdir(parents=True)
    data_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text('{"appId":"x"}', encoding="utf-8")
    secret = data_dir / "auth.json"
    secret.write_text('{"token":"secret"}', encoding="utf-8")

    observed: list[Path] = []
    orig_copytree = lark_cli.shutil.copytree

    def guarded_copytree(*args, **kwargs):
        dst = Path(args[1])
        if dst.parent.name == "credentials":
            # The snapshot boundary (dst.parent) must already be protected + owner-only
            # before any top-level credential directory is copied into it.
            assert _windows_acl_protected(dst.parent)
            assert _windows_acl_owner_sid(dst.parent) == owner_sid
            observed.append(dst)
        return orig_copytree(*args, **kwargs)

    monkeypatch.setattr(lark_cli.shutil, "copytree", guarded_copytree)
    with lark_cli._lark_credential_transaction("alice", root) as snapshot:
        assert _windows_acl_protected(snapshot)
        assert _windows_acl_owner_sid(snapshot) == owner_sid
        assert (snapshot / "data" / "auth.json").exists()
        # Copied children inherit owner-only from the protected snapshot.
        assert _windows_acl_sids(snapshot / "data") == {owner_sid}
        assert _windows_acl_sids(snapshot / "data" / "auth.json") == {owner_sid}
    assert observed


@pytest.mark.skipif(os.name != "nt", reason="requires a real NTFS junction")
def test_windows_credential_tree_rejects_reparse_ancestor(monkeypatch, tmp_path) -> None:
    """An ancestor junction (e.g. ``integrations``) is rejected before any use."""
    _patch_paths(monkeypatch, tmp_path / "home")
    base = tmp_path / "home"
    alice = base / "users" / "alice"
    alice.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    integrations = alice / "integrations"
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(integrations), str(outside)],
        check=True,
        capture_output=True,
        text=True,
    )
    try:
        with pytest.raises(ValueError, match="reparse"):
            lark_cli.ensure_lark_cli_credential_tree("alice")
        # The reparse ancestor was rejected before the credential root was used.
        assert not (outside / "lark-cli").exists()
        assert not (integrations / "lark-cli").exists()
        # The hardening lock is anchored under the trusted base_dir, never the external target.
        assert not (outside / ".lark-cli.hardening.lock").exists()
    finally:
        if integrations.exists():
            os.rmdir(integrations)


@pytest.mark.skipif(os.name != "nt", reason="requires a real NTFS junction")
def test_windows_credential_tree_swap_blocked_by_exclusive_parent(monkeypatch, tmp_path) -> None:
    """An exclusive directory handle blocks a child swap mid-walk.

    The reviewer's P1 is a validated child swapped for a junction before descent. Here
    the walker holds ``data`` open *exclusively* (share=0), so an attempt to swap
    ``data/nested`` (rename + ``mklink /J`` to an external directory) fails with a
    sharing violation — the namespace is locked for the duration of the walk. The
    external directory is never reached, opened, or hardened.
    """
    config_dir, data_dir = _bootstrap_credential_dirs(monkeypatch, tmp_path)
    nested = data_dir / "nested"
    nested.mkdir()
    (config_dir / "config.json").write_text("s", encoding="utf-8")
    (data_dir / "auth.json").write_text("t", encoding="utf-8")
    (nested / "inner.txt").write_text("x", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "foreign-secret").write_text("secret", encoding="utf-8")

    hardened: list[str] = []
    orig_set_security = lark_cli._WindowsTreeHandle.set_security

    def _record_security(self, owner_sid, *, inheritable_full):
        hardened.append(str(self.path))
        return orig_set_security(self, owner_sid, inheritable_full=inheritable_full)

    monkeypatch.setattr(lark_cli._WindowsTreeHandle, "set_security", _record_security)

    orig_open_child = lark_cli._WindowsTreeHandle.open_child
    swapped: list[str] = []

    def _swap_before_open(self, name):
        if self.path == data_dir and name == "nested":
            try:
                os.rename(nested, nested.with_name("nested-swapped"))
                subprocess.run(
                    ["cmd", "/c", "mklink", "/J", str(nested), str(outside)],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                swapped.append("swapped")
            except OSError as exc:  # noqa: BLE001 - assertion boundary
                swapped.append(f"blocked:{type(exc).__name__}")
        return orig_open_child(self, name)

    monkeypatch.setattr(lark_cli._WindowsTreeHandle, "open_child", _swap_before_open)

    try:
        lark_cli.ensure_lark_cli_credential_tree("alice")
        assert swapped and swapped[0].startswith("blocked:"), f"exclusive parent must block the swap, got {swapped}"
        assert (outside / "foreign-secret").read_text(encoding="utf-8") == "secret"
        assert not any(str(outside) in p for p in hardened), "walker must never harden the external target"
    finally:
        # Decide from the recorded swap outcome — ``Path.is_symlink()`` is unreliable
        # for NTFS junctions, so do not re-derive it here. If the swap succeeded,
        # ``nested`` is a junction pointing outside; remove only the junction itself.
        if swapped and swapped[0] == "swapped":
            if nested.exists():
                os.rmdir(nested)
        elif nested.exists():
            shutil.rmtree(nested, ignore_errors=True)
        swapped_dir = data_dir / "nested-swapped"
        if swapped_dir.exists():
            shutil.rmtree(swapped_dir, ignore_errors=True)


@pytest.mark.skipif(os.name != "nt", reason="requires real NTFS hard links")
def test_windows_credential_tree_rejects_hard_linked_file(monkeypatch, tmp_path) -> None:
    """A hard-linked file inside the tree must not have its ACL changed.

    The security descriptor belongs to the NTFS file object, so hardening a tree
    file that is hard-linked to an external file would also change that external
    file's owner/DACL. The walker must reject any file with ``nNumberOfLinks != 1``
    and leave the external file untouched.
    """
    config_dir, data_dir = _bootstrap_credential_dirs(monkeypatch, tmp_path)
    (config_dir / "config.json").write_text("s", encoding="utf-8")

    outside = tmp_path / "outside"
    outside.mkdir()
    victim = outside / "victim.txt"
    victim.write_text("secret", encoding="utf-8")
    planted = data_dir / "planted.txt"
    os.link(victim, planted)

    before_sids = _windows_acl_sids(victim)
    before_owner = _windows_acl_owner_sid(victim)

    try:
        with pytest.raises(ValueError, match="hard-link"):
            lark_cli.ensure_lark_cli_credential_tree("alice")
        assert _windows_acl_sids(victim) == before_sids
        assert _windows_acl_owner_sid(victim) == before_owner
    finally:
        # Remove only the hard link (not the victim) so pytest's recursive temp
        # cleanup does not hit a WinError on the shared file object.
        if planted.exists():
            planted.unlink()


@pytest.mark.skipif(os.name != "nt", reason="requires real Windows ACLs")
def test_windows_credential_tree_exclusive_parent_no_propagation(monkeypatch, tmp_path) -> None:
    """An exclusive directory handle blocks SetSecurityInfo propagation to children."""
    config_dir, _ = _bootstrap_credential_dirs(monkeypatch, tmp_path, data=False)
    child = config_dir / "config.json"
    child.write_text("s", encoding="utf-8")

    unwanted = "S-1-5-32-546"  # BUILTIN\Guests
    subprocess.run(
        ["icacls", str(child), "/grant:r", f"*{unwanted}:F"],
        check=True,
        capture_output=True,
        text=True,
    )
    before = _windows_acl_sids(child)
    assert unwanted in before, "seed child grant was not applied"

    owner_sid = lark_cli._resolve_current_user_sid()
    handle = lark_cli._open_windows_pinned(
        config_dir,
        access=lark_cli._WINDOWS_HARDEN_ACCESS,
        share=lark_cli._WINDOWS_EXCLUSIVE_SHARE,
    )
    try:
        # Exclusive handle: applying an inheritable OI|CI DACL must NOT rewrite the child.
        handle.set_security(owner_sid, inheritable_full=True)
    finally:
        handle.close()

    assert _windows_acl_sids(child) == before, "exclusive parent apply must not propagate to existing children"


@pytest.mark.skipif(os.name != "nt", reason="requires real NTFS hard links")
def test_windows_credential_tree_late_insertion_blocked_by_exclusive_parent(monkeypatch, tmp_path) -> None:
    """An exclusive directory handle closes the concurrent hard-link insertion window.

    During the walk the walker holds ``data`` open exclusively (share=0), so a local
    principal cannot ``os.link`` an external file into it (sharing violation) — the late
    insertion the children-first order exposed cannot happen. A hard link that already
    exists before ``ensure`` is still rejected by the ``link_count != 1`` check (covered
    by the static hard-link regression); here we prove the mutation window is closed and
    the external file's owner/DACL is left untouched.
    """
    config_dir, data_dir = _bootstrap_credential_dirs(monkeypatch, tmp_path)
    (config_dir / "config.json").write_text("s", encoding="utf-8")
    (data_dir / "auth.json").write_text("t", encoding="utf-8")

    outside = tmp_path / "outside"
    outside.mkdir()
    victim = outside / "victim.txt"
    victim.write_text("secret", encoding="utf-8")

    before_sids = _windows_acl_sids(victim)
    before_owner = _windows_acl_owner_sid(victim)

    orig_enumerate = lark_cli._WindowsTreeHandle.enumerate
    inserted: list[str] = []

    def _try_insert_late_link(self):
        if self.path == data_dir:
            late = data_dir / "late.txt"
            try:
                if not late.exists():
                    os.link(victim, late)
                    inserted.append("inserted")
            except OSError as exc:  # noqa: BLE001 - assertion boundary
                inserted.append(f"blocked:{type(exc).__name__}")
        return orig_enumerate(self)

    monkeypatch.setattr(lark_cli._WindowsTreeHandle, "enumerate", _try_insert_late_link)

    try:
        lark_cli.ensure_lark_cli_credential_tree("alice")
        assert inserted and inserted[0].startswith("blocked:"), f"exclusive parent must block late insertion, got {inserted}"
        assert _windows_acl_sids(victim) == before_sids
        assert _windows_acl_owner_sid(victim) == before_owner
    finally:
        late = data_dir / "late.txt"
        if late.exists():
            late.unlink()


def test_windows_credential_walker_iterative_handles_deep_tree() -> None:
    """The handle-relative walker is iterative, so an unbounded tree depth cannot hit the recursion limit."""
    depth = 1500

    class _DeepHandle:
        def __init__(self, path: Path, remaining: int) -> None:
            self.path = path
            self.remaining = remaining
            self.info = SimpleNamespace(reparse=False, is_dir=True, link_count=1)

        def set_security(self, owner_sid, *, inheritable_full):
            assert inheritable_full is True

        def enumerate(self):
            if self.remaining > 0:
                yield "child"

        def open_child(self, name):
            return _DeepHandle(self.path / name, self.remaining - 1)

        def open_or_create_child_dir(self, name):
            return _DeepHandle(self.path / name, self.remaining - 1)

        def close(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

    # Must not raise RecursionError even though the chain is far deeper than the default limit.
    lark_cli._walk_and_harden_windows_handle(Path("root"), _DeepHandle(Path("root"), depth), "S-1-5-21-1", Path("root"))


@pytest.mark.skipif(os.name != "nt", reason="requires real exclusive-share semantics")
def test_concurrent_ensure_serialized_by_hardening_lock(monkeypatch, tmp_path) -> None:
    """Concurrent ``ensure()`` on the same user serializes (no ERROR_SHARING_VIOLATION).

    The walker opens credential directories exclusively (share=0). Without serialization two
    concurrent ``ensure()`` calls would race: the second would fail to open the already-exclusive
    root. The per-user hardening lock must make the second caller wait and then succeed.
    """
    _bootstrap_credential_dirs(monkeypatch, tmp_path)
    started = threading.Event()
    release = threading.Event()
    orig = lark_cli._set_windows_security_info_handle

    def _pause_first(handle, owner_sid, *, inheritable_full):
        if not started.is_set():
            started.set()
            release.wait(timeout=10)
        return orig(handle, owner_sid, inheritable_full=inheritable_full)

    monkeypatch.setattr(lark_cli, "_set_windows_security_info_handle", _pause_first)

    results: list[str] = []

    def _worker():
        try:
            lark_cli.ensure_lark_cli_credential_tree("alice")
            results.append("ok")
        except OSError as exc:
            results.append(f"err:{type(exc).__name__}:{getattr(exc, 'winerror', None)}")

    thread_a = threading.Thread(target=_worker)
    thread_a.start()
    assert started.wait(timeout=10), "thread A did not reach the root hardening step"
    thread_b = threading.Thread(target=_worker)
    thread_b.start()
    time.sleep(0.2)  # give thread B a chance to race for the exclusive root
    release.set()
    thread_a.join(timeout=20)
    thread_b.join(timeout=20)

    assert results == ["ok", "ok"], f"concurrent ensure must serialize, got {results}"


def test_lark_cli_env_rejects_symlinks_in_credential_tree(monkeypatch, tmp_path) -> None:
    _patch_paths(monkeypatch, tmp_path / "home")
    config_dir = lark_cli.lark_cli_config_dir("alice")
    config_dir.mkdir(parents=True)
    outside = tmp_path / "outside-secret"
    outside.write_text("secret", encoding="utf-8")
    try:
        (config_dir / "config.json").symlink_to(outside)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlinks are not available: {exc}")

    # POSIX reports a symlink; the Windows walker reports a reparse point.
    expected_error = "reparse" if os.name == "nt" else "symlink"
    with pytest.raises(ValueError, match=expected_error):
        lark_cli.lark_cli_env_overlay("alice")


@pytest.mark.skipif(os.name == "nt", reason="POSIX root symlink rejection before mkdir")
def test_ensure_posix_rejects_symlink_root_before_creating_children(monkeypatch, tmp_path) -> None:
    """A symlinked credential root is rejected before any child dir is created (POSIX).

    ``mkdir(exist_ok=True)`` accepts a symlink that resolves to a directory, so a
    symlinked ``lark-cli`` root must be rejected up front — otherwise ``config`` /
    ``data`` would be created inside the symlink target (outside the credential tree)
    before the walker notices the reparse.
    """
    _patch_paths(monkeypatch, tmp_path / "home")
    root = lark_cli._lark_cli_credential_root("alice")
    root.parent.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        root.symlink_to(outside)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlinks are not available: {exc}")

    with pytest.raises(ValueError, match="symlink"):
        lark_cli.ensure_lark_cli_credential_tree("alice")

    # The root symlink must have been rejected before any child was created inside it.
    assert not (outside / "config").exists()
    assert not (outside / "data").exists()


def test_save_lark_app_config_rehardens_files_written_by_cli(monkeypatch, tmp_path) -> None:
    _patch_paths(monkeypatch, tmp_path / "home")
    rehardened: list[str] = []
    orig_ensure = lark_cli.ensure_lark_cli_credential_tree

    def _spy_ensure(user_id, *, paths=None):
        rehardened.append(user_id)
        return orig_ensure(user_id, paths=paths)

    monkeypatch.setattr(lark_cli, "ensure_lark_cli_credential_tree", _spy_ensure)

    def _run_init(*, app_id, app_secret, brand, env):
        config_file = Path(env["LARKSUITE_CLI_CONFIG_DIR"]) / "config.json"
        config_file.write_text('{"appSecret":"secret"}', encoding="utf-8")

    monkeypatch.setattr(lark_cli, "_run_lark_config_init", _run_init)

    lark_cli._save_lark_app_config_with_cli("alice", app_id="cli_app", app_secret="secret", brand="feishu")

    config_file = lark_cli.lark_cli_config_dir("alice") / "config.json"
    assert config_file.exists()
    assert "alice" in rehardened, "a CLI-written config file must be re-hardened"


def test_validate_lark_app_credentials_surfaces_cli_probe_rejection(monkeypatch, tmp_path) -> None:
    _patch_paths(monkeypatch, tmp_path / "home")

    def _reject(*, app_id, app_secret, brand, env):
        raise ValueError("The specified app does not exist.")

    monkeypatch.setattr(lark_cli, "_run_lark_config_init", _reject)

    with pytest.raises(ValueError, match="specified app does not exist"):
        lark_cli._validate_lark_app_credentials_with_cli(
            app_id="cli_invalid",
            app_secret="invalid-secret",
            brand="feishu",
        )


def test_run_lark_config_init_surfaces_cli_probe_rejection(monkeypatch) -> None:
    """The config-init CLI rejection is surfaced as a ValueError carrying the CLI message."""
    monkeypatch.setattr(lark_cli, "_require_lark_cli_path", lambda: "/usr/bin/lark-cli")

    def _run(args, **kwargs):
        return subprocess.CompletedProcess(
            args=args,
            returncode=3,
            stdout='{"ok":false,"error":{"type":"config","subtype":"invalid_client","message":"The specified app does not exist."}}',
            stderr="",
        )

    monkeypatch.setattr(lark_cli.subprocess, "run", _run)

    with pytest.raises(ValueError, match="specified app does not exist"):
        lark_cli._run_lark_config_init(
            app_id="cli_invalid",
            app_secret="invalid-secret",
            brand="feishu",
            env={"LARKSUITE_CLI_CONFIG_DIR": "/x", "LARKSUITE_CLI_DATA_DIR": "/y"},
        )


def test_lark_cli_json_rehardens_auth_files_written_by_cli(monkeypatch, tmp_path) -> None:
    _patch_paths(monkeypatch, tmp_path / "home")
    rehardened: list[str] = []

    def _spy_ensure(user_id, *, paths=None):
        # Record-only: this is an orchestration contract (the CLI writes files then
        # re-hardens). The real ACL behavior is covered by the native Windows ACL
        # regressions, so we do not run the identity probe here.
        rehardened.append(user_id)

    monkeypatch.setattr(lark_cli, "ensure_lark_cli_credential_tree", _spy_ensure)
    # The env is built without the credential subsystem so the identity probe
    # (whoami) does not get intercepted by the CLI subprocess fake.
    monkeypatch.setattr(
        lark_cli,
        "lark_cli_env",
        lambda user_id: {
            "LARKSUITE_CLI_CONFIG_DIR": str(lark_cli.lark_cli_config_dir(user_id)),
            "LARKSUITE_CLI_DATA_DIR": str(lark_cli.lark_cli_data_dir(user_id)),
        },
    )

    def _run(args, **kwargs):
        token_file = Path(kwargs["env"]["LARKSUITE_CLI_DATA_DIR"]) / "auth.json"
        token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text('{"token":"secret"}', encoding="utf-8")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="{}", stderr="")

    monkeypatch.setattr(lark_cli.subprocess, "run", _run)

    lark_cli._run_lark_cli_json(["/usr/bin/lark-cli", "auth", "login"], user_id="alice", timeout=5)

    token_file = lark_cli.lark_cli_data_dir("alice") / "auth.json"
    assert token_file.exists()
    assert "alice" in rehardened, "a CLI-written auth file must be re-hardened"


def test_lark_cli_env_from_runtime_uses_container_paths_for_sandbox_lark_commands():
    runtime = SimpleNamespace(context={"user_id": "alice"})

    env = _lark_cli_env_from_runtime(runtime, "/usr/bin/lark-cli auth status", sandbox_paths=True)

    assert env is not None
    assert env["LARKSUITE_CLI_CONFIG_DIR"] == lark_cli.LARK_CLI_SANDBOX_CONFIG_DIR
    assert env["LARKSUITE_CLI_DATA_DIR"] == lark_cli.LARK_CLI_SANDBOX_DATA_DIR


def test_lark_cli_env_from_runtime_ignores_non_lark_commands(tmp_path, monkeypatch):
    _patch_paths(monkeypatch, tmp_path / "home")
    runtime = SimpleNamespace(context={"user_id": "alice"})

    assert _lark_cli_env_from_runtime(runtime, "echo hello", sandbox_paths=False) is None


def test_lark_auth_probe_distinguishes_local_configuration_from_live_verification(monkeypatch, tmp_path) -> None:
    assert "verified" in lark_cli.LarkAuthProbe.__dataclass_fields__
    _patch_paths(monkeypatch, tmp_path / "home")
    calls: list[list[str]] = []

    monkeypatch.setattr(lark_cli, "_resolve_lark_cli_path", lambda: "/usr/bin/lark-cli")
    monkeypatch.setattr(
        lark_cli,
        "read_lark_app_config",
        lambda _user_id: {"configured": True, "app_id": "cli_app", "brand": "feishu"},
    )
    # Build env without the credential subsystem so the identity probe (whoami)
    # does not get intercepted by the CLI subprocess fake.
    monkeypatch.setattr(
        lark_cli,
        "lark_cli_env",
        lambda user_id: {
            "LARKSUITE_CLI_CONFIG_DIR": str(lark_cli.lark_cli_config_dir(user_id)),
            "LARKSUITE_CLI_DATA_DIR": str(lark_cli.lark_cli_data_dir(user_id)),
        },
    )

    def _run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout='{"identities":{"user":{"userName":"Alice"}}}',
            stderr="",
        )

    monkeypatch.setattr(lark_cli.subprocess, "run", _run)

    configured = lark_cli.probe_lark_auth("alice", verify=False)
    live_verified = lark_cli.probe_lark_auth("alice", verify=True)

    assert configured.status == "authenticated"
    assert configured.verified is False
    assert "not live-verified" in (configured.message or "")
    assert live_verified.verified is True
    assert "live-verified" in (live_verified.message or "")
    assert calls[0] == ["/usr/bin/lark-cli", "auth", "status", "--json"]
    assert calls[1] == ["/usr/bin/lark-cli", "auth", "status", "--json", "--verify"]


def test_complete_lark_auth_polls_device_code_and_returns_status(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path / "home")
    skills_root = tmp_path / "skills"
    (skills_root / "public").mkdir(parents=True)
    (skills_root / "custom").mkdir()
    config = _config(skills_root)
    captured: dict[str, object] = {}

    def _run_lark_cli_json(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return {}

    monkeypatch.setattr(lark_cli, "_resolve_lark_cli_path", lambda: "/usr/bin/lark-cli")
    monkeypatch.setattr(lark_cli, "_run_lark_cli_json", _run_lark_cli_json)
    monkeypatch.setattr(
        lark_cli,
        "get_lark_integration_status",
        lambda _user_id, _config, **_kwargs: lark_cli.LarkIntegrationStatus(
            installed=True,
            version="v1.0.65",
            manifest_version="v1.0.65",
            latest_available_version=None,
            runtime_version_mismatch=False,
            app_configured=True,
            app_id="cli_mock",
            app_brand="feishu",
            skills_expected=27,
            skills_installed=27,
            installed_skills=("lark-doc",),
            enabled_skills=("lark-doc",),
            install_path="/tmp/lark",
            cli=lark_cli.LarkCliProbe(available=True),
            auth=lark_cli.LarkAuthProbe(status="authenticated", user="Alice"),
        ),
    )

    generation = _advance_lark_flow()
    result = lark_cli.complete_lark_auth("alice", config, device_code="device-code", generation=generation)

    assert result.success is True
    assert captured["args"] == [
        "/usr/bin/lark-cli",
        "auth",
        "login",
        "--device-code",
        "device-code",
        "--json",
    ]
    assert captured["kwargs"] == {
        "user_id": "alice",
        "timeout": 45,
        "allow_empty_success": True,
    }


def test_complete_lark_auth_accepts_short_automatic_poll_timeout(monkeypatch, tmp_path) -> None:
    assert "wait_timeout_seconds" in inspect.signature(lark_cli.complete_lark_auth).parameters
    _patch_paths(monkeypatch, tmp_path / "home")
    config = _config(tmp_path / "skills")
    captured: dict[str, object] = {}

    monkeypatch.setattr(lark_cli, "_require_lark_cli_path", lambda: "/usr/bin/lark-cli")
    monkeypatch.setattr(
        lark_cli,
        "_run_lark_cli_json",
        lambda _args, **kwargs: captured.update(kwargs) or {},
    )
    monkeypatch.setattr(
        lark_cli,
        "get_lark_integration_status",
        lambda _user_id, _config, **_kwargs: lark_cli.LarkIntegrationStatus(
            installed=True,
            version="v1.0.65",
            manifest_version="v1.0.65",
            latest_available_version=None,
            runtime_version_mismatch=False,
            app_configured=True,
            app_id="cli_mock",
            app_brand="feishu",
            skills_expected=27,
            skills_installed=27,
            installed_skills=("lark-doc",),
            enabled_skills=("lark-doc",),
            install_path="/tmp/lark",
            cli=lark_cli.LarkCliProbe(available=True),
            auth=lark_cli.LarkAuthProbe(status="authenticated", user="Alice"),
        ),
    )

    generation = _advance_lark_flow()
    result = lark_cli.complete_lark_auth(
        "alice",
        config,
        device_code="device-code",
        generation=generation,
        wait_timeout_seconds=8,
    )

    assert result.success is True
    assert captured["timeout"] == 8


def test_complete_lark_auth_rejects_superseded_generation_before_token_write(monkeypatch, tmp_path) -> None:
    _patch_paths(monkeypatch, tmp_path / "home")
    config = _config(tmp_path / "skills")
    stale_generation = _advance_lark_flow()
    current_generation = _advance_lark_flow()
    monkeypatch.setattr(
        lark_cli,
        "_run_lark_cli_json",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("stale auth must not write tokens")),
    )

    with pytest.raises(lark_cli.LarkFlowSupersededError, match="superseded"):
        lark_cli.complete_lark_auth(
            "alice",
            config,
            device_code="stale-device-code",
            generation=stale_generation,
        )

    assert json.loads(lark_cli._lark_flow_state_path("alice").read_text(encoding="utf-8")) == {"generation": current_generation}


def test_auth_complete_request_bounds_poll_timeout() -> None:
    model = integrations_router.LarkAuthCompleteRequest(device_code="device-code", generation="flow-generation", wait_timeout_seconds=8)
    assert "wait_timeout_seconds" in type(model).model_fields
    assert model.wait_timeout_seconds == 8
    with pytest.raises(ValueError):
        integrations_router.LarkAuthCompleteRequest(device_code="device-code", generation="flow-generation", wait_timeout_seconds=4)
    with pytest.raises(ValueError):
        integrations_router.LarkAuthCompleteRequest(device_code="device-code", generation="flow-generation", wait_timeout_seconds=46)


def test_start_lark_config_returns_app_registration_url(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path / "home")
    monkeypatch.setattr(
        lark_cli,
        "_request_lark_app_registration_begin",
        lambda _brand: {
            "user_code": "abc",
            "device_code": "config-device-code",
            "expires_in": 600,
            "interval": 5,
        },
    )

    result = lark_cli.start_lark_config("alice", brand="feishu")

    assert result.device_code == "config-device-code"
    assert result.generation
    assert json.loads(lark_cli._lark_flow_state_path("alice").read_text(encoding="utf-8")) == {"generation": result.generation}
    assert result.user_code == "abc"
    assert result.verification_url.startswith("https://open.feishu.cn/page/cli?")
    assert "user_code=abc" in result.verification_url


def test_complete_lark_config_saves_app_credentials_and_returns_status(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path / "home")
    skills_root = tmp_path / "skills"
    (skills_root / "public").mkdir(parents=True)
    (skills_root / "custom").mkdir()
    config = _config(skills_root)
    captured: dict[str, object] = {}
    revoked: list[str] = []
    config_dir = lark_cli.lark_cli_config_dir("alice")
    data_dir = lark_cli.lark_cli_data_dir("alice")
    config_dir.mkdir(parents=True)
    data_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text("old-config", encoding="utf-8")
    token_file = data_dir / "token.json"
    token_file.write_text("old-token", encoding="utf-8")
    master_key = data_dir / "master.key"
    app_secret_file = data_dir / "appsecret_cli_mock.enc"
    generation = _advance_lark_flow()

    monkeypatch.setattr(
        lark_cli,
        "_poll_lark_app_registration",
        lambda **_kwargs: {
            "client_id": "cli_mock",
            "client_secret": "secret",
            "user_info": {"tenant_brand": "feishu"},
        },
    )

    def _save(user_id, **kwargs):
        captured.update({"user_id": user_id, **kwargs})
        master_key.write_text("new-master-key", encoding="utf-8")
        app_secret_file.write_text("encrypted-app-secret", encoding="utf-8")

    monkeypatch.setattr(lark_cli, "_save_lark_app_config_with_cli", _save)
    monkeypatch.setattr(
        lark_cli,
        "_revoke_lark_auth_from_snapshot",
        lambda snapshot: revoked.append((snapshot / "data" / "token.json").read_text(encoding="utf-8")),
    )
    monkeypatch.setattr(
        lark_cli,
        "get_lark_integration_status",
        lambda _user_id, _config, **_kwargs: lark_cli.LarkIntegrationStatus(
            installed=True,
            version="v1.0.65",
            manifest_version="v1.0.65",
            latest_available_version=None,
            runtime_version_mismatch=False,
            app_configured=True,
            app_id="cli_mock",
            app_brand="feishu",
            skills_expected=27,
            skills_installed=27,
            installed_skills=("lark-doc",),
            enabled_skills=("lark-doc",),
            install_path="/tmp/lark",
            cli=lark_cli.LarkCliProbe(available=True),
            auth=lark_cli.LarkAuthProbe(status="not_authorized", user=None),
        ),
    )

    result = lark_cli.complete_lark_config(
        "alice",
        config,
        device_code="config-device-code",
        generation=generation,
        brand="feishu",
    )

    assert result.success is True
    assert result.generation == generation
    assert revoked == ["old-token"]
    assert not token_file.exists()
    assert master_key.read_text(encoding="utf-8") == "new-master-key"
    assert app_secret_file.read_text(encoding="utf-8") == "encrypted-app-secret"
    assert captured == {
        "user_id": "alice",
        "app_id": "cli_mock",
        "app_secret": "secret",
        "brand": "feishu",
    }


def test_complete_lark_config_repolls_lark_tenant_for_client_secret(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path / "home")
    skills_root = tmp_path / "skills"
    (skills_root / "public").mkdir(parents=True)
    (skills_root / "custom").mkdir()
    config = _config(skills_root)
    poll_calls: list[dict[str, object]] = []
    captured: dict[str, object] = {}
    generation = _advance_lark_flow()

    def _poll_lark_app_registration(**kwargs):
        poll_calls.append(kwargs)
        if kwargs["brand"] == "feishu":
            return {
                "client_id": "cli_mock",
                "user_info": {"tenant_brand": "lark"},
            }
        return {
            "client_id": "cli_mock",
            "client_secret": "secret",
            "user_info": {"tenant_brand": "lark"},
        }

    monkeypatch.setattr(lark_cli, "_poll_lark_app_registration", _poll_lark_app_registration)
    monkeypatch.setattr(
        lark_cli,
        "_save_lark_app_config_with_cli",
        lambda user_id, **kwargs: captured.update({"user_id": user_id, **kwargs}),
    )
    monkeypatch.setattr(
        lark_cli,
        "get_lark_integration_status",
        lambda _user_id, _config, **_kwargs: lark_cli.LarkIntegrationStatus(
            installed=True,
            version="v1.0.65",
            manifest_version="v1.0.65",
            latest_available_version=None,
            runtime_version_mismatch=False,
            app_configured=True,
            app_id="cli_mock",
            app_brand="lark",
            skills_expected=27,
            skills_installed=27,
            installed_skills=("lark-doc",),
            enabled_skills=("lark-doc",),
            install_path="/tmp/lark",
            cli=lark_cli.LarkCliProbe(available=True),
            auth=lark_cli.LarkAuthProbe(status="not_authorized", user=None),
        ),
    )

    result = lark_cli.complete_lark_config(
        "alice",
        config,
        device_code="config-device-code",
        generation=generation,
        brand="feishu",
    )

    assert result.success is True
    assert [call["brand"] for call in poll_calls] == ["feishu", "lark"]
    assert captured == {
        "user_id": "alice",
        "app_id": "cli_mock",
        "app_secret": "secret",
        "brand": "lark",
    }


def test_complete_lark_config_rejects_registration_superseded_by_direct_switch(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path / "home")
    config = _config(tmp_path / "skills")
    stale_generation = _advance_lark_flow()
    poll_started = threading.Event()
    release_poll = threading.Event()
    saved_apps: list[str] = []
    monkeypatch.setattr(lark_cli, "_validate_lark_app_credentials_with_cli", lambda **_kwargs: None)
    monkeypatch.setattr(
        lark_cli,
        "_save_lark_app_config_with_cli",
        lambda _user_id, *, app_id, **_kwargs: saved_apps.append(app_id),
    )
    monkeypatch.setattr(lark_cli, "_revoke_lark_auth_from_snapshot", lambda _snapshot: None)
    monkeypatch.setattr(
        lark_cli,
        "get_lark_integration_status",
        lambda _user_id, _config, **_kwargs: _status_stub(
            app_configured=True,
            app_id="cli_direct",
            auth_status="not_authorized",
        ),
    )

    def _poll(**_kwargs):
        poll_started.set()
        assert release_poll.wait(timeout=3)
        return {
            "client_id": "cli_stale",
            "client_secret": "stale-secret",
            "user_info": {"tenant_brand": "feishu"},
        }

    monkeypatch.setattr(lark_cli, "_poll_lark_app_registration", _poll)
    with ThreadPoolExecutor(max_workers=1) as executor:
        completion = executor.submit(
            lark_cli.complete_lark_config,
            "alice",
            config,
            device_code="stale-device-code",
            generation=stale_generation,
        )
        assert poll_started.wait(timeout=3)
        try:
            switched = lark_cli.set_lark_app_credentials(
                "alice",
                config,
                app_id="cli_direct",
                app_secret="direct-secret",
            )
        finally:
            release_poll.set()
        with pytest.raises(lark_cli.LarkFlowSupersededError, match="superseded"):
            completion.result(timeout=3)

    assert switched.generation != stale_generation
    assert saved_apps == ["cli_direct"]
    assert json.loads(lark_cli._lark_flow_state_path("alice").read_text(encoding="utf-8")) == {"generation": switched.generation}


def _make_user(system_role: str) -> User:
    return User(email=f"{system_role}-integration@example.com", password_hash="x", system_role=system_role, id=uuid4())


def _make_app(*, system_role: str, config):
    app = make_authed_test_app(user_factory=lambda: _make_user(system_role))
    app.dependency_overrides[get_config] = lambda: config
    app.include_router(integrations_router.router)
    return app


def test_lark_install_requires_admin(monkeypatch, tmp_path):
    config = _config(tmp_path / "skills")
    app = _make_app(system_role="user", config=config)

    def _should_not_install(*args, **kwargs):
        raise AssertionError("install should be admin-gated")

    monkeypatch.setattr(integrations_router, "install_lark_integration", _should_not_install)

    with TestClient(app) as client:
        response = client.post("/api/integrations/lark/install")

    assert response.status_code == 403


def test_lark_status_is_available_to_authenticated_users(monkeypatch, tmp_path):
    config = _config(tmp_path / "skills")
    app = _make_app(system_role="user", config=config)

    monkeypatch.setattr(
        integrations_router,
        "get_lark_integration_status",
        lambda _user_id, _config, **_kwargs: lark_cli.LarkIntegrationStatus(
            installed=False,
            version="v1.0.65",
            manifest_version=None,
            latest_available_version=None,
            runtime_version_mismatch=False,
            app_configured=False,
            app_id=None,
            app_brand=None,
            skills_expected=27,
            skills_installed=0,
            installed_skills=(),
            enabled_skills=(),
            install_path="/tmp/lark-cli",
            cli=lark_cli.LarkCliProbe(available=False, error="missing"),
            auth=lark_cli.LarkAuthProbe(status="unavailable", message="missing"),
        ),
    )

    with TestClient(app) as client:
        response = client.get("/api/integrations/lark/status")

    assert response.status_code == 200
    assert response.json()["installed"] is False


def _status_with_host_paths() -> lark_cli.LarkIntegrationStatus:
    return lark_cli.LarkIntegrationStatus(
        installed=True,
        version="v1.0.65",
        manifest_version="v1.0.65",
        latest_available_version=None,
        runtime_version_mismatch=False,
        app_configured=True,
        app_id="cli_mock",
        app_brand="feishu",
        skills_expected=27,
        skills_installed=27,
        installed_skills=("lark-doc",),
        enabled_skills=("lark-doc",),
        install_path="/home/deer-flow/.deer-flow/integrations/skills/lark-cli",
        cli=lark_cli.LarkCliProbe(available=True, path="/usr/bin/lark-cli", version="1.0.65"),
        auth=lark_cli.LarkAuthProbe(status="authenticated", user="alice"),
    )


def test_lark_status_redacts_host_paths_for_non_admin(monkeypatch, tmp_path):
    config = _config(tmp_path / "skills")
    app = _make_app(system_role="user", config=config)
    monkeypatch.setattr(integrations_router, "get_lark_integration_status", lambda *_a, **_k: _status_with_host_paths())

    with TestClient(app) as client:
        body = client.get("/api/integrations/lark/status").json()

    assert body["install_path"] == ""
    assert body["cli"]["path"] is None
    # Non-sensitive fields are still reported.
    assert body["installed"] is True
    assert body["cli"]["version"] == "1.0.65"


def test_lark_status_exposes_host_paths_for_admin(monkeypatch, tmp_path):
    config = _config(tmp_path / "skills")
    app = _make_app(system_role="admin", config=config)
    monkeypatch.setattr(integrations_router, "get_lark_integration_status", lambda *_a, **_k: _status_with_host_paths())

    with TestClient(app) as client:
        body = client.get("/api/integrations/lark/status").json()

    assert body["install_path"] == "/home/deer-flow/.deer-flow/integrations/skills/lark-cli"
    assert body["cli"]["path"] == "/usr/bin/lark-cli"


def test_lark_config_start_route_returns_browser_url(monkeypatch, tmp_path):
    config = _config(tmp_path / "skills")
    app = _make_app(system_role="user", config=config)

    monkeypatch.setattr(
        integrations_router,
        "start_lark_config",
        lambda _user_id, **_kwargs: lark_cli.LarkConfigStartResult(
            verification_url="https://open.feishu.cn/page/cli?user_code=config",
            device_code="config-device-code",
            generation="config-generation",
            expires_in=600,
            interval=5,
            user_code="config",
            brand="feishu",
        ),
    )

    with TestClient(app) as client:
        response = client.post("/api/integrations/lark/config/start", json={"brand": "feishu"})

    assert response.status_code == 200
    assert response.json()["verification_url"] == "https://open.feishu.cn/page/cli?user_code=config"
    assert response.json()["device_code"] == "config-device-code"
    assert response.json()["generation"] == "config-generation"


def test_lark_config_complete_route_saves_app_credentials(monkeypatch, tmp_path):
    config = _config(tmp_path / "skills")
    app = _make_app(system_role="user", config=config)

    monkeypatch.setattr(
        integrations_router,
        "complete_lark_config",
        lambda _user_id, _config, *, device_code, **_kwargs: lark_cli.LarkConfigCompleteResult(
            success=True,
            message=f"configured {device_code}",
            generation="config-generation",
            status=lark_cli.LarkIntegrationStatus(
                installed=True,
                version="v1.0.65",
                manifest_version="v1.0.65",
                latest_available_version=None,
                runtime_version_mismatch=False,
                app_configured=True,
                app_id="cli_mock",
                app_brand="feishu",
                skills_expected=27,
                skills_installed=27,
                installed_skills=("lark-doc",),
                enabled_skills=("lark-doc",),
                install_path="/tmp/lark",
                cli=lark_cli.LarkCliProbe(available=True),
                auth=lark_cli.LarkAuthProbe(status="not_authorized", user=None),
            ),
        ),
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/integrations/lark/config/complete",
            json={
                "device_code": "config-device-code",
                "generation": "config-generation",
                "brand": "feishu",
                "interval": 5,
                "expires_in": 600,
            },
        )

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["generation"] == "config-generation"
    assert response.json()["status"]["app_configured"] is True


def test_lark_config_complete_route_rejects_superseded_flow(monkeypatch, tmp_path):
    config = _config(tmp_path / "skills")
    app = _make_app(system_role="user", config=config)
    monkeypatch.setattr(
        integrations_router,
        "complete_lark_config",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(lark_cli.LarkFlowSupersededError("This Lark integration flow was superseded by a newer action.")),
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/integrations/lark/config/complete",
            json={
                "device_code": "stale-device-code",
                "generation": "stale-generation",
                "brand": "feishu",
            },
        )

    assert response.status_code == 409
    assert "superseded" in response.json()["detail"]


def test_lark_auth_start_route_returns_browser_url(monkeypatch, tmp_path):
    config = _config(tmp_path / "skills")
    app = _make_app(system_role="user", config=config)
    captured_kwargs: dict[str, object] = {}

    monkeypatch.setattr(
        integrations_router,
        "start_lark_auth",
        lambda _user_id, **kwargs: (
            captured_kwargs.update(kwargs)
            or lark_cli.LarkAuthStartResult(
                verification_url="https://open.feishu.cn/auth/mock",
                device_code="device-code",
                generation="auth-generation",
                expires_in=600,
            )
        ),
    )

    with TestClient(app) as client:
        response = client.post("/api/integrations/lark/auth/start", json={})

    assert response.status_code == 200
    assert response.json()["verification_url"] == "https://open.feishu.cn/auth/mock"
    assert response.json()["device_code"] == "device-code"
    assert response.json()["generation"] == "auth-generation"
    assert captured_kwargs == {"domains": (), "scope": None, "recommend": False, "generation": None}


def test_lark_auth_start_route_passes_explicit_recommend(monkeypatch, tmp_path):
    config = _config(tmp_path / "skills")
    app = _make_app(system_role="user", config=config)
    captured_kwargs: dict[str, object] = {}

    monkeypatch.setattr(
        integrations_router,
        "start_lark_auth",
        lambda _user_id, **kwargs: (
            captured_kwargs.update(kwargs)
            or lark_cli.LarkAuthStartResult(
                verification_url="https://open.feishu.cn/auth/mock",
                device_code="device-code",
                generation="auth-generation",
                expires_in=600,
            )
        ),
    )

    with TestClient(app) as client:
        response = client.post("/api/integrations/lark/auth/start", json={"recommend": True})

    assert response.status_code == 200
    assert response.json()["verification_url"] == "https://open.feishu.cn/auth/mock"
    assert response.json()["device_code"] == "device-code"
    assert captured_kwargs == {"domains": (), "scope": None, "recommend": True, "generation": None}


def test_lark_auth_complete_route_polls_device_code(monkeypatch, tmp_path):
    config = _config(tmp_path / "skills")
    app = _make_app(system_role="user", config=config)
    captured_kwargs = {}

    def _complete_auth(_user_id, _config, **kwargs):
        captured_kwargs.update(kwargs)
        return lark_cli.LarkAuthCompleteResult(
            success=True,
            message=f"completed {kwargs['device_code']}",
            status=lark_cli.LarkIntegrationStatus(
                installed=True,
                version="v1.0.65",
                manifest_version="v1.0.65",
                latest_available_version=None,
                runtime_version_mismatch=False,
                app_configured=True,
                app_id="cli_mock",
                app_brand="feishu",
                skills_expected=27,
                skills_installed=27,
                installed_skills=("lark-doc",),
                enabled_skills=("lark-doc",),
                install_path="/tmp/lark",
                cli=lark_cli.LarkCliProbe(available=True),
                auth=lark_cli.LarkAuthProbe(status="authenticated", user="Alice", verified=True),
            ),
        )

    monkeypatch.setattr(integrations_router, "complete_lark_auth", _complete_auth)

    with TestClient(app) as client:
        response = client.post(
            "/api/integrations/lark/auth/complete",
            json={"device_code": "device-code", "generation": "auth-generation"},
        )

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["status"]["auth"]["status"] == "authenticated"
    assert response.json()["status"]["auth"]["verified"] is True
    assert captured_kwargs == {
        "device_code": "device-code",
        "generation": "auth-generation",
        "wait_timeout_seconds": 45,
    }


def _status_stub(*, app_configured: bool, app_id: str | None, auth_status: str) -> lark_cli.LarkIntegrationStatus:
    return lark_cli.LarkIntegrationStatus(
        installed=True,
        version="v1.0.65",
        manifest_version="v1.0.65",
        latest_available_version=None,
        runtime_version_mismatch=False,
        app_configured=app_configured,
        app_id=app_id,
        app_brand="feishu",
        skills_expected=27,
        skills_installed=27,
        installed_skills=("lark-doc",),
        enabled_skills=("lark-doc",),
        install_path="/tmp/lark",
        cli=lark_cli.LarkCliProbe(available=True),
        auth=lark_cli.LarkAuthProbe(status=auth_status, user=None),
    )


def test_set_lark_app_credentials_validates_switches_and_revokes_prior_auth(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path / "home")
    config = _config(tmp_path / "skills")
    calls: list[tuple[str, object]] = []
    pending_generation = _advance_lark_flow()

    config_dir = lark_cli.lark_cli_config_dir("alice")
    data_dir = lark_cli.lark_cli_data_dir("alice")
    config_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config.json").write_text('{"apps":[{"appId":"cli_old","appSecret":"old-secret"}]}', encoding="utf-8")
    token_file = data_dir / "token.json"
    token_file.write_text('{"access_token": "old-app-token"}', encoding="utf-8")

    monkeypatch.setattr(
        lark_cli,
        "_validate_lark_app_credentials_with_cli",
        lambda **kwargs: calls.append(
            (
                "validate",
                {
                    **kwargs,
                    "generation": json.loads(lark_cli._lark_flow_state_path("alice").read_text(encoding="utf-8"))["generation"],
                },
            )
        ),
    )

    def _save(user_id, **kwargs):
        calls.append(("save", {"user_id": user_id, **kwargs}))
        (config_dir / "config.json").write_text('{"apps":[{"appId":"cli_new","appSecret":"new-secret"}]}', encoding="utf-8")

    monkeypatch.setattr(
        lark_cli,
        "_save_lark_app_config_with_cli",
        _save,
    )
    monkeypatch.setattr(
        lark_cli,
        "_revoke_lark_auth_from_snapshot",
        lambda snapshot: calls.append(("revoke", (snapshot / "data" / "token.json").read_text(encoding="utf-8"))),
    )
    monkeypatch.setattr(
        lark_cli,
        "get_lark_integration_status",
        lambda _user_id, _config, **_kwargs: _status_stub(app_configured=True, app_id="cli_new", auth_status="not_authorized"),
    )

    result = lark_cli.set_lark_app_credentials("alice", config, app_id="  cli_new  ", app_secret="  new-secret  ", brand="lark")

    assert result.success is True
    assert calls == [
        ("validate", {"app_id": "cli_new", "app_secret": "new-secret", "brand": "lark", "generation": pending_generation}),
        ("save", {"user_id": "alice", "app_id": "cli_new", "app_secret": "new-secret", "brand": "lark"}),
        ("revoke", '{"access_token": "old-app-token"}'),
    ]
    assert result.generation != pending_generation
    assert json.loads(lark_cli._lark_flow_state_path("alice").read_text(encoding="utf-8")) == {"generation": result.generation}
    assert not token_file.exists()


def test_set_lark_app_credentials_validation_failure_preserves_active_tree(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path / "home")
    config = _config(tmp_path / "skills")
    config_dir = lark_cli.lark_cli_config_dir("alice")
    data_dir = lark_cli.lark_cli_data_dir("alice")
    config_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / "config.json"
    token_file = data_dir / "token.json"
    config_file.write_text("old-config", encoding="utf-8")
    token_file.write_text("old-token", encoding="utf-8")
    pending_generation = _advance_lark_flow()

    monkeypatch.setattr(
        lark_cli,
        "_validate_lark_app_credentials_with_cli",
        lambda **_kwargs: (_ for _ in ()).throw(ValueError("invalid credentials")),
    )
    monkeypatch.setattr(
        lark_cli,
        "_save_lark_app_config_with_cli",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("active config must not be touched")),
    )

    with pytest.raises(ValueError, match="invalid credentials"):
        lark_cli.set_lark_app_credentials("alice", config, app_id="cli_new", app_secret="bad-secret")

    assert config_file.read_text(encoding="utf-8") == "old-config"
    assert token_file.read_text(encoding="utf-8") == "old-token"
    assert json.loads(lark_cli._lark_flow_state_path("alice").read_text(encoding="utf-8")) == {"generation": pending_generation}


@pytest.mark.parametrize("failure_step", ["save", "revoke"])
def test_set_lark_app_credentials_failure_restores_active_tree(monkeypatch, tmp_path, failure_step):
    _patch_paths(monkeypatch, tmp_path / "home")
    config = _config(tmp_path / "skills")
    config_dir = lark_cli.lark_cli_config_dir("alice")
    data_dir = lark_cli.lark_cli_data_dir("alice")
    config_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / "config.json"
    token_file = data_dir / "token.json"
    config_file.write_text("old-config", encoding="utf-8")
    token_file.write_text("old-token", encoding="utf-8")

    monkeypatch.setattr(lark_cli, "_validate_lark_app_credentials_with_cli", lambda **_kwargs: None)

    def _save(*_args, **_kwargs):
        config_file.write_text("new-config", encoding="utf-8")
        if failure_step == "save":
            raise ValueError("save failed")

    monkeypatch.setattr(lark_cli, "_save_lark_app_config_with_cli", _save)
    monkeypatch.setattr(
        lark_cli,
        "_revoke_lark_auth_from_snapshot",
        lambda _snapshot: (_ for _ in ()).throw(ValueError("revoke failed")) if failure_step == "revoke" else None,
    )

    with pytest.raises(ValueError, match=f"{failure_step} failed"):
        lark_cli.set_lark_app_credentials("alice", config, app_id="cli_new", app_secret="new-secret")

    assert config_file.read_text(encoding="utf-8") == "old-config"
    assert token_file.read_text(encoding="utf-8") == "old-token"


@pytest.mark.parametrize(
    ("app_id", "app_secret"),
    [("", "secret"), ("cli_new", "")],
)
def test_set_lark_app_credentials_rejects_missing_fields(monkeypatch, tmp_path, app_id, app_secret):
    _patch_paths(monkeypatch, tmp_path / "home")
    config = _config(tmp_path / "skills")

    def _must_not_run(*_args, **_kwargs):
        raise AssertionError("credentials must be validated before touching the CLI")

    monkeypatch.setattr(lark_cli, "_save_lark_app_config_with_cli", _must_not_run)

    with pytest.raises(ValueError):
        lark_cli.set_lark_app_credentials("alice", config, app_id=app_id, app_secret=app_secret)


def test_set_lark_app_credentials_rejects_invalid_brand(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path / "home")
    config = _config(tmp_path / "skills")
    monkeypatch.setattr(
        lark_cli,
        "_validate_lark_app_credentials_with_cli",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("invalid brand must fail first")),
    )

    with pytest.raises(ValueError, match="brand must be feishu or lark"):
        lark_cli.set_lark_app_credentials("alice", config, app_id="cli_new", app_secret="new-secret", brand="larks")


def test_set_lark_app_credentials_serializes_same_user(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path / "home")
    config = _config(tmp_path / "skills")
    active = 0
    max_active = 0
    state_lock = threading.Lock()

    def _validate(**_kwargs):
        nonlocal active, max_active
        with state_lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.05)
        with state_lock:
            active -= 1

    monkeypatch.setattr(lark_cli, "_validate_lark_app_credentials_with_cli", _validate)
    monkeypatch.setattr(lark_cli, "_save_lark_app_config_with_cli", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(lark_cli, "_revoke_lark_auth_from_snapshot", lambda _snapshot: None)
    monkeypatch.setattr(
        lark_cli,
        "get_lark_integration_status",
        lambda _user_id, _config, **_kwargs: _status_stub(app_configured=True, app_id="cli_new", auth_status="not_authorized"),
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda suffix: lark_cli.set_lark_app_credentials(
                    "alice",
                    config,
                    app_id=f"cli_{suffix}",
                    app_secret="new-secret",
                ),
                ("one", "two"),
            )
        )

    assert all(result.success for result in results)
    assert max_active == 1


def test_lark_config_credentials_route_switches_app(monkeypatch, tmp_path):
    config = _config(tmp_path / "skills")
    app = _make_app(system_role="user", config=config)
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        integrations_router,
        "set_lark_app_credentials",
        lambda _user_id, _config, *, app_id, app_secret, brand: (
            captured.update({"app_id": app_id, "app_secret": app_secret, "brand": brand})
            or lark_cli.LarkConfigCompleteResult(
                success=True,
                message="Lark/Feishu app switched. Reconnect to authorize the new app.",
                generation="switch-generation",
                status=_status_stub(app_configured=True, app_id="cli_new", auth_status="not_authorized"),
            )
        ),
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/integrations/lark/config/credentials",
            json={"app_id": "cli_new", "app_secret": "new-secret", "brand": "feishu"},
        )

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["generation"] == "switch-generation"
    assert response.json()["status"]["app_configured"] is True
    assert response.json()["status"]["auth"]["status"] == "not_authorized"
    assert captured == {"app_id": "cli_new", "app_secret": "new-secret", "brand": "feishu"}


def test_lark_config_credentials_route_rejects_invalid_brand(tmp_path):
    config = _config(tmp_path / "skills")
    app = _make_app(system_role="user", config=config)

    with TestClient(app) as client:
        response = client.post(
            "/api/integrations/lark/config/credentials",
            json={"app_id": "cli_new", "app_secret": "new-secret", "brand": "larks"},
        )

    assert response.status_code == 422
