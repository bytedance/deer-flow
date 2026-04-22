"""Global authentication middleware for the auth plugin."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import HTTPException, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp

from app.plugins.auth.authorization import _ALL_PERMISSIONS, AuthContext
from app.plugins.auth.domain.errors import AuthErrorCode, AuthErrorResponse
from app.plugins.auth.injection.registry_loader import RoutePolicyRegistry
from app.plugins.auth.security.dependencies import get_current_user_from_request
from deerflow.runtime.actor_context import ActorContext, bind_actor_context, reset_actor_context

_PUBLIC_PATH_PREFIXES: tuple[str, ...] = ("/health", "/docs", "/redoc", "/openapi.json")

_PUBLIC_EXACT_PATHS: frozenset[str] = frozenset(
    {
        "/api/v1/auth/login/local",
        "/api/v1/auth/register",
        "/api/v1/auth/logout",
        "/api/v1/auth/setup-status",
        "/api/v1/auth/initialize",
    }
)


def _is_public(path: str) -> bool:
    stripped = path.rstrip("/")
    if stripped in _PUBLIC_EXACT_PATHS:
        return True
    return any(path.startswith(prefix) for prefix in _PUBLIC_PATH_PREFIXES)


class AuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        registry = getattr(request.app.state, "auth_route_policy_registry", None)
        is_public = False
        if isinstance(registry, RoutePolicyRegistry):
            is_public = registry.is_public_request(request.method, request.url.path)
        if is_public or _is_public(request.url.path):
            return await call_next(request)

        if not request.cookies.get("access_token"):
            return JSONResponse(
                status_code=401,
                content={
                    "detail": AuthErrorResponse(
                        code=AuthErrorCode.NOT_AUTHENTICATED,
                        message="Authentication required",
                    ).model_dump()
                },
            )

        try:
            user = await get_current_user_from_request(request)
        except HTTPException as exc:
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

        auth_context = AuthContext(user=user, permissions=_ALL_PERMISSIONS)
        request.scope["user"] = user
        request.scope["auth"] = auth_context
        request.state.user = user
        request.state.auth = auth_context
        token = bind_actor_context(ActorContext(user_id=str(user.id)))
        try:
            return await call_next(request)
        finally:
            reset_actor_context(token)


__all__ = ["AuthMiddleware", "_is_public"]
