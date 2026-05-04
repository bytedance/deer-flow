"""Authentication router — login, token refresh, and API key management."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
import bcrypt

from app.gateway.auth.api_key_handler import create_api_key, list_api_keys, revoke_api_key
from app.gateway.auth.dependencies import get_current_user, require_admin
from app.gateway.auth.jwt_handler import create_access_token, create_refresh_token, decode_token
from app.gateway.auth.models import (
    ApiKeyCreateRequest,
    ApiKeyCreateResponse,
    ApiKeyResponse,
    LoginRequest,
    RefreshRequest,
    TokenResponse,
)
from deerflow.config.auth_config import get_auth_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["authentication"])


@router.post("/login", response_model=TokenResponse)
def login(req: LoginRequest) -> TokenResponse:
    """Authenticate with username and password, returning a JWT access token."""
    config = get_auth_config()
    if not config.enabled:
        raise HTTPException(status_code=400, detail="Authentication is not enabled")

    if req.username != config.admin_username:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not config.admin_password_hash:
        raise HTTPException(status_code=401, detail="No admin password configured")

    if not bcrypt.checkpw(req.password.encode(), config.admin_password_hash.encode()):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token(tenant_id="default", username=req.username, role="admin")
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in=config.jwt_expire_minutes * 60,
    )


@router.post("/refresh", response_model=TokenResponse)
def refresh_token(req: RefreshRequest) -> TokenResponse:
    """Refresh an access token using a refresh token."""
    config = get_auth_config()
    if not config.enabled:
        raise HTTPException(status_code=400, detail="Authentication is not enabled")

    try:
        payload = decode_token(req.access_token)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))

    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Token is not a refresh token")

    new_token = create_access_token(
        tenant_id=payload["tenant_id"],
        username=payload["sub"],
        role=payload.get("role", "member"),
    )
    return TokenResponse(
        access_token=new_token,
        token_type="bearer",
        expires_in=config.jwt_expire_minutes * 60,
    )


@router.post("/api-keys", response_model=ApiKeyCreateResponse)
def create_api_key_route(
    req: ApiKeyCreateRequest,
    user=Depends(require_admin),
) -> ApiKeyCreateResponse:
    """Create a new API key (admin only). The raw key is returned only once."""
    result = create_api_key(name=req.name)
    return ApiKeyCreateResponse(**result)


@router.get("/api-keys", response_model=list[ApiKeyResponse])
def list_api_keys_route(user=Depends(require_admin)) -> list[ApiKeyResponse]:
    """List all active API keys for the current tenant (admin only)."""
    keys = list_api_keys()
    return [ApiKeyResponse(**k) for k in keys]


@router.delete("/api-keys/{key_id}")
def revoke_api_key_route(key_id: str, user=Depends(require_admin)) -> dict:
    """Revoke an API key by ID (admin only)."""
    ok = revoke_api_key(key_id)
    if not ok:
        raise HTTPException(status_code=404, detail="API key not found")
    return {"success": True, "message": "API key revoked"}
