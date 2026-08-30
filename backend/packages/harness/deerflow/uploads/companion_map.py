"""Persist original-filename → converted-markdown metadata next to uploads.

Written at convert time so historical listing can recover collision-renamed
companions (``a.pdf`` → ``a_1.md``) after summarization drops message metadata.
Each entry also carries the companion's convert-time fingerprint (size and
mtime) so a same-named file that later replaces the companion — for example
after the companion was deleted inside the sandbox — is not mistaken for it.
The sidecar lives beside the files it describes and is hidden from listings.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

COMPANION_MAP_FILENAME = ".deer-flow-companions.json"
COMPANION_MAP_LOCK_FILENAME = ".deer-flow-companions.lock"
_COMPANION_MAP_PREFIX = ".deer-flow-companions"
_MAP_VERSION = 2

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None  # type: ignore[assignment]
    import msvcrt
else:
    msvcrt = None  # type: ignore[assignment]

_locks_guard = threading.Lock()
_dir_locks: dict[str, threading.Lock] = {}


@dataclass(frozen=True)
class CompanionEntry:
    """One sidecar row: companion basename plus its convert-time fingerprint.

    ``size`` / ``mtime_ns`` are ``None`` for rows written before the map
    started recording fingerprints; those verify by existence only.
    """

    name: str
    size: int | None = None
    mtime_ns: int | None = None


def is_companion_map_file(filename: str) -> bool:
    """Return whether *filename* is the companion sidecar or its lock/tmp files."""
    return filename.startswith(_COMPANION_MAP_PREFIX)


def _is_safe_basename(name: str) -> bool:
    if not isinstance(name, str) or not name or name in {".", ".."}:
        return False
    if "/" in name or "\\" in name or "\0" in name:
        return False
    return Path(name).name == name and not is_companion_map_file(name)


def _is_safe_companion(name: str) -> bool:
    return _is_safe_basename(name) and name.endswith(".md") and name != ".md"


def _is_safe_original(name: str) -> bool:
    return _is_safe_basename(name)


def _lock_for(uploads_dir: Path) -> threading.Lock:
    key = str(uploads_dir)
    with _locks_guard:
        lock = _dir_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _dir_locks[key] = lock
        return lock


@contextmanager
def _map_write_lock(uploads_dir: Path) -> Iterator[None]:
    """Serialize sidecar writes in-process and across POSIX workers."""
    uploads_dir.mkdir(parents=True, exist_ok=True)
    lock_path = uploads_dir / COMPANION_MAP_LOCK_FILENAME
    process_lock = _lock_for(uploads_dir.resolve())
    with process_lock, lock_path.open("a+b") as lock_file:
        if lock_file.tell() == 0:
            lock_file.write(b"\0")
            lock_file.flush()
        lock_file.seek(0)
        if fcntl is not None:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        else:  # pragma: no cover - Windows
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            else:  # pragma: no cover - Windows
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)


def _map_path(uploads_dir: Path) -> Path:
    return uploads_dir / COMPANION_MAP_FILENAME


def _sanitize_fingerprint(value: object) -> int | None:
    """Return *value* as a valid fingerprint field, or ``None`` when malformed."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _sanitize_entry(key: object, value: object) -> tuple[str, CompanionEntry] | None:
    if not isinstance(key, str) or not _is_safe_original(key):
        return None
    if isinstance(value, str):
        # Version-1 rows stored the bare companion basename (no fingerprint).
        name: object = value
        size = mtime_ns = None
    elif isinstance(value, dict):
        name = value.get("name")
        size = _sanitize_fingerprint(value.get("size"))
        mtime_ns = _sanitize_fingerprint(value.get("mtime_ns"))
    else:
        return None
    if not isinstance(name, str) or not _is_safe_companion(name):
        return None
    return key, CompanionEntry(name=name, size=size, mtime_ns=mtime_ns)


def _sanitize_mapping(raw: object) -> dict[str, CompanionEntry]:
    if not isinstance(raw, dict):
        return {}
    companions = raw.get("companions")
    if not isinstance(companions, dict):
        return {}
    out: dict[str, CompanionEntry] = {}
    for key, value in companions.items():
        sanitized = _sanitize_entry(key, value)
        if sanitized is not None:
            original, entry = sanitized
            out[original] = entry
    return out


def _load_unlocked(uploads_dir: Path) -> dict[str, CompanionEntry]:
    path = _map_path(uploads_dir)
    try:
        if path.is_symlink() or not path.is_file():
            return {}
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("Ignoring corrupt companion map at %s", path)
        return {}
    except OSError:
        return {}
    return _sanitize_mapping(raw)


def _persist_unlocked(uploads_dir: Path, mapping: dict[str, CompanionEntry]) -> None:
    path = _map_path(uploads_dir)
    if path.is_symlink():
        raise ValueError("Companion map path is a symlink")
    if not mapping:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        return

    payload = {
        "version": _MAP_VERSION,
        "companions": {original: {"name": entry.name, "size": entry.size, "mtime_ns": entry.mtime_ns} for original, entry in mapping.items()},
    }
    data = json.dumps(payload, ensure_ascii=False, indent=2)
    fd, tmp_name = tempfile.mkstemp(prefix=f"{_COMPANION_MAP_PREFIX}.", suffix=".tmp", dir=uploads_dir)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        raise


def load_companion_map(uploads_dir: Path) -> dict[str, str]:
    """Return ``original basename → companion .md`` from the sidecar, if any.

    Name-only view of the raw sidecar, stale entries included; use
    :func:`lookup_companion_mapping` for a fingerprint-verified answer.
    """
    return {original: entry.name for original, entry in _load_unlocked(uploads_dir).items()}


