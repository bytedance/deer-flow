"""HMAC session tokens for PTC proxy authentication.

Tokens are created by the LangGraph server (when setting up PTC for a
sandbox execution) and validated by the Gateway PTC proxy endpoint.
Both processes derive the HMAC key from a shared secret (``PTC_SECRET``
env var or an auto-generated file-persisted key in dev mode).

Token lifecycle:
    1. ``create_session_token(thread_id)`` — called before ``execute_python``
    2. Token is injected as ``PTC_TOKEN`` env var in the sandbox process
    3. Sandbox client code sends the token in each ``/api/ptc/call`` request
    4. ``validate_session_token(token, ttl)`` — called by the Gateway proxy
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# Derive backend/ dir from this file's location (backend/src/ptc/session_token.py)
_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
_STORE_DIR = _BACKEND_DIR / ".think-tank"
_SECRET_FILE = _STORE_DIR / "ptc-secret.key"

DEFAULT_TTL_SECONDS = 3600  # 1 hour


def _get_ptc_secret() -> str:
    """Get or create the PTC shared secret.

    Resolution order:
        1. ``PTC_SECRET`` environment variable (production)
        2. File-persisted secret at ``.think-tank/ptc-secret.key`` (dev)
        3. Auto-generate a new secret and persist it (first run)

    When ``REQUIRE_ENV_SECRETS`` is set (production mode) the env var
    is required and file-based fallback is disabled.

    Returns:
        The PTC shared secret string.

    Raises:
        RuntimeError: If ``REQUIRE_ENV_SECRETS`` is set but ``PTC_SECRET`` is not.
    """
    env_secret = os.environ.get("PTC_SECRET")
    if env_secret:
        return env_secret

    if os.environ.get("REQUIRE_ENV_SECRETS"):
        raise RuntimeError(
            "PTC_SECRET environment variable is required when REQUIRE_ENV_SECRETS is set. "
            "Set PTC_SECRET in your environment or .env file for production deployments."
        )

    _STORE_DIR.mkdir(parents=True, exist_ok=True)
    if _SECRET_FILE.exists():
        return _SECRET_FILE.read_text(encoding="utf-8").strip()

    secret = secrets.token_urlsafe(64)
    tmp_path = _SECRET_FILE.with_suffix(".tmp")
    tmp_path.write_text(secret, encoding="utf-8")
    os.replace(tmp_path, _SECRET_FILE)
    try:
        os.chmod(_SECRET_FILE, 0o600)
    except OSError:
        pass
    logger.info("Generated new PTC shared secret at %s", _SECRET_FILE)
    return secret


def create_session_token(thread_id: str) -> str:
    """Create a signed session token for PTC proxy authentication.

    The token is a base64-encoded JSON payload with an HMAC-SHA256
    signature appended.

    Args:
        thread_id: The thread ID to bind the token to.

    Returns:
        Opaque token string (base64-encoded).
    """
    secret = _get_ptc_secret()
    payload = {
        "thread_id": thread_id,
        "iat": int(time.time()),
    }
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    sig = hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).digest()

    # Encode payload and signature separately, then join with '.'
    # This avoids issues with raw signature bytes containing '.'
    payload_b64 = base64.urlsafe_b64encode(payload_bytes).decode("ascii")
    sig_b64 = base64.urlsafe_b64encode(sig).decode("ascii")
    return f"{payload_b64}.{sig_b64}"


def validate_session_token(token: str, ttl: int = DEFAULT_TTL_SECONDS) -> str | None:
    """Validate a PTC session token and return the bound thread_id.

    Checks HMAC signature integrity and TTL expiry.

    Args:
        token: The opaque token string from ``create_session_token``.
        ttl: Maximum age in seconds (default: 3600 = 1 hour).

    Returns:
        The ``thread_id`` if the token is valid, or ``None`` if invalid/expired.
    """
    secret = _get_ptc_secret()

    # Token format: base64(payload).base64(signature)
    parts = token.split(".")
    if len(parts) != 2:
        logger.warning("PTC token: expected 2 parts (payload.signature), got %d", len(parts))
        return None

    try:
        payload_bytes = base64.urlsafe_b64decode(parts[0].encode("ascii"))
        sig_received = base64.urlsafe_b64decode(parts[1].encode("ascii"))
    except Exception:
        logger.warning("PTC token: failed to base64-decode")
        return None

    # Verify HMAC
    sig_expected = hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).digest()
    if not hmac.compare_digest(sig_received, sig_expected):
        logger.warning("PTC token: HMAC signature mismatch")
        return None

    # Parse payload
    try:
        payload = json.loads(payload_bytes)
    except (json.JSONDecodeError, UnicodeDecodeError):
        logger.warning("PTC token: failed to parse payload JSON")
        return None

    # Check TTL
    issued_at = payload.get("iat")
    if not isinstance(issued_at, int | float):
        logger.warning("PTC token: missing or invalid 'iat'")
        return None

    age = time.time() - issued_at
    if age > ttl:
        logger.warning("PTC token: expired (age=%.0fs, ttl=%ds)", age, ttl)
        return None
    if age < -60:  # Allow 60s clock skew
        logger.warning("PTC token: issued in the future (age=%.0fs)", age)
        return None

    thread_id = payload.get("thread_id")
    if not isinstance(thread_id, str) or not thread_id:
        logger.warning("PTC token: missing or invalid 'thread_id'")
        return None

    return thread_id
