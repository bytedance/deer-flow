from __future__ import annotations

import hashlib
import inspect
import io
import json
import multiprocessing
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
    monkeypatch.setattr(lark_cli, "_probe_provisioner_lark_cli_init_image", lambda _config: True)
    mode, ready, detail = lark_cli._resolve_sandbox_runtime_readiness(config, probe=True)
    assert mode == "init-container"
    assert ready is True
    assert detail is None


def test_status_runtime_mode_init_container_not_configured(monkeypatch, tmp_path) -> None:
    config = _config(tmp_path / "skills")
    config.sandbox = SimpleNamespace(
        use="deerflow.community.aio_sandbox:AioSandboxProvider",
        provisioner_url="http://provisioner:8002",
    )
    monkeypatch.setattr(lark_cli, "_probe_provisioner_lark_cli_init_image", lambda _config: False)
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
    monkeypatch.setattr(lark_cli, "_probe_provisioner_lark_cli_init_image", lambda _config: None)
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

    monkeypatch.setattr(lark_cli, "_probe_provisioner_lark_cli_init_image", _fail)
    mode, ready, detail = lark_cli._resolve_sandbox_runtime_readiness(config, probe=False)
    assert mode == "init-container"
    assert ready is False
    assert detail is None


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
        captured["args"] = args
        captured["env"] = kwargs["env"]
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=json.dumps(
                {
                    "verification_url": "https://open.feishu.cn/auth/mock",
                    "device_code": "device-code",
                    "expires_in": 600,
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(lark_cli.shutil, "which", lambda _name: "/usr/bin/lark-cli")
    monkeypatch.setattr(lark_cli.subprocess, "run", _run)

    result = lark_cli.start_lark_auth("alice", domains=("calendar",), recommend=True)

    assert result.verification_url == "https://open.feishu.cn/auth/mock"
    assert result.device_code == "device-code"
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
    env = captured["env"]
    assert isinstance(env, dict)
    assert env["LARKSUITE_CLI_CONFIG_DIR"].endswith("users/alice/integrations/lark-cli/config")


def test_start_lark_auth_uses_minimal_login_by_default(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path / "home")
    captured: dict[str, object] = {}

    def _run(args, **kwargs):
        captured["args"] = args
        captured["env"] = kwargs["env"]
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=json.dumps(
                {
                    "verification_url": "https://open.feishu.cn/auth/mock",
                    "device_code": "device-code",
                    "expires_in": 600,
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(lark_cli.shutil, "which", lambda _name: "/usr/bin/lark-cli")
    monkeypatch.setattr(lark_cli.subprocess, "run", _run)

    result = lark_cli.start_lark_auth("alice")

    assert result.verification_url == "https://open.feishu.cn/auth/mock"
    assert captured["args"] == [
        "/usr/bin/lark-cli",
        "auth",
        "login",
        "--no-wait",
        "--json",
    ]


def test_lark_cli_env_from_runtime_exposes_settings_auth_to_lark_commands(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path / "home")
    runtime = SimpleNamespace(context={"user_id": "alice"})

    env = _lark_cli_env_from_runtime(runtime, "lark-cli auth status --json", sandbox_paths=False)

    assert env is not None
    assert env["LARKSUITE_CLI_CONFIG_DIR"].endswith("users/alice/integrations/lark-cli/config")
    assert env["LARKSUITE_CLI_DATA_DIR"].endswith("users/alice/integrations/lark-cli/data")


def test_lark_cli_env_hardens_existing_credential_tree(monkeypatch, tmp_path) -> None:
    _patch_paths(monkeypatch, tmp_path / "home")
    config_dir = lark_cli.lark_cli_config_dir("alice")
    data_dir = lark_cli.lark_cli_data_dir("alice")
    config_dir.mkdir(parents=True)
    data_dir.mkdir(parents=True)
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
    assert stat.S_IMODE(data_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(secret_file.stat().st_mode) == 0o600
    assert stat.S_IMODE(token_file.stat().st_mode) == 0o600


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

    with pytest.raises(ValueError, match="symlink"):
        lark_cli.lark_cli_env_overlay("alice")


def test_save_lark_app_config_rehardens_files_written_by_cli(monkeypatch, tmp_path) -> None:
    _patch_paths(monkeypatch, tmp_path / "home")
    monkeypatch.setattr(lark_cli, "_require_lark_cli_path", lambda: "/usr/bin/lark-cli")

    def _run(args, **kwargs):
        config_file = Path(kwargs["env"]["LARKSUITE_CLI_CONFIG_DIR"]) / "config.json"
        config_file.write_text('{"appSecret":"secret"}', encoding="utf-8")
        config_file.chmod(0o644)
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(lark_cli.subprocess, "run", _run)

    lark_cli._save_lark_app_config_with_cli("alice", app_id="cli_app", app_secret="secret", brand="feishu")

    config_file = lark_cli.lark_cli_config_dir("alice") / "config.json"
    assert stat.S_IMODE(config_file.stat().st_mode) == 0o600


def test_lark_cli_json_rehardens_auth_files_written_by_cli(monkeypatch, tmp_path) -> None:
    _patch_paths(monkeypatch, tmp_path / "home")

    def _run(args, **kwargs):
        token_file = Path(kwargs["env"]["LARKSUITE_CLI_DATA_DIR"]) / "auth.json"
        token_file.write_text('{"token":"secret"}', encoding="utf-8")
        token_file.chmod(0o644)
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="{}", stderr="")

    monkeypatch.setattr(lark_cli.subprocess, "run", _run)

    lark_cli._run_lark_cli_json(["/usr/bin/lark-cli", "auth", "login"], user_id="alice", timeout=5)

    token_file = lark_cli.lark_cli_data_dir("alice") / "auth.json"
    assert stat.S_IMODE(token_file.stat().st_mode) == 0o600


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
    config_file = lark_cli.lark_cli_config_dir("alice") / "config.json"
    config_file.parent.mkdir(parents=True)
    config_file.write_text(
        json.dumps(
            {
                "currentApp": "cli_app",
                "apps": [
                    {
                        "name": "cli_app",
                        "appId": "cli_app",
                        "appSecret": "secret",
                        "brand": "feishu",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    calls: list[list[str]] = []

    monkeypatch.setattr(lark_cli, "_resolve_lark_cli_path", lambda: "/usr/bin/lark-cli")

    def _run(args, **_kwargs):
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

    result = lark_cli.complete_lark_auth("alice", config, device_code="device-code")

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

    result = lark_cli.complete_lark_auth(
        "alice",
        config,
        device_code="device-code",
        wait_timeout_seconds=8,
    )

    assert result.success is True
    assert captured["timeout"] == 8


def test_auth_complete_request_bounds_poll_timeout() -> None:
    model = integrations_router.LarkAuthCompleteRequest(device_code="device-code", wait_timeout_seconds=8)
    assert "wait_timeout_seconds" in type(model).model_fields
    assert model.wait_timeout_seconds == 8
    with pytest.raises(ValueError):
        integrations_router.LarkAuthCompleteRequest(device_code="device-code", wait_timeout_seconds=4)
    with pytest.raises(ValueError):
        integrations_router.LarkAuthCompleteRequest(device_code="device-code", wait_timeout_seconds=46)


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

    monkeypatch.setattr(
        lark_cli,
        "_poll_lark_app_registration",
        lambda **_kwargs: {
            "client_id": "cli_mock",
            "client_secret": "secret",
            "user_info": {"tenant_brand": "feishu"},
        },
    )
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

    result = lark_cli.complete_lark_config("alice", config, device_code="config-device-code", brand="feishu")

    assert result.success is True
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

    result = lark_cli.complete_lark_config("alice", config, device_code="config-device-code", brand="feishu")

    assert result.success is True
    assert [call["brand"] for call in poll_calls] == ["feishu", "lark"]
    assert captured == {
        "user_id": "alice",
        "app_id": "cli_mock",
        "app_secret": "secret",
        "brand": "lark",
    }


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


def test_lark_config_complete_route_saves_app_credentials(monkeypatch, tmp_path):
    config = _config(tmp_path / "skills")
    app = _make_app(system_role="user", config=config)

    monkeypatch.setattr(
        integrations_router,
        "complete_lark_config",
        lambda _user_id, _config, *, device_code, **_kwargs: lark_cli.LarkConfigCompleteResult(
            success=True,
            message=f"configured {device_code}",
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
            json={"device_code": "config-device-code", "brand": "feishu", "interval": 5, "expires_in": 600},
        )

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["status"]["app_configured"] is True


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
                expires_in=600,
            )
        ),
    )

    with TestClient(app) as client:
        response = client.post("/api/integrations/lark/auth/start", json={})

    assert response.status_code == 200
    assert response.json()["verification_url"] == "https://open.feishu.cn/auth/mock"
    assert response.json()["device_code"] == "device-code"
    assert captured_kwargs == {"domains": (), "scope": None, "recommend": False}


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
                expires_in=600,
            )
        ),
    )

    with TestClient(app) as client:
        response = client.post("/api/integrations/lark/auth/start", json={"recommend": True})

    assert response.status_code == 200
    assert response.json()["verification_url"] == "https://open.feishu.cn/auth/mock"
    assert response.json()["device_code"] == "device-code"
    assert captured_kwargs == {"domains": (), "scope": None, "recommend": True}


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
        response = client.post("/api/integrations/lark/auth/complete", json={"device_code": "device-code"})

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["status"]["auth"]["status"] == "authenticated"
    assert response.json()["status"]["auth"]["verified"] is True
    assert captured_kwargs == {"device_code": "device-code", "wait_timeout_seconds": 45}
