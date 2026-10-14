"""Shared upload management logic.

Pure business logic — no FastAPI/HTTP dependencies.
Both Gateway and Client delegate to these functions.
"""

import errno
import logging
import os
import shutil
import stat
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from datetime import timedelta
from pathlib import Path
from typing import BinaryIO
from urllib.parse import quote

from deerflow.config.paths import VIRTUAL_PATH_PREFIX, get_paths
from deerflow.runtime.user_context import get_effective_user_id
from deerflow.utils.host_paths import windows_incompatible_segment
from deerflow.utils.thread_id import validate_thread_id


class PathTraversalError(ValueError):
    """Raised when a path escapes its allowed base directory."""


class UnsafeUploadPathError(ValueError):
    """Raised when an upload destination is not a safe regular file path."""


logger = logging.getLogger(__name__)

UPLOAD_STAGING_PREFIX = ".upload-"
UPLOAD_STAGING_SUFFIX = ".part"
# Staging files younger than this are treated as in flight by the startup sweep.
# Mirrors the project-document ``.staging`` orphan guard (``projects/trash.py``).
UPLOAD_STAGING_MIN_AGE = timedelta(hours=24)

_MAX_FILENAME_BYTES = 255


def get_uploads_dir(thread_id: str, *, user_id: str | None = None) -> Path:
    """Return the uploads directory path for a thread (no side effects)."""
    validate_thread_id(thread_id)
    return get_paths().sandbox_uploads_dir(thread_id, user_id=user_id or get_effective_user_id())


def ensure_uploads_dir(thread_id: str, *, user_id: str | None = None) -> Path:
    """Return the uploads directory for a thread, creating it if needed."""
    base = get_uploads_dir(thread_id, user_id=user_id)
    base.mkdir(parents=True, exist_ok=True)
    return base


def normalize_filename(filename: str) -> str:
    """Sanitize a filename by extracting its basename.

    Strips any directory components and rejects traversal patterns.

    Args:
        filename: Raw filename from user input (may contain path components).

    Returns:
        Safe filename (basename only).

    Raises:
        ValueError: If filename is empty, unsafe, too long, or uses the reserved staging pattern.
    """
    if not filename:
        raise ValueError("Filename is empty")
    safe = Path(filename).name
    if not safe or safe in {".", ".."}:
        raise ValueError(f"Filename is unsafe: {filename!r}")
    if "\x00" in safe:
        raise ValueError(f"Filename contains NUL: {filename!r}")
    # Reject backslashes — on Linux Path.name keeps them as literal chars,
    # but they indicate a Windows-style path that should be stripped or rejected.
    if "\\" in safe:
        raise ValueError(f"Filename contains backslash: {filename!r}")
    if len(safe.encode("utf-8")) > _MAX_FILENAME_BYTES:
        raise ValueError(f"Filename too long: {len(safe)} chars")
    if is_reserved_upload_filename(safe):
        raise ValueError(f"Filename uses reserved upload staging pattern: {filename!r}")
    reason = windows_incompatible_segment(safe)
    if reason:
        raise ValueError(f"Filename is not portable to Windows: {filename!r} ({reason})")
    return safe


def _fit_utf8_bytes(text: str, budget: int) -> str:
    """Truncate *text* to at most *budget* UTF-8 bytes without splitting a code point."""
    encoded = text.encode("utf-8")
    if len(encoded) <= budget:
        return text
    return encoded[:budget].decode("utf-8", errors="ignore")


