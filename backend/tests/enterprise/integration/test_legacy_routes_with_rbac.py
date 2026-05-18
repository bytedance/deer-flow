"""Integration: legacy ``threads:*`` / ``runs:*`` routes still pass once RBAC is wired.

Plan §3.4 risk register highlights this exact regression: the moment
``RbacPermissionProvider`` is registered via
:func:`app.gateway.authz.set_permission_provider`, the old ``threads:read``
and ``runs:create`` permission strings stop coming from ``_ALL_PERMISSIONS``
and start coming from the provider's permission set. If the provider does
not include ``LEGACY_PERMISSIONS_FOR_ROLE`` in its result, every legacy
route 403s — even though no code in those routes changed.

This file proves two things with one wiring:

1. A user whose role maps to legacy strings (via
   :data:`LEGACY_PERMISSIONS_FOR_ROLE`) is granted ``threads:read`` /
   ``runs:create`` etc. — i.e. the legacy half of the union is honoured.
2. **Reverse evidence**: an instrumented provider's
   ``resolve_permissions`` is actually called at least once during the
   request. Without this check the test would pass trivially even if a
   future refactor bypassed the provider (e.g. moved permission
   resolution into a cached layer that never re-invokes it), and we'd
   silently lose the very integration the test was written to cover.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from dataclasses import dataclass, field

import pytest
import pytest_asyncio
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.gateway import authz as authz_module
from app.gateway.authz import (
    AuthContext,
    require_auth,
    require_permission,
    set_permission_provider,
)
from deerflow.enterprise.config import RbacConfig
from deerflow.enterprise.rbac.models import LEGACY_PERMISSIONS_FOR_ROLE, Role
from deerflow.enterprise.rbac.permission_provider import RbacPermissionProvider
from deerflow.enterprise.rbac.repository import (
    SqliteRbacRepository,
    seed_default_role_permissions,
)
from deerflow.persistence.base import Base

# ── Fakes ──────────────────────────────────────────────────────────────


@dataclass
class _FakeUser:
    id: str = "user-1"
    email: str = "user@example.com"
    system_role: str = ""
    roles: list[str] = field(default_factory=list)


class _CountingProvider:
    """Wrap :class:`RbacPermissionProvider` and count resolve calls.

    The provider's permission contract is delegated unchanged; the
    counter exists purely so the test can prove that
    ``resolve_permissions`` was *actually* invoked during the request
    lifecycle — i.e. that a future refactor cannot quietly bypass the
    provider without this assertion failing.
    """

    def __init__(self, inner: RbacPermissionProvider):
        self._inner = inner
        self.call_count = 0

    async def resolve_permissions(self, user) -> set[str]:
        self.call_count += 1
        return await self._inner.resolve_permissions(user)


# ── DB / provider fixtures ─────────────────────────────────────────────


@pytest_asyncio.fixture
async def session_factory() -> AsyncGenerator[async_sessionmaker, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def counting_provider(session_factory: async_sessionmaker) -> AsyncGenerator[_CountingProvider, None]:
    await seed_default_role_permissions(session_factory)
    repo = SqliteRbacRepository(session_factory)
    inner = RbacPermissionProvider(RbacConfig(enabled=True, default_role="viewer"), repo)
    yield _CountingProvider(inner)


@pytest.fixture(autouse=True)
def _clear_global_provider() -> None:
    """Make sure no provider leaks from a prior test."""
    set_permission_provider(None)
    yield
    set_permission_provider(None)


# ── Legacy-shaped route under test ─────────────────────────────────────


def _build_legacy_app(user: _FakeUser, monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    """Mount a single legacy-shaped route guarded by ``threads:read``.

    We don't import the real ``app.gateway.routers.threads`` module
    because pulling in its dependencies (run store, thread metadata,
    LangGraph runtime) would balloon the test surface area; the goal
    here is to verify the permission *gate*, which is identical for any
    route decorated with ``@require_permission("threads", "read")``.
    """

    app = FastAPI()

    @app.get("/legacy/threads/{thread_id}")
    @require_auth
    @require_permission("threads", "read")
    async def _get_legacy_thread(thread_id: str, request: Request) -> dict[str, str]:
        return {"thread_id": thread_id}

    @app.post("/legacy/runs")
    @require_auth
    @require_permission("runs", "create")
    async def _create_legacy_run(request: Request) -> dict[str, str]:
        return {"status": "ok"}

    # ``require_auth`` always calls ``_authenticate`` — patch it to return
    # a deterministic identity. The real provider then resolves its
    # permissions, which is what we want to exercise.
    async def _fake_authenticate(request):  # noqa: ARG001 - signature parity
        permissions = await authz_module._resolve_permissions_for_user(user)
        return AuthContext(user=user, permissions=permissions)  # type: ignore[arg-type]

    monkeypatch.setattr(authz_module, "_authenticate", _fake_authenticate)
    return app


# ── Tests ──────────────────────────────────────────────────────────────


def test_admin_can_read_legacy_thread_with_rbac_wired(
    counting_provider: _CountingProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An admin must still pass ``threads:read`` once RBAC is registered.

    ADMIN's permission set always includes the full
    :data:`LEGACY_PERMISSIONS_FOR_ROLE` mapping, so the route should
    succeed and the provider should have been consulted (call count
    > 0 — the reverse evidence).
    """
    set_permission_provider(counting_provider)
    admin = _FakeUser(roles=["admin"])
    app = _build_legacy_app(admin, monkeypatch)

    with TestClient(app) as client:
        resp = client.get("/legacy/threads/abc-123")

    assert resp.status_code == 200
    assert resp.json() == {"thread_id": "abc-123"}
    # Reverse evidence: the provider must have been called at least
    # once. ``>= 1`` rather than ``== 1`` because the request may
    # legitimately resolve permissions in more than one place (e.g.
    # both ``_authenticate`` and middleware). The contract is
    # "actually invoked", not "invoked exactly once".
    assert counting_provider.call_count >= 1, "RbacPermissionProvider.resolve_permissions was not called during the request — the legacy route must not bypass the provider, or future refactors will silently drop RBAC enforcement."


