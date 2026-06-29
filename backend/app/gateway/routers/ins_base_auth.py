"""InsBase authentication endpoints.

Provides login, token refresh, and authentication endpoints backed by the
ins-base-rpc Java microservice.
"""

import logging

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from app.gateway.auth.ins_base_provider import AuthProviderUnavailableError, RpcNotConfiguredError
from app.gateway.csrf_middleware import is_secure_request
from app.gateway.deps import get_ins_base_provider
from deerflow.config.auth_config import get_auth_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth/ins-base", tags=["auth-ins-base"])


class InsBaseLoginRequest(BaseModel):
    """Request model for ins-base encrypted login."""

    encrypted_username: str = Field(..., min_length=1, description="RSA-encrypted login username")
    encrypted_password: str = Field(..., min_length=1, description="RSA-encrypted login password")


class InsBaseLoginResponse(BaseModel):
    """Response model for ins-base login."""

    token: str
    refresh: str
    tenant_id: str = "default"


class InsBaseRefreshRequest(BaseModel):
    """Request model for ins-base token refresh."""

    refresh_token: str = Field(..., min_length=1, description="Refresh token")


class InsBaseAuthResponse(BaseModel):
    """Response model for ins-base authentication."""

    authenticated: bool
    permissions: list = []


class InsBasePublicKeyResponse(BaseModel):
    """Response model for the ins-base login RSA public key."""

    public_key: str


def _set_session_cookie(response: Response, token_value: str, request: Request) -> None:
    """Set the access_token HttpOnly cookie on the response."""
    config = get_auth_config()
    is_https = is_secure_request(request)
    response.set_cookie(
        key="access_token",
        value=token_value,
        path="/",
        httponly=True,
        secure=is_https,
        samesite="none" if is_https else "lax",
        max_age=config.token_expiry_days * 24 * 3600,
    )


def _set_refresh_cookie(response: Response, refresh_value: str, request: Request) -> None:
    """Set the refresh_token HttpOnly cookie on the response."""
    is_https = is_secure_request(request)
    response.set_cookie(
        key="refresh_token",
        value=refresh_value,
        path="/",
        httponly=True,
        secure=is_https,
        samesite="none" if is_https else "lax",
        max_age=7 * 24 * 3600,
    )


@router.get("/public-key", response_model=InsBasePublicKeyResponse)
async def public_key():
    """Return the RSA public key used by the browser for login encryption."""
    config = get_auth_config()
    if not config.rsa_public_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ins-base login RSA public key is not configured",
        )
    return InsBasePublicKeyResponse(public_key=config.rsa_public_key)


@router.post("/login", response_model=InsBaseLoginResponse)
async def login(request: Request, response: Response, body: InsBaseLoginRequest):
    """Authenticate with ins-base-rpc using browser-encrypted credentials.

    Gateway does not receive plaintext credentials. The encrypted username and
    password are forwarded directly to ins-base-rpc /auth/login.
    """
    provider = get_ins_base_provider()
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ins-base-rpc authentication provider is not configured",
        )

    try:
        user = await provider.authenticate_encrypted(
            body.encrypted_username,
            body.encrypted_password,
        )
    except RpcNotConfiguredError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )
    except AuthProviderUnavailableError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        )
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
        )

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Login failed: invalid username or password",
        )

    _set_session_cookie(response, user.ins_base_token, request)
    _set_refresh_cookie(response, user.ins_base_refresh, request)

    return InsBaseLoginResponse(
        token=user.ins_base_token,
        refresh=user.ins_base_refresh,
        tenant_id=user.tenant_id,
    )


@router.post("/refresh", response_model=InsBaseLoginResponse)
async def refresh(request: Request, response: Response, body: InsBaseRefreshRequest):
    """Refresh an access token using ins-base-rpc /auth/refresh."""
    provider = get_ins_base_provider()
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ins-base-rpc authentication provider is not configured",
        )

    new_token = await provider.refresh_token(body.refresh_token)
    if new_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

    _set_session_cookie(response, new_token, request)

    return InsBaseLoginResponse(
        token=new_token,
        refresh=body.refresh_token,
        tenant_id="default",
    )


@router.post("/authenticate", response_model=InsBaseAuthResponse)
async def authenticate(request: Request, response: Response):
    """Verify a token via ins-base-rpc /auth/authentication."""
    auth_header = request.headers.get("Authorization", "")
    access_token = auth_header[7:] if auth_header.startswith("Bearer ") else None
    if not access_token:
        access_token = request.cookies.get("access_token")

    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token",
        )

    provider = get_ins_base_provider()
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ins-base-rpc authentication provider is not configured",
        )

    try:
        user = await provider.get_user(access_token)
    except AuthProviderUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    _set_session_cookie(response, access_token, request)

    permissions = getattr(user, "ins_base_permissions", [])
    return InsBaseAuthResponse(
        authenticated=True,
        permissions=permissions,
    )
