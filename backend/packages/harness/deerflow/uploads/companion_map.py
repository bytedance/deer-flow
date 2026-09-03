"""Persist original-filename → converted-markdown metadata next to uploads.

Written at convert time so historical listing can recover collision-renamed
companions (``a.pdf`` → ``a_1.md``) after summarization drops message metadata.
Each entry also carries a convert-time fingerprint (size, mtime, inode) and,
when the filesystem allows, a private hard-link identity pin. Linux can reuse
an inode number immediately after ``unlink`` + recreate, so ``(st_dev, st_ino)``
alone is not an identity. The pin holds the convert-time inode outside the
sandbox-visible uploads directory (or as a hidden name in test layouts), so a
replacement file cannot masquerade as the companion even when the number is
reused, while an in-place edit of the same inode stays attached.
The sidecar JSON lives beside the files it describes and is hidden from
listings. Reads open it no-follow with a byte and entry cap so a sandbox
cannot turn the mapping file into an unbounded Gateway parse. Writes prune
to those same caps (oldest entries first) and unpin evicted rows so this
module cannot persist a map its own reader would drop. Companion deletion
renames the directory entry to a quarantine name, then verifies the moved
inode against the pin before unlinking, so a sandbox replacement of the
basename is restored instead of deleted. The lock file lives *outside*
sandbox-visible directories (beside ``user-data``, not inside ``uploads``),
is opened with no-follow semantics, and is acquired with a bounded
non-blocking flock so a held lock cannot pin the shared Gateway file-IO
pool.
"""

from __future__ import annotations

import errno
import json
import logging
import os
import secrets
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
COMPANION_ID_DIRNAME = ".deer-flow-companion-ids"
_COMPANION_MAP_PREFIX = ".deer-flow-companions"
_MAP_VERSION = 2
_IDENTITY_TOKEN_LENGTH = 32
MAX_COMPANION_MAP_BYTES = 256 * 1024
MAX_COMPANION_MAP_ENTRIES = 2048
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
    ``id`` is the basename of a private hard-link pin that holds the
    convert-time inode so Linux cannot reuse that number for a replacement.
    ``dev`` / ``ino`` are recorded for diagnostics; matching prefers the pin.
    """

    name: str
    size: int | None = None
    mtime_ns: int | None = None
    dev: int | None = None
    ino: int | None = None
    id: str | None = None


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


def _is_safe_identity_token(token: str) -> bool:
    return isinstance(token, str) and len(token) == _IDENTITY_TOKEN_LENGTH and all(c in "0123456789abcdef" for c in token)


def _sanitize_identity_token(value: object) -> str | None:
    if not isinstance(value, str) or not _is_safe_identity_token(value):
        return None
    return value


def companion_identity_dir(uploads_dir: Path) -> Path:
    """Return the directory that holds hard-link identity pins.

    Production uploads live at ``.../user-data/uploads``. Pins sit beside
    ``user-data`` (with the lock) so AIO mounts and ``/mnt/user-data`` cannot
    unlink them to free the convert-time inode. Test layouts that pass a bare
    temp dir keep pins as hidden files inside *uploads_dir* so they do not
    leak into a shared pytest parent.
    """
    resolved = uploads_dir.resolve()
    if resolved.parent.name == "user-data":
        return resolved.parent.parent / COMPANION_ID_DIRNAME
    return resolved


def companion_identity_path(uploads_dir: Path, token: str) -> Path:
    """Return the pin path for *token* under *uploads_dir*'s layout."""
    if not _is_safe_identity_token(token):
        raise ValueError(f"Unsafe companion identity token: {token!r}")
    directory = companion_identity_dir(uploads_dir)
    if directory.resolve() == uploads_dir.resolve():
        return directory / f"{_COMPANION_MAP_PREFIX}.id.{token}"
    return directory / token


_PIN_UNSUPPORTED_ERRNOS = {errno.EXDEV, errno.EPERM, errno.ENOTSUP}
if hasattr(errno, "ENOSYS"):
    _PIN_UNSUPPORTED_ERRNOS.add(errno.ENOSYS)
if hasattr(errno, "EOPNOTSUPP"):
    _PIN_UNSUPPORTED_ERRNOS.add(errno.EOPNOTSUPP)


