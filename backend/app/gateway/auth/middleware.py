"""Authentication middleware for the Gateway API.

Extracts and validates credentials, sets tenant ContextVar, and attaches
user information to ``request.state``.
"""

from __future__ import annotations

import logging

from fastapi import HTTPException, Request, Response
from starlette.responses import JSONResponse

from app.gateway.auth.api_key_handler import verify_and_track_api_key
from app.gateway.auth.jwt_handler import decode_token
from deerflow.config.auth_config import get_auth_config
from deerflow.config.tenant import reset_tenant_id, set_current_tenant_id, validate_tenant_id
from deerflow.config.tenant_storage import TenantStorage

logger = logging.getLogger(__name__)

_AUTH_WHITELIST = {
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/api/auth/login",
    "/api/auth/refresh",
}


def _is_whitelisted(path: str) -> bool:
    """Check if a request path is exempt from authentication."""
    return path in _AUTH_WHITELIST or path.startswith("/docs") or path.startswith("/redoc")


def _is_admin_path(path: str) -> bool:
    """Check if a request path is an admin API endpoint."""
    return path.startswith("/api/admin/")


def _json_error(status_code: int, detail: str) -> JSONResponse:
    """Return a JSON error response (avoids HTTPException + BaseHTTPMiddleware issues)."""
    return JSONResponse(status_code=status_code, content={"detail": detail})


def _check_tenant_active(tenant_id: str, request_path: str) -> JSONResponse | None:
    """Return a 403 response if the tenant does not exist or is disabled, unless this is an admin path."""
    if _is_admin_path(request_path):
        return None
    ts = TenantStorage()
    tc = ts.get(tenant_id)
    if tc is None:
        return JSONResponse(
            status_code=403,
            content={"detail": f"Tenant {tenant_id!r} does not exist", "code": "tenant_not_found"},
        )
    if not tc.is_active:
        return JSONResponse(
            status_code=403,
            content={"detail": f"Tenant {tenant_id!r} is disabled", "code": "tenant_disabled"},
        )
    return None


def create_auth_middleware():
    """Build an ASGI middleware function for authentication.

    Behaviour depends on ``auth.enabled`` in config:

    - **disabled** (default): Extracts tenant from ``X-DeerFlow-Tenant`` header
      (backward-compatible single-tenant behaviour).
    - **enabled**: Validates Bearer token (JWT or API Key), sets tenant from
      token claims, and attaches user info to ``request.state.user``.
    """

    async def auth_middleware(request: Request, call_next):
        config = get_auth_config()

        if _is_whitelisted(request.url.path):
            tenant_id = request.headers.get("X-DeerFlow-Tenant", "default")
            try:
                validate_tenant_id(tenant_id)
            except ValueError as e:
                return _json_error(400, str(e))
            error = _check_tenant_active(tenant_id, request.url.path)
            if error is not None:
                return error
            token = set_current_tenant_id(tenant_id)
            try:
                return await call_next(request)
            finally:
                reset_tenant_id(token)

        if not config.enabled:
            tenant_id = request.headers.get("X-DeerFlow-Tenant", "default")
            try:
                validate_tenant_id(tenant_id)
            except ValueError as e:
                return _json_error(400, str(e))
            error = _check_tenant_active(tenant_id, request.url.path)
            if error is not None:
                return error
            token = set_current_tenant_id(tenant_id)
            try:
                return await call_next(request)
            finally:
                reset_tenant_id(token)

        # Auth enabled: require Bearer token
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return _json_error(401, "Missing or invalid Authorization header")

        token_value = auth_header[7:]

        # Try API Key first (df- prefix)
        if token_value.startswith("df-"):
            meta = verify_and_track_api_key(token_value)
            if meta is None:
                return _json_error(401, "Invalid or revoked API key")
            tenant_id = request.headers.get("X-DeerFlow-Tenant", "default")
            try:
                validate_tenant_id(tenant_id)
            except ValueError as e:
                return _json_error(400, str(e))
            error = _check_tenant_active(tenant_id, request.url.path)
            if error is not None:
                return error
            ctx_token = set_current_tenant_id(tenant_id)
            request.state.user = {
                "username": f"apikey:{meta['name']}",
                "tenant_id": tenant_id,
                "role": "member",
                "auth_method": "api_key",
            }
            try:
                return await call_next(request)
            finally:
                reset_tenant_id(ctx_token)

        # JWT validation
        try:
            payload = decode_token(token_value)
        except ValueError as e:
            return _json_error(401, str(e))

        if payload.get("type") != "access":
            return _json_error(401, "Token is not an access token")

        tenant_id = payload.get("tenant_id", "default")
        try:
            validate_tenant_id(tenant_id)
        except ValueError as e:
            return _json_error(400, str(e))

        error = _check_tenant_active(tenant_id, request.url.path)
        if error is not None:
            return error

        ctx_token = set_current_tenant_id(tenant_id)
        request.state.user = {
            "username": payload["sub"],
            "tenant_id": tenant_id,
            "role": payload.get("role", "member"),
            "auth_method": "jwt",
        }
        try:
            return await call_next(request)
        finally:
            reset_tenant_id(ctx_token)

    return auth_middleware
