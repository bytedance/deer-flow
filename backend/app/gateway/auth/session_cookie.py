"""Browser session cookie policy for Gateway authentication."""

import logging
import os
from dataclasses import dataclass
from ipaddress import ip_address

from fastapi import Request, Response

from app.gateway.auth.config import get_auth_config
from app.gateway.auth.session_cookie_state import (
    SESSION_COOKIE_ISSUED_STATE_ATTR,
    SESSION_COOKIE_MAX_AGE_STATE_ATTR,
    SESSION_COOKIE_SECURE_STATE_ATTR,
)
from app.gateway.csrf_middleware import is_secure_request

ACCESS_TOKEN_COOKIE_NAME = "access_token"
SESSION_PERSISTENCE_COOKIE_NAME = "deerflow_session_persistent"
ALLOW_INSECURE_PERSISTENT_COOKIE_ENV = "DEER_FLOW_AUTH_ALLOW_INSECURE_PERSISTENT_COOKIE"

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SessionCookiePolicy:
    """Resolved cookie settings for a session-creating auth response."""

    secure: bool
    max_age: int | None
    reason: str


def _env_flag_enabled(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _request_hostname(request: Request) -> str:
    """Return the direct request host without trusting forwarded host headers."""
    if request.url.hostname:
        return request.url.hostname.lower()
    return ""


def is_local_browser_origin(request: Request) -> bool:
    """Return True for loopback browser origins where HTTP persistence is acceptable."""
    host = _request_hostname(request)
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


def _remember_me_from_cookie(request: Request, *, default: bool) -> bool:
    value = request.cookies.get(SESSION_PERSISTENCE_COOKIE_NAME)
    if value == "1":
        return True
    if value == "0":
        return False
    return default


def resolve_session_cookie_policy(request: Request, *, remember_me: bool | None = None, default_remember_me: bool = True) -> SessionCookiePolicy:
    """Resolve session cookie settings from user intent and deployment context."""
    remember = _remember_me_from_cookie(request, default=default_remember_me) if remember_me is None else remember_me
    secure = is_secure_request(request)
    lifetime_seconds = get_auth_config().token_expiry_days * 24 * 3600

    if not remember:
        return SessionCookiePolicy(secure=secure, max_age=None, reason="session_requested")

    if secure:
        return SessionCookiePolicy(secure=True, max_age=lifetime_seconds, reason="secure_persistent")

    if is_local_browser_origin(request):
        return SessionCookiePolicy(secure=False, max_age=lifetime_seconds, reason="localhost_persistent")

    if _env_flag_enabled(ALLOW_INSECURE_PERSISTENT_COOKIE_ENV):
        return SessionCookiePolicy(secure=False, max_age=lifetime_seconds, reason="operator_insecure_persistent")

    return SessionCookiePolicy(secure=False, max_age=None, reason="public_http_session")


def set_session_cookie(response: Response, request: Request, token: str, *, remember_me: bool | None = None, default_remember_me: bool = True) -> SessionCookiePolicy:
    """Set the HttpOnly access-token cookie and stamp its lifetime on request state."""
    resolved_remember_me = _remember_me_from_cookie(request, default=default_remember_me) if remember_me is None else remember_me
    policy = resolve_session_cookie_policy(request, remember_me=resolved_remember_me, default_remember_me=default_remember_me)
    response.set_cookie(
        key=ACCESS_TOKEN_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=policy.secure,
        samesite="lax",
        max_age=policy.max_age,
    )
    response.set_cookie(
        key=SESSION_PERSISTENCE_COOKIE_NAME,
        value="1" if resolved_remember_me else "0",
        httponly=True,
        secure=policy.secure,
        samesite="lax",
        max_age=policy.max_age,
    )
    setattr(request.state, SESSION_COOKIE_MAX_AGE_STATE_ATTR, policy.max_age)
    setattr(request.state, SESSION_COOKIE_SECURE_STATE_ATTR, policy.secure)
    setattr(request.state, SESSION_COOKIE_ISSUED_STATE_ATTR, True)
    logger.debug("Resolved auth session cookie policy: reason=%s secure=%s max_age=%s", policy.reason, policy.secure, policy.max_age)
    return policy
