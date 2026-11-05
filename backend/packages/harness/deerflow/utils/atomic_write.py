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


def publish_bytes_atomically(path: Path, content: bytes, *, temporary_prefix: str | None = None, preserve_metadata_from: int | None = None) -> None:
    """Replace *path* with complete bytes, preserving its existing mode.

    New files use ``0666 & ~umask``, like ``Path.write_bytes``, so captures
    remain readable through sandbox mounts under the usual ``0022`` umask.
    A hidden, exclusively created sibling keeps partial writes away from the
    final path. Failure before replacement leaves the previous file intact.
    A short temporary_prefix supports destinations near the filename limit.
    Linux/macOS callers may supply an already-open source descriptor to preserve
    access controls before writing content; ownership stays with the caller.
    """
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except FileNotFoundError:
        mode = None

    prefix = temporary_prefix if temporary_prefix is not None else f".{path.name}."
    temporary = path.with_name(f"{prefix}{uuid4().hex}.tmp")
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0)
    # Let the kernel apply umask; reading it via os.umask would mutate
    # process-global state while other threads may be creating files.
    fd = os.open(temporary, flags, 0o600 if preserve_metadata_from is not None else 0o666)
    try:
        handle = os.fdopen(fd, "wb")
        fd = None  # The file object now owns the descriptor.
        with handle:
            if preserve_metadata_from is not None:
                preserve_revision_metadata(preserve_metadata_from, handle.fileno())
            handle.write(content)
            handle.flush()
            if mode is not None and preserve_metadata_from is None:
                if os.name == "nt":
                    os.chmod(temporary, mode)
                else:
                    os.fchmod(handle.fileno(), mode)
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        cleanup_failed_atomic_write(temporary, fd)
        raise