def _pin_companion(uploads_dir: Path, companion_path: Path) -> str | None:
    """Hard-link *companion_path* to a private pin. Return the token, or None."""
    token = secrets.token_hex(_IDENTITY_TOKEN_LENGTH // 2)
    pin = companion_identity_path(uploads_dir, token)
    pin.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(companion_path, pin)
    except OSError as exc:
        if exc.errno in _PIN_UNSUPPORTED_ERRNOS:
            return None
        raise
    return token


def _unpin_companion(uploads_dir: Path, token: str | None) -> None:
    if not token or not _is_safe_identity_token(token):
        return
    try:
        companion_identity_path(uploads_dir, token).unlink()
    except FileNotFoundError:
        pass
    except OSError:
        logger.warning("Failed to remove companion identity pin %s", token, exc_info=True)


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
        size = mtime_ns = dev = ino = None
        identity = None
    elif isinstance(value, dict):
        name = value.get("name")
        size = _sanitize_fingerprint(value.get("size"))
        mtime_ns = _sanitize_fingerprint(value.get("mtime_ns"))
        dev = _sanitize_fingerprint(value.get("dev"))
        ino = _sanitize_fingerprint(value.get("ino"))
        identity = _sanitize_identity_token(value.get("id"))
    else:
        return None
    if not isinstance(name, str) or not _is_safe_companion(name):
        return None
    return key, CompanionEntry(name=name, size=size, mtime_ns=mtime_ns, dev=dev, ino=ino, id=identity)


def _sanitize_mapping(raw: object) -> dict[str, CompanionEntry]:
    if not isinstance(raw, dict):
        return {}
    companions = raw.get("companions")
    if not isinstance(companions, dict):
        return {}
    out: dict[str, CompanionEntry] = {}
    truncated = False
    for key, value in companions.items():
        if len(out) >= MAX_COMPANION_MAP_ENTRIES:
            truncated = True
            break
        sanitized = _sanitize_entry(key, value)
        if sanitized is not None:
            original, entry = sanitized
            out[original] = entry
    if truncated:
        logger.warning("Companion map exceeds %s entries; ignoring the rest", MAX_COMPANION_MAP_ENTRIES)
    return out


def _open_sidecar_no_follow(path: Path) -> int:
    """Open *path* read-only without following a symlink. Caller closes the fd."""
    has_nofollow = hasattr(os, "O_NOFOLLOW")
    flags = os.O_RDONLY
    if has_nofollow:
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY

    if not has_nofollow:
        try:
            pre_open = os.lstat(path)
        except FileNotFoundError:
            raise
        if stat.S_ISLNK(pre_open.st_mode) or not stat.S_ISREG(pre_open.st_mode):
            raise OSError(errno.ELOOP, "companion map is not a regular file", str(path))

    try:
        fd = os.open(path, flags)
    except OSError as exc:
        if exc.errno in _UNSAFE_LOCK_OPEN_ERRNOS:
            raise OSError(errno.ELOOP, "cannot open companion map without following a link", str(path)) from exc
        raise

    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode):
            raise OSError(errno.ELOOP, "companion map is not a regular file", str(path))
    except Exception:
        os.close(fd)
        raise
    return fd


