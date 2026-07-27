"""Managed Lark/Feishu CLI integration support.

The integration installs the official ``lark-*`` AI-agent skills into a
global read-only managed integration skill directory. It deliberately
does not use the ordinary custom-skill archive path: this is a trusted,
versioned first-party integration package, not user-authored mutable content.

Version resolution & integrity
-------------------------------
The installed skill-pack version follows the Gateway runtime ``lark-cli``
binary version (``lark-cli --version``). This keeps the managed skills aligned
with the server-side CLI that will execute them. ``FALLBACK_LARK_CLI_VERSION``
matches the Dockerfile/npm pin and is used only when the runtime binary is
unavailable or does not report a parseable version.

Integrity is enforced without pinning a per-version archive byte hash (GitHub
does not guarantee source-archive bytes are stable across their internal git
upgrades, and pinning conflicts with tracking latest). Instead:

* the download source is fixed to the official GitHub host over HTTPS and the
  version only comes from the Gateway runtime CLI version or the pinned
  fallback (no external URL injection);
* every archive member passes structural guards (zip-slip / symlink /
  executable-binary / size / required-skill completeness / ``SKILL.md`` parse);
* a **content** SHA-256 over the extracted skill tree, after DeerFlow's shared
  guidance is injected, is recorded in the manifest, so a reinstall whose
  effective skill content changed is detectable/auditable even when GitHub
  re-packs identical content with different archive bytes.

Runtime coupling: the npm-installed ``lark-cli`` binary version is pinned in
``backend/Dockerfile`` (``ARG LARK_CLI_NPM_VERSION``) and
``docker/docker-compose*.yaml`` as a bootstrap fallback. The admin install path
also manages a writable DeerFlow-owned Gateway CLI under
``.deer-flow/integrations/lark-cli/gateway-cli`` and prefers it over the system
PATH, so users do not need to run terminal installation commands. Reinstalling
the integration refreshes both the managed Gateway CLI and the skill pack to the
same version when network access is available. ``get_lark_integration_status``
surfaces ``latest_available_version`` and ``runtime_version_mismatch`` for
operators, and ``test_python_and_docker_lark_cli_versions_match`` pins the
fallback constant to the Dockerfile ARG so packaged deployments do not silently
diverge.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import posixpath
import re
import shutil
import subprocess
import tarfile
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback
    fcntl = None  # type: ignore[assignment]
    import msvcrt

from deerflow.config.app_config import AppConfig
from deerflow.config.paths import Paths, get_paths
from deerflow.skills.installer import is_executable_binary_prefix, is_symlink_member, is_unsafe_zip_member
from deerflow.skills.parser import parse_skill_file
from deerflow.skills.permissions import make_skill_tree_sandbox_readable
from deerflow.skills.types import SKILL_MD_FILE, SkillCategory

logger = logging.getLogger(__name__)

INTEGRATION_ID = "lark-cli"
# Matches the Gateway image/npm pin. Used when the runtime binary is unavailable
# or reports an unparsable version.
FALLBACK_LARK_CLI_VERSION = "v1.0.65"
LARK_CLI_NPM_VERSION = FALLBACK_LARK_CLI_VERSION.removeprefix("v")
LARK_CLI_NPM_PACKAGE = "@larksuite/cli"
LARK_CLI_GITHUB_REPO = "larksuite/cli"
LARK_CLI_LATEST_RELEASE_API = f"https://api.github.com/repos/{LARK_CLI_GITHUB_REPO}/releases/latest"
LARK_CLI_SOURCE_ARCHIVE_ENV = "DEER_FLOW_LARK_CLI_SKILLS_ARCHIVE"
LARK_CLI_SANDBOX_RUNTIME_SOURCE_ENV = "DEER_FLOW_LARK_CLI_SANDBOX_RUNTIME_DIR"
LARK_CLI_DOWNLOAD_TIMEOUT_SECONDS = 60
LARK_CLI_NPM_INSTALL_TIMEOUT_SECONDS = 180
LARK_HTTP_TIMEOUT_SECONDS = 20
LARK_CONFIG_POLL_TIMEOUT_SECONDS = 45
LARK_AUTH_COMPLETE_DEFAULT_WAIT_SECONDS = 45
LARK_AUTH_COMPLETE_MIN_WAIT_SECONDS = 5
LARK_AUTH_COMPLETE_MAX_WAIT_SECONDS = 45
LARK_CLI_LATEST_VERSION_TTL_SECONDS = 3600
LARK_CLI_MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
LARK_CLI_MAX_EXTRACTED_BYTES = 256 * 1024 * 1024
LARK_CLI_MAX_RUNTIME_ASSET_BYTES = 128 * 1024 * 1024
LARK_CLI_MANIFEST_FILE = ".deerflow-lark-cli-manifest.json"
LARK_CLI_SANDBOX_CONFIG_DIR = "/mnt/integrations/lark-cli/config"
LARK_CLI_SANDBOX_DATA_DIR = "/mnt/integrations/lark-cli/data"
LARK_CLI_SANDBOX_RUNTIME_DIR = "/mnt/integrations/lark-cli/runtime"
LARK_CLI_LINUX_ARCHES = ("amd64", "arm64")
LARK_CLI_RUNTIME_MANIFEST_FILE = ".deerflow-lark-cli-runtime.json"

# Arch-dispatch launcher for the sandbox runtime layout. Shared by the Gateway
# writer (`_write_lark_cli_sandbox_launcher`) and the `docker/lark-cli-init`
# init image so the two producers of `bin/lark-cli` never drift.
LARK_CLI_SANDBOX_LAUNCHER_SCRIPT = """#!/bin/sh
set -eu
case "$(uname -m)" in
  x86_64|amd64) arch=amd64 ;;
  aarch64|arm64) arch=arm64 ;;
  *) echo "Unsupported sandbox architecture: $(uname -m)" >&2; exit 126 ;;
