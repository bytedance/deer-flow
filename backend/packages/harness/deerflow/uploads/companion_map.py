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
listings. Reads open it no-follow and nonblocking, with a byte and entry
cap, so a sandbox cannot block the Gateway on a FIFO or turn the mapping
into an unbounded parse. Writes prune
to those same caps (oldest entries first, binary-searching the serialized
size) and unpin evicted rows so this
module cannot persist a map its own reader would drop. Dropped live rows
leave a durable original-name tombstone (or, if even that list cannot fit,
a sticky ``no_legacy_fallback`` flag) so collision-renamed companions are
not mistaken for pre-sidecar ``<stem>.md`` uploads. Companion deletion
renames the directory entry to a quarantine name, then verifies the moved
inode against the pin before unlinking, so a sandbox replacement of the
basename is restored instead of deleted. Thread branch copies only
``user-data``, so destination companions are new inodes; callers must
copy with :func:`copy_user_data_tree` (which records the source inode
actually opened) and :func:`rebind_cloned_companion_identities` instead of
copying the pin directory or comparing post-copy bytes. The copy restores
source file and directory permission bits, finishes each short ``os.write``, refuses a
companion identity when the source size/mtime/ctime change while it is
being read, and keeps that source inode alive with a temporary hard link
or a bounded number of open fds until :func:`release_copied_identities` so Linux cannot
reuse the number before rebind. A file copied without a live hold is omitted from the
identity map so rebind tombstones that companion instead of trusting inode numbers.
Fd fallback is capped against ``RLIMIT_NOFILE`` so a
tree whose filesystem cannot hard-link cannot exhaust the process fd table. Destination
directories stay writable until their children are copied, then the source mode is
applied. Unpinned sidecar rows still have to pass
the legacy size/mtime check; inode numbers alone cannot revive them. The lock file lives *outside*
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
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
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
_SKIP_COPY_ERRNOS = set(_UNSAFE_LOCK_OPEN_ERRNOS) | {errno.ENOENT, errno.EPERM, errno.EACCES}
_COPY_CHUNK_SIZE = 1024 * 1024
_COPY_HOLD_DIR_PREFIX = ".deer-flow-copy-holds."
_MAX_HELD_COPY_FDS = 16
_COPY_FD_HEADROOM = 8


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


class _SourceIdentityHold:
    """Keep a copied source inode allocated until rebind finishes.

    Linux may reuse an inode number as soon as the last name and last fd are
    gone. A temporary hard link is preferred so a large tree does not exhaust
    the process fd table; an open fd is a bounded fallback when linking is
    unsupported. When the fd budget is exhausted the copy still succeeds, but
    no rebind identity is recorded so inode numbers alone cannot revive a
    mapping. ``release`` is idempotent.
    """

    __slots__ = ("fd", "path")

    def __init__(self, *, fd: int = -1, path: Path | None = None) -> None:
        self.fd = fd
        self.path = path

    def is_live(self) -> bool:
        """Return whether this hold still keeps the source inode allocated."""
        return self.path is not None or self.fd >= 0

    def release(self) -> None:
        fd, self.fd = self.fd, -1
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass
        path, self.path = self.path, None
        if path is not None:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                logger.warning("Failed to remove copy identity hold %s", path, exc_info=True)

    def __del__(self) -> None:
        self.release()


class _CopyFdBudget:
    """Cap how many source fds one copy tree may keep open after each file."""

    __slots__ = ("remaining",)

    def __init__(self, limit: int) -> None:
        self.remaining = max(0, int(limit))

    def try_take(self) -> bool:
        if self.remaining <= 0:
            return False
        self.remaining -= 1
        return True


@dataclass(frozen=True)
class CopiedFileIdentity:
    """Inode pair recorded while copying one regular file from a no-follow fd.

    Branch rebind treats this as the only proof that the destination file came
    from a particular source inode. Byte equality after the copy is not used.
    The optional hold keeps that source inode from being reused until
    :func:`release_copied_identities`. Identities without a live hold are not
    accepted by branch rebind.
    """

    source_dev: int
    source_ino: int
    dest_dev: int
    dest_ino: int
    _hold: _SourceIdentityHold | None = field(default=None, compare=False, hash=False, repr=False)


@dataclass(frozen=True)
class CompanionMapState:
    """Sidecar contents: live rows, eviction tombstones, and the overflow flag.

    ``evicted`` originals once had a companion mapping that was pruned to
    fit the reader caps. They must not use the legacy ``<stem>.md`` heuristic.
    ``no_legacy_fallback`` is the sticky overflow switch used when even the
    tombstone list cannot fit the byte cap: then *every* unmapped original
    skips that heuristic. The flag is stored on disk, not in process memory.
    """

    companions: dict[str, CompanionEntry] = field(default_factory=dict)
    evicted: tuple[str, ...] = ()
    no_legacy_fallback: bool = False

    def blocks_legacy_fallback(self, original: str) -> bool:
        """Return whether *original* must not use the ``<stem>.md`` heuristic."""
        if not original:
            return False
        if self.no_legacy_fallback:
            return True
        return original in self.companions or original in self.evicted


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
    try:
        info = os.lstat(companion_path)
    except OSError:
        return None
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        return None
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


