"""Operator-facing installation management for packaged DeerFlow extensions."""

from __future__ import annotations

import ipaddress
import json
import logging
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
import urllib.parse
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from packaging.requirements import InvalidRequirement, Requirement

logger = logging.getLogger(__name__)

_ENTRY_POINT_GROUP = "deerflow.extensions"
_LOCK_RETRY_INTERVAL_SECONDS = 0.2
_SNAPSHOT_IGNORES = (".git", ".venv", "venv", "__pycache__", "*.pyc")
_DISTRIBUTION_NAME = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$")
_SENSITIVE_FILENAMES = {".npmrc", ".pypirc", "credentials.json"}
_SENSITIVE_SUFFIXES = {".key", ".pem", ".p12", ".pfx"}
_SECRET_QUERY_KEY = re.compile(
    r"(?:^|[-_])(?:api[-_]?key|access[-_]?key|auth(?:orization)?|code|credential|key|pass(?:wd|word)?|pw|sas|secret|signature|sig|token)(?:$|[-_])",
    re.IGNORECASE,
)
# The camel-case splitter only fires on case transitions, so `accessToken` is
# separated into words while `accesstoken` and `ACCESSTOKEN` are not. These
# spellings are distinctive enough to match without a word boundary; short
# generic words stay boundary-anchored above so `keyword` is still installable.
_SECRET_QUERY_SUBSTRING = re.compile(
    r"access[-_]?token|api[-_]?key|auth[-_]?token|session[-_]?token|credential|password|passwd|signature|secret",
    re.IGNORECASE,
)
# Git's SCP-like shorthand (`git@host:org/repo.git`) is a remote source that
# carries no URL scheme, so it reaches validation looking like a bare path.
_SCP_LIKE_REFERENCE = re.compile(r"^[^\s/:@]+@[^\s/:@]+:(?!/)")
_PEP508_NAME_PREFIX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\s*@\s*")
_UV_ENV_OVERRIDES = {
    "UV_ACTIVE",
    "UV_ALL_GROUPS",
    "UV_CONFIG_FILE",
    "UV_CONSTRAINT",
    "UV_DEFAULT_GROUPS",
    "UV_DEV",
    "UV_FROZEN",
    "UV_INSECURE_HOST",
    "UV_LOCKED",
    "UV_NO_BUILD_ISOLATION",
    "UV_NO_CONFIG",
    "UV_NO_DEFAULT_GROUPS",
    "UV_NO_DEV",
    "UV_NO_GROUP",
    "UV_NO_SOURCES",
    "UV_NO_SYNC",
    "UV_ONLY_DEV",
    "UV_ONLY_GROUP",
    "UV_PACKAGE",
    "UV_PROJECT",
    "UV_PROJECT_ENVIRONMENT",
    "UV_PYTHON",
    "UV_SCRIPT",
    "UV_WORKING_DIR",
}


@dataclass(frozen=True)
class InstalledExtension:
    """One extension made importable and active by :class:`ExtensionManager`."""

    name: str
    distribution: str
    use: str


@dataclass(frozen=True)
class ConfiguredExtension:
    """Operator-visible activation state for one configured extension."""

    name: str
    distribution: str
    use: str
    enabled: bool
    required: bool


@dataclass(frozen=True)
class _FileSnapshot:
    path: Path
    content: bytes | None

    @classmethod
    def capture(cls, path: Path) -> _FileSnapshot:
        return cls(path, path.read_bytes() if path.exists() else None)

    def restore(self) -> None:
        if self.content is None:
            self.path.unlink(missing_ok=True)
        else:
            self.path.write_bytes(self.content)


def _read_optional_bytes(path: Path) -> bytes | None:
    return path.read_bytes() if path.is_file() else None


