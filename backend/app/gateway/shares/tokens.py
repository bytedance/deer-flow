"""Share-token utilities for read-only conversation sharing (#4548).

Tokens are ``dfs_`` + urlsafe(32 CSPRNG bytes), shown exactly once in the
create response and persisted only as an HMAC-SHA-256 digest keyed by a
dedicated server-side pepper. The pepper is never a YAML field: it comes
from ``SHARE_TOKEN_PEPPER`` or a 0600 local secret file, mirroring the
``AUTH_JWT_SECRET`` lifecycle. A slow password hash is wrong here (indexed
opaque-token lookup) and reversible encryption is unnecessary (the raw
token never needs to be recovered).
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import os
import secrets
from pathlib import Path

logger = logging.getLogger(__name__)

SHARE_TOKEN_PREFIX = "dfs_"
SHARE_TOKEN_RANDOM_BYTES = 32

_PEPPER_ENV_VAR = "SHARE_TOKEN_PEPPER"
_PEPPER_FILE = ".share_token_pepper"
# Bounded wait for a concurrent creator to finish writing before a loser
# gives up (crashed-writer recovery is an operator fix, not a silent regen).
_PEPPER_READ_RETRIES = 20
_PEPPER_READ_RETRY_DELAY_SECONDS = 0.05

_share_pepper: str | None = None


# A generated pepper is urlsafe(32 bytes) = exactly 43 unpadded characters.
# Accept only that complete value: a loser caching any shorter mid-write
# prefix would diverge from the winner even though both "succeeded".
_GENERATED_PEPPER_LENGTH = 43


def _read_pepper_file(pepper_file: Path) -> str:
    """Read a pepper written by the O_EXCL winner, tolerating in-flight writes."""
    import time

    for _ in range(_PEPPER_READ_RETRIES):
        try:
            pepper = pepper_file.read_text(encoding="utf-8").strip()
            if len(pepper) == _GENERATED_PEPPER_LENGTH:
                return pepper
        except OSError:
            pass  # retried below; a hard failure surfaces after the loop
        time.sleep(_PEPPER_READ_RETRY_DELAY_SECONDS)
    raise RuntimeError(f"Share-token pepper file {pepper_file} exists but is unreadable or empty (a concurrent creator may have crashed mid-write). Delete the file or set SHARE_TOKEN_PEPPER explicitly, then restart.")


def _load_or_create_pepper() -> str:
    """Load the persisted pepper, or atomically generate one into a 0600 file.

    Winner/loser protocol for multi-worker cold starts: every worker that
    finds the file absent generates a candidate, but only the one whose
    ``O_CREAT | O_EXCL`` open succeeds persists and uses its own value —
    losers discard their candidate and read the winner's from disk. Without
    this, concurrent ``exists()`` passes plus ``O_TRUNC`` let each worker
    cache a different pepper while only the last writer survives on disk,
    so links minted by one worker 404 on another.
    """
    from deerflow.config.paths import get_paths

    paths = get_paths()
    pepper_file = paths.base_dir / _PEPPER_FILE

    try:
        if pepper_file.exists():
            return _read_pepper_file(pepper_file)
    except OSError as exc:
        raise RuntimeError(f"Failed to read share-token pepper from {pepper_file}. Set SHARE_TOKEN_PEPPER explicitly or fix DEER_FLOW_HOME/base directory permissions.") from exc

    candidate = secrets.token_urlsafe(32)
    try:
        pepper_file.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(pepper_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        # Another worker won the race: use whatever the winner persisted.
        return _read_pepper_file(pepper_file)
    except OSError as exc:
        raise RuntimeError(f"Failed to persist share-token pepper to {pepper_file}. Set SHARE_TOKEN_PEPPER explicitly or fix DEER_FLOW_HOME/base directory permissions.") from exc
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(candidate)
    return candidate


def generate_share_token() -> str:
    """Generate a show-once raw bearer token: ``dfs_`` + urlsafe(CSPRNG bytes)."""
    return SHARE_TOKEN_PREFIX + secrets.token_urlsafe(SHARE_TOKEN_RANDOM_BYTES)


def share_token_hash(token: str, pepper: str) -> str:
    """Return the hex HMAC-SHA-256 digest persisted for *token*."""
    return hmac.new(pepper.encode("utf-8"), token.encode("utf-8"), hashlib.sha256).hexdigest()


def get_share_pepper() -> str:
    """Return the process-wide pepper, resolving it on first use."""
    global _share_pepper
    if _share_pepper is None:
        pepper = os.environ.get(_PEPPER_ENV_VAR)
        if not pepper:
            pepper = _load_or_create_pepper()
            logger.warning("⚠ SHARE_TOKEN_PEPPER is not set — using an auto-generated pepper persisted to .share_token_pepper. Existing share links survive restarts. For production, set SHARE_TOKEN_PEPPER in the environment.")
        _share_pepper = pepper
    return _share_pepper


async def get_share_pepper_async() -> str:
    """Return the process-wide pepper without blocking an event loop."""
    if _share_pepper is not None:
        return _share_pepper
    return await asyncio.to_thread(get_share_pepper)


def set_share_pepper(pepper: str | None) -> None:
    """Override or reset the process-wide pepper (for testing)."""
    global _share_pepper
    _share_pepper = pepper