def load_companion_entries(uploads_dir: Path) -> dict[str, CompanionEntry]:
    """Return the raw sidecar entries, stale ones included."""
    return _load_unlocked(uploads_dir)


def companion_entry_matches(uploads_dir: Path, entry: CompanionEntry) -> bool:
    """Return whether *entry*'s companion file is still the converted original.

    Verifies existence plus the convert-time fingerprint when one was recorded,
    so a same-named replacement (companion deleted, then an unrelated file
    uploaded under its name) does not match. Legacy entries without a
    fingerprint verify by existence only.
    """
    candidate = uploads_dir / entry.name
    try:
        if candidate.is_symlink() or not candidate.is_file():
            return False
        if entry.size is None and entry.mtime_ns is None:
            return True
        current = candidate.stat()
    except OSError:
        return False
    if entry.size is not None and current.st_size != entry.size:
        return False
    return entry.mtime_ns is None or current.st_mtime_ns == entry.mtime_ns


def lookup_companion_mapping(uploads_dir: Path, original: str) -> str | None:
    """Return the mapped companion basename, or ``None``.

    ``None`` means either no entry exists or the recorded companion no longer
    matches its convert-time fingerprint (deleted or replaced).
    """
    if not _is_safe_original(original):
        return None
    entry = _load_unlocked(uploads_dir).get(original)
    if entry is None or not companion_entry_matches(uploads_dir, entry):
        return None
    return entry.name


def has_companion_entry(uploads_dir: Path, original: str) -> bool:
    """Return whether the sidecar holds any entry for *original*, even a stale one."""
    if not _is_safe_original(original):
        return False
    return original in _load_unlocked(uploads_dir)


def mapped_companion_names(uploads_dir: Path) -> set[str]:
    """Return companion basenames whose recorded file still matches its fingerprint."""
    names: set[str] = set()
    for entry in _load_unlocked(uploads_dir).values():
        if companion_entry_matches(uploads_dir, entry):
            names.add(entry.name)
    return names


def record_companion_mapping(uploads_dir: Path, original: str, companion: str) -> None:
    """Persist ``original → companion`` after a successful conversion.

    Captures the companion's current size and mtime as its fingerprint so a
    later same-named replacement is not mistaken for the converted file.

    Raises:
        ValueError: If either name is unsafe.
        FileNotFoundError: If the companion file does not exist.
    """
    if not _is_safe_original(original):
        raise ValueError(f"Unsafe original filename for companion map: {original!r}")
    if not _is_safe_companion(companion):
        raise ValueError(f"Unsafe companion filename for companion map: {companion!r}")
    if original == companion:
        raise ValueError("Companion mapping cannot point a file at itself")

    companion_path = uploads_dir / companion
    with _map_write_lock(uploads_dir):
        # Stat inside the lock: sampling the fingerprint before acquiring it
        # would let a concurrent writer swap the companion in between, so the
        # recorded size/mtime could describe a file this mapping never pointed at.
        try:
            if companion_path.is_symlink() or not companion_path.is_file():
                raise FileNotFoundError(f"Companion file does not exist: {companion!r}")
            companion_stat = companion_path.stat()
        except OSError as exc:
            raise FileNotFoundError(f"Companion file does not exist: {companion!r}") from exc

        mapping = _load_unlocked(uploads_dir)
        for key, entry in list(mapping.items()):
            if entry.name == companion and key != original:
                del mapping[key]
        mapping[original] = CompanionEntry(
            name=companion,
            size=companion_stat.st_size,
            mtime_ns=companion_stat.st_mtime_ns,
        )
        _persist_unlocked(uploads_dir, mapping)


def forget_companion_mappings(
    uploads_dir: Path,
    pairs: Iterable[tuple[str, str]],
) -> None:
    """Drop sidecar entries for specific ``(original, companion)`` pairs.

    Unlike :func:`forget_companion_mapping`, both halves must match: an entry
    is removed only when its key equals the pair's *original* **and** its
    recorded companion equals the pair's *companion*. This scopes a rollback
    to the mappings one operation actually wrote, so cleaning up after a
    failed upload cannot delete a pre-existing entry that merely shares a
    companion name (for example a previous ``notes.pdf → notes.md`` mapping
    when the rejected request happened to upload its own ``notes.md``).

    Entries are matched by exact pair, never by companion name alone.
    """
    wanted = {(original, companion) for original, companion in pairs if _is_safe_original(original)}
    if not wanted:
        return
    with _map_write_lock(uploads_dir):
        mapping = _load_unlocked(uploads_dir)
        stale = [key for key, entry in mapping.items() if (key, entry.name) in wanted]
        if not stale:
            return
        for key in stale:
            del mapping[key]
        _persist_unlocked(uploads_dir, mapping)


def forget_companion_mapping(
    uploads_dir: Path,
    *,
    original: str | None = None,
    companion: str | None = None,
) -> None:
    """Drop sidecar entries when an original or companion is deleted."""
    if original is None and companion is None:
        return
    with _map_write_lock(uploads_dir):
        mapping = _load_unlocked(uploads_dir)
        changed = False
        if original is not None and original in mapping:
            del mapping[original]
            changed = True
        if companion is not None:
            for key, entry in list(mapping.items()):
                if entry.name == companion:
                    del mapping[key]
                    changed = True
        if changed:
            _persist_unlocked(uploads_dir, mapping)