class ExtensionManager:
    """Install trusted Python extensions into one DeerFlow checkout."""

    def __init__(self, project_root: str | Path, *, config_path: str | Path | None = None) -> None:
        self.project_root = Path(project_root).resolve()
        self.backend_dir = self.project_root / "backend"
        self.pyproject_path = self.backend_dir / "pyproject.toml"
        if config_path is not None:
            selected_config = Path(config_path).expanduser()
        else:
            root_config = self.project_root / "config.yaml"
            legacy_config = self.backend_dir / "config.yaml"
            selected_config = root_config if root_config.is_file() or not legacy_config.is_file() else legacy_config
        self.config_path = selected_config.resolve()

    def install(self, source: str, *, yes: bool = False, required: bool = False) -> InstalledExtension:
        """Install an extension source and enable its packaging entry point."""
        with _manager_lock(self.project_root):
            return self._install(source, yes=yes, required=required)

    def _install(self, source: str, *, yes: bool, required: bool) -> InstalledExtension:
        if not yes:
            raise PermissionError("installing an extension executes trusted third-party code; pass yes=True to continue")

        source_argument = Path(source).expanduser()
        if _is_link_like(source_argument):
            raise ValueError("local extension snapshots cannot contain symbolic links or junctions")
        source_path = source_argument.resolve()
        managed_source: Path | None = None
        metadata: tuple[str, str, str] | None = None
        uv_source = source
        if source_path.is_dir():
            _validate_local_snapshot(source_path)
            metadata = _read_local_extension_metadata(source_path)
            distribution = metadata[0]
            normalized_distribution = _normalize_distribution(distribution)
            managed_root = (self.backend_dir / "extensions" / "sources").resolve()
            managed_source = (managed_root / normalized_distribution).resolve()
            if not managed_source.is_relative_to(managed_root):
                raise ValueError(f"invalid extension distribution name: {distribution!r}")
            if managed_source.exists():
                raise FileExistsError(f"extension source is already installed: {managed_source}")
            uv_source = str(managed_source.relative_to(self.backend_dir))
        else:
            if source_argument.exists():
                raise ValueError("local extension sources must be directories so they can be snapshotted for deployment")
            _validate_remote_source(source)
        # uv add/sync execute the package's build backend. A config this manager
        # could never write to must fail before that code runs, not afterwards
        # through rollback.
        self._read_plugins()
        _require_supported_uv(self.backend_dir)

        dependencies_before = _extension_dependency_names(self.pyproject_path)
        dependency_snapshots = (
            _FileSnapshot.capture(self.pyproject_path),
            _FileSnapshot.capture(self.backend_dir / "uv.lock"),
        )
        managed_dependency_contents: tuple[bytes | None, ...] | None = None
        uv_attempted = False
        try:
            if managed_source is not None:
                managed_source.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(
                    source_path,
                    managed_source,
                    ignore=shutil.ignore_patterns(*_SNAPSHOT_IGNORES),
                )
            uv_attempted = True
            try:
                _run_uv(
                    [
                        "uv",
                        "add",
                        "--project",
                        str(self.backend_dir),
                        "--group",
                        "extensions",
                        "--no-workspace",
                        "--no-sync",
                        "--",
                        uv_source,
                    ],
                    self.backend_dir,
                )
            except BaseException:
                # The manager owns dependency-file mutation while uv is
                # running. Treat even a failed command's partial writes as
                # manager output so the outer transaction can restore them.
                managed_dependency_contents = tuple(_read_optional_bytes(snapshot.path) for snapshot in dependency_snapshots)
                raise
            managed_dependency_contents = tuple(_read_optional_bytes(snapshot.path) for snapshot in dependency_snapshots)
            _validate_locked_local_sources(self.backend_dir / "uv.lock", self.backend_dir)
            _sync_environment(self.project_root, self.backend_dir, self.config_path)
            if metadata is None:
                added = _extension_dependency_names(self.pyproject_path) - dependencies_before
                if len(added) != 1:
                    raise RuntimeError("could not identify the distribution added by uv")
                distribution = next(iter(added))
                name, use = _discover_installed_entry_point(self.backend_dir, distribution)
                metadata = (distribution, name, use)
            else:
                installed_entry_point = _discover_installed_entry_point(self.backend_dir, metadata[0])
                if installed_entry_point != metadata[1:]:
                    raise ValueError("installed extension entry point does not match its source metadata")
            distribution, name, use = metadata
            self._enable_plugin(
                {
                    "name": name,
                    "package": distribution,
                    "use": use,
                    "enabled": True,
                    "required": required,
                    "config": {},
                }
            )
        except BaseException as operation_error:
            # _enable_plugin performs the only config mutation as the final,
            # atomic step. A failure before it must not roll back an operator
            # edit made while dependency resolution was running.
            expected_contents = managed_dependency_contents or tuple(snapshot.content for snapshot in dependency_snapshots)
            dependency_recovery_conflict = any(
                _read_optional_bytes(snapshot.path) != expected
                for snapshot, expected in zip(
                    dependency_snapshots,
                    expected_contents,
                    strict=True,
                )
            )
            if dependency_recovery_conflict:
                raise RuntimeError("extension installation recovery preserved a concurrent dependency-file edit") from operation_error
            for snapshot in dependency_snapshots:
                snapshot.restore()
            if managed_source is not None:
                shutil.rmtree(managed_source, ignore_errors=True)
            # The recovery sync itself may rewrite the dependency files, so the
            # second restore has to run even when that sync fails.
            try:
                # An interrupt is not answered by a full dependency resolve: the
                # declarations are already restored, and the next locked startup
                # sync reconciles the environment.
                if uv_attempted and isinstance(operation_error, Exception):
                    _sync_restored_environment(self.project_root, self.backend_dir, self.config_path)
            except RuntimeError as sync_error:
                raise RuntimeError(f"{sync_error}; original failure: {operation_error}") from operation_error
            finally:
                for snapshot in dependency_snapshots:
                    snapshot.restore()
            raise

        return InstalledExtension(name=name, distribution=distribution, use=use)

    def set_enabled(self, identifier: str, *, enabled: bool) -> str:
        """Enable or disable one configured extension without losing its config."""
        with _manager_lock(self.project_root):
            return self._set_enabled(identifier, enabled=enabled)

    def _set_enabled(self, identifier: str, *, enabled: bool) -> str:
        original, plugins = self._read_plugins()
        plugin = _find_plugin(plugins, identifier)
        plugin["enabled"] = enabled
        _write_plugins_block(self.config_path, original, plugins)
        return str(plugin.get("name") or plugin.get("use") or identifier)

    def remove(self, identifier: str) -> str:
        """Uninstall one managed distribution and remove its activation entry."""
        with _manager_lock(self.project_root):
            return self._remove(identifier)

    def _remove(self, identifier: str) -> str:
        original, plugins = self._read_plugins()
        plugin = _find_plugin(plugins, identifier)
        distribution = plugin.get("package")
        if not isinstance(distribution, str) or not distribution:
            raise ValueError(f"configured extension {identifier!r} has no managed package metadata")
        plugins.remove(plugin)
        if any(isinstance(candidate, dict) and _same_distribution(candidate.get("package"), distribution) for candidate in plugins):
            _write_plugins_block(self.config_path, original, plugins)
            return str(plugin.get("name") or plugin.get("use") or identifier)
        managed_source = self.backend_dir / "extensions" / "sources" / _normalize_distribution(distribution)
        dependency_snapshots = (
            _FileSnapshot.capture(self.pyproject_path),
            _FileSnapshot.capture(self.backend_dir / "uv.lock"),
        )
        config_snapshot = _FileSnapshot.capture(self.config_path)
        staging_root: Path | None = None
        staged_source: Path | None = None
        managed_dependency_contents: tuple[bytes | None, ...] | None = None
        managed_config_content: bytes | None = None
        uv_attempted = False
        try:
            # Deactivate first so an abrupt process exit cannot leave a required
            # plugin configured after its distribution declaration is gone.
            _write_plugins_block(self.config_path, original, plugins)
            managed_config_content = self.config_path.read_bytes()
            uv_attempted = True
            try:
                _run_uv(
                    [
                        "uv",
                        "remove",
                        "--project",
                        str(self.backend_dir),
                        "--group",
                        "extensions",
                        "--no-sync",
                        "--",
                        distribution,
                    ],
                    self.backend_dir,
                )
            except BaseException:
                # A failed uv mutation may still have rewritten either
                # dependency file. Those writes belong to this locked
                # transaction and must be rolled back with the config entry.
                managed_dependency_contents = tuple(_read_optional_bytes(snapshot.path) for snapshot in dependency_snapshots)
                raise
            managed_dependency_contents = tuple(_read_optional_bytes(snapshot.path) for snapshot in dependency_snapshots)
            _validate_locked_local_sources(self.backend_dir / "uv.lock", self.backend_dir)
            if managed_source.is_dir():
                staging_root = Path(
                    tempfile.mkdtemp(
                        prefix=f".{managed_source.name}.remove-",
                        dir=managed_source.parent,
                    )
                )
                staged_source = staging_root / "source"
                managed_source.rename(staged_source)
            _sync_environment(self.project_root, self.backend_dir, self.config_path)
        except BaseException as operation_error:
            expected_contents = managed_dependency_contents or tuple(snapshot.content for snapshot in dependency_snapshots)
            dependency_recovery_conflict = any(
                _read_optional_bytes(snapshot.path) != expected
                for snapshot, expected in zip(
                    dependency_snapshots,
                    expected_contents,
                    strict=True,
                )
            )
            current_config_content = self.config_path.read_bytes() if self.config_path.is_file() else None
            config_recovery_conflict = managed_config_content is not None and current_config_content != managed_config_content
            if staged_source is not None and staged_source.exists() and not managed_source.exists():
                staged_source.rename(managed_source)
            if staging_root is not None:
                shutil.rmtree(staging_root, ignore_errors=True)
            if dependency_recovery_conflict:
                raise RuntimeError("extension removal recovery preserved a concurrent dependency-file edit") from operation_error
            for snapshot in dependency_snapshots:
                snapshot.restore()
            if managed_config_content is not None and not config_recovery_conflict:
                config_snapshot.restore()
            # The recovery sync itself may rewrite the dependency files, so the
            # second restore has to run even when that sync fails.
            try:
                # An interrupt is not answered by a full dependency resolve: the
                # declarations are already restored, and the next locked startup
                # sync reconciles the environment.
                if uv_attempted and isinstance(operation_error, Exception):
                    _sync_restored_environment(self.project_root, self.backend_dir, self.config_path)
            except RuntimeError as sync_error:
                raise RuntimeError(f"{sync_error}; original failure: {operation_error}") from operation_error
            finally:
                for snapshot in dependency_snapshots:
                    snapshot.restore()
            if config_recovery_conflict:
                raise RuntimeError("extension removal recovery preserved a concurrent config edit") from operation_error
            raise
        if staging_root is not None:
            shutil.rmtree(staging_root, ignore_errors=True)
        return str(plugin.get("name") or plugin.get("use") or identifier)

    def list_configured(self) -> tuple[ConfiguredExtension, ...]:
        """Return configured extensions in their deterministic load order."""
        from deerflow.extensions.loader import ExtensionSpec

        _, plugins = self._read_plugins()
        configured: list[ConfiguredExtension] = []
        for plugin in plugins:
            spec = ExtensionSpec.model_validate(plugin)
            configured.append(
                ConfiguredExtension(
                    name=spec.name or spec.use,
                    distribution=spec.package or "-",
                    use=spec.use,
                    enabled=spec.enabled,
                    required=spec.required,
                )
            )
        return tuple(configured)

    def _enable_plugin(self, plugin: dict[str, Any]) -> None:
        original, plugins = self._read_plugins()
        exact_use_matches = [item for item in plugins if isinstance(item, dict) and item.get("use") == plugin["use"]]
        identity_conflicts = [item for item in plugins if isinstance(item, dict) and item not in exact_use_matches and (item.get("name") == plugin["name"] or _same_distribution(item.get("package"), plugin["package"]))]
        if len(exact_use_matches) > 1 or identity_conflicts:
            raise ValueError(f"multiple configured plugins conflict with extension {plugin['name']!r}")
        if exact_use_matches:
            existing = exact_use_matches[0]
            existing_package = existing.get("package")
            if existing.get("name") not in (None, plugin["name"]) or (existing_package is not None and not _same_distribution(existing_package, plugin["package"])):
                raise ValueError(f"configured plugin conflicts with extension {plugin['name']!r}")
            existing["name"] = plugin["name"]
            existing["package"] = plugin["package"]
            existing["use"] = plugin["use"]
            existing["enabled"] = True
            existing.setdefault("required", plugin["required"])
            existing.setdefault("config", {})
            _write_plugins_block(self.config_path, original, plugins)
            return
        plugins.append(plugin)
        _write_plugins_block(self.config_path, original, plugins)

    def _read_plugins(self) -> tuple[str, list[Any]]:
        if not self.config_path.is_file():
            raise FileNotFoundError(f"DeerFlow config not found: {self.config_path}")
        with self.config_path.open("r", encoding="utf-8", newline="") as stream:
            original = stream.read()
        try:
            config_node = yaml.compose(original)
            config = yaml.safe_load(original) or {}
        except yaml.YAMLError as exc:
            raise ValueError("invalid DeerFlow config YAML") from exc
        if isinstance(config_node, yaml.MappingNode):
            plugins_keys = [key for key, _ in config_node.value if isinstance(key, yaml.ScalarNode) and key.value == "plugins"]
            if len(plugins_keys) > 1:
                raise ValueError("config.yaml contains duplicate top-level plugins keys")
        if not isinstance(config, dict):
            raise ValueError("DeerFlow config root must be a mapping")
        plugins = config.get("plugins")
        if plugins is None:
            plugins = []
        if not isinstance(plugins, list):
            raise ValueError("config.yaml plugins must be a list")
        return original, plugins