def claim_unique_filename(name: str, seen: set[str]) -> str:
    """Generate a case-insensitively unique filename by appending ``_N`` on collision.

    Automatically adds the returned name to *seen* so callers don't need to.

    The deduplicated name stays within the 255-byte filename limit that
    :func:`normalize_filename` enforces: when appending ``_N`` (plus the
    preserved extension) would exceed it, the stem is truncated on a UTF-8
    boundary to make room. Otherwise a maximum-length upload that collides
    would produce a name the filesystem (and a later ``normalize_filename``
    call on the write path) rejects.

    Args:
        name: Candidate filename.
        seen: Set of filenames already claimed (mutated in place).

    Returns:
        A filename not present in *seen* even ignoring case (already added to *seen*).
    """
    claimed = {existing.casefold() for existing in seen}
    if name.casefold() not in claimed:
        seen.add(name)
        return name
    stem, suffix = Path(name).stem, Path(name).suffix
    counter = 1
    while True:
        tag = f"_{counter}"
        budget = _MAX_FILENAME_BYTES - len(tag.encode("utf-8")) - len(suffix.encode("utf-8"))
        if budget < 1:
            # Pathological suffix that leaves no room for a stem; keep the
            # unique tag and fit the rest (stem + suffix tail) around it.
            candidate = _fit_utf8_bytes(stem + suffix, _MAX_FILENAME_BYTES - len(tag.encode("utf-8"))) + tag
        else:
            candidate = f"{_fit_utf8_bytes(stem, budget)}{tag}{suffix}"
        if candidate.casefold() not in claimed:
            break
        counter += 1
    seen.add(candidate)
    return candidate


def is_upload_staging_file(filename: str) -> bool:
    """Return whether *filename* is a transient Gateway upload staging file."""
    return filename.startswith(UPLOAD_STAGING_PREFIX) and filename.endswith(UPLOAD_STAGING_SUFFIX)


def is_reserved_upload_filename(filename: str) -> bool:
    """Check a new basename against the staging namespace, including Win32 aliases.

    Win32 trims trailing dots and spaces and normally ignores case when opening
    a path. Reject those aliases on every host, without changing the name or
    the on-disk staging predicate used by listings and cleanup of existing files.
    """
    return is_upload_staging_file(filename.rstrip(" .").lower())


def validate_path_traversal(path: Path, base: Path) -> None:
    """Verify that *path* is inside *base*.

    Raises:
        PathTraversalError: If a path traversal is detected.
    """
    try:
        path.resolve().relative_to(base.resolve())
    except ValueError:
        raise PathTraversalError("Path traversal detected") from None


def _replacement_destination_is_hardlinked(st: os.stat_result) -> bool:
    """Whether a *replacement* destination shows an untrusted extra hard link.

    Only used on the non-exclusive replacement path, where the module is about to
    overwrite a file it published itself. On POSIX ``st_nlink`` is authoritative,
    so ``st_nlink > 1`` means a second name — possibly outside the uploads tree —
    aliases the destination and overwriting it would mutate that other file.

    Windows cannot answer that question with ``st_nlink``: NTFS leaves the count at
    2 once one of the two names of a published upload is unlinked, and unlinking a
    hard link does not decrement it either. The count there is therefore *always*
    at least 2 for a file this module just published, which made the guard reject
    every legitimate replacement upload (``copy_upload_file_no_symlink``) and made
    the alias-reclaiming sweep unable to clear it. Treat the count as unreliable on
    Windows; the symlink and regular-file guards on the same destination, and the
    ``exclusive`` (first-claim) path used by every untrusted caller, are unchanged.
    """
    return os.name != "nt" and st.st_nlink > 1


def validate_upload_destination(base_dir: Path, filename: str, *, exclusive: bool = False) -> Path:
    """Validate a destination; exclusive creation treats regular hardlinks as collisions."""
    safe_name = normalize_filename(filename)
    dest = base_dir / safe_name

    try:
        st = os.lstat(dest)
    except FileNotFoundError:
        st = None

    if st is not None and not stat.S_ISREG(st.st_mode):
        raise UnsafeUploadPathError(f"Upload destination is not a regular file: {safe_name}")
    if not exclusive and st is not None and _replacement_destination_is_hardlinked(st):
        raise UnsafeUploadPathError(f"Upload destination has multiple links: {safe_name}")

    validate_path_traversal(dest, base_dir)
    return dest


def _iter_upload_dirs(base_dir: Path):
    yield from base_dir.glob("threads/*/user-data/uploads")
    yield from base_dir.glob("users/*/threads/*/user-data/uploads")


def _staging_entry_stat(entry: os.DirEntry[str]) -> os.stat_result:
    # ``os.lstat`` rather than ``entry.stat``: on Windows a ``DirEntry`` stat leaves
    # ``st_nlink`` at zero, and the published-alias rule in the sweep depends on it.
    return os.lstat(entry.path)