esac
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec "$script_dir/../linux-$arch/lark-cli" "$@"
"""
_VERSION_TAG_RE = re.compile(r"v?\d+\.\d+\.\d+")
_DEERFLOW_LARK_SHARED_GUIDANCE_MARKER = "<!-- deerflow-lark-cli-auth-guidance-v2 -->"
_DEERFLOW_LARK_SHARED_GUIDANCE_LEGACY_MARKERS = ("<!-- deerflow-lark-cli-auth-guidance-v1 -->",)
_LARK_APP_REGISTRATION_PATH = "/oauth/v1/app/registration"

LARK_SKILL_NAMES: tuple[str, ...] = (
    "lark-approval",
    "lark-apps",
    "lark-attendance",
    "lark-base",
    "lark-calendar",
    "lark-contact",
    "lark-doc",
    "lark-drive",
    "lark-event",
    "lark-im",
    "lark-mail",
    "lark-markdown",
    "lark-minutes",
    "lark-note",
    "lark-okr",
    "lark-openapi-explorer",
    "lark-shared",
    "lark-sheets",
    "lark-skill-maker",
    "lark-slides",
    "lark-task",
    "lark-vc",
    "lark-vc-agent",
    "lark-whiteboard",
    "lark-wiki",
    "lark-workflow-meeting-summary",
    "lark-workflow-standup-report",
)
LARK_SKILL_NAME_SET = frozenset(LARK_SKILL_NAMES)
_LARK_INSTALL_THREAD_LOCK = threading.Lock()
_LARK_RUNTIME_INSTALL_THREAD_LOCK = threading.Lock()


@dataclass(frozen=True)
class LarkCliProbe:
    available: bool
    path: str | None = None
    version: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class LarkAuthProbe:
    status: str
    message: str | None = None
    user: str | None = None
    verified: bool = False


@dataclass(frozen=True)
class LarkIntegrationStatus:
    installed: bool
    version: str
    manifest_version: str | None
    latest_available_version: str | None
    runtime_version_mismatch: bool
    app_configured: bool
    app_id: str | None
    app_brand: str | None
    skills_expected: int
    skills_installed: int
    installed_skills: tuple[str, ...]
    enabled_skills: tuple[str, ...]
    install_path: str
    cli: LarkCliProbe
    auth: LarkAuthProbe
    sandbox_runtime_mode: str = "none"
    sandbox_runtime_ready: bool = False
    sandbox_runtime_detail: str | None = None


@dataclass(frozen=True)
class LarkInstallResult:
    success: bool
    installed_skills: tuple[str, ...]
    status: LarkIntegrationStatus
    message: str


@dataclass(frozen=True)
class LarkConfigStartResult:
    verification_url: str
    device_code: str
    expires_in: int | None = None
    interval: int | None = None
    user_code: str | None = None
    brand: str = "feishu"


@dataclass(frozen=True)
class LarkConfigCompleteResult:
    success: bool
    status: LarkIntegrationStatus
    message: str


@dataclass(frozen=True)
class LarkAuthStartResult:
    verification_url: str
    device_code: str
    expires_in: int | None = None
    user_code: str | None = None
    hint: str | None = None


@dataclass(frozen=True)
class LarkAuthCompleteResult:
    success: bool
    status: LarkIntegrationStatus
    message: str


def lark_integration_root(_user_id: str | None = None) -> Path:
    """Return the shared root for globally installed managed Lark skills.

    ``_user_id`` is accepted temporarily for source compatibility with the
    pre-global-install API; it does not influence the shared package path.
    """
    return get_paths().integration_skills_dir() / INTEGRATION_ID


def lark_manifest_path(user_id: str) -> Path:
    return lark_integration_root(user_id) / LARK_CLI_MANIFEST_FILE


def lark_skills_installed(user_id: str | None = None) -> bool:
    """Whether the managed Lark skill pack is installed.

    Mirrors the ``installed`` field of :func:`get_lark_integration_status`
    (manifest present and ``lark-shared`` extracted) without probing the CLI or
    auth. Used to decide whether a sandbox should request the lark-cli runtime.
    """
    root = lark_integration_root(user_id)
    manifest = _read_manifest(root)
    if not manifest:
        return False
    return "lark-shared" in _installed_lark_skill_names(root)


def lark_cli_config_dir(user_id: str) -> Path:
    return get_paths().user_dir(user_id) / "integrations" / INTEGRATION_ID / "config"


def lark_cli_data_dir(user_id: str) -> Path:
    return get_paths().user_dir(user_id) / "integrations" / INTEGRATION_ID / "data"


def ensure_lark_cli_credential_tree(user_id: str, *, paths: Paths | None = None) -> None:
    """Make the user's secret-bearing Lark CLI tree owner-only.

    The CLI writes plaintext app secrets and OAuth tokens beneath this tree.
    Reject links before changing modes so a compromised tree cannot redirect a
    chmod or subsequent CLI write outside the user's integration directory.
    """
    paths = paths or get_paths()
    root = paths.user_dir(user_id) / "integrations" / INTEGRATION_ID
    if root.is_symlink():
        raise ValueError(f"Lark CLI credential path must not be a symlink: {root}")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root.chmod(0o700)
    for required in (root / "config", root / "data"):
        if required.is_symlink():
            raise ValueError(f"Lark CLI credential path must not be a symlink: {required}")
        required.mkdir(parents=True, exist_ok=True, mode=0o700)
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"Lark CLI credential path must not be a symlink: {path}")
        if path.is_dir():
            path.chmod(0o700)
        elif path.is_file():
            path.chmod(0o600)
        else:
            raise ValueError(f"Unsupported file type in Lark CLI credential tree: {path}")


def lark_cli_managed_gateway_dir() -> Path:
    """Gateway-scoped DeerFlow-managed lark-cli install root."""
    return get_paths().base_dir / "integrations" / INTEGRATION_ID / "gateway-cli"


def lark_cli_managed_sandbox_dir() -> Path:
    """Gateway-visible source directory mounted into Linux AIO sandboxes."""
    return get_paths().base_dir / "integrations" / INTEGRATION_ID / "sandbox-cli"


def _lark_cli_release_asset_name(version: str, arch: str) -> str:
    tag = _normalize_lark_cli_version_tag(version)
    if tag is None:
        raise ValueError(f"Invalid Lark CLI version tag: {version!r}")
    if arch not in LARK_CLI_LINUX_ARCHES:
        raise ValueError(f"Unsupported Lark CLI Linux architecture: {arch!r}")
    return f"lark-cli-{tag.removeprefix('v')}-linux-{arch}.tar.gz"


def _lark_cli_release_asset_url(version: str, asset_name: str) -> str:
    tag = _normalize_lark_cli_version_tag(version)
    if tag is None:
        raise ValueError(f"Invalid Lark CLI version tag: {version!r}")
    quoted_asset = urllib.parse.quote(asset_name, safe="")
    return f"https://github.com/{LARK_CLI_GITHUB_REPO}/releases/download/{tag}/{quoted_asset}"


def _download_lark_release_asset(version: str, asset_name: str, *, max_bytes: int = LARK_CLI_MAX_RUNTIME_ASSET_BYTES) -> bytes:
    """Download one official release asset with a strict size bound."""
    request = urllib.request.Request(
        _lark_cli_release_asset_url(version, asset_name),
        headers={"Accept": "application/octet-stream", "User-Agent": "deer-flow"},
    )
    try:
        with urllib.request.urlopen(request, timeout=LARK_CLI_DOWNLOAD_TIMEOUT_SECONDS) as response:
            chunks: list[bytes] = []
            total = 0
            while chunk := response.read(1024 * 1024):
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError(f"Lark CLI release asset {asset_name!r} is too large.")
                chunks.append(chunk)
    except ValueError:
        raise
    except Exception as exc:  # noqa: BLE001 - network boundary
        raise ValueError(f"Could not download official Lark CLI release asset {asset_name!r} for {version}.") from exc
    return b"".join(chunks)


def _release_checksums(raw: bytes) -> dict[str, str]:
    checksums: dict[str, str] = {}
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("Lark CLI release checksums are not valid UTF-8.") from exc
    for line in text.splitlines():
        parts = line.strip().split()
        if len(parts) < 2 or not re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
            continue
        checksums[parts[-1].lstrip("*")] = parts[0].lower()
    return checksums


def _extract_lark_cli_runtime_binary(archive: bytes, destination: Path) -> None:
    """Safely extract the single CLI executable from an official tar archive."""
    candidate: bytes | None = None
    total = 0
    try:
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:*") as tf:
            for member in tf.getmembers():
                normalized = posixpath.normpath(member.name.replace("\\", "/"))
                parts = PurePosixPath(normalized).parts
                if normalized.startswith("/") or ".." in parts or member.issym() or member.islnk() or not (member.isdir() or member.isfile()):
                    raise ValueError(f"Unsafe Lark CLI runtime archive member: {member.name}")
                if member.isfile():
                    total += member.size
                    if total > LARK_CLI_MAX_RUNTIME_ASSET_BYTES:
                        raise ValueError("Lark CLI runtime archive expands beyond the allowed size.")
                    if PurePosixPath(normalized).name == "lark-cli":
                        extracted = tf.extractfile(member)
                        if extracted is None or candidate is not None:
                            raise ValueError("Lark CLI runtime archive must contain exactly one lark-cli executable.")
                        candidate = extracted.read()
    except tarfile.TarError as exc:
        raise ValueError("Lark CLI runtime archive is not a valid tar archive.") from exc
    if not candidate:
        raise ValueError("Lark CLI runtime archive does not contain a lark-cli executable.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(candidate)
    destination.chmod(0o755)


def _write_lark_cli_sandbox_launcher(staging: Path) -> None:
    launcher = staging / "bin" / "lark-cli"
    launcher.parent.mkdir(parents=True, exist_ok=True)
    launcher.write_text(LARK_CLI_SANDBOX_LAUNCHER_SCRIPT, encoding="utf-8")
    launcher.chmod(0o755)


def _validate_lark_cli_sandbox_runtime(root: Path) -> None:
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Managed Lark CLI sandbox runtime root must be a regular directory, not a symlink.")
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"Managed Lark CLI sandbox runtime must not contain a symlink: {path}")
        if not (path.is_dir() or path.is_file()):
            raise ValueError(f"Managed Lark CLI sandbox runtime contains an unsupported file type: {path}")
    for relative in (Path("bin/lark-cli"), *(Path(f"linux-{arch}/lark-cli") for arch in LARK_CLI_LINUX_ARCHES)):
        candidate = root / relative
        if not candidate.is_file():
            raise ValueError(f"Managed Lark CLI sandbox runtime is missing a regular file: {relative}")
        if candidate.stat().st_mode & 0o111 == 0:
            raise ValueError(f"Managed Lark CLI sandbox runtime file is not executable: {relative}")


def _read_json_object_file(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


@contextmanager
def _exclusive_install_lock(lock_path: Path, thread_lock):
    """Hold one advisory file lock plus its in-process counterpart."""
    with thread_lock, lock_path.open("a+b") as lock_file:
        lock_file.seek(0, os.SEEK_END)
        if lock_file.tell() == 0:
            lock_file.write(b"\0")
            lock_file.flush()
        lock_file.seek(0)
        if fcntl is not None:
            fcntl.flock(lock_file, fcntl.LOCK_EX)
        else:  # pragma: no cover - Windows fallback
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
        try:
            yield
        finally:
            lock_file.seek(0)
            if fcntl is not None:
                fcntl.flock(lock_file, fcntl.LOCK_UN)
            else:  # pragma: no cover - Windows fallback
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)


def _ensure_managed_sandbox_lark_cli(version: str) -> Path:
    """Install verified official Linux binaries for AIO sandbox execution."""
    tag = _normalize_lark_cli_version_tag(version)
    if tag is None:
        raise ValueError(f"Invalid Lark CLI version tag: {version!r}")
    target = lark_cli_managed_sandbox_dir()
    parent = target.parent
    parent.mkdir(parents=True, exist_ok=True)
    with _exclusive_install_lock(parent / ".sandbox-cli.install.lock", _LARK_RUNTIME_INSTALL_THREAD_LOCK):
        return _ensure_managed_sandbox_lark_cli_locked(tag, target, parent)


def _ensure_managed_sandbox_lark_cli_locked(tag: str, target: Path, parent: Path) -> Path:
    manifest = _read_json_object_file(target / LARK_CLI_RUNTIME_MANIFEST_FILE)
    if manifest and manifest.get("version") == tag:
        _validate_lark_cli_sandbox_runtime(target)
        return target

    staging = Path(tempfile.mkdtemp(prefix=".installing-sandbox-cli-", dir=str(parent)))
    backup: Path | None = None
    try:
        source_override = os.getenv(LARK_CLI_SANDBOX_RUNTIME_SOURCE_ENV)
        if source_override:
            source = Path(source_override)
            _validate_lark_cli_sandbox_runtime(source)
            shutil.copytree(source, staging, dirs_exist_ok=True, symlinks=False)
        else:
            checksums = _release_checksums(_download_lark_release_asset(tag, "checksums.txt", max_bytes=1024 * 1024))
            for arch in LARK_CLI_LINUX_ARCHES:
                asset_name = _lark_cli_release_asset_name(tag, arch)
                archive = _download_lark_release_asset(tag, asset_name)
                expected = checksums.get(asset_name)
                actual = hashlib.sha256(archive).hexdigest()
                if expected is None or actual != expected:
                    raise ValueError(f"Lark CLI release asset checksum mismatch: {asset_name}")
                _extract_lark_cli_runtime_binary(archive, staging / f"linux-{arch}" / "lark-cli")
            _write_lark_cli_sandbox_launcher(staging)

        _validate_lark_cli_sandbox_runtime(staging)
        (staging / LARK_CLI_RUNTIME_MANIFEST_FILE).write_text(
            json.dumps({"version": tag}, indent=2) + "\n",
            encoding="utf-8",
        )
        if target.exists():
            backup = parent / f".replacing-sandbox-cli-{os.getpid()}"
            if backup.exists():
                shutil.rmtree(backup, ignore_errors=True)
            target.rename(backup)
        staging.rename(target)
        if backup is not None:
            shutil.rmtree(backup, ignore_errors=True)
        return target
    except Exception:
        if backup is not None and backup.exists() and not target.exists():
            backup.rename(target)
        raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _lark_cli_managed_bin_dir() -> Path:
    return lark_cli_managed_gateway_dir() / "node_modules" / ".bin"


def _lark_cli_managed_path() -> str | None:
    for name in ("lark-cli", "lark-cli.cmd"):
        candidate = _lark_cli_managed_bin_dir() / name
        if candidate.exists():
            return str(candidate)
    return None


def lark_cli_env_overlay(user_id: str, *, sandbox_paths: bool = False) -> dict[str, str]:
    """Environment overlay for lark-cli using DeerFlow-managed credentials.

    The directories are per-user so a local trusted-mode login cannot bleed
    across accounts. Auth Proxy support can later replace these directories for
    sandbox execution without changing the status API contract.
    """
    if sandbox_paths:
        config_dir: Path | str = LARK_CLI_SANDBOX_CONFIG_DIR
        data_dir: Path | str = LARK_CLI_SANDBOX_DATA_DIR
    else:
        config_dir = lark_cli_config_dir(user_id)
        data_dir = lark_cli_data_dir(user_id)
        ensure_lark_cli_credential_tree(user_id)
    overlay = {
        "LARKSUITE_CLI_CONFIG_DIR": str(config_dir),
        "LARKSUITE_CLI_DATA_DIR": str(data_dir),
        "LARKSUITE_CLI_NO_UPDATE_NOTIFIER": "1",
        "LARKSUITE_CLI_NO_SKILLS_NOTIFIER": "1",
    }
    if not sandbox_paths and _lark_cli_managed_path() is not None:
        overlay["PATH"] = f"{_lark_cli_managed_bin_dir()}{os.pathsep}{os.environ.get('PATH', '')}"
    elif sandbox_paths:
        overlay["PATH"] = f"{LARK_CLI_SANDBOX_RUNTIME_DIR}/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
    return overlay


def lark_cli_env(user_id: str) -> dict[str, str]:
    """Full environment for Gateway-side lark-cli probes."""
    return {**os.environ, **lark_cli_env_overlay(user_id)}


def probe_lark_cli() -> LarkCliProbe:
    path = _resolve_lark_cli_path()
    if path is None:
        return LarkCliProbe(available=False, error="lark-cli is not installed on the Gateway")
    return _probe_lark_cli_at_path(path)


def _probe_lark_cli_at_path(path: str) -> LarkCliProbe:
    try:
        result = subprocess.run(
            [path, "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception as exc:  # noqa: BLE001 - probe boundary
        return LarkCliProbe(available=False, path=path, error=str(exc))

    output = (result.stdout or result.stderr or "").strip()
    if result.returncode != 0:
        return LarkCliProbe(available=False, path=path, error=output or f"exit code {result.returncode}")
    return LarkCliProbe(available=True, path=path, version=output or None)


def probe_lark_auth(user_id: str, *, verify: bool = False) -> LarkAuthProbe:
    """Probe the user's Lark authorization state.

    By default this only checks local token presence (``auth status --json``),
    which is cheap and offline — suitable for the frequently-polled status
    endpoint. Pass ``verify=True`` to add ``--verify`` for a live token check
    against Lark; reserve that for the explicit "complete authorization" step
    since it costs a network round-trip on every call.
    """
    path = _resolve_lark_cli_path()
    if path is None:
        return LarkAuthProbe(status="unavailable", message="lark-cli is not installed on the Gateway")
    app_config = read_lark_app_config(user_id)
    if not app_config["configured"]:
        return LarkAuthProbe(status="not_configured", message="Lark app is not configured")
    args = [path, "auth", "status", "--json"]
    if verify:
        args.append("--verify")
    try:
        result = subprocess.run(
            args,
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
            env=lark_cli_env(user_id),
        )
    except subprocess.TimeoutExpired:
        return LarkAuthProbe(status="error", message="lark-cli auth status timed out")
    except Exception as exc:  # noqa: BLE001 - probe boundary
        return LarkAuthProbe(status="error", message=str(exc))

    raw = (result.stdout or result.stderr or "").strip()
    data: dict[str, Any] | None = None
    if raw:
        try:
            parsed = json.loads(raw)
            data = parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            data = None

    if result.returncode != 0:
        message = _auth_error_message(data) if data else raw
        return LarkAuthProbe(status="not_authorized", message=message or "Lark user authorization is not configured")

    user = None
    if data:
        identities = data.get("identities")
        if isinstance(identities, dict):
            user_info = identities.get("user")
            if isinstance(user_info, dict):
                user = str(user_info.get("userName") or user_info.get("openId") or "") or None
        if user is None and data.get("userName"):
            user = str(data["userName"])
    if verify:
        return LarkAuthProbe(
            status="authenticated",
            user=user,
            message="Lark/Feishu authorization is live-verified.",
            verified=True,
        )
    return LarkAuthProbe(
        status="authenticated",
        user=user,
        message="Lark/Feishu credentials are configured locally but not live-verified.",
        verified=False,
    )


def _resolve_sandbox_runtime_readiness(
    config: AppConfig,
    *,
    probe: bool,
) -> tuple[str, bool, str | None]:
    """Resolve the sandbox lark-cli runtime mode and readiness.

    Modes:
    - ``none``: sandboxes don't run lark-cli (non-AIO provider).
    - ``gateway-download``: local AIO — the Gateway stages a ``sandbox-cli`` dir
      and bind-mounts it; ready when that dir validates.
    - ``init-container``: remote provisioner — a lark-cli init image provisions
      the runtime; ready when the provisioner reports the init image is configured.

    ``probe`` gates the (best-effort, short-timeout) provisioner capability call.
    """
    if not _uses_aio_sandbox(config):
        return "none", False, "Sandbox does not run lark-cli in this configuration."

    if _uses_remote_provisioner(config):
        if not probe:
            return "init-container", False, None
        init_image = _probe_provisioner_lark_cli_init_image(config)
        if init_image is None:
            return "init-container", False, "Could not reach the provisioner to confirm the lark-cli init image."
        if not init_image:
            return "init-container", False, "The provisioner has no lark-cli init image configured (LARK_CLI_INIT_IMAGE)."
        return "init-container", True, None

    # Local AIO: Gateway-download runtime dir.
    runtime_dir = lark_cli_managed_sandbox_dir()
    try:
        _validate_lark_cli_sandbox_runtime(runtime_dir)
    except (ValueError, OSError):
        return "gateway-download", False, "The managed sandbox lark-cli runtime is not installed."
    return "gateway-download", True, None


def get_lark_integration_status(
    user_id: str,
    config: AppConfig,
    *,
    verify_auth: bool = False,
    check_latest: bool = False,
    check_runtime: bool = False,
) -> LarkIntegrationStatus:
    root = lark_integration_root(user_id)
    manifest = _read_manifest(root)
    app_config = read_lark_app_config(user_id)
    installed_skills = tuple(sorted(_installed_lark_skill_names(root)))
    enabled_skills = tuple(sorted(_enabled_lark_skill_names(user_id, config)))
    manifest_version = str(manifest.get("version")) if manifest else None
    cli = probe_lark_cli()
    latest_available = _cached_latest_lark_cli_version() if check_latest else None
    runtime_mode, runtime_ready, runtime_detail = _resolve_sandbox_runtime_readiness(config, probe=check_runtime)
    return LarkIntegrationStatus(
        installed=bool(manifest) and "lark-shared" in installed_skills,
        version=manifest_version or FALLBACK_LARK_CLI_VERSION,
        manifest_version=manifest_version,
        latest_available_version=latest_available,
        runtime_version_mismatch=_versions_drifted(manifest_version, cli.version),
        app_configured=bool(app_config["configured"]),
        app_id=app_config["app_id"],
        app_brand=app_config["brand"],
        skills_expected=len(LARK_SKILL_NAMES),
        skills_installed=len(installed_skills),
        installed_skills=installed_skills,
        enabled_skills=enabled_skills,
        install_path=str(root),
        cli=cli,
        auth=probe_lark_auth(user_id, verify=verify_auth),
        sandbox_runtime_mode=runtime_mode,
        sandbox_runtime_ready=runtime_ready,
        sandbox_runtime_detail=runtime_detail,
    )


def _normalize_version(value: str | None) -> str | None:
    """Extract a comparable ``major.minor.patch`` from a version-ish string."""
    if not value:
        return None
    match = re.search(r"\d+\.\d+\.\d+", value)
    return match.group(0) if match else None


def _versions_drifted(manifest_version: str | None, cli_version: str | None) -> bool:
    """True when both versions are known and their numeric cores differ.

    The manifest records the installed skill-pack version; ``cli_version`` is
    the Gateway runtime ``lark-cli`` binary. Unknown on either side means we
    cannot claim a mismatch, so we stay quiet.
    """
    left = _normalize_version(manifest_version)
    right = _normalize_version(cli_version)
    if left is None or right is None:
        return False
    return left != right


def _resolve_runtime_lark_cli_version() -> str:
    """Resolve the skill-pack version that matches the Gateway runtime CLI.

    Managed Lark skills are executed by the server-side ``lark-cli`` binary, so
    integration installs should align to that binary rather than blindly taking
    GitHub's newest release. Packaged deployments install the pinned fallback in
    the Gateway image; local/dev deployments can override this by putting a
    newer ``lark-cli`` on the Gateway PATH and restarting the backend.
    """
    cli = probe_lark_cli()
    version = _normalize_version(cli.version)
    return f"v{version}" if version is not None else FALLBACK_LARK_CLI_VERSION


def read_lark_app_config(user_id: str) -> dict[str, str | bool | None]:
    ensure_lark_cli_credential_tree(user_id)
    config_path = lark_cli_config_dir(user_id) / "config.json"
    if not config_path.is_file():
        return {"configured": False, "app_id": None, "brand": None}
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"configured": False, "app_id": None, "brand": None}
    if not isinstance(data, dict):
        return {"configured": False, "app_id": None, "brand": None}
    apps = data.get("apps")
    if not isinstance(apps, list) or not apps:
        return {"configured": False, "app_id": None, "brand": None}
    current = data.get("currentApp")
    app = None
    if isinstance(current, str) and current:
        app = next((candidate for candidate in apps if isinstance(candidate, dict) and (candidate.get("name") == current or candidate.get("appId") == current)), None)
    if app is None:
        app = apps[0] if isinstance(apps[0], dict) else None
    if not isinstance(app, dict):
        return {"configured": False, "app_id": None, "brand": None}
    app_id = str(app.get("appId") or "").strip()
    app_secret = app.get("appSecret")
    brand = str(app.get("brand") or "feishu").strip() or "feishu"
    return {"configured": bool(app_id and app_secret), "app_id": app_id or None, "brand": brand}


def install_lark_integration(
    user_id: str,
    config: AppConfig,
    *,
    source_archive: str | Path | None = None,
) -> LarkInstallResult:
    env_archive = os.getenv(LARK_CLI_SOURCE_ARCHIVE_ENV)
    if source_archive is not None:
        archive_path = Path(source_archive)
        resolved_version = None
        created_temp_archive = False
    elif env_archive:
        archive_path = Path(env_archive)
        resolved_version = None
        created_temp_archive = False
    else:
        cli = _ensure_managed_gateway_lark_cli()
        runtime_version = _normalize_version(cli.version)
        resolved_version = f"v{runtime_version}" if runtime_version is not None else FALLBACK_LARK_CLI_VERSION
        archive_path = _download_lark_archive(resolved_version)
        created_temp_archive = True

    previous = _read_manifest(lark_integration_root(user_id))
    previous_content_sha = str(previous.get("content_sha256")) if previous else None
    try:
        installed_skills, content_sha = _install_lark_skills_from_archive(user_id, archive_path, version=resolved_version)
    finally:
        if created_temp_archive:
            try:
                archive_path.unlink(missing_ok=True)
            except OSError:
                pass

    if _uses_aio_sandbox(config) and not _uses_remote_provisioner(config):
        installed_manifest = _read_manifest(lark_integration_root()) or {}
        sandbox_version = str(installed_manifest.get("version") or resolved_version or FALLBACK_LARK_CLI_VERSION)
        _ensure_managed_sandbox_lark_cli(sandbox_version)

    status = get_lark_integration_status(user_id, config)
    content_changed = previous_content_sha is not None and previous_content_sha != content_sha
    message = f"Installed {len(installed_skills)} Lark/Feishu skills."
    if content_changed:
        message += " Skill content changed since the previous install."
    return LarkInstallResult(
        success=True,
        installed_skills=installed_skills,
        status=status,
        message=message,
    )


def _uses_aio_sandbox(config: AppConfig) -> bool:
    sandbox = getattr(config, "sandbox", None)
    use = getattr(sandbox, "use", None)
    if use is None and isinstance(sandbox, dict):
        use = sandbox.get("use")
    return isinstance(use, str) and "aio_sandbox" in use.lower()


def _sandbox_config_value(config: AppConfig, key: str) -> str:
    """Read a sandbox config value as a string, tolerating dict/attr configs."""
    sandbox = getattr(config, "sandbox", None)
    value = getattr(sandbox, key, None)
    if value is None and isinstance(sandbox, dict):
        value = sandbox.get(key)
    return str(value).strip() if value else ""


def _uses_remote_provisioner(config: AppConfig) -> bool:
    """True when sandboxes are provisioned by a remote provisioner (K8s mode)."""
    return bool(_sandbox_config_value(config, "provisioner_url"))


def _probe_provisioner_lark_cli_init_image(config: AppConfig) -> bool | None:
    """Best-effort read of the provisioner's lark-cli init-image capability.

    Returns True/False when the provisioner answers, or None when it can't be
    reached. Used only to surface a sandbox-runtime readiness signal; failures
    degrade to "not ready" rather than raising.
    """
    base = _sandbox_config_value(config, "provisioner_url")
    if not base:
        return None
    api_key = _sandbox_config_value(config, "provisioner_api_key")
    headers = {"X-API-Key": api_key} if api_key else {}
    url = f"{base.rstrip('/')}/api/capabilities"
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "deer-flow", **headers})
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return bool(payload.get("lark_cli_init_image"))
    except Exception:
        return None


def start_lark_config(user_id: str, *, brand: str = "feishu") -> LarkConfigStartResult:
    """Start the browser flow that creates/binds a Lark OAuth app for this user."""
    parsed_brand = _normalize_lark_brand(brand)
    begin_data = _request_lark_app_registration_begin(parsed_brand)
    user_code = str(begin_data.get("user_code") or "").strip()
    device_code = str(begin_data.get("device_code") or "").strip()
    if not user_code or not device_code:
        raise ValueError("Lark app registration did not return a user_code and device_code.")
    verification_url = _build_lark_config_verification_url(parsed_brand, user_code)
    return LarkConfigStartResult(
        verification_url=verification_url,
        device_code=device_code,
        expires_in=_int_or_none(begin_data.get("expires_in")),
        interval=_int_or_none(begin_data.get("interval")),
        user_code=user_code,
        brand=parsed_brand,
    )


def complete_lark_config(
    user_id: str,
    config: AppConfig,
    *,
    device_code: str,
    brand: str = "feishu",
    interval: int | None = None,
    expires_in: int | None = None,
) -> LarkConfigCompleteResult:
    """Complete app registration and persist app credentials through lark-cli."""
    device_code = device_code.strip()
    if not device_code:
        raise ValueError("device_code is required.")
    parsed_brand = _normalize_lark_brand(brand)
    result = _poll_lark_app_registration(
        device_code=device_code,
        brand=parsed_brand,
        interval=interval or 5,
        expires_in=expires_in or 300,
    )
    if not result.get("client_secret") and _tenant_brand(result) == "lark":
        # Lark CLI starts polling on the Feishu accounts host for both brands.
        # For Lark tenants that response can include user_info.tenant_brand and
        # client_id but omit client_secret; polling the Lark accounts host with
        # the same device_code returns the complete app credentials.
        result = _poll_lark_app_registration(
            device_code=device_code,
            brand="lark",
            interval=interval or 5,
            expires_in=expires_in or 300,
        )

    app_id = str(result.get("client_id") or "").strip()
    app_secret = str(result.get("client_secret") or "").strip()
    final_brand = _tenant_brand(result) or parsed_brand
    if not app_id or not app_secret:
        raise ValueError("Lark app registration succeeded but did not return app credentials.")

    _save_lark_app_config_with_cli(user_id, app_id=app_id, app_secret=app_secret, brand=final_brand)
    status = get_lark_integration_status(user_id, config)
    return LarkConfigCompleteResult(
        success=True,
        status=status,
        message="Lark/Feishu connection setup completed.",
    )


def start_lark_auth(
    user_id: str,
    *,
    domains: tuple[str, ...] = (),
    scope: str | None = None,
    recommend: bool = False,
) -> LarkAuthStartResult:
    """Start a non-blocking Lark device authorization flow.

    The returned URL is safe to show in the browser UI or in a chat message.
    ``device_code`` must be sent back to :func:`complete_lark_auth` after the
    user finishes authorization in Lark/Feishu.
    """
    path = _require_lark_cli_path()
    args = [path, "auth", "login", "--no-wait", "--json"]
    if recommend:
        args.append("--recommend")
    if scope:
        args.extend(["--scope", scope])
    for domain in domains:
        if domain:
            args.extend(["--domain", domain])

    data = _run_lark_cli_json(args, user_id=user_id, timeout=20)
    verification_url = str(data.get("verification_url") or data.get("verification_uri_complete") or "").strip()
    device_code = str(data.get("device_code") or "").strip()
    if not verification_url or not device_code:
        raise ValueError("lark-cli did not return a verification_url and device_code.")

    return LarkAuthStartResult(
        verification_url=verification_url,
        device_code=device_code,
        expires_in=_int_or_none(data.get("expires_in")),
        user_code=str(data.get("user_code") or "") or None,
        hint=str(data.get("hint") or "") or None,
    )


def complete_lark_auth(
    user_id: str,
    config: AppConfig,
    *,
    device_code: str,
    wait_timeout_seconds: int = LARK_AUTH_COMPLETE_DEFAULT_WAIT_SECONDS,
) -> LarkAuthCompleteResult:
    """Complete a Lark device authorization flow after the user approves it."""
    device_code = device_code.strip()
    if not device_code:
        raise ValueError("device_code is required.")
    if not LARK_AUTH_COMPLETE_MIN_WAIT_SECONDS <= wait_timeout_seconds <= LARK_AUTH_COMPLETE_MAX_WAIT_SECONDS:
        raise ValueError(f"wait_timeout_seconds must be between {LARK_AUTH_COMPLETE_MIN_WAIT_SECONDS} and {LARK_AUTH_COMPLETE_MAX_WAIT_SECONDS}.")

    path = _require_lark_cli_path()
    _run_lark_cli_json(
        [path, "auth", "login", "--device-code", device_code, "--json"],
        user_id=user_id,
        timeout=wait_timeout_seconds,
        allow_empty_success=True,
    )
    status = get_lark_integration_status(user_id, config, verify_auth=True)
    return LarkAuthCompleteResult(
        success=status.auth.status == "authenticated",
        status=status,
        message="Lark/Feishu authorization completed." if status.auth.status == "authenticated" else (status.auth.message or "Lark/Feishu authorization status is still pending."),
    )


def _resolve_lark_cli_path() -> str | None:
    return _lark_cli_managed_path() or shutil.which("lark-cli")


def _ensure_managed_gateway_lark_cli() -> LarkCliProbe:
    """Install/update the DeerFlow-managed Gateway lark-cli.

    This is called by the admin install endpoint so non-technical users do not
    need to install ``@larksuite/cli`` in a terminal. If npm/GitHub are not
    reachable but an existing CLI is already available (managed or on PATH), we
    keep using it and let the skill-pack install align to that runtime version.
    """
    target_version = _resolve_latest_lark_cli_version()
    current = probe_lark_cli()
    current_version = _normalize_version(current.version)
    if current.available and current_version == _normalize_version(target_version):
        return current

    try:
        return _install_managed_gateway_lark_cli(target_version)
    except Exception:
        fallback = probe_lark_cli()
        if fallback.available:
            logger.warning("Could not update managed lark-cli; using existing Gateway lark-cli", exc_info=True)
            return fallback
        raise


def _install_managed_gateway_lark_cli(version: str) -> LarkCliProbe:
    normalized = _normalize_lark_cli_version_tag(version)
    if normalized is None:
        raise ValueError(f"Invalid Lark CLI npm version: {version!r}")
    npm_version = normalized.removeprefix("v")
    npm = shutil.which("npm")
    if npm is None:
        raise FileNotFoundError("npm is not available on the Gateway; cannot install managed @larksuite/cli.")

    install_root = lark_cli_managed_gateway_dir()
    install_root.mkdir(parents=True, exist_ok=True)
    # NOTE: this runs @larksuite/cli's install scripts (postinstall fetches the
    # platform lark-cli binary), so `--ignore-scripts` is not viable here — the
    # CLI would be unusable without it. The tradeoff: an admin-triggered install
    # executes the official package's install scripts (and those of its deps)
    # with Gateway privileges, so a supply-chain compromise of that package is
    # the blast radius. This mirrors the pinned `npm install -g` in the Gateway
    # Dockerfile; both are gated behind the admin install action.
    result = subprocess.run(
        [
            npm,
            "install",
            "--prefix",
            str(install_root),
            "--no-audit",
            "--no-fund",
            f"{LARK_CLI_NPM_PACKAGE}@{npm_version}",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=LARK_CLI_NPM_INSTALL_TIMEOUT_SECONDS,
        env={**os.environ, "npm_config_update_notifier": "false"},
    )
    if result.returncode != 0:
        raw = (result.stderr or result.stdout or "").strip()
        raise ValueError(raw or f"npm install {LARK_CLI_NPM_PACKAGE}@{npm_version} exited with code {result.returncode}")

    path = _lark_cli_managed_path()
    if path is None:
        raise FileNotFoundError("Managed lark-cli install completed, but no lark-cli binary was found.")
    probe = _probe_lark_cli_at_path(path)
    if not probe.available:
        raise ValueError(probe.error or "Managed lark-cli install did not produce a runnable CLI.")
    return probe


def _require_lark_cli_path() -> str:
    path = _resolve_lark_cli_path()
    if path is None:
        raise FileNotFoundError("lark-cli is not installed on the Gateway. Install the managed Lark integration as an admin, or rebuild the Gateway image with @larksuite/cli installed.")
    return path


def _normalize_lark_brand(brand: str) -> str:
    return "lark" if brand.strip().lower() == "lark" else "feishu"


def _lark_endpoints(brand: str) -> dict[str, str]:
    if _normalize_lark_brand(brand) == "lark":
        return {
            "open": "https://open.larksuite.com",
            "accounts": "https://accounts.larksuite.com",
        }
    return {
        "open": "https://open.feishu.cn",
        "accounts": "https://accounts.feishu.cn",
    }


def _request_lark_app_registration_begin(brand: str) -> dict[str, Any]:
    # lark-cli uses the Feishu accounts endpoint for the begin step, then
    # switches to the tenant brand only if the poll response indicates Lark.
    accounts_url = _lark_endpoints("feishu")["accounts"] + _LARK_APP_REGISTRATION_PATH
    body = urllib.parse.urlencode(
        {
            "action": "begin",
            "archetype": "PersonalAgent",
            "auth_method": "client_secret",
            "request_user_info": "open_id tenant_brand",
        }
    ).encode("utf-8")
    data = _post_lark_form(accounts_url, body)
    if "error" in data:
        raise ValueError(str(data.get("error_description") or data.get("error") or "Lark app registration failed."))
    return data


def _build_lark_config_verification_url(brand: str, user_code: str) -> str:
    base = f"{_lark_endpoints(brand)['open']}/page/cli"
    # lpv/ocv mirror the *runtime* lark-cli client version doing the auth, which
    # is the server-side Gateway binary — not the latest available skill-pack
    # version.
    runtime_version = _resolve_runtime_lark_cli_version()
    query = urllib.parse.urlencode(
        {
            "user_code": user_code,
            "lpv": runtime_version,
            "ocv": runtime_version,
            "from": "cli",
        }
    )
    return f"{base}?{query}"


def _poll_lark_app_registration(
    *,
    device_code: str,
    brand: str,
    interval: int,
    expires_in: int,
) -> dict[str, Any]:
    accounts_url = _lark_endpoints(brand)["accounts"] + _LARK_APP_REGISTRATION_PATH
    deadline = time.monotonic() + min(max(expires_in, 1), LARK_CONFIG_POLL_TIMEOUT_SECONDS)
    poll_interval = max(min(interval, 10), 1)
    last_error = "authorization_pending"
    while time.monotonic() < deadline:
        body = urllib.parse.urlencode({"action": "poll", "device_code": device_code}).encode("utf-8")
        data = _post_lark_form(accounts_url, body)
        if not data.get("error") and data.get("client_id"):
            return data
        error = str(data.get("error") or "")
        last_error = str(data.get("error_description") or error or "Lark app registration is still pending.")
        if error == "authorization_pending":
            time.sleep(poll_interval)
            continue
        if error == "slow_down":
            poll_interval = min(poll_interval + 5, 30)
            time.sleep(poll_interval)
            continue
        raise ValueError(last_error)
    raise TimeoutError(f"Lark app registration is still pending: {last_error}")


def _post_lark_form(url: str, body: bytes) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=LARK_HTTP_TIMEOUT_SECONDS) as response:
            raw = response.read().decode("utf-8")
    except Exception as exc:  # noqa: BLE001 - network boundary
        raise ValueError(f"Lark app registration request failed: {exc}") from exc
    parsed = _parse_json_object(raw)
    if parsed is None:
        raise ValueError("Lark app registration returned non-JSON response.")
    return parsed


def _tenant_brand(result: dict[str, Any]) -> str | None:
    user_info = result.get("user_info")
    if not isinstance(user_info, dict):
        return None
    brand = str(user_info.get("tenant_brand") or "").strip().lower()
    return brand if brand in {"feishu", "lark"} else None


def _save_lark_app_config_with_cli(user_id: str, *, app_id: str, app_secret: str, brand: str) -> None:
    path = _require_lark_cli_path()
    try:
        try:
            result = subprocess.run(
                [path, "config", "init", "--app-id", app_id, "--app-secret-stdin", "--brand", _normalize_lark_brand(brand)],
                input=app_secret + "\n",
                check=False,
                capture_output=True,
                text=True,
                timeout=15,
                env=lark_cli_env(user_id),
            )
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError("Timed out while saving Lark connection setup.") from exc
    finally:
        ensure_lark_cli_credential_tree(user_id)
    if result.returncode != 0:
        raw = (result.stderr or result.stdout or "").strip()
        parsed = _parse_json_object(raw)
        message = _auth_error_message(parsed) if parsed else raw
        raise ValueError(message or f"lark-cli config init exited with code {result.returncode}")


def _run_lark_cli_json(
    args: list[str],
    *,
    user_id: str,
    timeout: int,
    allow_empty_success: bool = False,
) -> dict[str, Any]:
    try:
        try:
            result = subprocess.run(
                args,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=lark_cli_env(user_id),
            )
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError("Timed out waiting for Lark/Feishu authorization. Complete authorization in the browser, then try again.") from exc
    finally:
        # OAuth commands may create new plaintext token files after the
        # pre-command environment guard has run. Re-harden every file even on
        # timeout or CLI failure before returning control to the Gateway.
        ensure_lark_cli_credential_tree(user_id)

    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    raw = stdout or stderr
    parsed = _parse_json_object(raw)

    if result.returncode != 0:
        message = _auth_error_message(parsed) if parsed else raw
        raise ValueError(message or f"lark-cli exited with code {result.returncode}")

    if not raw and allow_empty_success:
        return {}
    if parsed is None:
        if allow_empty_success:
            return {}
        raise ValueError(raw or "lark-cli did not return JSON output.")
    return parsed


def _parse_json_object(raw: str) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _auth_error_message(data: dict[str, Any] | None) -> str | None:
    if not data:
        return None
    error = data.get("error")
    if isinstance(error, dict):
        for key in ("message", "hint", "type"):
            value = error.get(key)
            if value:
                return str(value)
    for key in ("message", "msg", "hint"):
        value = data.get(key)
        if value:
            return str(value)
    return None


def _read_manifest(root: Path) -> dict[str, Any] | None:
    path = root / LARK_CLI_MANIFEST_FILE
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _installed_lark_skill_names(root: Path) -> set[str]:
    names: set[str] = set()
    if not root.is_dir():
        return names
    for skill_name in LARK_SKILL_NAMES:
        if (root / skill_name / SKILL_MD_FILE).is_file():
            names.add(skill_name)
    return names


def _enabled_lark_skill_names(user_id: str, config: AppConfig) -> set[str]:
    from deerflow.skills.storage import get_or_new_user_skill_storage

    try:
        storage = get_or_new_user_skill_storage(user_id, app_config=config)
        return {skill.name for skill in storage.load_skills(enabled_only=True) if skill.name in LARK_SKILL_NAME_SET}
    except Exception:
        return set()


def _resolve_latest_lark_cli_version() -> str:
    """Resolve the newest published ``larksuite/cli`` release tag.

    Queries the official ``releases/latest`` API. Any failure (rate limit,
    offline, air-gapped, malformed payload) falls back to
    ``FALLBACK_LARK_CLI_VERSION`` so an install can still proceed with a known
    good version rather than aborting.
    """
    try:
        request = urllib.request.Request(
            LARK_CLI_LATEST_RELEASE_API,
            headers={"Accept": "application/vnd.github+json", "User-Agent": "deer-flow"},
        )
        with urllib.request.urlopen(request, timeout=LARK_HTTP_TIMEOUT_SECONDS) as response:
            raw = response.read().decode("utf-8")
        data = json.loads(raw)
        tag = str(data.get("tag_name") or "").strip() if isinstance(data, dict) else ""
        version = _normalize_lark_cli_version_tag(tag)
        if version is not None:
            return version
    except Exception:  # noqa: BLE001 - version discovery is best-effort
        pass
    return FALLBACK_LARK_CLI_VERSION


def _cached_latest_lark_cli_version() -> str | None:
    """Best-effort latest version for status display, cached with a short TTL.

    Returns ``None`` on failure so the status endpoint never blocks the UI on a
    GitHub outage; the install path uses :func:`_resolve_latest_lark_cli_version`
    which has its own fallback.
    """
    now = time.monotonic()
    cached = getattr(_cached_latest_lark_cli_version, "_cache", None)
    if cached is not None and now - cached[0] < LARK_CLI_LATEST_VERSION_TTL_SECONDS:
        return cached[1]
    try:
        request = urllib.request.Request(
            LARK_CLI_LATEST_RELEASE_API,
            headers={"Accept": "application/vnd.github+json", "User-Agent": "deer-flow"},
        )
        with urllib.request.urlopen(request, timeout=LARK_HTTP_TIMEOUT_SECONDS) as response:
            data = json.loads(response.read().decode("utf-8"))
        tag = str(data.get("tag_name") or "").strip() if isinstance(data, dict) else ""
        version = _normalize_lark_cli_version_tag(tag)
    except Exception:  # noqa: BLE001 - status probe is best-effort
        version = None
    _cached_latest_lark_cli_version._cache = (now, version)  # type: ignore[attr-defined]
    return version


def _lark_archive_url(version: str) -> str:
    tag = _normalize_lark_cli_version_tag(version)
    if tag is None:
        raise ValueError(f"Invalid Lark CLI version tag: {version!r}")
    return f"https://codeload.github.com/{LARK_CLI_GITHUB_REPO}/zip/refs/tags/{tag}"


def _normalize_lark_cli_version_tag(value: str | None) -> str | None:
    tag = (value or "").strip()
    if not _VERSION_TAG_RE.fullmatch(tag):
        return None
    return tag if tag.startswith("v") else f"v{tag}"


def _download_lark_archive(version: str) -> Path:
    fd, archive_name = tempfile.mkstemp(prefix="lark-cli-skills-", suffix=".zip")
    os.close(fd)
    archive_path = Path(archive_name)
    url = _lark_archive_url(version)
    try:
        with urllib.request.urlopen(url, timeout=LARK_CLI_DOWNLOAD_TIMEOUT_SECONDS) as response:
            total = 0
            with archive_path.open("wb") as out:
                while chunk := response.read(1024 * 1024):
                    total += len(chunk)
                    if total > LARK_CLI_MAX_ARCHIVE_BYTES:
                        raise ValueError("Lark CLI source archive is too large.")
                    out.write(chunk)
    except ValueError:
        archive_path.unlink(missing_ok=True)
        raise
    except Exception as exc:  # noqa: BLE001 - network boundary
        archive_path.unlink(missing_ok=True)
        raise ValueError(f"Could not download the Lark skill pack ({version}) from GitHub. Check the Gateway's internet access, or pre-stage the archive via {LARK_CLI_SOURCE_ARCHIVE_ENV}.") from exc
    return archive_path


def _content_sha256(root: Path, skill_names: set[str]) -> str:
    """SHA-256 over effective installed skill contents (not archive bytes).

    The caller computes this after injecting DeerFlow's shared guidance, so the
    digest covers both official extracted files and the guidance users/agents
    actually read. It remains stable across GitHub re-packs of identical
    content. Paths and bytes are hashed in sorted order for determinism.
    """
    digest = hashlib.sha256()
    for skill_name in sorted(skill_names):
        skill_dir = root / skill_name
        if not skill_dir.is_dir():
            continue
        for file_path in sorted(p for p in skill_dir.rglob("*") if p.is_file()):
            rel = file_path.relative_to(root).as_posix()
            digest.update(rel.encode("utf-8"))
            digest.update(b"\0")
            digest.update(file_path.read_bytes())
            digest.update(b"\0")
    return digest.hexdigest()


def _infer_lark_archive_version(zf: zipfile.ZipFile) -> str | None:
    """Infer version from GitHub source archive roots such as ``cli-1.0.65/``.

    This keeps air-gapped / pre-staged archives from being mislabeled as the
    fallback version when the archive itself clearly identifies its release.
    """
    for info in zf.infolist():
        normalized = posixpath.normpath(info.filename.replace("\\", "/"))
        parts = PurePosixPath(normalized).parts
        if not parts:
            continue
        match = re.fullmatch(r"cli-(\d+\.\d+\.\d+)", parts[0])
        if match:
            return f"v{match.group(1)}"
    return None


def _install_lark_skills_from_archive(user_id: str, archive_path: Path, *, version: str | None = None) -> tuple[tuple[str, ...], str]:
    if not archive_path.is_file():
        raise FileNotFoundError(f"Lark CLI skills archive not found: {archive_path}")

    parent = get_paths().integration_skills_dir()
    parent.mkdir(parents=True, exist_ok=True)
    with _lark_install_lock(parent):
        return _install_lark_skills_from_archive_locked(archive_path, parent, version=version)


@contextmanager
def _lark_install_lock(parent: Path):
    """Serialize the cross-process atomic replacement of the global pack."""
    with _exclusive_install_lock(parent / ".lark-cli.install.lock", _LARK_INSTALL_THREAD_LOCK):
        yield


def _install_lark_skills_from_archive_locked(
    archive_path: Path,
    parent: Path,
    *,
    version: str | None = None,
) -> tuple[tuple[str, ...], str]:
    target = parent / INTEGRATION_ID
    staging_parent = Path(tempfile.mkdtemp(prefix=".installing-lark-cli-", dir=str(parent)))
    staging_target = staging_parent / INTEGRATION_ID
    staging_target.mkdir(parents=True, exist_ok=True)

    backup: Path | None = None
    try:
        with zipfile.ZipFile(archive_path, "r") as zf:
            archive_version = version or _infer_lark_archive_version(zf)
            extracted = _extract_lark_skills(zf, staging_target)
        _validate_extracted_lark_skills(staging_target, extracted)
        _append_deerflow_lark_shared_guidance(staging_target)
        content_sha = _content_sha256(staging_target, extracted)
        _write_manifest(staging_target, extracted, version=archive_version, content_sha256=content_sha)
        make_skill_tree_sandbox_readable(staging_target)

        if target.exists():
            backup = parent / f".replacing-{INTEGRATION_ID}-{os.getpid()}"
            if backup.exists():
                shutil.rmtree(backup)
            target.rename(backup)
        staging_target.rename(target)
        if backup is not None:
            # Best-effort: the new skills are already live after the rename, so a
            # transient error deleting the old backup must not flip a successful
            # install into a failure (the except-branch restore guard would also
            # not fire because ``target`` now exists with the new content).
            shutil.rmtree(backup, ignore_errors=True)
        return tuple(sorted(extracted)), content_sha
    except Exception:
        if backup is not None and backup.exists() and not target.exists():
            backup.rename(target)
        raise
    finally:
        shutil.rmtree(staging_parent, ignore_errors=True)


def _extract_lark_skills(zf: zipfile.ZipFile, destination: Path) -> set[str]:
    extracted: set[str] = set()
    total_written = 0
    dest_root = destination.resolve()

    for info in zf.infolist():
        if info.is_dir():
            continue
        if is_unsafe_zip_member(info) or is_symlink_member(info):
            raise ValueError(f"Unsafe Lark CLI archive member: {info.filename!r}")

        skill_name, relative = _resolve_lark_skill_member(info.filename)
        if skill_name is None or relative is None:
            continue

        target = dest_root / skill_name / relative
        if not target.resolve().is_relative_to(dest_root):
            raise ValueError(f"Archive member escapes destination: {info.filename!r}")
        target.parent.mkdir(parents=True, exist_ok=True)

        with zf.open(info) as src, target.open("wb") as out:
            first_chunk = True
            while chunk := src.read(65536):
                if first_chunk and is_executable_binary_prefix(chunk):
                    raise ValueError(f"Archive contains executable binary member: {info.filename!r}")
                first_chunk = False
                total_written += len(chunk)
                if total_written > LARK_CLI_MAX_EXTRACTED_BYTES:
                    raise ValueError("Lark CLI skills archive expands to too much data.")
                out.write(chunk)
        extracted.add(skill_name)

    return extracted


def _resolve_lark_skill_member(raw_name: str) -> tuple[str | None, Path | None]:
    normalized = posixpath.normpath(raw_name.replace("\\", "/"))
    if normalized in {"", "."} or normalized.startswith("../"):
        return None, None
    parts = PurePosixPath(normalized).parts

    if "skills" in parts:
        idx = parts.index("skills")
        if len(parts) <= idx + 2:
            return None, None
        skill_name = parts[idx + 1]
        rel_parts = parts[idx + 2 :]
    elif parts and parts[0] in LARK_SKILL_NAME_SET:
        skill_name = parts[0]
        rel_parts = parts[1:]
    else:
        return None, None

    if skill_name not in LARK_SKILL_NAME_SET or not rel_parts:
        return None, None
    if any(part in {"", ".", ".."} for part in rel_parts):
        raise ValueError(f"Unsafe Lark skill archive member: {raw_name!r}")
    return skill_name, Path(*rel_parts)


def _validate_extracted_lark_skills(root: Path, extracted: set[str]) -> None:
    missing = sorted(set(LARK_SKILL_NAMES) - extracted)
    if missing:
        raise ValueError(f"Lark CLI archive is missing required skills: {', '.join(missing)}")

    for skill_name in LARK_SKILL_NAMES:
        skill_file = root / skill_name / SKILL_MD_FILE
        parsed = parse_skill_file(skill_file, SkillCategory.INTEGRATION, relative_path=Path(INTEGRATION_ID) / skill_name)
        if parsed is None:
            raise ValueError(f"Invalid Lark skill metadata: {skill_name}/{SKILL_MD_FILE}")
        if parsed.name != skill_name:
            raise ValueError(f"Lark skill directory {skill_name!r} declares name {parsed.name!r}")


def _append_deerflow_lark_shared_guidance(root: Path) -> None:
    skill_file = root / "lark-shared" / SKILL_MD_FILE
    content = skill_file.read_text(encoding="utf-8")
    if _DEERFLOW_LARK_SHARED_GUIDANCE_MARKER in content:
        return
    for legacy_marker in _DEERFLOW_LARK_SHARED_GUIDANCE_LEGACY_MARKERS:
        if legacy_marker in content:
            content = content.split(legacy_marker, maxsplit=1)[0].rstrip()
            break
    guidance = f"""