def _normalize_distribution(name: str) -> str:
    if not _DISTRIBUTION_NAME.fullmatch(name):
        raise ValueError(f"invalid extension distribution name: {name!r}")
    return re.sub(r"[-_.]+", "-", name).lower()


def _retry_until_locked(acquire: Callable[[], None], *, sleep: Callable[[float], None] = time.sleep) -> None:
    """Retry a non-blocking lock acquisition until the region is free.

    Windows' blocking mode (``msvcrt.LK_LOCK``) gives up after roughly ten
    seconds. A real install holds this lock across ``uv add`` plus a full
    ``uv sync``, so blocking mode reports contention as ``Permission denied``
    instead of serializing the two operations.
    """
    while True:
        try:
            acquire()
            return
        except OSError:
            sleep(_LOCK_RETRY_INTERVAL_SECONDS)


@contextmanager
def _manager_lock(project_root: Path) -> Iterator[None]:
    """Serialize extension mutations across processes for one checkout."""
    lock_directory = project_root / ".deer-flow"
    lock_directory.mkdir(parents=True, exist_ok=True)
    lock_path = lock_directory / "extension-manager.lock"
    with lock_path.open("a+b") as stream:
        if os.name == "nt":
            import msvcrt

            if stream.seek(0, os.SEEK_END) == 0:
                stream.write(b"\0")
                stream.flush()

            def _acquire_region() -> None:
                # msvcrt locks a byte range from the current file position.
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)

            _retry_until_locked(_acquire_region)
            try:
                yield
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _same_distribution(left: object, right: object) -> bool:
    if not isinstance(left, str) or not isinstance(right, str):
        return False
    try:
        return _normalize_distribution(left) == _normalize_distribution(right)
    except ValueError:
        return False