def _uploads_dir_entry_stats(uploads_dir: Path) -> dict[str, os.stat_result]:
    """One ``lstat`` per entry, keyed by name.

    Built once per *uploads_dir* so the stale-staging sweep stays linear in the
    number of entries instead of rescanning the directory for every staging file.
    Entries that cannot be stat'ed are omitted: a file that cannot be stat'ed is
    kept, never removed on a guess.
    """
    try:
        with os.scandir(uploads_dir) as entries:
            stats: dict[str, os.stat_result] = {}
            for entry in entries:
                # ``_staging_entry_stat`` uses ``os.lstat`` rather than
                # ``entry.stat``: on Windows a ``DirEntry`` stat reports zero
                # for ``st_dev``/``st_ino`` and leaves ``st_nlink`` at zero
                # (the same limitation the ``st_nlink`` note above records),
                # so it can never match a real inode there.
                try:
                    stats[entry.name] = _staging_entry_stat(entry)
                except FileNotFoundError:
                    continue  # vanished mid-scan; nothing left to clean
                except OSError:
                    logger.warning("Could not stat upload staging file %s; keeping it", entry.path, exc_info=True)
                    continue
            return stats
    except FileNotFoundError:
        return {}  # directory vanished during cleanup
    except OSError:
        logger.warning("Could not scan uploads directory for stale staging files: %s", uploads_dir, exc_info=True)
        return {}


def _staging_name_shares_inode_with_sibling(sibling_stats: dict[str, os.stat_result], name: str, st: os.stat_result) -> bool:
    """Whether another entry in the uploads dir names the same inode as *name*.

    A commit publishes a staged part with ``os.link``, so its bytes carry two names
    for an instant and the staged name is an alias once the final name exists. Any
    sibling sharing ``(st_dev, st_ino)`` marks it as such an alias. Inode
    identity is the portable signal: unlike ``st_nlink`` it stays meaningful on
    Windows, where the count is not decremented when a hard link is removed, so the
    sweep can still reclaim a published alias there instead of mistaking it for an
    in-flight upload and leaving the destination stuck behind the multi-link check.

    A zero ``st_ino`` on either side never matches: on filesystems that cannot
    answer inode identity (FAT/exFAT, some SMB/network shares) every name would
    look like every other name's alias and the sweep would delete in-flight
    uploads at any age. Such a volume falls back to the ``min_age`` guard only.
    """
    if st.st_ino == 0:
        return False
    for sibling_name, sibling_st in sibling_stats.items():
        if sibling_name == name or sibling_st.st_ino == 0:
            continue
        if sibling_st.st_dev == st.st_dev and sibling_st.st_ino == st.st_ino:
            return True
    return False


def cleanup_stale_upload_staging_files(base_dir: Path | str | None = None, *, min_age: timedelta = UPLOAD_STAGING_MIN_AGE) -> int:
    """Remove orphaned Gateway upload staging files left by a hard crash.

    A lone ``.upload-*.part`` is removed only once its mtime is older than
    *min_age*. The uploads directories may live on a volume shared by several
    Gateway replicas, so at startup such a file can belong to an upload another
    replica is still writing; each chunk write refreshes its mtime, which keeps it
    younger than the guard until it is committed or abandoned. "Lone" is decided by
    whether a sibling entry names the same inode rather than by ``st_nlink``, which
    Windows does not decrement when a hard link is removed.

    A staging name that shares an inode with a sibling is removed at any age: the
    commit's ``os.link`` already published those bytes under their final name, so
    the staged name is only an alias left behind by a crash (or a deferred removal
    that never ran). Keeping it would make that destination fail the multi-link
    safety check on the next replacement upload (embedded
    ``DeerFlowClient.upload_files`` goes through ``copy_upload_file_no_symlink``).
    Removing the alias cannot affect an upload in flight: a staged part gains
    its second link only through its own commit.

    A file that cannot be stat'ed is kept, never removed on a guess.
    """
    root = Path(base_dir) if base_dir is not None else get_paths().base_dir
    cutoff = time.time() - min_age.total_seconds()
    removed = 0
    for uploads_dir in _iter_upload_dirs(root):
        if not uploads_dir.is_dir():
            continue
        entry_stats = _uploads_dir_entry_stats(uploads_dir)
        for name, st in entry_stats.items():
            if not is_upload_staging_file(name) or not stat.S_ISREG(st.st_mode):
                continue
            if not _staging_name_shares_inode_with_sibling(entry_stats, name, st) and st.st_mtime >= cutoff:
                continue  # a lone, young part may still be in flight on another replica
            try:
                os.unlink(uploads_dir / name)
                removed += 1
            except FileNotFoundError:
                pass
            except OSError:
                logger.warning("Failed to remove stale upload staging file: %s", uploads_dir / name, exc_info=True)
    return removed