def _dedupe_evicted(names: Iterable[str], *, occupied: Mapping[str, CompanionEntry] | None = None) -> list[str]:
    """Return safe original names not currently mapped, first occurrence kept."""
    occupied_keys = occupied if occupied is not None else {}
    out: list[str] = []
    seen: set[str] = set()
    for name in names:
        if not isinstance(name, str) or not _is_safe_original(name):
            continue
        if name in occupied_keys or name in seen:
            continue
        out.append(name)
        seen.add(name)
    return out


def _sanitize_mapping(raw: object) -> dict[str, CompanionEntry]:
    return _sanitize_state(raw).companions


def _sanitize_state(raw: object) -> CompanionMapState:
    if not isinstance(raw, dict):
        return CompanionMapState()
    companions_raw = raw.get("companions")
    out: dict[str, CompanionEntry] = {}
    if isinstance(companions_raw, dict):
        truncated = False
        for key, value in companions_raw.items():
            if len(out) >= MAX_COMPANION_MAP_ENTRIES:
                truncated = True
                break
            sanitized = _sanitize_entry(key, value)
            if sanitized is not None:
                original, entry = sanitized
                out[original] = entry
        if truncated:
            logger.warning("Companion map exceeds %s entries; ignoring the rest", MAX_COMPANION_MAP_ENTRIES)
    evicted_raw = raw.get("evicted")
    evicted: list[str] = []
    if isinstance(evicted_raw, list):
        evicted = _dedupe_evicted(evicted_raw, occupied=out)
    return CompanionMapState(
        companions=out,
        evicted=tuple(evicted),
        no_legacy_fallback=raw.get("no_legacy_fallback") is True,
    )


def _open_sidecar_no_follow(path: Path) -> int:
    """Open *path* read-only without following a symlink. Caller closes the fd.

    ``O_NONBLOCK`` keeps a sandbox-replaced FIFO from stalling ``os.open``
    before the regular-file check runs.
    """
    has_nofollow = hasattr(os, "O_NOFOLLOW")
    flags = os.O_RDONLY
    if has_nofollow:
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_NONBLOCK"):
        flags |= os.O_NONBLOCK
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