def test_member_can_create_legacy_run_with_rbac_wired(
    counting_provider: _CountingProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MEMBER's legacy set includes ``runs:create`` — the route must pass."""
    set_permission_provider(counting_provider)
    member = _FakeUser(roles=["member"])
    app = _build_legacy_app(member, monkeypatch)

    with TestClient(app) as client:
        resp = client.post("/legacy/runs")

    assert resp.status_code == 200
    assert counting_provider.call_count >= 1


def test_viewer_denied_runs_create_with_rbac_wired(
    counting_provider: _CountingProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Viewer does NOT have ``runs:create`` legacy permission — must 403."""
    # Reverse-evidence the *positive* direction: viewer.legacy_perms
    # should not include ``runs:create``, so the route 403s.
    assert "runs:create" not in LEGACY_PERMISSIONS_FOR_ROLE[Role.VIEWER]

    set_permission_provider(counting_provider)
    viewer = _FakeUser(roles=["viewer"])
    app = _build_legacy_app(viewer, monkeypatch)

    with TestClient(app) as client:
        resp = client.post("/legacy/runs")

    assert resp.status_code == 403
    assert counting_provider.call_count >= 1


def test_provider_actually_grants_legacy_permissions_to_admin(
    counting_provider: _CountingProvider,
) -> None:
    """Direct unit-level proof: ADMIN gets every legacy string.

    A pure assertion on the provider output, kept here (next to the
    end-to-end test) so a failure shows "the provider lost legacy
    permissions" right next to "the legacy route 403s" — diagnosing
    becomes a one-grep job instead of a hunt across files.
    """
    admin = _FakeUser(roles=["admin"])

    import asyncio

    resolved = asyncio.run(counting_provider.resolve_permissions(admin))

    for legacy_perm in LEGACY_PERMISSIONS_FOR_ROLE[Role.ADMIN]:
        assert legacy_perm in resolved, f"ADMIN must retain legacy '{legacy_perm}'"
