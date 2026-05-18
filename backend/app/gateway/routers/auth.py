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


@router.post("/logout", response_model=MessageResponse)
async def logout(request: Request, response: Response):
    """Logout current user by clearing the cookie."""
    response.delete_cookie(key="access_token", secure=is_secure_request(request), samesite="lax")
    return MessageResponse(message="Successfully logged out")


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

    return UserResponse(
        id=user_id,
        email=user.email,
        system_role=user.system_role,
        tenant_id=user.tenant_id,
    )
