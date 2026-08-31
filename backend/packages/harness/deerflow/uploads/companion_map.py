"""Persist original-filename → converted-markdown metadata next to uploads.

Written at convert time so historical listing can recover collision-renamed
companions (``a.pdf`` → ``a_1.md``) after summarization drops message metadata.
Each entry also carries the companion's convert-time fingerprint (size and
mtime) so a same-named file that later replaces the companion — for example
after the companion was deleted inside the sandbox — is not mistaken for it.
The sidecar JSON lives beside the files it describes and is hidden from
listings. The lock file lives *outside* sandbox-visible directories (beside
``user-data``, not inside ``uploads``), is opened with no-follow semantics,
and is acquired with a bounded non-blocking flock so a held lock cannot pin
the shared Gateway file-IO pool.
"""

from __future__ import annotations

import errno
import json
import logging
import os
import stat
import tempfile
import threading
import time
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

COMPANION_MAP_FILENAME = ".deer-flow-companions.json"
COMPANION_MAP_LOCK_FILENAME = ".deer-flow-companions.lock"
_COMPANION_MAP_PREFIX = ".deer-flow-companions"
_MAP_VERSION = 2
_LOCK_RETRY_ATTEMPTS = 10
_LOCK_RETRY_INTERVAL_S = 0.02
_UNSAFE_LOCK_OPEN_ERRNOS = {errno.ELOOP, errno.EISDIR, errno.ENOTDIR, errno.ENXIO, errno.EAGAIN}
if hasattr(errno, "EWOULDBLOCK"):
    _UNSAFE_LOCK_OPEN_ERRNOS.add(errno.EWOULDBLOCK)
_LOCK_BUSY_ERRNOS = {errno.EAGAIN, errno.EACCES}
if hasattr(errno, "EWOULDBLOCK"):
    _LOCK_BUSY_ERRNOS.add(errno.EWOULDBLOCK)


class CompanionMapLockError(OSError):
    """Raised when the sidecar lock path is not a safe exclusive regular file."""


class CompanionMapLockTimeout(Exception):
    """Raised when the sidecar lock cannot be taken within the bounded wait."""


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


def companion_map_lock_path(uploads_dir: Path) -> Path:
    """Return the flock path for *uploads_dir*.

    Production uploads live at ``.../user-data/uploads``. The lock sits beside
    ``user-data`` (the thread directory) so it is outside AIO's three mounts
    and the local sandbox's ``/mnt/user-data`` mapping. The JSON sidecar stays
    inside *uploads_dir*.

    Nonstandard layouts (tests that pass a bare temp dir) keep the lock one
    directory above *uploads_dir* so they do not write two levels up into a
    shared parent.
    """
    resolved = uploads_dir.resolve()
    parent = resolved.parent
    if parent.name == "user-data":
        return parent.parent / COMPANION_MAP_LOCK_FILENAME
    return parent / COMPANION_MAP_LOCK_FILENAME


def _reject_unsafe_lock(lock_path: Path, reason: str) -> CompanionMapLockError:
    return CompanionMapLockError(f"Unsafe companion-map lock at {lock_path}: {reason}")


def _open_lock_no_follow(lock_path: Path):
    """Open *lock_path* without following a symlink.

    The lock lives outside sandbox mounts in the production layout, but
    no-follow plus an exclusive-regular-file check still apply: a confused or
    nonstandard layout must not let ``open()`` follow a link with Gateway
    privileges. POSIX uses ``O_NOFOLLOW``; Windows falls back to ``lstat``
    plus ``fstat``.
    """
    has_nofollow = hasattr(os, "O_NOFOLLOW")
    flags = os.O_RDWR | os.O_CREAT
    if has_nofollow:
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_NONBLOCK"):
        flags |= os.O_NONBLOCK
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC

    if not has_nofollow:
        try:
            pre_open = os.lstat(lock_path)
        except FileNotFoundError:
            pre_open = None
        if pre_open is not None and (stat.S_ISLNK(pre_open.st_mode) or not stat.S_ISREG(pre_open.st_mode)):
            raise _reject_unsafe_lock(lock_path, "not a regular file")
        if pre_open is not None and pre_open.st_nlink != 1:
            raise _reject_unsafe_lock(lock_path, "not an exclusive regular file")

    fd = -1
    handle = None
    try:
        try:
            fd = os.open(lock_path, flags, 0o600)
        except OSError as exc:
            if exc.errno in _UNSAFE_LOCK_OPEN_ERRNOS:
                raise _reject_unsafe_lock(lock_path, "cannot open without following a link") from exc
            raise

        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
            raise _reject_unsafe_lock(lock_path, "not an exclusive regular file")

        handle = os.fdopen(fd, "r+b")
        fd = -1
        if opened.st_size == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        return handle
    except Exception:
        if fd >= 0:
            os.close(fd)
        if handle is not None:
            handle.close()
        raise


