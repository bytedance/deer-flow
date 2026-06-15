"""Authentication middleware for the Gateway API.

Extracts and validates credentials, sets tenant ContextVar, and attaches
user information to ``request.state``.
"""

from __future__ import annotations

import logging

from fastapi import Request
from starlette.responses import JSONResponse

from app.gateway.auth.api_key_handler import verify_and_track_api_key
from app.gateway.auth.errors import AuthErrorCode, AuthErrorResponse
from app.gateway.auth.jwt_handler import decode_token
from deerflow.config.auth_config import get_auth_config
from deerflow.config.tenant import reset_tenant_id, set_current_tenant_id, validate_tenant_id

logger = logging.getLogger(__name__)

_AUTH_WHITELIST = {
    "/health",
    "/health/live",
    "/health/ready",
    "/health/metrics",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/api/auth/login",
    "/api/auth/refresh",
    "/api/v1/auth/refresh",
    "/api/v1/auth/ins-base/login",
    "/api/v1/auth/ins-base/refresh",
    "/api/v1/auth/ins-base/authenticate",
    "/api/v1/auth/logout",
}


def _is_whitelisted(path: str) -> bool:
    """Check if a request path is exempt from authentication."""
    return path in _AUTH_WHITELIST or path.startswith("/docs") or path.startswith("/redoc")


class _UserState:
    """Attribute-accessible user object set on ``request.state.user``.

    Downstream code (``_principal_from_request``, ``require_permission``, etc.)
    accesses user fields via ``getattr(user, "system_role")`` which silently
    returns the default for plain dicts. This wrapper makes the same access
    pattern work regardless of how the middleware constructed the user.

    Maps ``"role"`` → ``system_role`` to match the dict key used by
    ``create_auth_middleware``.
    """

    _KEY_ALIASES = {"system_role": "role"}

    def __init__(self, data: dict) -> None:
        self._data = data

    def __getattr__(self, name: str):
        actual_key = self._KEY_ALIASES.get(name, name)
        try:
            return self._data[actual_key]
        except KeyError:
            raise AttributeError(name)


def _is_admin_path(path: str) -> bool:
    """Check if a request path is an admin API endpoint."""
    return path.startswith("/api/admin/")


def _json_error(status_code: int, detail: str | AuthErrorResponse) -> JSONResponse:
    """Return a JSON error response (avoids HTTPException + BaseHTTPMiddleware issues)."""
    if isinstance(detail, AuthErrorResponse):
        return JSONResponse(status_code=status_code, content={"detail": detail.model_dump()})
    return JSONResponse(status_code=status_code, content={"detail": detail})