def _read_local_extension_metadata(source: Path) -> tuple[str, str, str]:
    pyproject = source / "pyproject.toml"
    if not pyproject.is_file():
        raise ValueError(f"extension has no pyproject.toml: {source}")
    with pyproject.open("rb") as stream:
        document = tomllib.load(stream)
    project = document.get("project")
    if not isinstance(project, dict) or not isinstance(project.get("name"), str):
        raise ValueError("extension pyproject.toml must declare project.name")
    entry_point_groups = project.get("entry-points", {})
    if not isinstance(entry_point_groups, dict):
        raise ValueError(f"extension must declare exactly one {_ENTRY_POINT_GROUP!r} entry point")
    entry_points = entry_point_groups.get(_ENTRY_POINT_GROUP, {})
    if not isinstance(entry_points, dict) or len(entry_points) != 1:
        raise ValueError(f"extension must declare exactly one {_ENTRY_POINT_GROUP!r} entry point")
    name, use = next(iter(entry_points.items()))
    if not isinstance(name, str) or not isinstance(use, str):
        raise ValueError(f"invalid {_ENTRY_POINT_GROUP!r} entry point metadata")
    _validate_entry_point(name, use)
    return project["name"], name, use


def _validate_entry_point(name: str, use: str) -> None:
    if not name or name != name.strip() or any(character in name for character in "\r\n\t"):
        raise ValueError(f"invalid {_ENTRY_POINT_GROUP!r} entry point name")
    try:
        module, attribute = use.rsplit(":", 1)
    except ValueError as exc:
        raise ValueError(f"invalid {_ENTRY_POINT_GROUP!r} entry point target") from exc
    if not attribute.isidentifier() or not module or any(not part.isidentifier() for part in module.split(".")):
        raise ValueError(f"invalid {_ENTRY_POINT_GROUP!r} entry point target")


