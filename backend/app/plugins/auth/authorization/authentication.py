"""Authentication helpers used by auth-plugin authorization decorators."""

from __future__ import annotations

from fastapi import Request

from app.plugins.auth.authorization.providers import PermissionProvider, default_permission_provider
from app.plugins.auth.authorization.types import AuthContext


def get_auth_context(request: Request) -> AuthContext | None:
    """Get AuthContext, preferring Starlette-style request.auth."""

    auth = request.scope.get("auth")
    if isinstance(auth, AuthContext):
        return auth
    return getattr(request.state, "auth", None)


def set_auth_context(request: Request, auth_context: AuthContext) -> AuthContext:
    """Persist AuthContext on the standard request surfaces."""

    request.scope["auth"] = auth_context
    request.state.auth = auth_context
    return auth_context


async def authenticate_request(
    request: Request,
    *,
    permission_provider: PermissionProvider = default_permission_provider,
) -> AuthContext:
    """Authenticate request and build AuthContext."""

    from app.plugins.auth.security.dependencies import get_optional_user_from_request

    user = await get_optional_user_from_request(request)
    if user is None:
        return AuthContext(user=None, permissions=[])
    return AuthContext(user=user, permissions=permission_provider(user))


__all__ = ["authenticate_request", "get_auth_context", "set_auth_context"]
