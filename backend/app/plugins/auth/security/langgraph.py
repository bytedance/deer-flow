"""LangGraph auth adapter for the auth plugin."""

from __future__ import annotations

import secrets
from types import SimpleNamespace

from langgraph_sdk import Auth

from app.plugins.auth.security.dependencies import get_current_user_from_request

auth = Auth()

_CSRF_METHODS = frozenset({"POST", "PUT", "DELETE", "PATCH"})


def _check_csrf(request) -> None:
    method = getattr(request, "method", "") or ""
    if method.upper() not in _CSRF_METHODS:
        return

    cookie_token = request.cookies.get("csrf_token")
    header_token = request.headers.get("x-csrf-token")

    if not cookie_token or not header_token:
        raise Auth.exceptions.HTTPException(
            status_code=403,
            detail="CSRF token missing. Include X-CSRF-Token header.",
        )

    if not secrets.compare_digest(cookie_token, header_token):
        raise Auth.exceptions.HTTPException(status_code=403, detail="CSRF token mismatch.")


@auth.authenticate
async def authenticate(request):
    _check_csrf(request)
    resolver_request = SimpleNamespace(
        cookies=getattr(request, "cookies", {}),
        state=SimpleNamespace(_auth_session=getattr(request, "_auth_session", None)),
        app=SimpleNamespace(state=SimpleNamespace(persistence=getattr(request, "_persistence", None))),
    )

    try:
        user = await get_current_user_from_request(resolver_request)
    except Exception as exc:
        status_code = getattr(exc, "status_code", None)
        if status_code is None:
            raise
        detail = getattr(exc, "detail", "Not authenticated")
        message = detail.get("message") if isinstance(detail, dict) else str(detail)
        raise Auth.exceptions.HTTPException(status_code=status_code, detail=message) from exc

    return user.id


@auth.on
async def add_owner_filter(ctx: Auth.types.AuthContext, value: dict):
    metadata = value.setdefault("metadata", {})
    metadata["user_id"] = ctx.user.identity
    return {"user_id": ctx.user.identity}


__all__ = ["add_owner_filter", "auth", "authenticate"]
