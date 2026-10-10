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
nothing can have been signed or encrypted with an empty secret. A rename is
last-writer-wins, so the replacement is single-winner too: the process that
exclusively creates ``<name>.replacing`` writes the new value there and renames
it over the empty file, which publishes the value and releases the claim in one
step; every other process waits for that value. A non-empty file that never
validates is refused and left untouched: it may be the only copy of a key that
protects stored data.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from pathlib import Path

logger = logging.getLogger(__name__)

_POLL_INTERVAL_SECONDS = 0.05
# How long to wait on a peer's replacement claim before declaring it abandoned.
_CLAIM_WAIT_SECONDS = 10.0


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
    claim_deadline: float | None = None
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
        if _replace_abandoned(path, generate):
            # Read back what we published, or what a peer published first.
            continue
        # A peer holds the replacement claim: wait for its value, bounded so a
        # replacer that crashed mid-claim cannot block startup forever.
        if claim_deadline is None:
            claim_deadline = time.monotonic() + max(_CLAIM_WAIT_SECONDS, settle_seconds)
        if time.monotonic() >= claim_deadline:
            raise InvalidSecretFileError(f"{path} is empty and {_claim_path(path)} was left by an interrupted replacement; remove both so a new secret can be generated")
        time.sleep(_POLL_INTERVAL_SECONDS)


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


def _claim_path(path: Path) -> Path:
    return path.with_name(f"{path.name}.replacing")


def _replace_abandoned(path: Path, generate: Callable[[], str]) -> bool:
    """Replace the abandoned empty file at ``path`` unless a peer already is.

    Returns ``False`` only when a peer holds the replacement claim. Holding the
    claim excludes every other replacer until our rename publishes the value
    (and removes the claim), and the file is re-read after claiming, so a
    process that saw the empty file before a peer's replacement landed backs
    off instead of overwriting the value peers may already have returned.
    """
    claim = _claim_path(path)
    try:
        fd = os.open(claim, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
    except FileExistsError:
        return False
    published = False
    try:
        try:
            if _read(path) != "":
                # A peer's replacement (or creation) landed before our claim.
                return True
            logger.warning("Replacing the empty secret file %s left by an interrupted creation", path)
            _write_all(fd, generate().encode("utf-8"))
        finally:
            os.close(fd)
        os.replace(claim, path)
        published = True
        return True
    finally:
        if not published:
            claim.unlink(missing_ok=True)