def open_upload_file_no_symlink(base_dir: Path, filename: str, *, exclusive: bool = False) -> tuple[Path, object]:
    """Open an upload destination for safe streaming writes.

    Upload directories may be mounted into local sandboxes. A sandbox process can
    therefore leave a symlink at a future upload filename. Normal ``Path.write_bytes``
    follows that link and can overwrite files outside the uploads directory with
    gateway privileges. This helper rejects symlink destinations using ``O_NOFOLLOW``
    on POSIX. On Windows (which lacks ``O_NOFOLLOW``), it uses dual ``lstat`` checks
    and ``fstat`` validation after ``open()`` to reduce the TOCTOU window; this does
    not eliminate all races but makes exploitation significantly harder. Path-traversal
    validation prevents escapes from *base_dir* in both cases.

    ``exclusive=True`` atomically claims a new filename. An existing regular
    file raises ``FileExistsError`` without truncation so the caller can retry
    under another name. The default retains replacement semantics.
    """
    safe_name = normalize_filename(filename)
    dest = validate_upload_destination(base_dir, safe_name, exclusive=exclusive)
    try:
        st = os.lstat(dest)
    except FileNotFoundError:
        st = None

    has_nofollow = hasattr(os, "O_NOFOLLOW")

    if has_nofollow:
        # POSIX: O_NOFOLLOW makes open() fail with ELOOP if dest is a symlink.
        flags = os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW
        if exclusive:
            flags |= os.O_EXCL
        if hasattr(os, "O_NONBLOCK"):
            flags |= os.O_NONBLOCK

        try:
            fd = os.open(dest, flags, 0o600)
        except OSError as exc:
            if exc.errno in {errno.ELOOP, errno.EISDIR, errno.ENOTDIR, errno.ENXIO, errno.EAGAIN}:
                raise UnsafeUploadPathError(f"Unsafe upload destination: {safe_name}") from exc
            raise

        try:
            opened_stat = os.fstat(fd)
            if not stat.S_ISREG(opened_stat.st_mode) or opened_stat.st_nlink != 1:
                raise UnsafeUploadPathError(f"Upload destination is not an exclusive regular file: {safe_name}")
            os.ftruncate(fd, 0)
            fh = os.fdopen(fd, "wb")
            fd = -1
        finally:
            if fd >= 0:
                os.close(fd)
        return dest, fh

    # Windows: no O_NOFOLLOW available. Uses a second lstat immediately before open()
    # to narrow the TOCTOU window, then fstat after open() as a further defence.
    # Note: a narrow race window remains between the pre-open lstat and open(); the
    # path-traversal check mitigates escapes from base_dir but cannot prevent an
    # attacker who can atomically replace dest with a symlink after the check.
    if not exclusive and st is not None and _replacement_destination_is_hardlinked(st):
        raise UnsafeUploadPathError(f"Upload destination has multiple links: {safe_name}")

    flags = os.O_WRONLY | os.O_CREAT
    if exclusive:
        flags |= os.O_EXCL
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY

    try:
        pre_open_st = os.lstat(dest)
    except FileNotFoundError:
        pre_open_st = None

    if pre_open_st is not None and not stat.S_ISREG(pre_open_st.st_mode):
        raise UnsafeUploadPathError(f"Upload destination is not a regular file: {safe_name}")
    if not exclusive and pre_open_st is not None and _replacement_destination_is_hardlinked(pre_open_st):
        raise UnsafeUploadPathError(f"Upload destination has multiple links: {safe_name}")

    try:
        fd = os.open(dest, flags, 0o600)
    except OSError as exc:
        if exc.errno in {errno.EISDIR, errno.ENOTDIR, errno.ENXIO, errno.EAGAIN}:
            raise UnsafeUploadPathError(f"Unsafe upload destination: {safe_name}") from exc
        raise

    try:
        opened_stat = os.fstat(fd)
        # The exclusive path keeps the strict post-open single-link check on every
        # platform (a just-exclusively-created file must have exactly one link);
        # only the non-exclusive replacement path defers to the Windows-aware guard.
        if not stat.S_ISREG(opened_stat.st_mode) or (exclusive and opened_stat.st_nlink != 1) or (not exclusive and _replacement_destination_is_hardlinked(opened_stat)):
            raise UnsafeUploadPathError(f"Upload destination is not an exclusive regular file: {safe_name}")
        os.ftruncate(fd, 0)
        fh = os.fdopen(fd, "wb")
        fd = -1
    finally:
        if fd >= 0:
            os.close(fd)
    return dest, fh


