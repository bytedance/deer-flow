"""Authentication endpoints — local auth removed, only logout and me remain."""

import logging

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from app.gateway.auth.models import UserResponse
from app.gateway.auth.ins_base_provider import InsBaseAuthProvider
from app.gateway.csrf_middleware import is_secure_request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class MessageResponse(BaseModel):
    """Generic message response."""

    message: str


class RefreshResponse(BaseModel):
    """Response model for token refresh."""

    message: str = "Token refreshed"


def _set_session_cookie(response: Response, token_value: str, request: Request) -> None:
    """Set the access_token HttpOnly cookie on the response."""
    from deerflow.config.auth_config import get_auth_config

    config = get_auth_config()
    is_https = is_secure_request(request)
    response.set_cookie(
        key="access_token",
        value=token_value,
        httponly=True,
        secure=is_https,
        samesite="lax",
        max_age=config.token_expiry_days * 24 * 3600 if is_https else None,
    )


def _set_refresh_cookie(response: Response, refresh_value: str, request: Request) -> None:
    """Set the refresh_token HttpOnly cookie on the response."""
    is_https = is_secure_request(request)
    response.set_cookie(
        key="refresh_token",
        value=refresh_value,
        httponly=True,
        secure=is_https,
        samesite="lax",
        max_age=7 * 24 * 3600 if is_https else None,
    )


@router.post("/logout", response_model=MessageResponse)
async def logout(request: Request, response: Response):
    """Logout current user by clearing the cookie."""
    response.delete_cookie(key="access_token", secure=is_secure_request(request), samesite="lax")
    response.delete_cookie(key="refresh_token", secure=is_secure_request(request), samesite="lax")
    return MessageResponse(message="Successfully logged out")


@router.post("/refresh", response_model=RefreshResponse)
async def refresh(request: Request, response: Response):
    """Refresh the access_token using the refresh_token cookie.

    Reads ``refresh_token`` cookie, validates it against ins-base-rpc,
    and sets new ``access_token`` and ``refresh_token`` cookies on success.
    """
    refresh_token = request.cookies.get("refresh_token")
    if not refresh_token:
        raise HTTPException(status_code=401, detail="No refresh token")

    from app.gateway.deps import get_ins_base_provider

    provider = get_ins_base_provider()
    if provider is None or not isinstance(provider, InsBaseAuthProvider):
        raise HTTPException(status_code=503, detail="Authentication provider not available")

    new_token = await provider.refresh_token(refresh_token)
    if new_token is None:
        response.delete_cookie(key="access_token", secure=is_secure_request(request), samesite="lax")
        response.delete_cookie(key="refresh_token", secure=is_secure_request(request), samesite="lax")
        raise HTTPException(status_code=401, detail="Refresh token expired or invalid")

    _set_session_cookie(response, new_token, request)
    # Keep the same refresh_token cookie (refresh rotation not supported by ins-base)
    _set_refresh_cookie(response, refresh_token, request)

    return RefreshResponse(message="Token refreshed")


@router.get("/me", response_model=UserResponse)
async def get_me(request: Request):
    """Get current authenticated user info from the ins-base token.

    Reads the ``access_token`` cookie, validates it against ins-base-rpc,
    and returns the user profile.
    """
    access_token = request.cookies.get("access_token")
    if not access_token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    from app.gateway.deps import get_ins_base_provider

    provider = get_ins_base_provider()
    if provider is None or not isinstance(provider, InsBaseAuthProvider):
        raise HTTPException(status_code=503, detail="Authentication provider not available")

    user = await provider.get_user(access_token)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user_data = getattr(user, "ins_base_user_data", {})
    user_id = str(user_data.get("userId", user.id))
    user_name = str(user_data.get("userName", ""))
    real_name = str(user_data.get("realName", ""))

    return UserResponse(
        id=user_id,
        email=user.email,
        system_role=user.system_role,
        tenant_id=user.tenant_id,
        user_name=user_name,
        real_name=real_name,
    )
