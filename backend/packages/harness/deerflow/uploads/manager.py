"""Shared upload management logic.

Pure business logic — no FastAPI/HTTP dependencies.
Both Gateway and Client delegate to these functions.
"""

import errno
import logging
import os
import shutil
import stat
from pathlib import Path
from urllib.parse import quote

from deerflow.config.paths import VIRTUAL_PATH_PREFIX, get_paths
from deerflow.runtime.user_context import get_effective_user_id
from deerflow.utils.thread_id import validate_thread_id


class PathTraversalError(ValueError):
    """Raised when a path escapes its allowed base directory."""


class UnsafeUploadPathError(ValueError):
    """Raised when an upload destination is not a safe regular file path."""


logger = logging.getLogger(__name__)

UPLOAD_STAGING_PREFIX = ".upload-"
UPLOAD_STAGING_SUFFIX = ".part"

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
        ValueError: If filename is empty or resolves to a traversal pattern.
    """
    if not filename:
        raise ValueError("Filename is empty")
    safe = Path(filename).name
    if not safe or safe in {".", ".."}:
        raise ValueError(f"Filename is unsafe: {filename!r}")
    # Reject backslashes — on Linux Path.name keeps them as literal chars,
    # but they indicate a Windows-style path that should be stripped or rejected.
    if "\\" in safe:
        raise ValueError(f"Filename contains backslash: {filename!r}")
    if len(safe.encode("utf-8")) > _MAX_FILENAME_BYTES:
        raise ValueError(f"Filename too long: {len(safe)} chars")
    return safe


def _fit_utf8_bytes(text: str, budget: int) -> str:
    """Truncate *text* to at most *budget* UTF-8 bytes without splitting a code point."""
    encoded = text.encode("utf-8")
    if len(encoded) <= budget:
        return text
    return encoded[:budget].decode("utf-8", errors="ignore")


def claim_unique_filename(name: str, seen: set[str]) -> str:
    """Generate a unique filename by appending ``_N`` suffix on collision.

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
        A filename not present in *seen* (already added to *seen*).
    """
    if name not in seen:
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
        if candidate not in seen:
            break
        counter += 1
    seen.add(candidate)
    return candidate


def is_upload_staging_file(filename: str) -> bool:
    """Return whether *filename* is a transient Gateway upload staging file."""
    return filename.startswith(UPLOAD_STAGING_PREFIX) and filename.endswith(UPLOAD_STAGING_SUFFIX)


def validate_path_traversal(path: Path, base: Path) -> None:
    """Verify that *path* is inside *base*.

    Raises:
        PathTraversalError: If a path traversal is detected.
    """
    try:
        path.resolve().relative_to(base.resolve())
    except ValueError:
        raise PathTraversalError("Path traversal detected") from None


def validate_upload_destination(base_dir: Path, filename: str) -> Path:
    """Validate an upload destination without mutating an existing file."""
    safe_name = normalize_filename(filename)
    dest = base_dir / safe_name

    try:
        st = os.lstat(dest)
    except FileNotFoundError:
        st = None

    if st is not None and not stat.S_ISREG(st.st_mode):
        raise UnsafeUploadPathError(f"Upload destination is not a regular file: {safe_name}")
    if st is not None and st.st_nlink > 1:
        raise UnsafeUploadPathError(f"Upload destination has multiple links: {safe_name}")

    validate_path_traversal(dest, base_dir)
    return dest


def _iter_upload_dirs(base_dir: Path):
    yield from base_dir.glob("threads/*/user-data/uploads")
    yield from base_dir.glob("users/*/threads/*/user-data/uploads")


def cleanup_stale_upload_staging_files(base_dir: Path | str | None = None) -> int:
    """Remove orphaned Gateway upload staging files left by a hard crash."""
    root = Path(base_dir) if base_dir is not None else get_paths().base_dir
    removed = 0
    for uploads_dir in _iter_upload_dirs(root):
        if not uploads_dir.is_dir():
            continue
        try:
            with os.scandir(uploads_dir) as entries:
                for entry in entries:
                    if not is_upload_staging_file(entry.name) or not entry.is_file(follow_symlinks=False):
                        continue
                    try:
                        os.unlink(entry.path)
                        removed += 1
                    except FileNotFoundError:
                        pass
                    except OSError:
                        logger.warning("Failed to remove stale upload staging file: %s", entry.path, exc_info=True)
        except FileNotFoundError:
            continue
        except OSError:
            logger.warning("Failed to scan uploads directory for stale staging files: %s", uploads_dir, exc_info=True)
    return removed


def open_upload_file_no_symlink(base_dir: Path, filename: str) -> tuple[Path, object]:
    """Open an upload destination for safe streaming writes.

    Upload directories may be mounted into local sandboxes. A sandbox process can
    therefore leave a symlink at a future upload filename. Normal ``Path.write_bytes``
    follows that link and can overwrite files outside the uploads directory with
    gateway privileges. This helper rejects symlink destinations using ``O_NOFOLLOW``
    on POSIX. On Windows (which lacks ``O_NOFOLLOW``), it uses dual ``lstat`` checks
    and ``fstat`` validation after ``open()`` to reduce the TOCTOU window; this does
    not eliminate all races but makes exploitation significantly harder. Path-traversal
    validation prevents escapes from *base_dir* in both cases.
    """
    safe_name = normalize_filename(filename)
    dest = validate_upload_destination(base_dir, safe_name)
    try:
        st = os.lstat(dest)
    except FileNotFoundError:
        st = None

    has_nofollow = hasattr(os, "O_NOFOLLOW")

    if has_nofollow:
        # POSIX: O_NOFOLLOW makes open() fail with ELOOP if dest is a symlink.
        flags = os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW
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
    if st is not None and st.st_nlink > 1:
        raise UnsafeUploadPathError(f"Upload destination has multiple links: {safe_name}")

    flags = os.O_WRONLY | os.O_CREAT
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY

    try:
        pre_open_st = os.lstat(dest)
    except FileNotFoundError:
        pre_open_st = None

    if pre_open_st is not None and not stat.S_ISREG(pre_open_st.st_mode):
        raise UnsafeUploadPathError(f"Upload destination is not a regular file: {safe_name}")
    if pre_open_st is not None and pre_open_st.st_nlink > 1:
        raise UnsafeUploadPathError(f"Upload destination has multiple links: {safe_name}")

    try:
        fd = os.open(dest, flags, 0o600)
    except OSError as exc:
        if exc.errno in {errno.EISDIR, errno.ENOTDIR, errno.ENXIO, errno.EAGAIN}:
            raise UnsafeUploadPathError(f"Unsafe upload destination: {safe_name}") from exc
        raise

    try:
        opened_stat = os.fstat(fd)
        if not stat.S_ISREG(opened_stat.st_mode) or opened_stat.st_nlink > 1:
            raise UnsafeUploadPathError(f"Upload destination is not an exclusive regular file: {safe_name}")
        os.ftruncate(fd, 0)
        fh = os.fdopen(fd, "wb")
        fd = -1
    finally:
        if fd >= 0:
            os.close(fd)
    return dest, fh


def write_upload_file_no_symlink(base_dir: Path, filename: str, data: bytes) -> Path:
    """Write upload bytes without following a pre-existing destination symlink."""
    dest, fh = open_upload_file_no_symlink(base_dir, filename)
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


def copy_upload_file_no_symlink(base_dir: Path, filename: str, src: Path) -> Path:
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
    """
    with open(src, "rb") as src_fh:
        src_stat = os.fstat(src_fh.fileno())
        _reject_same_file(base_dir, filename, src, src_stat)
        dest, fh = open_upload_file_no_symlink(base_dir, filename)
        with fh:
            shutil.copyfileobj(src_fh, fh)
            fh.flush()
            if os.chmod in os.supports_fd:
                os.chmod(fh.fileno(), stat.S_IMODE(src_stat.st_mode))
            if os.utime in os.supports_fd:
                os.utime(fh.fileno(), ns=(src_stat.st_atime_ns, src_stat.st_mtime_ns))
    return dest


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
    with os.scandir(directory) as entries:
        for entry in sorted(entries, key=lambda e: e.name):
            if is_upload_staging_file(entry.name):
                continue
            if not entry.is_file(follow_symlinks=False):
                continue
            st = entry.stat(follow_symlinks=False)
            files.append(
                {
                    "filename": entry.name,
                    "size": st.st_size,
                    "path": entry.path,
                    "extension": Path(entry.name).suffix,
                    "modified": st.st_mtime,
                }
            )
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