def _load_unlocked(uploads_dir: Path) -> dict[str, CompanionEntry]:
    path = _map_path(uploads_dir)
    fd = -1
    raw_bytes = b""
    try:
        fd = _open_sidecar_no_follow(path)
        info = os.fstat(fd)
        if info.st_size <= 0:
            return {}
        if info.st_size > MAX_COMPANION_MAP_BYTES:
            logger.warning("Ignoring oversized companion map at %s (%s bytes)", path, info.st_size)
            return {}
        raw_bytes = os.read(fd, info.st_size)
    except FileNotFoundError:
        return {}
    except OSError:
        return {}
    finally:
        if fd >= 0:
            os.close(fd)

    try:
        raw = json.loads(raw_bytes.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        logger.warning("Ignoring corrupt companion map at %s", path)
        return {}
    return _sanitize_mapping(raw)


def _mapping_payload(mapping: dict[str, CompanionEntry]) -> dict:
    return {
        "version": _MAP_VERSION,
        "companions": {
            original: {
                "name": entry.name,
                "size": entry.size,
                "mtime_ns": entry.mtime_ns,
                "dev": entry.dev,
                "ino": entry.ino,
                **({"id": entry.id} if entry.id else {}),
            }
            for original, entry in mapping.items()
        },
    }


def _serialized_map_bytes(mapping: dict[str, CompanionEntry]) -> int:
    return len(json.dumps(_mapping_payload(mapping), ensure_ascii=False, indent=2).encode("utf-8"))


def _trim_mapping_to_limits(uploads_dir: Path, mapping: dict[str, CompanionEntry]) -> dict[str, CompanionEntry]:
    """Drop oldest rows until the payload fits the reader caps; unpin evicted pins."""
    items = list(mapping.items())
    evicted: list[CompanionEntry] = []
    while len(items) > MAX_COMPANION_MAP_ENTRIES:
        evicted.append(items.pop(0)[1])
    while items and _serialized_map_bytes(dict(items)) > MAX_COMPANION_MAP_BYTES:
        if len(items) == 1:
            raise ValueError(f"Companion map exceeds {MAX_COMPANION_MAP_BYTES} bytes even after pruning")
        evicted.append(items.pop(0)[1])
    if evicted:
        logger.warning("Companion map exceeded persist limits; dropping %s older entries", len(evicted))
        for entry in evicted:
            _unpin_companion(uploads_dir, entry.id)
    return dict(items)


def _persist_unlocked(uploads_dir: Path, mapping: dict[str, CompanionEntry]) -> None:
    path = _map_path(uploads_dir)
    if path.is_symlink():
        raise ValueError("Companion map path is a symlink")
    if mapping:
        mapping = _trim_mapping_to_limits(uploads_dir, mapping)
    if not mapping:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        return

    payload = _mapping_payload(mapping)
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


def _stat_regular_companion(uploads_dir: Path, entry: CompanionEntry) -> os.stat_result | None:
    candidate = uploads_dir / entry.name
    try:
        current = os.lstat(candidate)
    except OSError:
        return None
    if stat.S_ISLNK(current.st_mode) or not stat.S_ISREG(current.st_mode):
        return None
    return current


def _identity_pin_matches(uploads_dir: Path, entry: CompanionEntry, current: os.stat_result) -> bool:
    if not entry.id or not _is_safe_identity_token(entry.id):
        return False
    pin = companion_identity_path(uploads_dir, entry.id)
    try:
        pin_st = os.lstat(pin)
    except OSError:
        return False
    if stat.S_ISLNK(pin_st.st_mode) or not stat.S_ISREG(pin_st.st_mode):
        return False
    return current.st_dev == pin_st.st_dev and current.st_ino == pin_st.st_ino


def companion_entry_matches(uploads_dir: Path, entry: CompanionEntry) -> bool:
    """Return whether *entry*'s companion file is still the converted original.

    A hard-link identity pin is conclusive: the pin holds the convert-time
    inode, so an in-place edit stays attached and a delete-then-recreate is
    stale even when Linux reuses the inode number. Legacy rows without a pin
    fall back to size/mtime (inode numbers are not trusted). Rows with no
    fingerprint verify by existence only.
    """
    current = _stat_regular_companion(uploads_dir, entry)
    if current is None:
        return False
    if entry.id:
        return _identity_pin_matches(uploads_dir, entry, current)
    if entry.size is None and entry.mtime_ns is None:
        return True
    if entry.size is not None and current.st_size != entry.size:
        return False
    return entry.mtime_ns is None or current.st_mtime_ns == entry.mtime_ns


def _quarantine_companion_path(uploads_dir: Path) -> Path:
    """Return a unique quarantine path, preferring the pin directory."""
    token = secrets.token_hex(16)
    directory = companion_identity_dir(uploads_dir)
    directory.mkdir(parents=True, exist_ok=True)
    if directory.resolve() == uploads_dir.resolve():
        return directory / f"{_COMPANION_MAP_PREFIX}.quarantine.{token}"
    return directory / f"quarantine.{token}"


def _restore_quarantined(quarantine: Path, dest: Path) -> None:
    try:
        os.rename(quarantine, dest)
    except OSError:
        logger.warning("Failed to restore quarantined companion to %s", dest, exc_info=True)


def _stat_matches_entry(
    uploads_dir: Path,
    entry: CompanionEntry,
    current: os.stat_result,
    *,
    unmodified: bool,
) -> bool:
    if stat.S_ISLNK(current.st_mode) or not stat.S_ISREG(current.st_mode):
        return False
    if unmodified:
        if entry.id and not _identity_pin_matches(uploads_dir, entry, current):
            return False
        if entry.size is not None and current.st_size != entry.size:
            return False
        if entry.mtime_ns is not None and current.st_mtime_ns != entry.mtime_ns:
            return False
        return True
    if entry.id:
        return _identity_pin_matches(uploads_dir, entry, current)
    if entry.size is None and entry.mtime_ns is None:
        return True
    if entry.size is not None and current.st_size != entry.size:
        return False
    return entry.mtime_ns is None or current.st_mtime_ns == entry.mtime_ns


def unlink_verified_companion(
    uploads_dir: Path,
    entry: CompanionEntry,
    *,
    unmodified: bool = False,
) -> bool:
    """Quarantine the companion basename, then unlink only if it still matches *entry*.

    ``os.rename`` steals the directory entry atomically. The moved inode is
    checked against the identity pin (and, when *unmodified* is true, the
    convert-time size/mtime). A mismatch restores the file so a sandbox
    replacement of the basename is not deleted.

    Returns:
        True if the quarantined file was removed, False if it was preserved
        or missing.
    """
    if not _is_safe_companion(entry.name):
        return False
    src = uploads_dir / entry.name
    quarantine = _quarantine_companion_path(uploads_dir)
    try:
        os.rename(src, quarantine)
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            return False
        quarantine = uploads_dir / f"{_COMPANION_MAP_PREFIX}.quarantine.{secrets.token_hex(16)}"
        try:
            os.rename(src, quarantine)
        except OSError:
            return False
    try:
        current = os.lstat(quarantine)
        if _stat_matches_entry(uploads_dir, entry, current, unmodified=unmodified):
            os.unlink(quarantine)
            return True
        _restore_quarantined(quarantine, src)
        return False
    except OSError:
        _restore_quarantined(quarantine, src)
        return False


def _unlink_unmodified_companion(uploads_dir: Path, entry: CompanionEntry, *, keep_name: str) -> None:
    """Remove a still-current, unmodified conversion artifact being replaced.

    Edited or stale files are left in place so a later re-upload cannot delete
    user notes that reused or mutated the previous companion name.
    """
    if entry.name == keep_name:
        return
    if not companion_entry_matches(uploads_dir, entry):
        return
    unlink_verified_companion(uploads_dir, entry, unmodified=True)


def lookup_companion_mapping(uploads_dir: Path, original: str) -> str | None:
    """Return the mapped companion basename, or ``None``.

    ``None`` means either no entry exists or the recorded companion no longer
    matches its convert-time fingerprint (deleted, replaced, or — for legacy
    size/mtime rows — edited in place).
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

    Captures the companion's current size, mtime, and inode, and pins the
    convert-time inode with a private hard link so a later same-named
    replacement cannot reuse that number. An in-place edit of the same inode
    stays attached. Re-recording the same original drops the previous mapping
    and unlinks the prior companion only when it is still the unmodified
    conversion artifact.

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
            # recorded fingerprint could describe a file this mapping never pointed at.
            try:
                if companion_path.is_symlink() or not companion_path.is_file():
                    raise FileNotFoundError(f"Companion file does not exist: {companion!r}")
            except OSError as exc:
                raise FileNotFoundError(f"Companion file does not exist: {companion!r}") from exc

            pin_token = _pin_companion(uploads_dir, companion_path)
            try:
                companion_stat = companion_path.stat()
            except OSError as exc:
                _unpin_companion(uploads_dir, pin_token)
                raise FileNotFoundError(f"Companion file does not exist: {companion!r}") from exc
            mapping = _load_unlocked(uploads_dir)
            previous = mapping.pop(original, None)
            displaced: list[CompanionEntry] = []
            for key, entry in list(mapping.items()):
                if entry.name == companion:
                    displaced.append(mapping.pop(key))
            mapping[original] = CompanionEntry(
                name=companion,
                size=companion_stat.st_size,
                mtime_ns=companion_stat.st_mtime_ns,
                dev=companion_stat.st_dev,
                ino=companion_stat.st_ino,
                id=pin_token,
            )
            try:
                _persist_unlocked(uploads_dir, mapping)
            except Exception:
                _unpin_companion(uploads_dir, pin_token)
                raise
            if previous is not None:
                _unlink_unmodified_companion(uploads_dir, previous, keep_name=companion)
                if previous.id and previous.id != pin_token:
                    _unpin_companion(uploads_dir, previous.id)
            for entry in displaced:
                if entry.id and entry.id != pin_token:
                    _unpin_companion(uploads_dir, entry.id)
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
            dropped = [mapping.pop(key) for key in stale]
            _persist_unlocked(uploads_dir, mapping)
            for entry in dropped:
                _unpin_companion(uploads_dir, entry.id)
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
            dropped: list[CompanionEntry] = []
            if original is not None and original in mapping:
                dropped.append(mapping.pop(original))
            if companion is not None:
                for key, entry in list(mapping.items()):
                    if entry.name == companion:
                        dropped.append(mapping.pop(key))
            if dropped:
                _persist_unlocked(uploads_dir, mapping)
                for entry in dropped:
                    _unpin_companion(uploads_dir, entry.id)
    except CompanionMapLockTimeout:
        logger.warning("Skipping companion-map forget; lock busy at %s", companion_map_lock_path(uploads_dir))