def write_upload_file_no_symlink(base_dir: Path, filename: str, data: bytes, *, exclusive: bool = False) -> Path:
    """Write upload bytes without following a pre-existing destination symlink."""
    dest, fh = open_upload_file_no_symlink(base_dir, filename, exclusive=exclusive)
    with fh:
        fh.write(data)
    return dest


def _reject_same_file(base_dir: Path, filename: str, src: Path, src_stat: os.stat_result) -> None:
    """Raise :class:`shutil.SameFileError` when *filename* already is *src*.

    Compares identity with ``os.path.samestat`` — what ``copy2`` itself uses —
    rather than the path text, so a hardlink or a differently spelled path to
    the same file is caught too.
    ``lstat`` keeps a planted symlink from being resolved here; the open
    itself rejects that destination.
    """
    dest = base_dir / normalize_filename(filename)
    try:
        dest_stat = os.lstat(dest)
    except (FileNotFoundError, NotADirectoryError):
        return
    if os.path.samestat(src_stat, dest_stat):
        raise shutil.SameFileError(f"{src!r} and {dest!r} are the same file")


@contextmanager
def _open_upload_copy_source(base_dir: Path, filename: str, src: Path, *, snapshot_path: Path | None = None) -> Iterator[tuple[BinaryIO, os.stat_result]]:
    """Hold one source identity and, when requested, capture its bytes once."""
    with open(snapshot_path, "w+b") if snapshot_path is not None else nullcontext() as captured:
        with open(src, "rb") as src_fh:
            src_stat = os.fstat(src_fh.fileno())
            _reject_same_file(base_dir, filename, src, src_stat)
            if captured is None:
                yield src_fh, src_stat
                return
            shutil.copyfileobj(src_fh, captured)
            captured.seek(0)
        # Release the caller's file before publication, so removal during a
        # collision retry is supported on hosts that cannot unlink open files.
        yield captured, src_stat


def copy_upload_file_no_symlink(base_dir: Path, filename: str, src: Path, *, snapshot_path: Path | None = None) -> Path:
    """Copy *src* into an upload destination without following a destination symlink.

    Matches ``shutil.copy2`` for content, permission bits and timestamps, but
    opens the destination through :func:`open_upload_file_no_symlink` and
    applies the metadata to that descriptor, never to the name. The source is
    opened first, so a missing source leaves an existing destination intact.
    Where descriptor-based ``chmod``/``utime`` are unavailable (Windows), the
    destination keeps its default mode and the copy time.

    Copying a file onto itself raises :class:`shutil.SameFileError` as
    ``copy2`` does, and does so before the destination is opened: opening it
    truncates, which would otherwise leave the caller copying an emptied file
    over itself. Re-uploading a file that already sits in the uploads
    directory takes exactly that path.

    With ``snapshot_path``, first capture the opened source there and publish
    those captured bytes. The caller owns this path in a private directory
    outside the sandbox tree and can convert it without reopening ``src``.
    """
    with _open_upload_copy_source(base_dir, filename, src, snapshot_path=snapshot_path) as (captured, src_stat):
        dest, fh = open_upload_file_no_symlink(base_dir, filename)
        with fh:
            shutil.copyfileobj(captured, fh)
            fh.flush()
            if os.chmod in os.supports_fd:
                os.chmod(fh.fileno(), stat.S_IMODE(src_stat.st_mode))
            if os.utime in os.supports_fd:
                os.utime(fh.fileno(), ns=(src_stat.st_atime_ns, src_stat.st_mtime_ns))
    return dest


