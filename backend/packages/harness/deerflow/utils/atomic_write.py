"""Atomic byte publication with normal file-creation permissions."""

from __future__ import annotations

import logging
import os
import stat
from pathlib import Path
from uuid import uuid4

logger = logging.getLogger(__name__)


def publish_bytes_atomically(path: Path, content: bytes, *, overwrite: bool = True) -> None:
    """Publish complete bytes, replacing *path* and preserving its mode by default.

    New files use ``0666 & ~umask``, like ``Path.write_bytes``, so captures
    remain readable through sandbox mounts under the usual ``0022`` umask.
    A hidden, exclusively created sibling keeps partial writes away from the
    final path. Failure before replacement leaves the previous file intact.

    With ``overwrite=False``, publish the completed sibling through an atomic
    hard link instead. An occupied destination raises ``FileExistsError`` so
    callers can select another name, including across processes. Filesystems
    without hard-link support fail rather than falling back to replacement.
    Once linked, temporary cleanup is best-effort: its failure cannot undo the
    successful publication or cause the caller to report it as failed.
    """
    mode = None
    if overwrite:
        try:
            mode = stat.S_IMODE(path.stat().st_mode)
        except FileNotFoundError:
            pass

    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0)
    # Let the kernel apply umask; reading it via os.umask would mutate
    # process-global state while other threads may be creating files.
    fd = os.open(temporary, flags, 0o666)
    try:
        handle = os.fdopen(fd, "wb")
        fd = None  # The file object now owns the descriptor.
        with handle:
            handle.write(content)
            handle.flush()
            if mode is not None:
                if os.name == "nt":
                    os.chmod(temporary, mode)
                else:
                    os.fchmod(handle.fileno(), mode)
            os.fsync(handle.fileno())
        if overwrite:
            os.replace(temporary, path)
        else:
            os.link(temporary, path)
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                logger.warning("Published %s but could not remove temporary capture %s", path, temporary, exc_info=True)
    except BaseException:
        if fd is not None:
            os.close(fd)
        temporary.unlink(missing_ok=True)
        raise