def _try_acquire_exclusive(lock_file) -> bool:
    """Take a non-blocking exclusive lock. Return False when the lock is busy."""
    if fcntl is not None:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError as exc:
            if exc.errno in _LOCK_BUSY_ERRNOS:
                return False
            raise
    try:  # pragma: no cover - Windows
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        return True
    except OSError:  # pragma: no cover - Windows
        return False


def _release_exclusive(lock_file) -> None:
    if fcntl is not None:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        return
    lock_file.seek(0)  # pragma: no cover - Windows
    msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)  # pragma: no cover - Windows


def _acquire_exclusive_bounded(lock_file, lock_path: Path) -> None:
    """Acquire *lock_file* with a short bounded wait, then raise on timeout.

    The sidecar is advisory: callers catch :class:`CompanionMapLockTimeout` and
    skip the write rather than block a shared file-IO worker indefinitely.
    """
    attempts = max(1, _LOCK_RETRY_ATTEMPTS)
    for attempt in range(attempts):
        if _try_acquire_exclusive(lock_file):
            return
        if attempt + 1 < attempts and _LOCK_RETRY_INTERVAL_S > 0:
            time.sleep(_LOCK_RETRY_INTERVAL_S)
    raise CompanionMapLockTimeout(f"Timed out acquiring companion-map lock at {lock_path}")


@contextmanager
def _map_write_lock(uploads_dir: Path) -> Iterator[None]:
    """Serialize sidecar writes in-process and across POSIX workers.

    Flock is taken first with a bounded non-blocking wait so a held lock
    cannot pin the per-directory threading lock (or a file-IO worker) forever.
    The in-process lock is acquired only after flock succeeds.
    """
    uploads_dir.mkdir(parents=True, exist_ok=True)
    lock_path = companion_map_lock_path(uploads_dir)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    process_lock = _lock_for(uploads_dir.resolve())
    with _open_lock_no_follow(lock_path) as lock_file:
        _acquire_exclusive_bounded(lock_file, lock_path)
        try:
            with process_lock:
                yield
        finally:
            _release_exclusive(lock_file)


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


def mapped_companion_names(
    uploads_dir: Path,
    entries: Mapping[str, CompanionEntry] | None = None,
) -> set[str]:
    """Return companion basenames whose recorded file still matches its fingerprint.

    Pass a preloaded *entries* mapping (from :func:`load_companion_entries`) so a
    listing pass can reuse one sidecar read instead of opening the JSON again.
    ``entries is None`` loads from disk; an empty mapping means no companions.
    """
    source = _load_unlocked(uploads_dir) if entries is None else entries
    names: set[str] = set()
    for entry in source.values():
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
    try:
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
    except CompanionMapLockTimeout:
        logger.warning(
            "Skipping companion-map write for %s → %s; lock busy at %s",
            original,
            companion,
            companion_map_lock_path(uploads_dir),
        )


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
    try:
        with _map_write_lock(uploads_dir):
            mapping = _load_unlocked(uploads_dir)
            stale = [key for key, entry in mapping.items() if (key, entry.name) in wanted]
            if not stale:
                return
            for key in stale:
                del mapping[key]
            _persist_unlocked(uploads_dir, mapping)
    except CompanionMapLockTimeout:
        logger.warning("Skipping companion-map rollback; lock busy at %s", companion_map_lock_path(uploads_dir))


def forget_companion_mapping(
    uploads_dir: Path,
    *,
    original: str | None = None,
    companion: str | None = None,
) -> None:
    """Drop sidecar entries when an original or companion is deleted."""
    if original is None and companion is None:
        return
    try:
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
    except CompanionMapLockTimeout:
        logger.warning("Skipping companion-map forget; lock busy at %s", companion_map_lock_path(uploads_dir))