def _validate_upload_copy_identity(path: Path, expected: os.stat_result) -> None:
    try:
        current = path.lstat()
    except (FileNotFoundError, NotADirectoryError) as exc:
        raise UnsafeUploadPathError(f"Upload copy disappeared: {path.name}") from exc
    if not stat.S_ISREG(current.st_mode) or not os.path.samestat(current, expected):
        raise UnsafeUploadPathError(f"Upload copy changed during publication: {path.name}")


def _publish_upload_copy_source(base_dir: Path, filename: str, source: BinaryIO, src_stat: os.stat_result) -> Path:
    """Publish an opened source without replacing a concurrently claimed name."""
    safe_name = normalize_filename(filename)
    dest = validate_upload_destination(base_dir, safe_name, exclusive=True)
    fd, staging_name = tempfile.mkstemp(prefix=UPLOAD_STAGING_PREFIX, suffix=UPLOAD_STAGING_SUFFIX, dir=base_dir)
    staging = Path(staging_name)
    try:
        with os.fdopen(fd, "wb") as staged_fh:
            shutil.copyfileobj(source, staged_fh)
            staged_fh.flush()
            if os.chmod in os.supports_fd:
                os.chmod(staged_fh.fileno(), stat.S_IMODE(src_stat.st_mode))
            staged_stat = os.fstat(staged_fh.fileno())
            _validate_upload_copy_identity(staging, staged_stat)
            if os.link in os.supports_follow_symlinks:
                os.link(staging, dest, follow_symlinks=False)
            else:
                os.link(staging, dest)
            try:
                _validate_upload_copy_identity(dest, staged_stat)
            except (UnsafeUploadPathError, OSError):
                try:
                    dest.unlink(missing_ok=True)
                except OSError:
                    logger.warning("Failed to remove invalid upload copy: %s", dest, exc_info=True)
                raise
            # Keep staging timestamps fresh until publication, so the orphan
            # sweep cannot remove an in-flight copy of an old source.
            if os.utime in os.supports_fd:
                os.utime(staged_fh.fileno(), ns=(src_stat.st_atime_ns, src_stat.st_mtime_ns))
    finally:
        try:
            staging.unlink(missing_ok=True)
        except OSError:
            logger.warning("Failed to remove upload staging file: %s", staging, exc_info=True)
    return dest


def copy_upload_file_no_replace(base_dir: Path, filename: str, src: Path, *, snapshot_path: Path | None = None) -> Path:
    """Publish a complete copy without replacing a concurrently claimed name.

    Staging in the upload directory makes the final hard link atomic without
    crossing filesystems. Reject staging/published names that no longer identify
    the open copy. Use no-follow links where supported; otherwise identity checks
    narrow, but cannot eliminate, the link-time race. Cleanup is best effort.
    ``snapshot_path`` captures the opened source privately before publication.
    """
    with _open_upload_copy_source(base_dir, filename, src, snapshot_path=snapshot_path) as (source, src_stat):
        return _publish_upload_copy_source(base_dir, filename, source, src_stat)


def publish_upload_copy(base_dir: Path, filename: str, src: Path, *, claim_seed: str, seen_names: set[str], snapshot_path: Path | None = None) -> Path:
    """Retry occupied names using one opened source and its original metadata.

    For conversion, capture once before the retry loop. Every publication attempt
    reads that held private capture rather than reopening the caller's source.
    """
    claim_seed = normalize_filename(claim_seed)
    seen_names.add(filename)
    with _open_upload_copy_source(base_dir, filename, src, snapshot_path=snapshot_path) as (source, src_stat):
        while True:
            try:
                source.seek(0)
                return _publish_upload_copy_source(base_dir, filename, source, src_stat)
            except FileExistsError:
                filename = claim_unique_filename(claim_seed, seen_names)