def _validate_local_snapshot(source: Path) -> None:
    ignored_names = {".git", ".venv", "venv", "__pycache__"}
    for directory, dirnames, filenames in os.walk(source, followlinks=False):
        directory_path = Path(directory)
        retained_dirs: list[str] = []
        for name in dirnames:
            if name in ignored_names:
                continue
            candidate = directory_path / name
            if _is_link_like(candidate):
                raise ValueError("local extension snapshots cannot contain symbolic links or junctions")
            retained_dirs.append(name)
        dirnames[:] = retained_dirs
        for name in filenames:
            candidate = directory_path / name
            if name == ".env" or name.startswith(".env.") or name in _SENSITIVE_FILENAMES or Path(name).suffix.lower() in _SENSITIVE_SUFFIXES:
                raise ValueError(f"local extension snapshot contains a likely sensitive file: {name}")
            if name.endswith(".pyc"):
                continue
            if _is_link_like(candidate):
                raise ValueError("local extension snapshots cannot contain symbolic links or junctions")
            if not candidate.is_file():
                raise ValueError("local extension snapshots may contain only directories and regular files")


def _is_link_like(path: Path) -> bool:
    return path.is_symlink() or path.is_junction()


def _validate_remote_source(source: str) -> None:
    raw_source = source.strip()
    try:
        requirement = Requirement(raw_source)
    except InvalidRequirement:
        requirement = None
    if requirement is not None and requirement.url is None:
        return

    candidate = _strip_git_prefix(requirement.url if requirement is not None else raw_source)
    parsed = urllib.parse.urlsplit(candidate)
    scheme = parsed.scheme.lower()
    for query in (parsed.query, parsed.fragment):
        if any(_is_secret_query_key(key) for key, _ in urllib.parse.parse_qsl(query, keep_blank_values=True)):
            raise ValueError("extension source URLs cannot contain credential-like query parameters")
    if _is_scp_like_reference(raw_source):
        raise ValueError("Git SSH shorthand is not deployable; remote Git sources must use public HTTPS, as in git+https://host/org/repo.git")
    if not scheme:
        raise ValueError("local path references are not deployable; pass a local directory so DeerFlow can snapshot it")
    if scheme == "file":
        raise ValueError("file URLs are not deployable; pass a local directory so DeerFlow can snapshot it")
    if scheme == "ssh":
        raise ValueError("remote Git sources must use public HTTPS; SSH sources are not deployable by the stock Docker builder")
    if scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("remote extension sources must use HTTPS")
    if scheme not in {"http", "https"}:
        raise ValueError("remote extension sources must use HTTPS")
    if parsed.password is not None or (parsed.username is not None and scheme != "ssh"):
        raise ValueError("extension source URLs cannot contain embedded credentials")


