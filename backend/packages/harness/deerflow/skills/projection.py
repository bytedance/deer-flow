"""Materialize enabled-only skill trees for sandbox filesystem exposure."""

from __future__ import annotations

import errno
import hashlib
import json
import logging
import os
import shutil
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from deerflow.skills.parser import parse_skill_file
from deerflow.skills.types import SKILL_MD_FILE, Skill, SkillCategory

if TYPE_CHECKING:
    from deerflow.skills.storage.skill_storage import SkillStorage

logger = logging.getLogger(__name__)

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None  # type: ignore[assignment]
    import msvcrt

_locks_guard = threading.Lock()
_process_locks: dict[Path, threading.RLock] = {}
_MANIFEST_VERSION = 1
_MAX_REBUILD_ATTEMPTS = 2


@dataclass(frozen=True)
class SkillProjectionPaths:
    """Stable category roots mounted or uploaded by sandbox providers."""

    public: Path
    custom: Path
    legacy: Path


def get_skill_projection_paths(storage: SkillStorage) -> SkillProjectionPaths:
    from deerflow.config.paths import get_paths

    paths = getattr(storage, "_paths", None) or get_paths()
    user_id = getattr(storage, "user_id", None)
    if user_id is None:
        return SkillProjectionPaths(
            public=paths.public_skills_view_dir,
            custom=paths.skills_view_dir / "custom",
            legacy=paths.skills_view_dir / "legacy",
        )
    return SkillProjectionPaths(
        public=paths.public_skills_view_dir,
        custom=paths.user_custom_skills_view_dir(user_id),
        legacy=paths.user_legacy_skills_view_dir(user_id),
    )


def _lock_for(path: Path) -> threading.RLock:
    resolved = path.resolve()
    with _locks_guard:
        return _process_locks.setdefault(resolved, threading.RLock())


@contextmanager
def _projection_lock(root: Path) -> Iterator[None]:
    """Serialize projection replacement in-process and across POSIX workers."""
    lock_path = root.parent / f".{root.name}.projection.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    process_lock = _lock_for(lock_path)
    with process_lock, lock_path.open("a", encoding="utf-8") as lock_file:
        if fcntl is not None:
            fcntl.flock(lock_file, fcntl.LOCK_EX)
        else:  # pragma: no cover - Windows
            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(lock_file, fcntl.LOCK_UN)
            else:  # pragma: no cover - Windows
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)


def _link_or_copy(source: str, target: str, *, follow_symlinks: bool = True) -> str:
    try:
        os.link(source, target, follow_symlinks=follow_symlinks)
    except OSError as exc:
        if exc.errno not in {errno.EXDEV, errno.EPERM, errno.EACCES, errno.ENOTSUP}:
            raise
        shutil.copy2(source, target, follow_symlinks=follow_symlinks)
    return target


def _stage_skill(source: Path, target: Path, nested_skill_roots: set[Path]) -> None:
    def _exclude_nested_skills(current: str, names: list[str]) -> list[str]:
        relative_root = Path(current).relative_to(source)
        return [name for name in names if relative_root / name in nested_skill_roots]

    shutil.copytree(
        source,
        target,
        copy_function=_link_or_copy,
        symlinks=True,
        ignore=_exclude_nested_skills,
        dirs_exist_ok=True,
    )


def _replace_category(root: Path, desired: dict[Path, Skill], skill_boundaries: set[Path]) -> None:
    """Replace entries beneath a stable category root, removing first."""
    root.mkdir(parents=True, exist_ok=True)
    # Keep the category root inode stable because live sandboxes bind-mount that
    # directory. Clear before staging so allocation/copy failures cannot leave a
    # stale enabled view behind.
    _clear_category(root)
    try:
        with tempfile.TemporaryDirectory(prefix=f".{root.name}.projection-", dir=root.parent) as staging_dir:
            staging = Path(staging_dir)
            for relative_path, skill in desired.items():
                nested_roots = {boundary.relative_to(relative_path) for boundary in skill_boundaries if boundary != relative_path and boundary.is_relative_to(relative_path)}
                _stage_skill(skill.skill_dir, staging / relative_path, nested_roots)
            for path in staging.iterdir():
                path.replace(root / path.name)
    except Exception:
        _clear_category(root)
        raise


