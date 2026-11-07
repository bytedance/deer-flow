"""Atomic byte publication with normal file-creation permissions."""

from __future__ import annotations

import logging
import os
import stat
from contextlib import suppress
from pathlib import Path
from uuid import uuid4

from deerflow.utils.file_revision_metadata import preserve_revision_metadata

logger = logging.getLogger(__name__)


def cleanup_failed_atomic_write(temporary: Path, fd: int | None = None) -> None:
    """Release an owned temporary without replacing the caller's outcome.

    Pass *fd* only while the raw descriptor is still owned by the caller;
    successful ``fdopen`` transfers that ownership to the file object.
    An explicitly transferred duplicate descriptor is also caller-owned.
    Also use this to discard staging after a publication decision. Filesystem
    and logging-handler errors remain independent best-effort steps.
    """
    # Cleanup and diagnostics are best-effort: keep the original error
    # and attempt unlink even if closing an untransferred descriptor fails.
    if fd is not None:
        try:
            os.close(fd)
        except OSError:
            with suppress(Exception):
                logger.warning("Failed to close temporary output descriptor for %s", temporary, exc_info=True)
    try:
        temporary.unlink(missing_ok=True)
    except OSError:
        with suppress(Exception):
            logger.warning("Failed to remove temporary output file %s", temporary, exc_info=True)


def _clear_destination_read_only(path: Path, mode: int | None) -> bool:
    """Clear a Windows read-only attribute blocking ``os.replace`` over *path*.

    POSIX rename ignores the target's permission bits; Windows refuses to
    replace a read-only file. Only the destination itself is cleared, never a
    symlink's target (the replacement discards the link), matching
    ``projects/trash.py`` and ``config/paths.py``. Returns ``True`` when the
    attribute was cleared, so the caller reapplies *mode* afterwards.
    """
    if os.name != "nt" or mode is None or mode & stat.S_IWRITE:
        return False
    try:
        if stat.S_ISLNK(os.lstat(path).st_mode):
            return False
        os.chmod(path, mode | stat.S_IWRITE)
    except OSError:
        return False
    return True


def publish_bytes_atomically(path: Path, content: bytes, *, temporary_prefix: str | None = None, preserve_metadata_from: int | None = None) -> None:
    """Replace *path* with complete bytes, preserving its existing mode.

    New files use ``0666 & ~umask``, like ``Path.write_bytes``, so captures
    remain readable through sandbox mounts under the usual ``0022`` umask.
    A hidden, exclusively created sibling keeps partial writes away from the
    final path. Failure before replacement leaves the previous file intact,
    including a read-only attribute the replacement had to clear.
    A short temporary_prefix supports destinations near the filename limit.
    Linux/macOS callers may supply an already-open source descriptor to preserve
    access controls before writing content; ownership stays with the caller.
    """
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except FileNotFoundError:
        mode = None

    # Windows refuses to replace a read-only destination *and* to unlink a
    # sibling that inherited that mode, so the preserved mode is copied after
    # publication there; POSIX copies it onto the sibling before the rename.
    mode_after_publish = os.name == "nt" and mode is not None and preserve_metadata_from is None

    prefix = temporary_prefix if temporary_prefix is not None else f".{path.name}."
    temporary = path.with_name(f"{prefix}{uuid4().hex}.tmp")
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0)
    # Let the kernel apply umask; reading it via os.umask would mutate
    # process-global state while other threads may be creating files.
    fd = os.open(temporary, flags, 0o600 if preserve_metadata_from is not None else 0o666)
    cleared_read_only = False
    try:
        handle = os.fdopen(fd, "wb")
        fd = None  # The file object now owns the descriptor.
        with handle:
            if preserve_metadata_from is not None:
                preserve_revision_metadata(preserve_metadata_from, handle.fileno())
            handle.write(content)
            handle.flush()
            if mode is not None and preserve_metadata_from is None and not mode_after_publish:
                os.fchmod(handle.fileno(), mode)
            os.fsync(handle.fileno())
        cleared_read_only = _clear_destination_read_only(path, mode)
        os.replace(temporary, path)
        if mode_after_publish or cleared_read_only:
            try:
                os.chmod(path, mode)
            except OSError:
                with suppress(Exception):
                    logger.warning("Failed to restore permissions on %s", path, exc_info=True)
    except BaseException:
        if cleared_read_only:
            # The replacement failed after the attribute was cleared; give the
            # operator's mode back without masking the publication error.
            with suppress(Exception):
                os.chmod(path, mode)
        cleanup_failed_atomic_write(temporary, fd)
        raise
