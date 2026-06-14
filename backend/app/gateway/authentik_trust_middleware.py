"""Authentik forward-auth trust middleware.

When the deer-flow ingress sits behind Traefik + Authentik forward-auth, the
proxy strips the Authentik cookie and re-injects identity headers on the
request to the backend. We trust these headers to mint a local session
cookie, so users who have already authenticated to Authentik are not asked
for a second set of credentials at the deer-flow login form.

Activation requires the env var ``DEER_FLOW_AUTHENTIK_TRUST_ENABLED=true``.
The trusted email header defaults to ``X-authentik-email`` (case-insensitive
header lookup is handled by Starlette).

Flow per request:

1. If trust disabled, pass-through.
2. If request already carries a valid ``access_token`` cookie, pass-through.
3. If no Authentik email header is present, pass-through (will hit
   AuthMiddleware which will 401 non-public paths).
4. Resolve / auto-create the local user keyed on the Authentik email.
5. Mint a JWT, inject it as a synthetic ``cookie`` request header so
   ``AuthMiddleware`` finds it on the same request, AND set the cookie
   on the response so the browser keeps it for subsequent requests.

The middleware is opt-in via env to keep the default (non-Authentik)
deployment posture unchanged.
"""

from __future__ import annotations

import logging
import os
import secrets
from collections.abc import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)

_TRUST_ENV_VAR = "DEER_FLOW_AUTHENTIK_TRUST_ENABLED"
_EMAIL_HEADER_ENV = "DEER_FLOW_AUTHENTIK_EMAIL_HEADER"
_DEFAULT_EMAIL_HEADER = "X-authentik-email"


def _is_enabled() -> bool:
    return os.environ.get(_TRUST_ENV_VAR, "").lower() in ("1", "true", "yes")


def _email_header_name() -> str:
    return os.environ.get(_EMAIL_HEADER_ENV) or _DEFAULT_EMAIL_HEADER


def _inject_cookie_header(request: Request, token: str) -> None:
    """Mutate request scope so downstream AuthMiddleware sees access_token."""
    scope = request.scope
    raw_headers: list[tuple[bytes, bytes]] = list(scope.get("headers", []))
    cookie_idx: int | None = None
    existing_cookie = b""
    for i, (k, v) in enumerate(raw_headers):
        if k.lower() == b"cookie":
            cookie_idx = i
            existing_cookie = v
            break

    new_pair = f"access_token={token}".encode()
    if existing_cookie:
        new_value = existing_cookie + b"; " + new_pair
    else:
        new_value = new_pair

    if cookie_idx is None:
        raw_headers.append((b"cookie", new_value))
    else:
        raw_headers[cookie_idx] = (b"cookie", new_value)
    scope["headers"] = raw_headers
    # Starlette caches parsed cookies on the Request object; reset so the
    # next .cookies access re-parses the mutated header.
    if hasattr(request, "_cookies"):
        try:
            del request._cookies  # type: ignore[attr-defined]
        except AttributeError:
            pass


class AuthentikTrustMiddleware(BaseHTTPMiddleware):
    """Mint a local session cookie from an upstream Authentik email header."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if not _is_enabled():
            return await call_next(request)

        if request.cookies.get("access_token"):
            return await call_next(request)

        header_name = _email_header_name()
        email = request.headers.get(header_name)
        if not email:
            return await call_next(request)

        token: str | None = None
        try:
            from app.gateway.auth import create_access_token
            from app.gateway.deps import get_local_provider

            provider = get_local_provider()
            user = await provider.get_user_by_email(email)
            if user is None:
                # Authentik already authenticated this principal, so we
                # never need to know its password locally. Use a random
                # 32-byte secret as the placeholder hash so the
                # /login/local route (still a valid path) cannot be used
                # to impersonate the user with a guessable credential.
                user = await provider.create_user(
                    email=email,
                    password=secrets.token_urlsafe(32),
                    system_role="user",
                    needs_setup=False,
                )
                logger.info("authentik-trust: auto-created local user for %s", email)
            token = create_access_token(str(user.id), token_version=user.token_version)
            _inject_cookie_header(request, token)
        except Exception as exc:  # noqa: BLE001 — broad catch is deliberate; trust-middleware must never fail-open
            logger.exception("authentik-trust: failed to mint session for %s: %s", email, exc)
            return await call_next(request)

        response = await call_next(request)

        # Cache the cookie on the browser so subsequent requests skip the
        # mint path. SameSite=lax matches _set_session_cookie in
        # routers/auth.py. Secure flag tracks the proxy-resolved scheme.
        is_https = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
        # Best-effort: pull token_expiry_days from auth config if available.
        try:
            from app.gateway.auth.config import get_auth_config

            max_age = get_auth_config().token_expiry_days * 24 * 3600 if is_https else None
        except Exception:  # noqa: BLE001
            max_age = None

        response.set_cookie(
            key="access_token",
            value=token,
            httponly=True,
            secure=is_https,
            samesite="lax",
            max_age=max_age,
        )
        return response
