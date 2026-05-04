"""FastAPI dependency injection for authentication."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.gateway.auth.api_key_handler import verify_and_track_api_key
from app.gateway.auth.jwt_handler import decode_token
from deerflow.config.auth_config import get_auth_config

logger = logging.getLogger(__name__)

security_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class CurrentUser:
    """Authenticated user information injected into request state."""

    username: str
    tenant_id: str
    role: str
    auth_method: str  # "jwt" or "api_key"


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security_scheme),
) -> CurrentUser:
    """FastAPI dependency that extracts and validates the current user.

    Supports both JWT (Bearer token) and API Key (Bearer token with ``df-`` prefix).

    Raises:
        HTTPException 401: If no credentials are provided or they are invalid.
    """
    config = get_auth_config()
    if not config.enabled:
        from deerflow.config.tenant import get_current_tenant_id

        return CurrentUser(
            username="admin",
            tenant_id=get_current_tenant_id(),
            role="admin",
            auth_method="none",
        )

    if credentials is None:
        raise HTTPException(status_code=401, detail="Missing authorization header")

    token = credentials.credentials

    # Try API Key first (df- prefix)
    if token.startswith("df-"):
        meta = verify_and_track_api_key(token)
        if meta is None:
            raise HTTPException(status_code=401, detail="Invalid or revoked API key")
        from deerflow.config.tenant import get_current_tenant_id

        return CurrentUser(
            username=f"apikey:{meta['name']}",
            tenant_id=get_current_tenant_id(),
            role="member",
            auth_method="api_key",
        )

    # Try JWT
    try:
        payload = decode_token(token)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))

    if payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="Token is not an access token")

    return CurrentUser(
        username=payload["sub"],
        tenant_id=payload["tenant_id"],
        role=payload.get("role", "member"),
        auth_method="jwt",
    )


def require_admin(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """Dependency that requires the current user to have the ``admin`` role."""
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")
    return user
