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


def _current_user_from_request_state(request: Request) -> CurrentUser | None:
    """Return the authenticated user already resolved by middleware.

    The gateway's cookie/session auth path is enforced earlier by
    ``AuthMiddleware`` which stamps a real ``User`` object onto
    ``request.state.user``. Bearer/API-key auth may also populate the same
    field as a plain dict in ``create_auth_middleware``.

    Admin/cost dependencies should trust that resolved principal instead of
    re-demanding an Authorization header and accidentally rejecting valid
    cookie-authenticated browser requests.
    """
    state_user = getattr(getattr(request, "state", None), "user", None)
    if state_user is None:
        return None

    if isinstance(state_user, dict):
        username = str(
            state_user.get("username")
            or state_user.get("email")
            or state_user.get("id")
            or "unknown"
        )
        tenant_id = str(state_user.get("tenant_id", "default"))
        role = str(state_user.get("role") or state_user.get("system_role") or "member")
        auth_method = str(state_user.get("auth_method", "state"))
        return CurrentUser(
            username=username,
            tenant_id=tenant_id,
            role=role,
            auth_method=auth_method,
        )

    username = str(
        getattr(state_user, "id", None)
        or getattr(state_user, "email", None)
        or "unknown"
    )
    tenant_id = str(getattr(state_user, "tenant_id", "default"))
    role = str(
        getattr(state_user, "role", None)
        or getattr(state_user, "system_role", "member")
    )
    auth_method = str(getattr(state_user, "auth_method", "cookie"))
    return CurrentUser(
        username=username,
        tenant_id=tenant_id,
        role=role,
        auth_method=auth_method,
    )


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
            role="superadmin",
            auth_method="none",
        )

    current_from_state = _current_user_from_request_state(request)
    if current_from_state is not None:
        return current_from_state

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
    if user.role not in ("superadmin", "tenant_admin"):
        raise HTTPException(status_code=403, detail="Admin role required")
    return user
