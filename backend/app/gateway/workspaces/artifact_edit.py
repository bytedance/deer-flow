"""Bounded mounted-file publication, called under live private-thread SQL fencing.

Use directory descriptors so a replaced parent symlink cannot redirect writes.
This does not provide remote sandbox synchronization or crash reconciliation.
"""

import errno
import logging
import os
import stat
import uuid
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

from fastapi import HTTPException

logger = logging.getLogger(__name__)


def _identity(metadata):
    return (metadata.st_dev, metadata.st_ino, metadata.st_size, metadata.st_mtime_ns, metadata.st_ctime_ns, metadata.st_nlink)


@contextmanager
def _parent_descriptor(parent):
    if not parent.is_absolute() or not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY") or os.open not in os.supports_dir_fd:
        raise HTTPException(status_code=503, detail="Secure workspace file editing is unavailable on this platform")
    descriptor = os.open(parent.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for component in parent.parts[1:]:
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        yield descriptor
    finally:
        os.close(descriptor)


def replace_mounted_artifact(outputs_dir: Path, relative_path: str, updated: bytes, *, expected_sha256: str, max_bytes: int, temp_prefix: str):
    """Validate and atomically replace one existing file relative to a pinned parent."""
    import hashlib

    parts = PurePosixPath(relative_path).parts
    if not parts or any(part in ("", ".", "..", "/") for part in parts) or PurePosixPath(relative_path).is_absolute():
        raise HTTPException(status_code=400, detail="Invalid output artifact path")
    parent = outputs_dir.joinpath(*parts[:-1])
    publication_started = False
    try:
        with _parent_descriptor(parent) as directory:
            source = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0), dir_fd=directory)
            temp_name = None
            temp_descriptor = None
            try:
                before = os.fstat(source)
                if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                    raise HTTPException(status_code=415, detail="Only ordinary output files can be edited")
                if before.st_size > max_bytes:
                    raise HTTPException(status_code=413, detail="Artifact is too large to edit")
                chunks = []
                remaining = max_bytes + 1
                while remaining:
                    block = os.read(source, min(64 * 1024, remaining))
                    if not block:
                        break
                    chunks.append(block)
                    remaining -= len(block)
                current = b"".join(chunks)
                if len(current) > max_bytes:
                    raise HTTPException(status_code=413, detail="Artifact is too large to edit")
                if b"\x00" in current:
                    raise HTTPException(status_code=415, detail="Binary artifacts cannot be edited")
                try:
                    current.decode("utf-8")
                except UnicodeDecodeError:
                    raise HTTPException(status_code=415, detail="Only UTF-8 text artifacts can be edited") from None
                if _identity(os.fstat(source)) != _identity(before) or hashlib.sha256(current).hexdigest() != expected_sha256:
                    raise HTTPException(status_code=412, detail="Artifact changed since it was opened")
                candidate_name = temp_prefix + uuid.uuid4().hex
                temp_descriptor = os.open(candidate_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
                temp_name = candidate_name
                if hasattr(os, "fchown"):
                    try:
                        os.fchown(temp_descriptor, before.st_uid, before.st_gid)
                    except OSError:
                        pass  # Same owner/group best effort, matching the native editor.
                os.fchmod(temp_descriptor, stat.S_IMODE(before.st_mode) | 0o660)
                with os.fdopen(temp_descriptor, "wb") as handle:
                    temp_descriptor = None
                    handle.write(updated)
                    handle.flush()
                    os.fsync(handle.fileno())
                if _identity(os.stat(parts[-1], dir_fd=directory, follow_symlinks=False)) != _identity(before):
                    raise HTTPException(status_code=412, detail="Artifact changed since it was opened")
                publication_started = True
                os.replace(temp_name, parts[-1], src_dir_fd=directory, dst_dir_fd=directory)
            finally:
                os.close(source)
                if temp_descriptor is not None:
                    os.close(temp_descriptor)
                if temp_name is not None:
                    try:
                        os.unlink(temp_name, dir_fd=directory)
                    except FileNotFoundError:
                        pass
                    except OSError as exc:
                        logger.error("Failed to clean workspace edit temporary file (%s)", type(exc).__name__)
    except OSError as exc:
        if publication_started:
            # Remote filesystems can lose the acknowledgement after replacement.
            # Do not roll back or retry an outcome we cannot establish.
            raise HTTPException(status_code=503, detail="Artifact update could not be confirmed; reload before saving again") from None
        if isinstance(exc, FileNotFoundError):
            raise HTTPException(status_code=404, detail="Artifact not found") from None
        if exc.errno in (errno.ELOOP, errno.ENOTDIR):
            raise HTTPException(status_code=415, detail="Unsafe output artifact path") from None
        raise HTTPException(status_code=503, detail="Artifact filesystem is unavailable") from None
