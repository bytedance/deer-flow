"""Security layer for the auth plugin."""

from app.plugins.auth.security.actor_context import (
    bind_request_actor_context,
    bind_user_actor_context,
    resolve_request_user_id,
)
from app.plugins.auth.security.csrf import (
    CSRF_COOKIE_NAME,
    CSRF_HEADER_NAME,
    CSRFMiddleware,
    get_csrf_token,
    is_secure_request,
)
from app.plugins.auth.security.dependencies import (
    CurrentAuthService,
    CurrentUserRepository,
    get_auth_service,
    get_current_user_from_request,
    get_current_user_id,
    get_optional_user_from_request,
    get_user_repository,
)
from app.plugins.auth.security.langgraph import add_owner_filter, auth, authenticate
from app.plugins.auth.security.middleware import AuthMiddleware

__all__ = [
    "CSRF_COOKIE_NAME",
    "CSRF_HEADER_NAME",
    "CSRFMiddleware",
    "AuthMiddleware",
    "CurrentAuthService",
    "CurrentUserRepository",
    "add_owner_filter",
    "auth",
    "authenticate",
    "bind_request_actor_context",
    "bind_user_actor_context",
    "get_auth_service",
    "get_csrf_token",
    "get_current_user_from_request",
    "get_current_user_id",
    "get_optional_user_from_request",
    "get_user_repository",
    "is_secure_request",
    "resolve_request_user_id",
]