async def _check_tenant_active(tenant_id: str, request: Request) -> JSONResponse | None:
    """Return a 403 response if the tenant does not exist or is disabled, unless this is an admin path."""
    if _is_admin_path(request.url.path):
        return None
    ts = getattr(request.app.state, "tenant_store", None)
    if ts is None:
        return None
    tc = await ts.get(tenant_id)
    if tc is None:
        logger.error(
            "_check_tenant_active: tenant %r NOT FOUND in tenant_store (type=%s). Path=%s",
            tenant_id,
            type(ts).__name__,
            request.url.path,
        )
        return JSONResponse(
            status_code=403,
            content={
                "detail": AuthErrorResponse(
                    code=AuthErrorCode.TENANT_NOT_FOUND,
                    message=f"Tenant {tenant_id!r} does not exist",
                ).model_dump()
            },
        )
    if not tc.is_active:
        return JSONResponse(
            status_code=403,
            content={
                "detail": AuthErrorResponse(
                    code=AuthErrorCode.TENANT_DISABLED,
                    message=f"Tenant {tenant_id!r} is disabled",
                ).model_dump()
            },
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
            error = await _check_tenant_active(tenant_id, request)
            if error is not None:
                return error
            token = set_current_tenant_id(tenant_id)
            try:
                return await call_next(request)
            finally:
                reset_tenant_id(token)

        from app.gateway.internal_auth import INTERNAL_AUTH_HEADER_NAME, is_valid_internal_auth_token

        if is_valid_internal_auth_token(request.headers.get(INTERNAL_AUTH_HEADER_NAME)):
            tenant_id = request.headers.get("X-DeerFlow-Tenant", "default")
            try:
                validate_tenant_id(tenant_id)
            except ValueError as e:
                return _json_error(400, str(e))
            error = await _check_tenant_active(tenant_id, request)
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
            error = await _check_tenant_active(tenant_id, request)
            if error is not None:
                return error
            ctx_token = set_current_tenant_id(tenant_id)
            request.state.user = _UserState({
                "id": "default",
                "username": "default",
                "tenant_id": tenant_id,
                "role": "superadmin",
            })
            try:
                return await call_next(request)
            finally:
                reset_tenant_id(ctx_token)

        # InsBase provider: verify token via ins-base-rpc /auth/authentication
        if config.provider == "ins_base":
            access_token = request.cookies.get("access_token")
            auth_header = request.headers.get("Authorization", "")
            if not access_token and auth_header.startswith("Bearer "):
                access_token = auth_header[7:]

            if access_token:
                try:
                    from app.gateway.auth.ins_base_provider import AuthProviderUnavailableError
                    from app.gateway.deps import get_ins_base_provider
                    ins_provider = get_ins_base_provider()
                    if ins_provider is not None:
                        user = await ins_provider.get_user(access_token)

                        # Auto-refresh: if Java RPC rejected the access token,
                        # try using the refresh_token cookie to obtain a new one.
                        if user is None:
                            refresh_token = request.cookies.get("refresh_token")
                            if not refresh_token:
                                logger.warning(
                                    "create_auth_middleware (ins_base): access_token rejected "
                                    "and NO refresh_token cookie for path=%s",
                                    request.url.path,
                                )
                            else:
                                logger.info(
                                    "create_auth_middleware (ins_base): access_token rejected, "
                                    "attempting auto-refresh for path=%s (refresh_token=%s…)",
                                    request.url.path, refresh_token[:16],
                                )
                                new_token = await ins_provider.refresh_token(refresh_token)
                                if not new_token:
                                    logger.warning(
                                        "create_auth_middleware (ins_base): auto-refresh FAILED "
                                        "(refresh_token rejected by Java RPC) for path=%s",
                                        request.url.path,
                                    )
                                else:
                                    user = await ins_provider.get_user(new_token)
                                    if user is not None:
                                        access_token = new_token
                                        logger.info(
                                            "create_auth_middleware (ins_base): auto-refresh "
                                            "succeeded for path=%s",
                                            request.url.path,
                                        )
                                    else:
                                        logger.warning(
                                            "create_auth_middleware (ins_base): refresh returned "
                                            "new token but get_user still failed for path=%s",
                                            request.url.path,
                                        )

                        if user is not None:
                            tenant_id = getattr(user, "tenant_id", "default")
                            try:
                                validate_tenant_id(tenant_id)
                            except ValueError as e:
                                return _json_error(400, str(e))
                            error = await _check_tenant_active(tenant_id, request)
                            if error is not None:
                                return error
                            ctx_token = set_current_tenant_id(tenant_id)
                            request.state.user = _UserState({
                                "id": getattr(user, "id", tenant_id),
                                "username": getattr(user, "email", "ins-base-user"),
                                "tenant_id": tenant_id,
                                "role": getattr(user, "system_role", "member"),
                                "auth_method": "ins_base",
                                "ins_base_token": access_token,
                            })
                            try:
                                response = await call_next(request)
                                # If we refreshed the token, update the cookie
                                # so subsequent requests use the new token.
                                if access_token != request.cookies.get("access_token"):
                                    from app.gateway.csrf_middleware import is_secure_request

                                    is_https = is_secure_request(request)
                                    response.set_cookie(
                                        key="access_token",
                                        value=access_token,
                                        path="/",
                                        httponly=True,
                                        secure=is_https,
                                        samesite="none" if is_https else "lax",
                                    )
                                return response
                            finally:
                                reset_tenant_id(ctx_token)
                except AuthProviderUnavailableError:
                    logger.exception(
                        "InsBase auth provider unavailable for path=%s — translated_code=%s",
                        request.url.path, AuthErrorCode.PROVIDER_UNAVAILABLE.value,
                    )
                    return _json_error(
                        503,
                        AuthErrorResponse(
                            code=AuthErrorCode.PROVIDER_UNAVAILABLE,
                            message="Authentication service unavailable",
                        ),
                    )
                except Exception:
                    logger.exception(
                        "InsBase token verification failed for path=%s — translated_code=%s",
                        request.url.path, AuthErrorCode.TOKEN_INVALID.value,
                    )

            logger.warning("create_auth_middleware (ins_base): no valid token for path=%s", request.url.path)
            return _json_error(
                401,
                AuthErrorResponse(
                    code=AuthErrorCode.NOT_AUTHENTICATED,
                    message="Missing or invalid authentication token",
                ),
            )

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
                    return _json_error(
                        401,
                        AuthErrorResponse(
                            code=AuthErrorCode.INVALID_CREDENTIALS,
                            message="Invalid or revoked API key",
                        ),
                    )
                tenant_id = request.headers.get("X-DeerFlow-Tenant", "default")
                try:
                    validate_tenant_id(tenant_id)
                except ValueError as e:
                    return _json_error(400, str(e))
                error = await _check_tenant_active(tenant_id, request)
                if error is not None:
                    return error
                ctx_token = set_current_tenant_id(tenant_id)
                request.state.user = _UserState({
                    "username": f"apikey:{meta['name']}",
                    "tenant_id": tenant_id,
                    "role": "member",
                    "auth_method": "api_key",
                })
                try:
                    return await call_next(request)
                finally:
                    reset_tenant_id(ctx_token)

            # Bearer JWT validation (for API clients using jwt_handler format)
            try:
                payload = decode_token(token_value)
            except ValueError as e:
                return _json_error(
                    401,
                    AuthErrorResponse(
                        code=AuthErrorCode.TOKEN_INVALID,
                        message=str(e),
                    ),
                )

            if payload.get("type") != "access":
                return _json_error(
                    401,
                    AuthErrorResponse(
                        code=AuthErrorCode.TOKEN_INVALID,
                        message="Token is not an access token",
                    ),
                )

            tenant_id = payload.get("tenant_id", "default")
            try:
                validate_tenant_id(tenant_id)
            except ValueError as e:
                return _json_error(400, str(e))

            error = await _check_tenant_active(tenant_id, request)
            if error is not None:
                return error

            ctx_token = set_current_tenant_id(tenant_id)
            request.state.user = _UserState({
                "username": payload["sub"],
                "tenant_id": tenant_id,
                "role": payload.get("role", "member"),
                "auth_method": "jwt",
            })
            try:
                return await call_next(request)
            finally:
                reset_tenant_id(ctx_token)

        elif cookie_token:
            # Cookie-based auth: decode the JWT to extract tenant_id from
            # token claims. Falls back to X-DeerFlow-Tenant header when the
            # cookie JWT is expired/malformed (the inner AuthMiddleware will
            # reject the request with a proper 401 in that case).
            from app.gateway.auth.errors import TokenError
            from app.gateway.auth.jwt import decode_token as decode_cookie_token

            payload = decode_cookie_token(cookie_token)
            if isinstance(payload, TokenError):
                tenant_id = request.headers.get("X-DeerFlow-Tenant", "default")
            else:
                tenant_id = payload.tenant_id

            try:
                validate_tenant_id(tenant_id)
            except ValueError as e:
                return _json_error(400, str(e))
            error = await _check_tenant_active(tenant_id, request)
            if error is not None:
                return error
            token = set_current_tenant_id(tenant_id)
            try:
                return await call_next(request)
            finally:
                reset_tenant_id(token)

        else:
            logger.warning("create_auth_middleware: no Bearer token or cookie for path=%s", request.url.path)
            return _json_error(
                401,
                AuthErrorResponse(
                    code=AuthErrorCode.NOT_AUTHENTICATED,
                    message="Missing or invalid Authorization header",
                ),
            )

    return auth_middleware