def apply_upload_sandbox_permits(file_path: os.PathLike[str] | str, extra_mode_bits: int) -> None:
    """Apply sandbox permission bits to an upload, bound to its validated inode.

    The gateway writes uploads as root with ``0o600``. In AIO/Docker sandbox mode
    the sandbox runs as a non-root user on the bind-mounted path, so it needs
    extra group/other (and, for the writable variant, write) bits.

    The change is applied with ``os.fchmod`` on a descriptor opened with
    ``O_NOFOLLOW`` (and ``O_NONBLOCK`` where available) and validated as a
    regular file via ``os.fstat``. That binds the permission change to the exact
    inode that was validated instead of re-resolving the pathname, so a sandbox
    process that swaps the upload for a symlink after validation cannot redirect
    the change to a target outside the uploads directory. ``O_NONBLOCK`` stops a
    swapped-in FIFO from blocking the open before the type check. On platforms
    without ``O_NOFOLLOW``/``os.fchmod`` (Windows) the ``os.chmod`` path (with
    the lstat symlink guard) is retained. A path that disappears or becomes a
    symlink during validation is skipped; other permission errors propagate so
    callers do not report an upload the sandbox still cannot access.
    """
    try:
        file_stat = os.lstat(file_path)
    except (FileNotFoundError, NotADirectoryError):
        return
    if stat.S_ISLNK(file_stat.st_mode):
        return

    if hasattr(os, "O_NOFOLLOW") and hasattr(os, "fchmod"):
        open_flags = os.O_RDONLY | os.O_NOFOLLOW
        if hasattr(os, "O_NONBLOCK"):
            # The uploads directory is sandbox-writable, so the sandbox can swap
            # the just-written file for a FIFO before this open. Without
            # O_NONBLOCK an O_RDONLY open on a FIFO blocks in the kernel waiting
            # for a writer (before the fstat regular-file check below), hanging
            # ingestion and occupying a Gateway file-IO executor thread that
            # coroutine cancellation cannot interrupt. O_NONBLOCK returns
            # immediately; the S_ISREG check then skips the non-regular inode.
            open_flags |= os.O_NONBLOCK
        try:
            fd = os.open(file_path, open_flags)
        except OSError as exc:
            # The path disappeared, stopped resolving, or became a symlink
            # after lstat. Leave permissions untouched for these expected
            # replacement races, but surface operational failures such as
            # EACCES so callers cannot report an unreadable upload as ready.
            if exc.errno in {errno.ENOENT, errno.ENOTDIR, errno.ELOOP}:
                return
            raise
        try:
            opened = os.fstat(fd)
            if not stat.S_ISREG(opened.st_mode):
                return
            os.fchmod(fd, stat.S_IMODE(opened.st_mode) | extra_mode_bits)
        finally:
            os.close(fd)
        return

    # Windows / platforms without O_NOFOLLOW + fchmod: retain the lstat-guarded
    # chmod fallback. Expected replacement races are no-ops; permission errors
    # must still reach the caller.
    try:
        os.chmod(file_path, stat.S_IMODE(file_stat.st_mode) | extra_mode_bits)
    except OSError as exc:
        if exc.errno in {errno.ENOENT, errno.ENOTDIR, errno.ELOOP}:
            return
        raise