def _clear_category(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for path in root.iterdir():
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()


def _clear_projection_scope(scope_root: Path, *category_roots: Path) -> None:
    for category_root in category_roots:
        _clear_category(category_root)
    _manifest_path(scope_root).unlink(missing_ok=True)


def _update_tree_digest(digest, root: Path, label: str) -> None:
    digest.update(f"root:{label}\0".encode())
    if not root.exists():
        digest.update(b"absent\0")
        return

    stack = [(root, Path("."))]
    while stack:
        current, relative_root = stack.pop()
        with os.scandir(current) as entries:
            ordered = sorted(entries, key=lambda entry: entry.name)
        child_dirs: list[tuple[Path, Path]] = []
        for entry in ordered:
            relative = relative_root / entry.name
            metadata = entry.stat(follow_symlinks=False)
            if entry.is_symlink():
                kind = "link"
            elif entry.is_dir(follow_symlinks=False):
                kind = "dir"
                child_dirs.append((Path(entry.path), relative))
            else:
                kind = "file"
            digest.update((f"{label}:{relative.as_posix()}:{kind}:{metadata.st_ino}:{metadata.st_mode}:{metadata.st_size}:{metadata.st_mtime_ns}\0").encode())
        stack.extend(reversed(child_dirs))


def _extensions_state() -> dict:
    from deerflow.config.extensions_config import ExtensionsConfig

    config = ExtensionsConfig.from_file()
    return {name: state.model_dump(mode="json") for name, state in config.skills.items()}


def _source_signature(storage: SkillStorage, scope: str) -> str:
    digest = hashlib.sha256()
    host_root = storage.get_skills_root_path()
    if scope == "public":
        _update_tree_digest(digest, host_root / SkillCategory.PUBLIC.value, "public")
        state = {"extensions": _extensions_state()}
    elif scope == "user":
        user_custom_root = storage.get_user_custom_root()
        _update_tree_digest(digest, user_custom_root, "custom")
        _update_tree_digest(digest, host_root / SkillCategory.CUSTOM.value, "legacy")
        state = {
            "extensions": _extensions_state(),
            "user": storage._read_skill_states(),
        }
    else:  # pragma: no cover - internal invariant
        raise ValueError(f"Unknown skill projection scope: {scope}")
    digest.update(json.dumps(state, sort_keys=True, separators=(",", ":")).encode())
    return digest.hexdigest()


def _manifest_path(scope_root: Path) -> Path:
    return scope_root / ".projection-manifest.json"


def _read_manifest(scope_root: Path) -> dict | None:
    try:
        value = json.loads(_manifest_path(scope_root).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _write_manifest(scope_root: Path, source_signature: str) -> None:
    scope_root.mkdir(parents=True, exist_ok=True)
    target = _manifest_path(scope_root)
    fd, temporary_name = tempfile.mkstemp(prefix=".projection-manifest-", suffix=".tmp", dir=scope_root)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({"version": _MANIFEST_VERSION, "source_signature": source_signature}, stream, sort_keys=True)
        temporary.replace(target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _load_public_skills(storage: SkillStorage, *, enabled_only: bool) -> list[Skill]:
    from deerflow.config.extensions_config import ExtensionsConfig

    public_root = storage.get_skills_root_path() / SkillCategory.PUBLIC.value
    if not public_root.is_dir():
        return []
    extensions = ExtensionsConfig.from_file()
    skills: list[Skill] = []
    for current_root, dir_names, file_names in os.walk(public_root, followlinks=True):
        dir_names[:] = sorted(name for name in dir_names if not name.startswith("."))
        if SKILL_MD_FILE not in file_names:
            continue
        skill_file = Path(current_root) / SKILL_MD_FILE
        skill = parse_skill_file(
            skill_file,
            category=SkillCategory.PUBLIC,
            relative_path=skill_file.parent.relative_to(public_root),
        )
        if skill is None:
            continue
        enabled = extensions.is_skill_enabled(skill.name, SkillCategory.PUBLIC.value)
        if not enabled_only or enabled:
            skills.append(skill)
    return skills


def _by_relative_path(skills: list[Skill], category: SkillCategory) -> dict[Path, Skill]:
    return {skill.relative_path: skill for skill in skills if skill.category == category}


def _category_boundaries(skills: list[Skill], category: SkillCategory) -> set[Path]:
    return {skill.relative_path for skill in skills if skill.category == category}


def _rebuild_public_locked(storage: SkillStorage, paths: SkillProjectionPaths) -> None:
    scope_root = paths.public.parent
    try:
        for _attempt in range(_MAX_REBUILD_ATTEMPTS):
            before = _source_signature(storage, "public")
            all_public_skills = _load_public_skills(storage, enabled_only=False)
            enabled_public_skills = _load_public_skills(storage, enabled_only=True)
            _replace_category(
                paths.public,
                _by_relative_path(enabled_public_skills, SkillCategory.PUBLIC),
                _category_boundaries(all_public_skills, SkillCategory.PUBLIC),
            )
            after = _source_signature(storage, "public")
            if before == after:
                _write_manifest(scope_root, after)
                return
        raise RuntimeError("Public skills changed repeatedly while rebuilding the sandbox projection")
    except Exception:
        _clear_projection_scope(scope_root, paths.public)
        raise


def _rebuild_user_locked(storage: SkillStorage, paths: SkillProjectionPaths) -> None:
    scope_root = paths.custom.parent
    try:
        for _attempt in range(_MAX_REBUILD_ATTEMPTS):
            before = _source_signature(storage, "user")
            all_user_skills = storage.load_skills(enabled_only=False)
            enabled_user_skills = [skill for skill in all_user_skills if skill.enabled]
            _replace_category(
                paths.custom,
                _by_relative_path(enabled_user_skills, SkillCategory.CUSTOM),
                _category_boundaries(all_user_skills, SkillCategory.CUSTOM),
            )
            _replace_category(
                paths.legacy,
                _by_relative_path(enabled_user_skills, SkillCategory.LEGACY),
                _category_boundaries(all_user_skills, SkillCategory.LEGACY),
            )
            after = _source_signature(storage, "user")
            if before == after:
                _write_manifest(scope_root, after)
                return
        raise RuntimeError("User skills changed repeatedly while rebuilding the sandbox projection")
    except Exception:
        _clear_projection_scope(scope_root, paths.custom, paths.legacy)
        raise


def rebuild_skill_projections(
    storage: SkillStorage,
    *,
    include_public: bool = True,
    include_user: bool = True,
) -> SkillProjectionPaths:
    """Rebuild enabled-only projection scopes visible through ``storage``."""
    paths = get_skill_projection_paths(storage)
    user_id = getattr(storage, "user_id", None)
    if include_public:
        with _projection_lock(paths.public.parent):
            _rebuild_public_locked(storage, paths)
    if include_user and user_id is not None:
        with _projection_lock(paths.custom.parent):
            _rebuild_user_locked(storage, paths)

    return paths


def ensure_skill_projections(storage: SkillStorage) -> SkillProjectionPaths:
    """Repair stale projection scopes, otherwise leave their inodes untouched."""
    paths = get_skill_projection_paths(storage)
    with _projection_lock(paths.public.parent):
        try:
            manifest = _read_manifest(paths.public.parent)
            signature = _source_signature(storage, "public")
            if not paths.public.is_dir() or manifest is None or manifest.get("version") != _MANIFEST_VERSION or manifest.get("source_signature") != signature:
                _rebuild_public_locked(storage, paths)
        except Exception:
            _clear_projection_scope(paths.public.parent, paths.public)
            raise

    if getattr(storage, "user_id", None) is not None:
        with _projection_lock(paths.custom.parent):
            try:
                manifest = _read_manifest(paths.custom.parent)
                signature = _source_signature(storage, "user")
                if not paths.custom.is_dir() or not paths.legacy.is_dir() or manifest is None or manifest.get("version") != _MANIFEST_VERSION or manifest.get("source_signature") != signature:
                    _rebuild_user_locked(storage, paths)
            except Exception:
                _clear_projection_scope(paths.custom.parent, paths.custom, paths.legacy)
                raise
    return paths


@contextmanager
def skill_projection_mutation(storage: SkillStorage, scope: str) -> Iterator[None]:
    """Hold a projection scope lock across a source/state mutation."""
    if not isinstance(storage.get_skills_root_path(), Path):
        # Lightweight unit-test doubles sometimes return MagicMock here. The
        # SkillStorage contract requires a Path; real storage implementations
        # therefore never take this compatibility branch.
        yield
        return
    paths = get_skill_projection_paths(storage)
    if scope == "public":
        scope_root = paths.public.parent
        category_roots = (paths.public,)

        def rebuild() -> None:
            _rebuild_public_locked(storage, paths)

    elif scope == "user":
        scope_root = paths.custom.parent
        category_roots = (paths.custom, paths.legacy)

        def rebuild() -> None:
            _rebuild_user_locked(storage, paths)

    else:
        raise ValueError(f"Unknown skill projection scope: {scope}")

    with _projection_lock(scope_root):
        for category_root in category_roots:
            _clear_category(category_root)
        _manifest_path(scope_root).unlink(missing_ok=True)
        try:
            yield
        except Exception:
            # Keep the view empty. A later acquire compares the missing manifest
            # with the actual source state and repairs it under the same lock.
            raise
        else:
            rebuild()


def rebuild_all_skill_projections(*, app_config=None) -> int:
    """Rebuild public and every known user's views during gateway boot.

    Each scope's rebuild is isolated: a single broken user directory (bad
    permissions, corrupted state file, unreadable content) fails closed for
    that scope only (``_rebuild_*_locked`` already clears the view on error)
    and must not abort the whole gateway boot — the same failure mode that
    isolates a scope at acquire/mutation time applies here too, since this is
    just another rebuild trigger. Sandbox acquire self-heals a scope left
    empty by a boot failure on next actual use.
    """
    from deerflow.config import get_app_config
    from deerflow.config.paths import _validate_user_id, get_paths
    from deerflow.skills.storage import get_or_new_skill_storage, get_or_new_user_skill_storage

    config = app_config or get_app_config()
    public_storage = get_or_new_skill_storage(app_config=config)
    try:
        rebuild_skill_projections(public_storage, include_user=False)
    except Exception:
        logger.warning("Failed to rebuild the public skill projection during boot; it stays empty until a sandbox acquire self-heals it", exc_info=True)

    users_dir = get_paths().base_dir / "users"
    if not users_dir.is_dir():
        return 0

    rebuilt = 0
    for user_dir in sorted(users_dir.iterdir(), key=lambda path: path.name):
        if not user_dir.is_dir() or user_dir.name.startswith("."):
            continue
        try:
            user_id = _validate_user_id(user_dir.name)
        except ValueError:
            logger.warning("Skipping invalid user directory while rebuilding skill projections")
            continue
        storage = get_or_new_user_skill_storage(user_id, app_config=config)
        try:
            rebuild_skill_projections(storage, include_public=False)
        except Exception:
            logger.warning("Failed to rebuild the skill projection for user %s during boot; it stays empty until a sandbox acquire self-heals it", user_id, exc_info=True)
            continue
        rebuilt += 1
    return rebuilt