def _strip_git_prefix(reference: str) -> str:
    return reference[4:] if reference.lower().startswith("git+") else reference


def _is_scp_like_reference(source: str) -> bool:
    # The bare shorthand is checked directly; a PEP 508 direct reference keeps
    # it behind the requirement name, which packaging strips off the URL.
    candidates = [source]
    named = _PEP508_NAME_PREFIX.sub("", source, count=1)
    if named != source:
        candidates.append(named)
    return any(_SCP_LIKE_REFERENCE.match(_strip_git_prefix(candidate)) for candidate in candidates)


def _is_secret_query_key(key: str) -> bool:
    normalized = _normalize_query_key(key)
    return bool(_SECRET_QUERY_KEY.search(normalized) or _SECRET_QUERY_SUBSTRING.search(normalized))


def _normalize_query_key(key: str) -> str:
    camel_case_split = re.sub(
        r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])",
        "-",
        key,
    )
    return re.sub(r"[^A-Za-z0-9]+", "-", camel_case_split).strip("-").lower()


def _extension_dependency_names(pyproject: Path) -> set[str]:
    with pyproject.open("rb") as stream:
        document = tomllib.load(stream)
    dependencies = document.get("dependency-groups", {}).get("extensions", [])
    names: set[str] = set()
    for dependency in dependencies:
        if not isinstance(dependency, str):
            continue
        match = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", dependency)
        if match:
            names.add(_normalize_distribution(match.group(1)))
    return names


_LOCK_LOCAL_PATH_KEYS = frozenset({"path", "directory", "editable", "virtual"})
_LOCK_LOCAL_URL_KEYS = frozenset({"registry", "url", "git"})
_LOCK_LOCAL_SOURCE_VIOLATION = "uv.lock contains a local dependency source outside the backend Docker build context"
_LOCK_LOOPBACK_SOURCE_WARNING = "uv.lock records a loopback dependency source the backend Docker build cannot reach"
_WINDOWS_ABSOLUTE_PATH = re.compile(r"^[A-Za-z]:[\\/]")


def _validate_locked_local_sources(lock_path: Path, backend_dir: Path) -> None:
    """Reject lock entries that the stock backend Docker build cannot reproduce.

    The image build copies ``backend/`` and runs ``uv sync --locked`` inside
    it, so every local reference in the lock must be a relative path that
    resolves to the project itself, an exact workspace member, or a managed
    snapshot under ``extensions/sources/``. Absolute paths, ``file:`` URLs,
    and other local locations (for example a ``UV_FIND_LINKS`` wheelhouse
    pulled in by environment configuration) install on this host but fail
    the image build, so the caller rolls back the whole transaction when one
    appears.
    """
    with lock_path.open("rb") as stream:
        document = tomllib.load(stream)
    backend_root = backend_dir.resolve()
    workspace_members = _workspace_member_dirs(backend_root)
    managed_snapshots_root = backend_root / "extensions" / "sources"

    def is_reproducible_by_backend_builder(path: Path) -> bool:
        if path == backend_root or path in workspace_members:
            return True
        return path.is_relative_to(managed_snapshots_root)

    def visit(value: object) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if isinstance(child, str):
                    local_path: Path | None = None
                    if key in _LOCK_LOCAL_PATH_KEYS:
                        local_path = _resolve_locked_local_path(child, backend_root, path_only=True)
                    elif key in _LOCK_LOCAL_URL_KEYS:
                        local_path = _resolve_locked_local_path(child, backend_root, path_only=False)
                        if local_path is None and _is_loopback_reference(child):
                            # An explicit loopback source is an operator choice,
                            # unlike an environment-driven wheelhouse resolution,
                            # so it is reported rather than rolled back.
                            logger.warning("%s: %s", _LOCK_LOOPBACK_SOURCE_WARNING, child)
                    if local_path is not None and not is_reproducible_by_backend_builder(local_path):
                        raise ValueError(_LOCK_LOCAL_SOURCE_VIOLATION)
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(document)