def list_files_in_dir(directory: Path) -> dict:
    """List files (not directories) in *directory*.

    Listing is best-effort under concurrent deletion: vanished entries are
    omitted, and a directory that disappears or becomes a non-directory
    returns the entries collected so far. Operational errors still propagate.

    Args:
        directory: Directory to scan.

    Returns:
        Dict with "files" list (sorted by name) and "count".
        Each file entry has ``size`` as *int* (bytes).  Call
        :func:`enrich_file_listing` to add virtual / artifact URLs.
    """
    if not directory.is_dir():
        return {"files": [], "count": 0}

    files = []
    try:
        with os.scandir(directory) as entries:
            for entry in sorted(entries, key=lambda e: e.name):
                if is_upload_staging_file(entry.name):
                    continue
                if not entry.is_file(follow_symlinks=False):
                    continue
                try:
                    st = entry.stat(follow_symlinks=False)
                except OSError as exc:
                    # The entry can vanish between the scandir sweep and this stat
                    # (the DELETE endpoint via delete_file_safe, possibly from
                    # another replica, or a sandbox process removing its own file).
                    # Same policy as the chmod path above: skip expected races,
                    # surface operational errors like EACCES.
                    if exc.errno in {errno.ENOENT, errno.ENOTDIR, errno.ELOOP}:
                        logger.debug("Skipped upload entry that vanished mid-scan: %s", entry.path)
                        continue
                    raise
                files.append(
                    {
                        "filename": entry.name,
                        "size": st.st_size,
                        "path": entry.path,
                        "extension": Path(entry.name).suffix,
                        "modified": st.st_mtime,
                    }
                )
    except (FileNotFoundError, NotADirectoryError):
        # Thread deletion or a sandbox process may remove or replace the
        # directory after the is_dir() check. Keep the collected snapshot.
        logger.debug("Uploads directory vanished mid-scan, keeping partial snapshot of %d entries: %s", len(files), directory)
    return {"files": files, "count": len(files)}


def delete_file_safe(base_dir: Path, filename: str) -> dict:
    """Delete a file inside *base_dir* after path-traversal validation.

    Only the requested file is removed. A converted document's Markdown
    companion is left in place: conversion names it after the document's stem
    and falls back to a ``_N`` suffix when that name is taken, so the ``.md``
    beside a document may belong to another document sharing that stem, or to
    the user. Removing it on that guess destroyed the wrong file. It stays
    listed and can be deleted on its own (issue #5672).

    Only regular files are deleted. Upload directories may be mounted into
    local sandboxes, so a sandbox process can plant a symlink under an upload
    name; following it would delete the upload it aliases instead. Such
    entries are reported as not found, matching ``list_files_in_dir``.

    Args:
        base_dir: Directory containing the file.
        filename: Name of file to delete.

    Returns:
        Dict with success and message.

    Raises:
        FileNotFoundError: If the file does not exist.
        PathTraversalError: If path traversal is detected.
    """
    file_path = base_dir / filename
    validate_path_traversal(file_path, base_dir)

    if file_path.is_symlink() or not file_path.is_file():
        raise FileNotFoundError(f"File not found: {filename}")

    file_path.unlink()

    return {"success": True, "message": f"Deleted {filename}"}


def upload_artifact_url(thread_id: str, filename: str) -> str:
    """Build the artifact URL for a file in a thread's uploads directory.

    *filename* is percent-encoded so that spaces, ``#``, ``?`` etc. are safe.
    """
    return f"/api/threads/{thread_id}/artifacts{VIRTUAL_PATH_PREFIX}/uploads/{quote(filename, safe='')}"


def upload_virtual_path(filename: str) -> str:
    """Build the virtual path for a file in the uploads directory."""
    return f"{VIRTUAL_PATH_PREFIX}/uploads/{filename}"


def output_artifact_url(thread_id: str, filename: str) -> str:
    """Build the artifact URL for a file in a thread's outputs directory.

    *filename* is percent-encoded so that spaces, ``#``, ``?`` etc. are safe.
    """
    return f"/api/threads/{thread_id}/artifacts{VIRTUAL_PATH_PREFIX}/outputs/{quote(filename, safe='')}"


def output_virtual_path(filename: str) -> str:
    """Build the virtual path for a file in the outputs directory."""
    return f"{VIRTUAL_PATH_PREFIX}/outputs/{filename}"


def enrich_file_listing(result: dict, thread_id: str) -> dict:
    """Add virtual paths and artifact URLs on a listing result.

    Mutates *result* in place and returns it for convenience.
    """
    for f in result["files"]:
        filename = f["filename"]
        f["virtual_path"] = upload_virtual_path(filename)
        f["artifact_url"] = upload_artifact_url(thread_id, filename)
    return result
