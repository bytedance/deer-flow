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
    "/api/v1/auth/login/local",
    "/api/v1/auth/register",
    "/api/v1/auth/logout",
    "/api/v1/auth/setup-status",
    "/api/v1/auth/initialize",
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

        # Auth enabled: resolve token from Authorization header or access_token cookie.
        # Cookie-based auth is the primary frontend mechanism (HttpOnly cookie set
        # at login via auth/jwt.py). The outer AuthMiddleware validates cookie JWTs
        # using the same jwt.py library — we only need to extract the tenant here
        # and pass through.
        # Bearer token auth is for API clients (SDK, IM channels, CI/CD).
        auth_header = request.headers.get("Authorization", "")
        cookie_token = request.cookies.get("access_token")

        if auth_header.startswith("Bearer "):
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

            # Bearer JWT validation (for API clients using jwt_handler format)
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

        elif cookie_token:
            # Cookie-based auth: delegate JWT validation to AuthMiddleware which
            # uses auth/jwt.py (same library as the login endpoint). We only
            # extract the tenant from the header.
            logger.debug("create_auth_middleware: cookie found for path=%s, passing through to AuthMiddleware",
                         request.url.path)
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

        else:
            logger.warning("create_auth_middleware: no Bearer token or cookie for path=%s", request.url.path)
            return _json_error(401, "Missing or invalid Authorization header")

    return auth_middleware