def _is_loopback_reference(value: str) -> bool:
    """Report whether a lock URL points back at the installing host.

    Only loopback is rejected. A private-network index (an internal mirror at
    ``10.0.0.5``) is reachable from a builder on that network, but ``127.0.0.1``
    resolves to the builder itself, so the recorded source silently means
    something different — or nothing — during ``make up``.
    """
    candidate = value[4:] if value.lower().startswith("git+") else value
    parsed = urllib.parse.urlsplit(candidate)
    if not parsed.scheme:
        return False
    try:
        host = parsed.hostname
    except ValueError:
        return False
    if host is None:
        return False
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _workspace_member_dirs(backend_root: Path) -> frozenset[Path]:
    """Return the resolved directories of the backend uv workspace members."""
    pyproject_path = backend_root / "pyproject.toml"
    if not pyproject_path.is_file():
        return frozenset()
    with pyproject_path.open("rb") as stream:
        document = tomllib.load(stream)
    tool = document.get("tool")
    uv_config = tool.get("uv") if isinstance(tool, dict) else None
    workspace = uv_config.get("workspace") if isinstance(uv_config, dict) else None
    members = workspace.get("members") if isinstance(workspace, dict) else None
    if not isinstance(members, list):
        return frozenset()
    resolved: set[Path] = set()
    for member in members:
        if not isinstance(member, str) or Path(member).is_absolute():
            continue
        for candidate in backend_root.glob(member):
            if candidate.is_dir():
                resolved.add(candidate.resolve())
    return frozenset(resolved)


def _resolve_locked_local_path(value: str, backend_root: Path, *, path_only: bool) -> Path | None:
    """Resolve one lock reference to its in-project path, or None for remote URLs.

    Raises :class:`ValueError` for absolute local references: the stock
    backend image build copies ``backend/`` and cannot reproduce host-absolute
    paths, even ones that point inside this checkout.
    """
    if _WINDOWS_ABSOLUTE_PATH.match(value):
        raise ValueError(_LOCK_LOCAL_SOURCE_VIOLATION)
    parsed = urllib.parse.urlsplit(value)
    scheme = parsed.scheme.lower()
    if scheme == "file":
        raise ValueError(_LOCK_LOCAL_SOURCE_VIOLATION)
    if not path_only and scheme:
        return None
    path = Path(value).expanduser()
    if path.is_absolute():
        raise ValueError(_LOCK_LOCAL_SOURCE_VIOLATION)
    return (backend_root / path).resolve()


def _first_json_array(stdout: str | None) -> Any:
    """Return the first JSON array printed by the probe interpreter.

    The child may emit unrelated startup output first — a `sitecustomize` or
    `.pth` banner, a vendored import notice — so the payload is located rather
    than assumed to occupy the first line.
    """
    for line in (stdout or "").splitlines():
        candidate = line.strip()
        if not candidate.startswith("["):
            continue
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return []


def _discover_installed_entry_point(backend_dir: Path, distribution: str) -> tuple[str, str]:
    python = backend_dir / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    script = f"""\
import json
import sys
from importlib.metadata import distribution

entry_points = [
    entry_point
    for entry_point in distribution(sys.argv[1]).entry_points
    if entry_point.group == {_ENTRY_POINT_GROUP!r}
]
print(json.dumps([[entry_point.name, entry_point.value] for entry_point in entry_points]), flush=True)
if len(entry_points) == 1 and not callable(entry_points[0].load()):
    raise TypeError("extension entry point is not callable")
"""
    completed = subprocess.run(
        [str(python), "-c", script, distribution],
        cwd=backend_dir,
        check=False,
        capture_output=True,
        text=True,
    )
    entry_points = _first_json_array(completed.stdout)
    if not isinstance(entry_points, list) or len(entry_points) != 1:
        raise ValueError(f"distribution {distribution!r} must expose exactly one {_ENTRY_POINT_GROUP!r} entry point")
    name, use = entry_points[0]
    if not isinstance(name, str) or not isinstance(use, str):
        raise ValueError(f"distribution {distribution!r} has invalid extension entry point metadata")
    _validate_entry_point(name, use)
    if completed.returncode != 0:
        raise ValueError(f"distribution {distribution!r} extension entry point could not be loaded")
    return name, use