{_DEERFLOW_LARK_SHARED_GUIDANCE_MARKER}

## DeerFlow 授权入口

在 DeerFlow 中，如果 `lark-cli auth status` 或业务命令提示未配置、未登录、token 过期或缺少用户授权：

1. 不要要求用户在终端执行 `lark-cli config init`、`lark-cli auth login` 或 `lark-cli auth login --device-code`。
2. 回复用户这个可点击链接：[打开飞书授权设置](?settings=integrations)。
3. 告诉用户在 **Settings → Integrations → Lark / Feishu CLI** 点击“连接飞书”，在浏览器里完成授权后再回来继续当前任务。
4. 如果错误中包含缺失的 `scope`、`permission_violations` 或建议的 `--domain`，告诉用户在该设置页选择对应权限域（例如日历选择 Calendar），或把具体 scope 填入“Exact OAuth scope / 具体 OAuth scope”后重新授权。

只有在用户明确说明已经完成授权后，才继续调用具体的 `lark-cli` 业务命令。
"""
    skill_file.write_text(content.rstrip() + guidance + "\n", encoding="utf-8")


def _write_manifest(root: Path, installed_skills: set[str], *, version: str | None, content_sha256: str) -> None:
    resolved_version = version or FALLBACK_LARK_CLI_VERSION
    manifest = {
        "provider": INTEGRATION_ID,
        "version": resolved_version,
        "source": _lark_archive_url(resolved_version),
        "content_sha256": content_sha256,
        "installed_at": datetime.now(UTC).isoformat(),
        "skills": sorted(installed_skills),
    }
    (root / LARK_CLI_MANIFEST_FILE).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
