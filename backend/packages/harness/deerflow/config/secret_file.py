"""Exclusive-create helper for small secret files shared by concurrent processes.

Gateway processes that share a runtime home -- uvicorn workers of one host, or
replicas on a shared volume -- cold-start together and may all find a secret
file missing. A read-then-truncating write lets each keep a different value,
so ``read_or_create_secret_file`` publishes with ``O_CREAT | O_EXCL`` instead:
exactly one creator wins and every other process reads the winner's value back.

``O_EXCL`` makes the name visible before its content is written, so a reader
can briefly see an empty (or, for a validated format, incomplete) file; the
helper re-reads for a bounded settle window before deciding. Once the window
passes, an empty file is an abandoned creation -- a crash between create and
write, or an older release's truncating write -- and is replaced, because
nothing can have been signed or encrypted with an empty secret. A non-empty
file that never validates is refused and left untouched: it may be the only
copy of a key that protects stored data.
"""

from __future__ import annotations

import logging
import os
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

logger = logging.getLogger(__name__)

_POLL_INTERVAL_SECONDS = 0.05


class InvalidSecretFileError(ValueError):
    """The secret file holds content that never validated; its content is never included."""


def read_or_create_secret_file(
    path: Path,
    generate: Callable[[], str],
    *,
    validate: Callable[[str], object] | None = None,
    settle_seconds: float = 1.0,
) -> str:
    """Return the secret stored at ``path``, creating it exclusively (mode ``0600``) when absent.

    ``generate`` is called only when this process attempts the create, and its
    value is returned only when this process wins; otherwise the value another
    process published is returned. ``validate`` raises ``ValueError`` for an
    incomplete or malformed value (whitespace is stripped before both checks).
    ``OSError`` from the filesystem propagates.
    """
    path = Path(path)
    deadline: float | None = None
    while True:
        value = _read(path)
        if value is None:
            created = _create_exclusive(path, generate())
            if created is not None:
                return created
            # A peer published first; read its value on the next pass.
            continue
        if value and _is_valid(value, validate):
            return value
        if deadline is None:
            deadline = time.monotonic() + settle_seconds
        if time.monotonic() < deadline:
            time.sleep(_POLL_INTERVAL_SECONDS)
            continue
        if value:
            raise InvalidSecretFileError(f"{path} does not hold a valid secret; restore it from a backup or remove it")
        logger.warning("Replacing the empty secret file %s left by an interrupted creation", path)
        _replace(path, generate())
        deadline = None


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None


def _is_valid(value: str, validate: Callable[[str], object] | None) -> bool:
    if validate is None:
        return True
    try:
        validate(value)
    except ValueError:
        return False
    return True


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        view = view[written:]
    os.fsync(fd)


def _create_exclusive(path: Path, value: str) -> str | None:
    """Publish ``value`` at ``path`` unless it already exists; ``None`` when a peer won."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
    except FileExistsError:
        return None
    try:
        _write_all(fd, value.encode("utf-8"))
    except BaseException:
        # Our own creation never held a usable value: remove it so peers do not
        # wait out the settle window on an empty file.
        os.close(fd)
        path.unlink(missing_ok=True)
        raise
    os.close(fd)
    return value


def _replace(path: Path, value: str) -> None:
    """Atomically replace an abandoned empty file with a fully written ``0600`` one."""
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        try:
            _write_all(fd, value.encode("utf-8"))
        finally:
            os.close(fd)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
