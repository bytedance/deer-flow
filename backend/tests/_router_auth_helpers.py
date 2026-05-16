"""Helpers for router-level tests that need a stubbed auth context.

The production gateway runs ``AuthMiddleware`` (validates the JWT cookie)
ahead of every router, plus ``@require_permission(owner_check=True)``
decorators that read ``request.state.auth`` and call
``thread_store.check_access``. Router-level unit tests construct
**bare** FastAPI apps that include only one router — they have neither
the auth middleware nor a real thread_store, so the decorators raise
401 (TestClient path) or ValueError (direct-call path).

This module provides two surfaces:

1. :func:`make_authed_test_app` — wraps ``FastAPI()`` with a tiny
   ``BaseHTTPMiddleware`` that stamps a fake user / AuthContext on every
   request, plus a permissive ``thread_store`` mock on
   ``app.state``. Use from TestClient-based router tests.

2. :func:`call_unwrapped` — invokes the underlying function bypassing
   the ``@require_permission`` decorator chain by walking ``__wrapped__``.
   Use from direct-call tests that previously imported the route
   function and called it positionally.

Both helpers are deliberately permissive: they never deny a request.
Tests that want to verify the *auth boundary itself* (e.g.
``test_auth_middleware``, ``test_auth_type_system``) build their own
apps with the real middleware — those should not use this module.
"""

from __future__ import annotations

from collections.abc import Callable
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.gateway.auth.models import User
from app.gateway.authz import AuthContext, Permissions

# Default permission set granted to the stub user. Mirrors `_ALL_PERMISSIONS`
# in authz.py — kept inline so the tests don't import a private symbol.
_STUB_PERMISSIONS: list[str] = [
    Permissions.THREADS_READ,
    Permissions.THREADS_WRITE,
    Permissions.THREADS_DELETE,
    Permissions.RUNS_CREATE,
    Permissions.RUNS_READ,
    Permissions.RUNS_CANCEL,
]


def _make_stub_user() -> User:
    """A deterministic test user — same shape as production, fresh UUID."""
    return User(
        email="router-test@example.com",
        password_hash="x",
        system_role="user",
        id=uuid4(),
    )


class _StubAuthMiddleware(BaseHTTPMiddleware):
    """Stamp a fake user / AuthContext onto every request.

    Mirrors what production ``AuthMiddleware`` does after the JWT decode
    + DB lookup short-circuit, so ``@require_permission`` finds an
    authenticated context and skips its own re-authentication path.
    """

    def __init__(self, app: ASGIApp, user_factory: Callable[[], User]) -> None:
        super().__init__(app)
        self._user_factory = user_factory

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        user = self._user_factory()
        request.state.user = user
        request.state.auth = AuthContext(user=user, permissions=list(_STUB_PERMISSIONS))
        return await call_next(request)


def make_authed_test_app(
    *,
    user_factory: Callable[[], User] | None = None,
    owner_check_passes: bool = True,
) -> FastAPI:
    """Build a FastAPI test app with stub auth + permissive thread_store.

    Args:
        user_factory: Override the default test user. Must return a fully
            populated :class:`User`. Useful for cross-user isolation tests
            that need a stable id across requests.
        owner_check_passes: When True (default), ``thread_store.check_access``
            returns True for every call so ``@require_permission(owner_check=True)``
            never blocks the route under test. Pass False to verify that
            permission failures surface correctly.

    Returns:
        A ``FastAPI`` app with the stub middleware installed and
        ``app.state.thread_store`` set to a permissive mock. The
        caller is still responsible for ``app.include_router(...)``.
    """
    factory = user_factory or _make_stub_user
    app = FastAPI()
    app.add_middleware(_StubAuthMiddleware, user_factory=factory)

    repo = MagicMock()
    repo.check_access = AsyncMock(return_value=owner_check_passes)
    app.state.thread_store = repo

    return app


def call_unwrapped[*P, R](decorated: Callable[P, R], /, *args: P.args, **kwargs: P.kwargs) -> R:
    """Invoke the underlying function of a ``@require_permission``-decorated route.

    ``functools.wraps`` sets ``__wrapped__`` on each layer; we walk all
    the way down to the original handler, bypassing every authz +
    require_auth wrapper. Use from tests that need to call route
    functions directly (without TestClient) and don't want to construct
    a fake ``Request`` just to satisfy the decorator. The ``ParamSpec``
    propagates the wrapped route's signature so call sites still get
    parameter checking despite the unwrapping.
    """
    fn: Callable = decorated
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__  # type: ignore[attr-defined]
    return fn(*args, **kwargs)
