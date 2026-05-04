"""JWT token creation, decoding, and validation."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt

from deerflow.config.auth_config import get_auth_config

logger = logging.getLogger(__name__)


def create_access_token(tenant_id: str, username: str, role: str = "admin") -> str:
    """Create a signed JWT access token.

    Args:
        tenant_id: The tenant the user belongs to.
        username: The authenticated username.
        role: The user's role (default: ``"admin"``).

    Returns:
        Encoded JWT string.
    """
    config = get_auth_config()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": username,
        "tenant_id": tenant_id,
        "role": role,
        "iat": now,
        "exp": now + timedelta(minutes=config.jwt_expire_minutes),
        "type": "access",
    }
    return jwt.encode(payload, config.jwt_secret, algorithm=config.jwt_algorithm)


def create_refresh_token(tenant_id: str, username: str) -> str:
    """Create a longer-lived refresh token."""
    config = get_auth_config()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": username,
        "tenant_id": tenant_id,
        "iat": now,
        "exp": now + timedelta(days=7),
        "type": "refresh",
    }
    return jwt.encode(payload, config.jwt_secret, algorithm=config.jwt_algorithm)


def decode_token(token: str) -> dict:
    """Decode and validate a JWT token.

    Args:
        token: The encoded JWT string.

    Returns:
        The decoded payload dict.

    Raises:
        ValueError: If the token is invalid, expired, or malformed.
    """
    config = get_auth_config()
    try:
        payload = jwt.decode(token, config.jwt_secret, algorithms=[config.jwt_algorithm])
        return payload
    except JWTError as e:
        raise ValueError(f"Invalid token: {e}") from e
