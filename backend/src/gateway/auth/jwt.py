"""JWT token creation and validation."""

from __future__ import annotations

import os
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt

# Derive backend/ dir from this file's location (backend/src/gateway/auth/jwt.py)
# instead of os.getcwd() which is blocked inside the async event loop by blockbuster.
_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent.parent
_STORE_DIR = _BACKEND_DIR / ".think-tank"
_SECRET_FILE = _STORE_DIR / "jwt-secret.key"

ACCESS_TOKEN_EXPIRE_MINUTES = 15
REFRESH_TOKEN_EXPIRE_DAYS = 7
ALGORITHM = "HS256"


def _get_secret_key() -> str:
    """Get or create the JWT secret key.

    The secret is read from the JWT_SECRET_KEY environment variable.
    If not set, a random secret is generated and persisted to disk.

    When REQUIRE_ENV_SECRETS is set (production mode), the JWT_SECRET_KEY
    environment variable is required and file-based fallback is disabled.
    """
    env_secret = os.environ.get("JWT_SECRET_KEY")
    if env_secret:
        return env_secret

    if os.environ.get("REQUIRE_ENV_SECRETS"):
        raise RuntimeError("JWT_SECRET_KEY environment variable is required when REQUIRE_ENV_SECRETS is set. Set JWT_SECRET_KEY in your environment or .env file for production deployments.")

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
    return secret


def create_access_token(user_id: str, email: str) -> str:
    """Create a short-lived access token.

    Args:
        user_id: The user's unique identifier.
        email: The user's email address.

    Returns:
        Encoded JWT string.
    """
    now = datetime.now(UTC)
    payload = {
        "sub": user_id,
        "email": email,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, _get_secret_key(), algorithm=ALGORITHM)


def create_refresh_token(user_id: str) -> str:
    """Create a long-lived refresh token.

    Args:
        user_id: The user's unique identifier.

    Returns:
        Encoded JWT string.
    """
    now = datetime.now(UTC)
    payload = {
        "sub": user_id,
        "type": "refresh",
        "iat": now,
        "exp": now + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
    }
    return jwt.encode(payload, _get_secret_key(), algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    """Decode and verify a JWT token.

    Args:
        token: The JWT string to decode.

    Returns:
        The decoded payload dictionary.

    Raises:
        jwt.ExpiredSignatureError: If the token has expired.
        jwt.InvalidTokenError: If the token is malformed or has an invalid signature.
    """
    return jwt.decode(token, _get_secret_key(), algorithms=[ALGORITHM])
