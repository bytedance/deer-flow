"""Personal Access Token (PAT) credentials for programmatic API access.

Tokens are ``dfp_`` + base62(32 CSPRNG bytes), shown exactly once in the
create response and persisted only as a SHA-256 digest. Validation is a
digest-indexed lookup plus a constant-time re-comparison, with a single
generic failure surface so a 401 never reveals which check failed.

v1 scopes are exactly the route-permission strings owned by
``app.gateway.authz`` — a PAT can only narrow its owning user's
permissions, never widen them.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Any

PAT_TOKEN_PREFIX = "dfp_"
PAT_RANDOM_BYTES = 32
# Best-effort ``last_used_at`` writes are throttled per token so high-volume
# automation does not turn every request into a database write.
PAT_LAST_USED_WRITE_INTERVAL_SECONDS = 300.0

PAT_ALLOWED_SCOPES: frozenset[str] = frozenset(
    {
        "threads:read",
        "threads:write",
        "threads:delete",
        "runs:create",
        "runs:read",
        "runs:cancel",
    }
)

PAT_MAX_NAME_LENGTH = 128

_BASE62_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"


def _base62(data: bytes) -> str:
    value = int.from_bytes(data, "big")
    digits: list[str] = []
    while value:
        value, remainder = divmod(value, 62)
        digits.append(_BASE62_ALPHABET[remainder])
    return "".join(reversed(digits))


def generate_pat_token() -> str:
    """Generate a show-once raw token: ``dfp_`` + base62(CSPRNG bytes)."""
    return PAT_TOKEN_PREFIX + _base62(secrets.token_bytes(PAT_RANDOM_BYTES))


def pat_token_digest(token: str) -> str:
    """Return the hex SHA-256 digest persisted for *token*."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def digest_matches(stored_digest: str | None, token: str) -> bool:
    """Constant-time comparison of *token* against a stored digest."""
    if not isinstance(stored_digest, str) or not stored_digest:
        return False
    return hmac.compare_digest(stored_digest, pat_token_digest(token))


def extract_bearer_token(authorization: str | None) -> str | None:
    """Return the Bearer credential from an Authorization header value.

    ``None`` means the request carries no Authorization header at all, so the
    caller should fall through to the session-cookie path. Any other unusable
    value (non-Bearer scheme, empty credential) returns ``""`` so callers
    treat it as an invalid credential rather than an absent one.
    """
    if authorization is None:
        return None
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer":
        return ""
    return value.strip()


async def authenticate_pat(app: Any, authorization: str | None) -> tuple[Any, frozenset[str]]:
    """Validate the Bearer credential and resolve its owning user.

    Returns ``(user, scopes)``. Every failure mode — malformed token, unknown
    or revoked or expired token, PAT store not configured, missing owning
    user — raises the same generic 401 so responses cannot serve as an oracle
    on which check failed.
    """
    from fastapi import HTTPException

    token = extract_bearer_token(authorization)
    if not token or not token.startswith(PAT_TOKEN_PREFIX):
        raise HTTPException(status_code=401, detail="Invalid token")
    pat_repo = getattr(app.state, "pat_repo", None)
    if pat_repo is None:
        raise HTTPException(status_code=401, detail="Invalid token")
    record = await pat_repo.get_active_by_digest(pat_token_digest(token))
    if record is None or not digest_matches(record.get("token_digest"), token):
        raise HTTPException(status_code=401, detail="Invalid token")
    from app.gateway.deps import get_local_provider

    user = await get_local_provider().get_user(str(record["user_id"]))
    if user is None:
        # The owning user was deleted or became unresolvable; the token is
        # dead even though its row survives (deleting a user revokes their
        # PATs, without needing a FK cascade).
        raise HTTPException(status_code=401, detail="Invalid token")
    await pat_repo.touch_last_used(str(record["id"]))
    return user, frozenset(record.get("scopes") or ())


def validate_scopes(scopes: list[str]) -> list[str]:
    """Validate a creation-time scope list; returns the deduplicated order."""
    unknown = sorted(set(scopes) - PAT_ALLOWED_SCOPES)
    if unknown:
        raise ValueError(f"Unknown PAT scopes: {', '.join(unknown)}")
    deduplicated = sorted(set(scopes))
    if not deduplicated:
        raise ValueError("A PAT must request at least one scope")
    return deduplicated