def _write_plugins_block(path: Path, original: str, plugins: list[Any]) -> None:
    newline = "\r\n" if "\r\n" in original else "\n"
    rendered = yaml.safe_dump(
        {"plugins": plugins},
        allow_unicode=True,
        sort_keys=False,
    ).rstrip()
    rendered = rendered.replace("\n", newline) + newline
    span = _plugins_block_span(original)
    if span is None:
        separator = "" if not original or original.endswith(newline * 2) else newline
        updated = original + separator + rendered
    else:
        start, end = span
        updated = original[:start] + rendered + original[end:]

    mode = path.stat().st_mode
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as stream:
            stream.write(updated)
            temporary = Path(stream.name)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _plugins_block_span(original: str) -> tuple[int, int] | None:
    """Locate the character span of an existing top-level ``plugins:`` entry.

    Both boundaries come from the YAML parser rather than a key-shaped regex.
    ``AppConfig`` allows extra top-level keys, so a following section may be
    named anything YAML accepts — ``my.key``, ``2fa``, ``$schema``, a non-ASCII
    word. A pattern that fails to recognize that key does not fail loudly: it
    reports "no next section", and the rewrite then replaces the neighbour and
    its whole subtree with the managed block. Trailing comments below a
    file-final block are preserved for the same reason.
    """
    root = yaml.compose(original)
    if not isinstance(root, yaml.MappingNode):
        return None
    for index, (key, _value) in enumerate(root.value):
        if not isinstance(key, yaml.ScalarNode) or key.value != "plugins":
            continue
        start = key.start_mark.index
        line_end = original.find("\n", start)
        content_start = len(original) if line_end < 0 else line_end + 1
        following = root.value[index + 1 :]
        next_start = following[0][0].start_mark.index if following else len(original)
        between = original[content_start:next_start]
        return start, content_start + _trailing_section_comment_start(between)
    return None


def _trailing_section_comment_start(text: str) -> int:
    lines = text.splitlines(keepends=True)
    index = len(lines) - 1
    saw_comment = False
    while index >= 0:
        content = lines[index].rstrip("\r\n")
        if not content.strip():
            index -= 1
            continue
        if content.startswith("#"):
            saw_comment = True
            index -= 1
            continue
        break
    if not saw_comment:
        return len(text)
    return sum(len(line) for line in lines[: index + 1])


def _find_plugin(plugins: list[Any], identifier: str) -> dict[str, Any]:
    matches = [plugin for plugin in plugins if isinstance(plugin, dict) and (plugin.get("name") == identifier or plugin.get("use") == identifier or _same_distribution(plugin.get("package"), identifier))]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one configured extension matching {identifier!r}")
    return matches[0]


def _controlled_uv_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for name in _UV_ENV_OVERRIDES:
        environment.pop(name, None)
    return environment


def _run_uv(command: list[str], backend_dir: Path) -> None:
    subprocess.run(
        command,
        cwd=backend_dir,
        env=_controlled_uv_environment(),
        check=True,
    )


def _require_supported_uv(backend_dir: Path) -> None:
    completed = subprocess.run(
        ["uv", "--version"],
        cwd=backend_dir,
        env=_controlled_uv_environment(),
        check=True,
        capture_output=True,
        text=True,
    )
    match = re.search(r"\b(\d+)\.(\d+)\.(\d+)\b", completed.stdout)
    if match is None or tuple(int(part) for part in match.groups()) < (0, 8, 0):
        raise RuntimeError("extension installation requires uv 0.8.0 or newer")


def _detect_extra_flags(project_root: Path, config_path: Path) -> list[str]:
    detector = project_root / "scripts" / "detect_uv_extras.py"
    if not detector.is_file():
        return []
    environment = _controlled_uv_environment()
    environment["DEER_FLOW_CONFIG_PATH"] = str(config_path)
    completed = subprocess.run(
        [sys.executable, str(detector)],
        cwd=project_root,
        env=environment,
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    )
    tokens = shlex.split(completed.stdout or "")
    if len(tokens) % 2 or any(tokens[index] != "--extra" or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", tokens[index + 1]) for index in range(0, len(tokens), 2)):
        raise RuntimeError("extension dependency sync received invalid optional-dependency flags")
    return tokens


def _sync_environment(
    project_root: Path,
    backend_dir: Path,
    config_path: Path,
    *,
    locked: bool = True,
) -> None:
    command = [
        "uv",
        "sync",
        "--project",
        str(backend_dir),
        "--all-packages",
    ]
    if locked:
        command.append("--locked")
    command.extend(_detect_extra_flags(project_root, config_path))
    _run_uv(command, backend_dir)


def _sync_restored_environment(project_root: Path, backend_dir: Path, config_path: Path) -> None:
    try:
        _sync_environment(
            project_root,
            backend_dir,
            config_path,
            locked=(backend_dir / "uv.lock").is_file(),
        )
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        raise RuntimeError("extension operation failed and the restored environment could not be synchronized") from exc