def _load_state_unlocked(uploads_dir: Path) -> CompanionMapState:
    path = _map_path(uploads_dir)
    fd = -1
    raw_bytes = b""
    try:
        fd = _open_sidecar_no_follow(path)
        info = os.fstat(fd)
        if info.st_size <= 0:
            return CompanionMapState()
        if info.st_size > MAX_COMPANION_MAP_BYTES:
            logger.warning("Ignoring oversized companion map at %s (%s bytes)", path, info.st_size)
            return CompanionMapState()
        raw_bytes = os.read(fd, info.st_size)
    except FileNotFoundError:
        return CompanionMapState()
    except OSError:
        return CompanionMapState()
    finally:
        if fd >= 0:
            os.close(fd)

    try:
        raw = json.loads(raw_bytes.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        logger.warning("Ignoring corrupt companion map at %s", path)
        return CompanionMapState()
    return _sanitize_state(raw)


def _mapping_payload(
    mapping: dict[str, CompanionEntry],
    evicted: Iterable[str] = (),
    no_legacy_fallback: bool = False,
) -> dict:
    payload: dict = {
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
    if no_legacy_fallback:
        payload["no_legacy_fallback"] = True
    else:
        names = _dedupe_evicted(evicted, occupied=mapping)
        if names:
            payload["evicted"] = names
    return payload


def _serialized_map_bytes(
    mapping: dict[str, CompanionEntry],
    evicted: Iterable[str] = (),
    no_legacy_fallback: bool = False,
) -> int:
    return len(json.dumps(_mapping_payload(mapping, evicted, no_legacy_fallback), ensure_ascii=False, indent=2).encode("utf-8"))


def _trim_mapping_to_limits(
    mapping: dict[str, CompanionEntry],
    evicted: Iterable[str] = (),
    no_legacy_fallback: bool = False,
) -> tuple[dict[str, CompanionEntry], list[CompanionEntry], list[str], bool]:
    """Drop oldest live rows until the payload fits the reader caps.

    Byte-cap eviction binary-searches the drop count so the exclusive flock is
    not held across a quadratic ``json.dumps`` loop. Dropped originals are kept
    as tombstones so they are not treated as pre-sidecar uploads. If even the
    tombstone list cannot fit, ``no_legacy_fallback`` is set and names are omitted.
    """
    items = list(mapping.items())
    prior_evicted = _dedupe_evicted(evicted, occupied=mapping)
    dropped: list[tuple[str, CompanionEntry]] = []
    flag = no_legacy_fallback

    overflow = len(items) - MAX_COMPANION_MAP_ENTRIES
    if overflow > 0:
        dropped.extend(items[:overflow])
        items = items[overflow:]

    def merge_tombstones(kept: dict[str, CompanionEntry], extra: list[tuple[str, CompanionEntry]]) -> list[str]:
        return _dedupe_evicted(
            [original for original, _ in extra] + prior_evicted,
            occupied=kept,
        )

    def payload_bytes(kept: dict[str, CompanionEntry], names: Iterable[str], sticky: bool) -> int:
        return _serialized_map_bytes(kept, names, sticky)

    def fit(
        kept: dict[str, CompanionEntry],
        extra: list[tuple[str, CompanionEntry]],
        sticky: bool,
    ) -> tuple[list[str], bool, int]:
        names = merge_tombstones(kept, extra)
        size = payload_bytes(kept, names, sticky)
        if size <= MAX_COMPANION_MAP_BYTES:
            return names, sticky, size
        sticky_size = payload_bytes(kept, (), True)
        if sticky_size <= MAX_COMPANION_MAP_BYTES:
            return [], True, sticky_size
        return names, sticky, size

    extra_all = dropped
    if not items:
        names, flag, size = fit({}, extra_all, flag)
        if size <= MAX_COMPANION_MAP_BYTES:
            return {}, [entry for _, entry in extra_all], names, flag
        raise ValueError(f"Companion map exceeds {MAX_COMPANION_MAP_BYTES} bytes even after pruning")

    names, flag, size = fit(dict(items), extra_all, flag)
    if size <= MAX_COMPANION_MAP_BYTES:
        return dict(items), [entry for _, entry in extra_all], names, flag

    last_kept = dict(items[-1:])
    last_extra = extra_all + items[:-1]
    _, _, last_size = fit(last_kept, last_extra, flag)
    if last_size > MAX_COMPANION_MAP_BYTES:
        raise ValueError(f"Companion map exceeds {MAX_COMPANION_MAP_BYTES} bytes even after pruning")

    lo, hi = 1, len(items) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        kept = dict(items[mid:])
        extra = extra_all + items[:mid]
        _, _, candidate = fit(kept, extra, flag)
        if candidate <= MAX_COMPANION_MAP_BYTES:
            hi = mid
        else:
            lo = mid + 1
    kept = dict(items[lo:])
    extra = extra_all + items[:lo]
    names, flag, size = fit(kept, extra, flag)
    if size > MAX_COMPANION_MAP_BYTES:
        raise ValueError(f"Companion map exceeds {MAX_COMPANION_MAP_BYTES} bytes even after pruning")
    return kept, [entry for _, entry in extra], names, flag


def _persist_unlocked(
    uploads_dir: Path,
    mapping: dict[str, CompanionEntry],
    *,
    evicted: Iterable[str] = (),
    no_legacy_fallback: bool = False,
) -> None:
    path = _map_path(uploads_dir)
    if path.is_symlink():
        raise ValueError("Companion map path is a symlink")
    dropped: list[CompanionEntry] = []
    evicted_names = list(evicted)
    flag = no_legacy_fallback
    if mapping or evicted_names or flag:
        mapping, dropped, evicted_names, flag = _trim_mapping_to_limits(mapping, evicted_names, flag)
    if not mapping and not evicted_names and not flag:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        if dropped:
            logger.warning("Companion map exceeded persist limits; dropping %s older entries", len(dropped))
            for entry in dropped:
                _unpin_companion(uploads_dir, entry.id)
        return

    payload = _mapping_payload(mapping, evicted_names, flag)
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

    if dropped:
        logger.warning("Companion map exceeded persist limits; dropping %s older entries", len(dropped))
        for entry in dropped:
            _unpin_companion(uploads_dir, entry.id)


def load_companion_map(uploads_dir: Path) -> dict[str, str]:
    """Return ``original basename → companion .md`` from the sidecar, if any.

    Name-only view of the raw sidecar, stale entries included; use
    :func:`lookup_companion_mapping` for a fingerprint-verified answer.
    """
    return {original: entry.name for original, entry in _load_state_unlocked(uploads_dir).companions.items()}


def load_companion_entries(uploads_dir: Path) -> dict[str, CompanionEntry]:
    """Return the raw sidecar entries, stale ones included."""
    return _load_state_unlocked(uploads_dir).companions


def load_companion_state(uploads_dir: Path) -> CompanionMapState:
    """Return live rows, eviction tombstones, and the overflow flag."""
    return _load_state_unlocked(uploads_dir)


def coerce_companion_state(
    uploads_dir: Path,
    entries: CompanionMapState | Mapping[str, CompanionEntry] | None = None,
) -> CompanionMapState:
    """Reuse a preloaded sidecar view, or load one from *uploads_dir*.

    A bare mapping is treated as live rows only (no tombstones), matching
    callers that already decided there are no sidecar rows.
    """
    if isinstance(entries, CompanionMapState):
        return entries
    if entries is None:
        return _load_state_unlocked(uploads_dir)
    return CompanionMapState(companions=dict(entries), evicted=(), no_legacy_fallback=False)


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
    entry = _load_state_unlocked(uploads_dir).companions.get(original)
    if entry is None or not companion_entry_matches(uploads_dir, entry):
        return None
    return entry.name


def has_companion_entry(uploads_dir: Path, original: str) -> bool:
    """Return whether the sidecar holds a live or tombstoned row for *original*."""
    if not _is_safe_original(original):
        return False
    state = _load_state_unlocked(uploads_dir)
    return original in state.companions or original in state.evicted


def mapped_companion_names(
    uploads_dir: Path,
    entries: CompanionMapState | Mapping[str, CompanionEntry] | None = None,
) -> set[str]:
    """Return companion basenames whose recorded file still matches its fingerprint.

    Pass a preloaded sidecar view so a listing pass can reuse one read.
    ``entries is None`` loads from disk; an empty mapping means no companions.
    """
    source = coerce_companion_state(uploads_dir, entries).companions
    names: set[str] = set()
    for entry in source.values():
        if companion_entry_matches(uploads_dir, entry):
            names.add(entry.name)
    return names


def _same_mapping_generation(copied: CompanionEntry, current: CompanionEntry) -> bool:
    """Return whether *current* is still the sidecar generation *copied* described.

    Branch rebind must not treat a later same-name convert as the copied row.
    Pinned rows compare identity tokens; unpinned rows compare convert-time
    fingerprints. Name is part of the generation (``report.md`` vs ``report_1.md``).
    """
    if copied.name != current.name:
        return False
    if copied.id or current.id:
        return copied.id is not None and copied.id == current.id
    return copied.size == current.size and copied.mtime_ns == current.mtime_ns and copied.dev == current.dev and copied.ino == current.ino


def _open_regular_nofollow(path: Path, flags: int, *, mode: int = 0o644) -> int:
    """Open *path* no-follow and nonblocking, then fstat the fd as a regular file."""
    has_nofollow = hasattr(os, "O_NOFOLLOW")
    open_flags = flags
    if has_nofollow:
        open_flags |= os.O_NOFOLLOW
    if hasattr(os, "O_NONBLOCK"):
        open_flags |= os.O_NONBLOCK
    if hasattr(os, "O_CLOEXEC"):
        open_flags |= os.O_CLOEXEC
    if hasattr(os, "O_BINARY"):
        open_flags |= os.O_BINARY

    creating = bool(flags & os.O_CREAT)
    if not has_nofollow:
        try:
            pre_open = os.lstat(path)
        except FileNotFoundError:
            if not creating:
                raise
            pre_open = None
        if pre_open is not None and (stat.S_ISLNK(pre_open.st_mode) or not stat.S_ISREG(pre_open.st_mode)):
            raise OSError(errno.ELOOP, "not a regular file", str(path))

    try:
        fd = os.open(path, open_flags, mode) if creating else os.open(path, open_flags)
    except OSError as exc:
        if exc.errno in _UNSAFE_LOCK_OPEN_ERRNOS:
            raise OSError(errno.ELOOP, "cannot open without following a link", str(path)) from exc
        raise

    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode):
            raise OSError(errno.ELOOP, "not a regular file", str(path))
    except Exception:
        os.close(fd)
        raise
    return fd


def _source_copy_fingerprint(st: os.stat_result) -> tuple[int, int, int]:
    """Size/mtime/ctime snapshot used to detect edits during a copy."""
    ctime_ns = getattr(st, "st_ctime_ns", None)
    if ctime_ns is None:
        ctime_ns = int(st.st_ctime * 1_000_000_000)
    return (st.st_size, st.st_mtime_ns, int(ctime_ns))


def _write_all(fd: int, data: bytes) -> None:
    """Write *data* completely; ``os.write`` may return a short count."""
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise OSError(errno.EIO, "short write")
        view = view[written:]


def _apply_copied_mode(dst_fd: int, dst: Path, mode: int) -> None:
    """Restore permission bits on the destination fd, bypassing umask."""
    if hasattr(os, "fchmod"):
        os.fchmod(dst_fd, mode)
        return
    os.chmod(dst, mode)


def _stamp_copied_times(dst_fd: int, dst: Path, src_st: os.stat_result) -> None:
    try:
        os.utime(dst_fd, ns=(src_st.st_atime_ns, src_st.st_mtime_ns))
    except (OSError, AttributeError, TypeError):
        try:
            os.utime(dst, ns=(src_st.st_atime_ns, src_st.st_mtime_ns))
        except OSError:
            pass


def _chmod_unfollowed(path: Path, mode: int) -> None:
    """Set permission bits on *path* without following a symlink."""
    chmod_kwargs = {"follow_symlinks": False} if os.chmod in os.supports_follow_symlinks else {}
    os.chmod(path, mode, **chmod_kwargs)


def _writable_dir_mode(src_mode: int) -> int:
    """Permission bits used while filling a copied directory.

    The destination must stay owner-writable until its children are copied.
    A source mode of ``0555`` would otherwise lock the directory before
    ``data.txt`` can be created, and ``EACCES`` is treated as a skippable copy
    error.
    """
    return stat.S_IMODE(src_mode) | stat.S_IWUSR


def _mkdir_copied_dir(dest_path: Path, src_mode: int) -> None:
    """Create *dest_path* and keep it owner-writable for child copies."""
    dest_path.mkdir(parents=True, exist_ok=True)
    try:
        dest_info = os.lstat(dest_path)
    except OSError:
        return
    if stat.S_ISLNK(dest_info.st_mode) or not stat.S_ISDIR(dest_info.st_mode):
        return
    _chmod_unfollowed(dest_path, _writable_dir_mode(src_mode))


def _finalize_copied_dir_mode(dest_path: Path, src_mode: int) -> None:
    """Restore the source directory's permission bits after children are copied."""
    try:
        dest_info = os.lstat(dest_path)
    except OSError:
        return
    if stat.S_ISLNK(dest_info.st_mode) or not stat.S_ISDIR(dest_info.st_mode):
        return
    _chmod_unfollowed(dest_path, stat.S_IMODE(src_mode))


def _open_fd_count() -> int | None:
    """Return the number of open fds, or None when it cannot be counted."""
    for path in (Path("/dev/fd"), Path("/proc/self/fd")):
        try:
            return max(0, sum(1 for _ in os.scandir(path)) - 1)
        except OSError:
            continue
    return None


def _nofile_soft_limit() -> int | None:
    """Return a finite RLIMIT_NOFILE soft limit, or None when unbounded."""
    try:
        import resource
    except ImportError:
        return None
    try:
        soft, _hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    except (OSError, ValueError):
        return None
    infinity = getattr(resource, "RLIM_INFINITY", -1)
    if soft == infinity or soft < 0 or soft > 1_000_000:
        return None
    return int(soft)


def _copy_fd_hold_limit() -> int:
    """How many source fds this copy may keep, leaving headroom to open more files."""
    soft = _nofile_soft_limit()
    if soft is None:
        return _MAX_HELD_COPY_FDS
    open_count = _open_fd_count() or 0
    remaining = soft - open_count - _COPY_FD_HEADROOM
    return max(0, min(_MAX_HELD_COPY_FDS, remaining))


def _make_copy_hold_root(anchor: Path) -> Path | None:
    """Create a unique hold directory beside *anchor*, outside sandbox mounts."""
    try:
        parent = Path(anchor).resolve().parent
    except OSError:
        parent = Path(anchor).parent
    path = parent / f"{_COPY_HOLD_DIR_PREFIX}{secrets.token_hex(8)}"
    try:
        path.mkdir(parents=True, exist_ok=False)
    except OSError:
        return None
    return path


def _hold_copied_source(
    src: Path,
    src_fd: int,
    src_st: os.stat_result,
    hold_root: Path | None,
    fd_budget: _CopyFdBudget,
) -> _SourceIdentityHold | None:
    """Keep *src_fd*'s inode alive until rebind; prefer a hard link over the fd.

    Returns ``None`` when neither a hard link nor an fd hold is available so
    the caller can copy the file without recording a rebind identity.
    """
    if hold_root is not None:
        path = hold_root / secrets.token_hex(16)
        try:
            os.link(src, path)
            held = os.lstat(path)
            if not stat.S_ISLNK(held.st_mode) and stat.S_ISREG(held.st_mode) and held.st_dev == src_st.st_dev and held.st_ino == src_st.st_ino:
                return _SourceIdentityHold(path=path)
        except OSError:
            pass
        try:
            path.unlink()
        except OSError:
            pass
    if fd_budget.try_take():
        return _SourceIdentityHold(fd=src_fd)
    return None


def release_copied_identities(copied: Mapping[str, CopiedFileIdentity]) -> None:
    """Drop hard-link / fd holds recorded by :func:`copy_user_data_tree`."""
    parents: set[Path] = set()
    for identity in copied.values():
        hold = identity._hold
        if hold is None:
            continue
        if hold.path is not None:
            parents.add(hold.path.parent)
        hold.release()
    for parent in parents:
        try:
            parent.rmdir()
        except OSError:
            pass


def _copy_regular_file_nofollow(
    src: Path,
    dst: Path,
    *,
    hold_root: Path | None = None,
    fd_budget: _CopyFdBudget | None = None,
) -> CopiedFileIdentity | None:
    """Copy *src* to *dst* from a no-follow fd. Skip FIFOs and other non-files.

    Permission bits are restored from the source fd. Each chunk is written to
    completion. A source size/mtime/ctime change while the contents are read
    leaves the destination file but does not return a companion identity. A
    failed write unlinks the partial destination so it cannot be treated as a
    successful copy.
    """
    src_fd = dst_fd = -1
    content_copied = False
    budget = fd_budget if fd_budget is not None else _CopyFdBudget(_copy_fd_hold_limit())
    try:
        src_fd = _open_regular_nofollow(src, os.O_RDONLY)
        src_st = os.fstat(src_fd)
        src_mode = stat.S_IMODE(src_st.st_mode)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst_fd = _open_regular_nofollow(dst, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode=src_mode)
        while True:
            chunk = os.read(src_fd, _COPY_CHUNK_SIZE)
            if not chunk:
                break
            _write_all(dst_fd, chunk)
        _apply_copied_mode(dst_fd, dst, src_mode)
        src_after = os.fstat(src_fd)
        content_copied = True
        if _source_copy_fingerprint(src_st) != _source_copy_fingerprint(src_after):
            return None
        _stamp_copied_times(dst_fd, dst, src_after)
        dst_st = os.fstat(dst_fd)
        hold = _hold_copied_source(src, src_fd, src_st, hold_root, budget)
        if hold is None or not hold.is_live():
            return None
        if hold.fd == src_fd:
            src_fd = -1
        return CopiedFileIdentity(
            source_dev=src_st.st_dev,
            source_ino=src_st.st_ino,
            dest_dev=dst_st.st_dev,
            dest_ino=dst_st.st_ino,
            _hold=hold,
        )
    except OSError as exc:
        if exc.errno in _SKIP_COPY_ERRNOS:
            return None
        raise
    finally:
        if src_fd >= 0:
            os.close(src_fd)
        if dst_fd >= 0:
            os.close(dst_fd)
        if not content_copied:
            try:
                dst.unlink()
            except OSError:
                pass


def copy_user_data_tree(
    src: Path,
    dst: Path,
    *,
    ignore: Callable[[str, list[str]], Iterable[str]] | None = None,
) -> dict[str, CopiedFileIdentity]:
    """Copy *src* to *dst*, recording the source inode actually opened for each file.

    Opens each source file no-follow and nonblocking, then ``fstat``s the fd
    so a FIFO cannot stall the Gateway file-IO thread. Symlinks and non-regular
    files are skipped. Keys are posix paths relative to *dst*. Directory and
    file permission bits are restored from the source. Destination directories
    stay owner-writable until their children are copied, then the source mode
    is applied so a read-only tree still receives its files.

    Returned identities keep the source inode allocated until
    :func:`release_copied_identities`. Call that after
    :func:`rebind_cloned_companion_identities` (or on any path that will not
    rebind) so hard links and fds do not leak. Fd holds are capped so a
    hard-link failure cannot exhaust ``RLIMIT_NOFILE``; files copied without a
    live hold are omitted from the identity map so rebind tombstones them.
    """
    src_root = Path(src)
    dst_root = Path(dst)
    try:
        src_root_st = os.lstat(src_root)
    except OSError:
        src_root_st = None
    src_root_mode = src_root_st.st_mode if src_root_st is not None else 0o755
    _mkdir_copied_dir(dst_root, src_root_mode)
    hold_root = _make_copy_hold_root(src_root)
    fd_budget = _CopyFdBudget(_copy_fd_hold_limit())
    copied: dict[str, CopiedFileIdentity] = {}

    def _walk(src_dir: Path, dst_dir: Path, rel: Path) -> None:
        try:
            names = [entry.name for entry in os.scandir(src_dir)]
        except OSError:
            return
        ignored = set(ignore(str(src_dir), names)) if ignore else set()
        for name in names:
            if name in ignored:
                continue
            source_path = src_dir / name
            dest_path = dst_dir / name
            child_rel = rel / name
            try:
                info = os.lstat(source_path)
            except OSError:
                continue
            if stat.S_ISLNK(info.st_mode):
                continue
            if stat.S_ISDIR(info.st_mode):
                _mkdir_copied_dir(dest_path, info.st_mode)
                _walk(source_path, dest_path, child_rel)
                _finalize_copied_dir_mode(dest_path, info.st_mode)
                continue
            identity = _copy_regular_file_nofollow(source_path, dest_path, hold_root=hold_root, fd_budget=fd_budget)
            if identity is not None:
                copied[child_rel.as_posix()] = identity

    try:
        _walk(src_root, dst_root, Path())
        _finalize_copied_dir_mode(dst_root, src_root_mode)
    except Exception:
        release_copied_identities(copied)
        raise
    finally:
        if hold_root is not None:
            try:
                hold_root.rmdir()
            except OSError:
                pass
    return copied


def copied_upload_identities(copied: Mapping[str, CopiedFileIdentity]) -> dict[str, CopiedFileIdentity]:
    """Return copy identities keyed by uploads basename.

    A copy of ``user-data`` records ``uploads/<name>``. A copy whose root is
    the uploads directory itself records ``<name>`` at the top level. The
    ``uploads/`` key always wins, so a sibling ``user-data/notes.md`` cannot
    replace the identity of ``user-data/uploads/notes.md`` and cause rebind
    to tombstone a still-valid companion.
    """
    out: dict[str, CopiedFileIdentity] = {}
    root_level: dict[str, CopiedFileIdentity] = {}
    for rel, identity in copied.items():
        posix = rel.replace("\\", "/")
        parts = posix.split("/")
        if len(parts) == 2 and parts[0] == "uploads":
            out[parts[1]] = identity
        elif len(parts) == 1:
            root_level[parts[0]] = identity
    for name, identity in root_level.items():
        out.setdefault(name, identity)
    return out


def _claimed_mapping_inode(uploads_dir: Path, entry: CompanionEntry) -> tuple[int, int] | None:
    """Return the inode the mapping still claims, from the pin or live file.

    A pin is conclusive. Unpinned legacy rows must still pass the size/mtime
    check used by :func:`companion_entry_matches`; sidecar ``dev``/``ino``
    numbers alone cannot revive a mapping that an in-place edit already
    invalidated.
    """
    if entry.id:
        pin = companion_identity_path(uploads_dir, entry.id)
        try:
            pin_st = os.lstat(pin)
        except OSError:
            return None
        if stat.S_ISLNK(pin_st.st_mode) or not stat.S_ISREG(pin_st.st_mode):
            return None
        return pin_st.st_dev, pin_st.st_ino
    if not companion_entry_matches(uploads_dir, entry):
        return None
    current = _stat_regular_companion(uploads_dir, entry)
    if current is None:
        return None
    return current.st_dev, current.st_ino


def _copied_dest_still_present(path: Path, identity: CopiedFileIdentity) -> bool:
    try:
        current = os.lstat(path)
    except OSError:
        return False
    if stat.S_ISLNK(current.st_mode) or not stat.S_ISREG(current.st_mode):
        return False
    return current.st_dev == identity.dest_dev and current.st_ino == identity.dest_ino


def rebind_cloned_companion_identities(
    source_uploads: Path,
    dest_uploads: Path,
    *,
    copied_from: Mapping[str, CopiedFileIdentity],
) -> bool:
    """Rebuild destination pins after a :func:`copy_user_data_tree` copy.

    Branch copy clones ``user-data`` (sidecar JSON + Markdown files) but not
    ``.deer-flow-companion-ids`` beside it. Copied companions are new inodes,
    so a copied ``id`` cannot match. Copying the pin files independently also
    fails: those copies are yet more inodes, not hard links to the destination
    Markdown.

    ``copied_from`` is the uploads-basename map from the copy that opened each
    source file. Rebind pins a destination row only when that recorded source
    inode is still the inode the source mapping claims (the pin, or the live
    companion file after the legacy size/mtime check when unpinned), the copy
    identity still holds that source inode, and the
    destination file is still the
    copied inode. Same bytes after the copy are not identity: an independent
    restore can match a later convert. Post-copy path opens are not used, so a
    FIFO planted at the source basename cannot stall the file-IO thread.

    A still-valid dest row gets a new pin and dest inode fields; convert-time
    size/mtime stay as recorded so an in-place edit is still "modified" and a
    later re-upload will not unlink it. Rows whose sidecar generation no longer
    matches, whose copy record is missing, or whose copied source inode is not
    the claimed mapping inode, are moved to ``evicted``. Lock timeout skips
    the rewrite and returns ``False``. Unexpected errors raise.
    """
    try:
        source_resolved = source_uploads.resolve()
        dest_resolved = dest_uploads.resolve()
    except OSError:
        return True
    if source_resolved == dest_resolved or not dest_uploads.is_dir():
        return True
    source_state = load_companion_state(source_uploads)
    if not source_state.companions:
        return True

    try:
        with _map_write_lock(dest_uploads):
            dest_state = _load_state_unlocked(dest_uploads)
            mapping = dict(dest_state.companions)
            if not mapping:
                return True
            new_pins: list[str] = []
            previous_ids: list[str] = []
            stale_originals: list[str] = []

            def _tombstone(name: str) -> None:
                mapping.pop(name, None)
                stale_originals.append(name)

            try:
                for original, dest_entry in list(mapping.items()):
                    source_entry = source_state.companions.get(original)
                    if source_entry is None:
                        if not companion_entry_matches(dest_uploads, dest_entry):
                            _tombstone(original)
                        continue
                    if not _same_mapping_generation(dest_entry, source_entry):
                        _tombstone(original)
                        continue
                    identity = copied_from.get(dest_entry.name)
                    claimed = _claimed_mapping_inode(source_uploads, source_entry)
                    dest_path = dest_uploads / dest_entry.name
                    if identity is None or identity._hold is None or not identity._hold.is_live() or claimed is None or (identity.source_dev, identity.source_ino) != claimed or not _copied_dest_still_present(dest_path, identity):
                        _tombstone(original)
                        continue
                    token = _pin_companion(dest_uploads, dest_path)
                    if token:
                        new_pins.append(token)
                    try:
                        dest_stat = os.lstat(dest_path)
                    except OSError:
                        _unpin_companion(dest_uploads, token)
                        _tombstone(original)
                        continue
                    if dest_stat.st_dev != identity.dest_dev or dest_stat.st_ino != identity.dest_ino:
                        _unpin_companion(dest_uploads, token)
                        _tombstone(original)
                        continue
                    mapping[original] = CompanionEntry(
                        name=dest_entry.name,
                        size=source_entry.size,
                        mtime_ns=source_entry.mtime_ns,
                        dev=dest_stat.st_dev,
                        ino=dest_stat.st_ino,
                        id=token,
                    )
                    if dest_entry.id and dest_entry.id != token:
                        previous_ids.append(dest_entry.id)
                _persist_unlocked(
                    dest_uploads,
                    mapping,
                    evicted=_dedupe_evicted([*dest_state.evicted, *stale_originals], occupied=mapping),
                    no_legacy_fallback=dest_state.no_legacy_fallback,
                )
            except Exception:
                for token in new_pins:
                    _unpin_companion(dest_uploads, token)
                raise
            for token in previous_ids:
                _unpin_companion(dest_uploads, token)
    except CompanionMapLockTimeout:
        logger.warning(
            "Skipping companion-identity rebind; lock busy at %s",
            companion_map_lock_path(dest_uploads),
        )
        return False
    return True


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
            state = _load_state_unlocked(uploads_dir)
            mapping = dict(state.companions)
            previous = mapping.pop(original, None)
            displaced_keys: list[str] = []
            displaced: list[CompanionEntry] = []
            for key, entry in list(mapping.items()):
                if entry.name == companion:
                    displaced_keys.append(key)
                    displaced.append(mapping.pop(key))
            mapping[original] = CompanionEntry(
                name=companion,
                size=companion_stat.st_size,
                mtime_ns=companion_stat.st_mtime_ns,
                dev=companion_stat.st_dev,
                ino=companion_stat.st_ino,
                id=pin_token,
            )
            tombstones = _dedupe_evicted(
                list(state.evicted) + displaced_keys,
                occupied=mapping,
            )
            try:
                _persist_unlocked(
                    uploads_dir,
                    mapping,
                    evicted=tombstones,
                    no_legacy_fallback=state.no_legacy_fallback,
                )
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
            state = _load_state_unlocked(uploads_dir)
            mapping = dict(state.companions)
            stale = [key for key, entry in mapping.items() if (key, entry.name) in wanted]
            if not stale:
                return
            dropped = [mapping.pop(key) for key in stale]
            tombstones = _dedupe_evicted(list(state.evicted) + stale, occupied=mapping)
            _persist_unlocked(
                uploads_dir,
                mapping,
                evicted=tombstones,
                no_legacy_fallback=state.no_legacy_fallback,
            )
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
            state = _load_state_unlocked(uploads_dir)
            mapping = dict(state.companions)
            dropped: list[CompanionEntry] = []
            companion_forgotten: list[str] = []
            if original is not None and original in mapping:
                dropped.append(mapping.pop(original))
            if companion is not None:
                for key, entry in list(mapping.items()):
                    if entry.name == companion:
                        dropped.append(mapping.pop(key))
                        companion_forgotten.append(key)
            tombstones = [name for name in state.evicted if name != original]
            tombstones = _dedupe_evicted(tombstones + companion_forgotten, occupied=mapping)
            if dropped or tombstones != list(state.evicted):
                _persist_unlocked(
                    uploads_dir,
                    mapping,
                    evicted=tombstones,
                    no_legacy_fallback=state.no_legacy_fallback,
                )
                for entry in dropped:
                    _unpin_companion(uploads_dir, entry.id)
    except CompanionMapLockTimeout:
        logger.warning("Skipping companion-map forget; lock busy at %s", companion_map_lock_path(uploads_dir))
