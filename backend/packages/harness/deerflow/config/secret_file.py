"""Exclusive-create helper for small secret files shared by concurrent processes.

Gateway processes that share a runtime home -- uvicorn workers of one host, or
replicas on a shared volume -- cold-start together and may all find a secret
file missing. A read-then-truncating write lets each keep a different value,
so ``read_or_create_secret_file`` publishes exclusively instead: exactly one
creator wins and every other process reads the winner's value back.

A creator writes and syncs the whole value into a private temporary file first
and then hard-links it to the final name, which fails if the name exists. The
name therefore never appears empty or half-written, however long a creator
stalls, and a creator that fails only ever removes its own temporary file.
Filesystems without hard links (SMB shares) publish through the replacement
claim described below instead.

An empty or incomplete file can still come from an older release (which
created the name before writing it) or from external tampering. The helper
re-reads it for a bounded settle window; a non-empty file that never validates
is refused and left untouched, because it may be the only copy of a key that
protects stored data. An empty one is abandoned -- nothing can have been
signed or encrypted with an empty secret -- and is replaced. A rename is
last-writer-wins, so replacement is single-winner: the process that exclusively
creates ``<name>.replacing`` re-checks the name under that claim, writes the
new value into the claim and renames it over the name, which publishes the
value and releases the claim in one step; every other process waits for that
value, for a bounded time.
"""

from __future__ import annotations

import errno
import logging
import os
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

logger = logging.getLogger(__name__)

_POLL_INTERVAL_SECONDS = 0.05
# How long to wait on a peer's replacement claim before declaring it abandoned.
_CLAIM_WAIT_SECONDS = 10.0
# os.link() errors meaning the filesystem cannot hard-link at all.
_NO_HARD_LINK_ERRNOS = frozenset({errno.EPERM, errno.EOPNOTSUPP, errno.ENOTSUP, errno.ENOSYS})


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
            if _create_exclusive(path, generate):
                # Read back what we published, or what a peer published first.
                continue
        elif value and _is_valid(value, validate):
            return value
        else:
            if deadline is None:
                deadline = time.monotonic() + settle_seconds
            if time.monotonic() < deadline:
                time.sleep(_POLL_INTERVAL_SECONDS)
                continue
            if value:
                raise InvalidSecretFileError(f"{path} does not hold a valid secret; restore it from a backup or remove it")
            if _publish_under_claim(path, generate, replace_empty=True):
                continue
        # A peer holds the replacement claim: wait for its value, bounded so a
        # replacer that crashed mid-claim cannot block startup forever.
        if claim_deadline is None:
            claim_deadline = time.monotonic() + max(_CLAIM_WAIT_SECONDS, settle_seconds)
        if time.monotonic() >= claim_deadline:
            raise InvalidSecretFileError(f"{path} is missing or empty and {_claim_path(path)} was left by an interrupted creation; remove both so a new secret can be generated")
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


def _create_exclusive(path: Path, generate: Callable[[], str]) -> bool:
    """Publish a generated value at the missing ``path`` without ever exposing it partially written.

    Returns ``False`` only when the filesystem cannot hard-link and a peer holds
    the replacement claim; otherwise the caller re-reads ``path``.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        try:
            _write_all(fd, generate().encode("utf-8"))
        finally:
            os.close(fd)
        try:
            os.link(temporary, path)
        except FileExistsError:
            pass  # A peer published first.
        except OSError as exc:
            if exc.errno not in _NO_HARD_LINK_ERRNOS:
                raise
            logger.debug("%s cannot hard-link (%s); publishing through the replacement claim", path.parent, exc)
            return _publish_under_claim(path, generate, replace_empty=False)
        return True
    finally:
        Path(temporary).unlink(missing_ok=True)


def _claim_path(path: Path) -> Path:
    return path.with_name(f"{path.name}.replacing")


def _publish_under_claim(path: Path, generate: Callable[[], str], *, replace_empty: bool) -> bool:
    """Publish a generated value at ``path`` while holding the exclusive ``<name>.replacing`` claim.

    ``replace_empty`` replaces an abandoned empty file; otherwise only a missing
    name is filled (creation on filesystems without hard links). Returns
    ``False`` only when a peer holds the claim. Holding it excludes every other
    claimant until our rename publishes the value (and removes the claim), and
    ``path`` is re-read under the claim, so a process that decided before a
    peer's value landed backs off instead of overwriting a value peers may
    already have returned. A failure removes only the claim we created.
    """
    claim = _claim_path(path)
    try:
        fd = os.open(claim, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
    except FileExistsError:
        return False
    published = False
    try:
        try:
            if _read(path) != ("" if replace_empty else None):
                # A peer's value landed (or the name changed state) before our claim.
                return True
            if replace_empty:
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
