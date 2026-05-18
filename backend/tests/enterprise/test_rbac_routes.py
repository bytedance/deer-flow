"""Integration tests for the enterprise RBAC HTTP routes (plan M1-8, RFC §9.1).

Plan §3.2 spells out the coverage we owe these routes:

    7 个路由的权限校验:admin 全通、member 部分通、未认证 401

So we run each route three ways:

1. **Admin** — full role+user manage rights, every call should succeed.
2. **Member** — has neither ``role:manage`` nor ``user:manage``; only
   ``/my-permissions`` (which only requires ``@require_auth``) returns 200.
3. **Unauthenticated** — request lacks an ``AuthContext`` entirely and
   must surface 401, not 403.

The route module relies on three pieces of app-wide state:

* :func:`app.enterprise.deps.get_rbac_repo` — patched per test to point
  at an in-memory SQLite repo seeded with the default role/permission
  rows. This keeps the test hermetic and lets the response assertions
  hit real ``replace_role_permissions`` round-trips.
* :func:`app.gateway.deps.get_local_provider` — patched to a fake user
  store so ``PUT /users/{id}/role`` and ``GET /users/{id}/role`` resolve
  without touching the gateway's SQLite user repository.
* :class:`app.gateway.authz.AuthContext` — pre-stamped on
  ``request.state.auth`` by a tiny ASGI middleware so we don't need to
  spin up the real cookie/JWT pipeline. The ``require_permission``
  decorator short-circuits its own ``_authenticate`` call when
  ``request.state.auth`` is already populated (see
  ``app/gateway/authz.py`` around line 328).
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, AsyncIterator
from dataclasses import dataclass, field

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.enterprise.routers import rbac as rbac_router_module
from app.gateway import authz as authz_module
from app.gateway.authz import AuthContext
from deerflow.enterprise.rbac.models import DEFAULT_ROLE_PERMISSIONS, Permission, Role
from deerflow.enterprise.rbac.repository import (
    SqliteRbacRepository,
    seed_default_role_permissions,
)
from deerflow.persistence.base import Base

# ── Fake user / provider scaffolding ────────────────────────────────────


@dataclass
class _FakeUser:
    """Duck-typed stand-in for ``app.gateway.auth.models.User``.

    The route handlers only read ``id``, ``email``, ``system_role`` and
    ``roles``; anything else is irrelevant for these tests.
    """

    id: str = "user-1"
    email: str = "user@example.com"
    system_role: str = "user"
    roles: list[str] = field(default_factory=list)


class _FakeProvider:
    """Minimal stand-in for ``LocalAuthProvider`` used by RBAC user routes."""

    def __init__(self, users: dict[str, _FakeUser]):
        self._users = users
        self.update_calls: list[_FakeUser] = []

    async def get_user(self, user_id: str) -> _FakeUser | None:  # noqa: D401
        return self._users.get(user_id)

    async def update_user(self, user: _FakeUser) -> None:
        # Record the call so tests can assert role mutations were
        # persisted, without standing up a real DB.
        self.update_calls.append(user)
        self._users[user.id] = user


# ── Auth patching helper ───────────────────────────────────────────────


def _patch_authenticate(monkeypatch: pytest.MonkeyPatch, auth: AuthContext | None) -> None:
    """Make ``authz._authenticate`` return ``auth`` (or an anonymous ctx).

    ``require_auth`` calls ``_authenticate(request)`` unconditionally
    (unless ``_deerflow_test_bypass_auth`` is set on the request — but
    that flag *also* short-circuits the permission check, which would
    defeat the point of these tests). Patching the underlying resolver
    is the cleanest way to inject a deterministic identity while still
    exercising the decorator's real permission-gating branch.

    Passing ``auth=None`` simulates an anonymous request — the decorator
    will see ``is_authenticated=False`` and raise 401.
    """

    async def _fake_authenticate(request):  # noqa: ARG001 - signature parity
        if auth is None:
            return AuthContext(user=None, permissions=[])
        return auth

    monkeypatch.setattr(authz_module, "_authenticate", _fake_authenticate)


# ── DB / repo fixtures ─────────────────────────────────────────────────


@pytest_asyncio.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def seeded_repo(session_factory: async_sessionmaker) -> AsyncGenerator[SqliteRbacRepository, None]:
    await seed_default_role_permissions(session_factory)
    yield SqliteRbacRepository(session_factory)


# ── Permission helpers ─────────────────────────────────────────────────


def _admin_perms() -> list[str]:
    """All permissions an ADMIN holds — derived from the default map.

    Pulling from :data:`DEFAULT_ROLE_PERMISSIONS` instead of hard-coding
    avoids the test breaking when M2/M3 add new permissions to the
    admin set.
    """
    return sorted({p.value for p in DEFAULT_ROLE_PERMISSIONS[Role.ADMIN]})


def _member_perms() -> list[str]:
    return sorted({p.value for p in DEFAULT_ROLE_PERMISSIONS[Role.MEMBER]})


# ── App factory ────────────────────────────────────────────────────────


def _build_app(
    seeded_repo: SqliteRbacRepository,
    provider: _FakeProvider,
    auth: AuthContext | None,
    monkeypatch: pytest.MonkeyPatch,
) -> FastAPI:
    """Construct a minimal FastAPI app that only mounts the RBAC router.

    Patches three module-level dependencies:

    * ``get_rbac_repo`` (used inside the router) — points at an
      in-memory SQLite repo seeded with default permissions.
    * ``get_local_provider`` (used for user routes) — points at the
      provided fake user store.
    * ``authz._authenticate`` — returns ``auth`` (or an anonymous
      context if ``auth is None``) so the real ``require_auth`` /
      ``require_permission`` decorators run with a deterministic
      identity. See :func:`_patch_authenticate` for why we patch the
      resolver rather than pre-stamping ``request.state.auth``.
    """

    async def _fake_get_repo() -> SqliteRbacRepository:
        return seeded_repo

    def _fake_get_provider() -> _FakeProvider:
        return provider

    monkeypatch.setattr(rbac_router_module, "get_rbac_repo", _fake_get_repo)
    monkeypatch.setattr(rbac_router_module, "get_local_provider", _fake_get_provider)
    _patch_authenticate(monkeypatch, auth)

    app = FastAPI()
    app.include_router(rbac_router_module.router, prefix="/api/enterprise/rbac")
    return app


# ── Admin: every route should succeed ──────────────────────────────────


def test_admin_can_list_roles(
    seeded_repo: SqliteRbacRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = _FakeUser(id="admin-1", system_role="admin", roles=["admin"])
    provider = _FakeProvider({admin.id: admin})
    auth = AuthContext(user=admin, permissions=_admin_perms())  # type: ignore[arg-type]
    app = _build_app(seeded_repo, provider, auth, monkeypatch)

    with TestClient(app) as client:
        resp = client.get("/api/enterprise/rbac/roles")

    assert resp.status_code == 200
    body = resp.json()
    role_ids = {row["id"] for row in body["roles"]}
    # Every enum value must be reported, even if not persisted yet.
    assert role_ids == {r.value for r in Role}


def test_admin_can_get_single_role(
    seeded_repo: SqliteRbacRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = _FakeUser(id="admin-1", system_role="admin", roles=["admin"])
    provider = _FakeProvider({admin.id: admin})
    auth = AuthContext(user=admin, permissions=_admin_perms())  # type: ignore[arg-type]
    app = _build_app(seeded_repo, provider, auth, monkeypatch)

    with TestClient(app) as client:
        resp = client.get(f"/api/enterprise/rbac/roles/{Role.MEMBER.value}")

    assert resp.status_code == 200
    assert resp.json()["id"] == Role.MEMBER.value


def test_admin_get_unknown_role_returns_404(
    seeded_repo: SqliteRbacRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = _FakeUser(id="admin-1", system_role="admin", roles=["admin"])
    provider = _FakeProvider({admin.id: admin})
    auth = AuthContext(user=admin, permissions=_admin_perms())  # type: ignore[arg-type]
    app = _build_app(seeded_repo, provider, auth, monkeypatch)

    with TestClient(app) as client:
        resp = client.get("/api/enterprise/rbac/roles/no-such-role")

    assert resp.status_code == 404


def test_admin_can_replace_role_permissions(
    seeded_repo: SqliteRbacRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PUT /roles/{id}/permissions replaces the row set and echoes it back."""
    admin = _FakeUser(id="admin-1", system_role="admin", roles=["admin"])
    provider = _FakeProvider({admin.id: admin})
    auth = AuthContext(user=admin, permissions=_admin_perms())  # type: ignore[arg-type]
    app = _build_app(seeded_repo, provider, auth, monkeypatch)

    desired = sorted({Permission.AGENT_VIEW.value, Permission.DATA_READ.value})
    with TestClient(app) as client:
        resp = client.put(
            f"/api/enterprise/rbac/roles/{Role.VIEWER.value}/permissions",
            json={"permissions": desired},
        )

    assert resp.status_code == 200
    assert resp.json()["permissions"] == desired
    # And the response itself reflects what the repo stored — the route
    # re-reads via ``get_role_permissions`` before responding, so a
    # truthful 200 body is end-to-end evidence.


def test_replace_role_permissions_rejects_unknown_permission(
    seeded_repo: SqliteRbacRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Operator typos surface as 400 — we never silently drop perms."""
    admin = _FakeUser(id="admin-1", system_role="admin", roles=["admin"])
    provider = _FakeProvider({admin.id: admin})
    auth = AuthContext(user=admin, permissions=_admin_perms())  # type: ignore[arg-type]
    app = _build_app(seeded_repo, provider, auth, monkeypatch)

    with TestClient(app) as client:
        resp = client.put(
            f"/api/enterprise/rbac/roles/{Role.VIEWER.value}/permissions",
            json={"permissions": ["agent:view", "totally:bogus"]},
        )

    assert resp.status_code == 400
    assert "Unknown permission" in resp.json()["detail"]


def test_admin_can_list_permission_catalog(
    seeded_repo: SqliteRbacRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = _FakeUser(id="admin-1", system_role="admin", roles=["admin"])
    provider = _FakeProvider({admin.id: admin})
    auth = AuthContext(user=admin, permissions=_admin_perms())  # type: ignore[arg-type]
    app = _build_app(seeded_repo, provider, auth, monkeypatch)

    with TestClient(app) as client:
        resp = client.get("/api/enterprise/rbac/permissions")

    assert resp.status_code == 200
    assert set(resp.json()["permissions"]) == {p.value for p in Permission}


def test_admin_can_get_user_role(
    seeded_repo: SqliteRbacRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = _FakeUser(id="admin-1", system_role="admin", roles=["admin"])
    target = _FakeUser(id="target-1", email="t@example.com", system_role="user", roles=["member"])
    provider = _FakeProvider({admin.id: admin, target.id: target})
    auth = AuthContext(user=admin, permissions=_admin_perms())  # type: ignore[arg-type]
    app = _build_app(seeded_repo, provider, auth, monkeypatch)

    with TestClient(app) as client:
        resp = client.get(f"/api/enterprise/rbac/users/{target.id}/role")

    assert resp.status_code == 200
    body = resp.json()
    assert body["user_id"] == target.id
    assert body["roles"] == ["member"]


def test_admin_get_missing_user_returns_404(
    seeded_repo: SqliteRbacRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = _FakeUser(id="admin-1", system_role="admin", roles=["admin"])
    provider = _FakeProvider({admin.id: admin})
    auth = AuthContext(user=admin, permissions=_admin_perms())  # type: ignore[arg-type]
    app = _build_app(seeded_repo, provider, auth, monkeypatch)

    with TestClient(app) as client:
        resp = client.get("/api/enterprise/rbac/users/ghost/role")

    assert resp.status_code == 404


def test_admin_can_update_user_role(
    seeded_repo: SqliteRbacRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = _FakeUser(id="admin-1", system_role="admin", roles=["admin"])
    target = _FakeUser(id="target-1", email="t@example.com", system_role="user", roles=["viewer"])
    provider = _FakeProvider({admin.id: admin, target.id: target})
    auth = AuthContext(user=admin, permissions=_admin_perms())  # type: ignore[arg-type]
    app = _build_app(seeded_repo, provider, auth, monkeypatch)

    with TestClient(app) as client:
        resp = client.put(
            f"/api/enterprise/rbac/users/{target.id}/role",
            json={"roles": ["member"]},
        )

    assert resp.status_code == 200
    assert resp.json()["roles"] == ["member"]
    # Provider received the mutation.
    assert provider.update_calls and provider.update_calls[-1].roles == ["member"]


def test_update_user_role_rejects_unknown_role(
    seeded_repo: SqliteRbacRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = _FakeUser(id="admin-1", system_role="admin", roles=["admin"])
    target = _FakeUser(id="target-1", email="t@example.com")
    provider = _FakeProvider({admin.id: admin, target.id: target})
    auth = AuthContext(user=admin, permissions=_admin_perms())  # type: ignore[arg-type]
    app = _build_app(seeded_repo, provider, auth, monkeypatch)

    with TestClient(app) as client:
        resp = client.put(
            f"/api/enterprise/rbac/users/{target.id}/role",
            json={"roles": ["ghost"]},
        )

    assert resp.status_code == 400
    # Critical: the bogus role must not have been persisted.
    assert provider.update_calls == []


# ── Member: only /my-permissions is allowed ────────────────────────────


def test_member_cannot_list_roles(
    seeded_repo: SqliteRbacRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    member = _FakeUser(id="member-1", system_role="user", roles=["member"])
    provider = _FakeProvider({member.id: member})
    auth = AuthContext(user=member, permissions=_member_perms())  # type: ignore[arg-type]
    app = _build_app(seeded_repo, provider, auth, monkeypatch)

    with TestClient(app) as client:
        resp = client.get("/api/enterprise/rbac/roles")

    assert resp.status_code == 403


def test_member_cannot_update_role_permissions(
    seeded_repo: SqliteRbacRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    member = _FakeUser(id="member-1", system_role="user", roles=["member"])
    provider = _FakeProvider({member.id: member})
    auth = AuthContext(user=member, permissions=_member_perms())  # type: ignore[arg-type]
    app = _build_app(seeded_repo, provider, auth, monkeypatch)

    with TestClient(app) as client:
        resp = client.put(
            f"/api/enterprise/rbac/roles/{Role.VIEWER.value}/permissions",
            json={"permissions": [Permission.DATA_READ.value]},
        )

    assert resp.status_code == 403


def test_member_cannot_read_other_users_role(
    seeded_repo: SqliteRbacRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``user:manage`` gates the user-role routes — members have neither."""
    member = _FakeUser(id="member-1", system_role="user", roles=["member"])
    other = _FakeUser(id="other-1")
    provider = _FakeProvider({member.id: member, other.id: other})
    auth = AuthContext(user=member, permissions=_member_perms())  # type: ignore[arg-type]
    app = _build_app(seeded_repo, provider, auth, monkeypatch)

    with TestClient(app) as client:
        resp = client.get(f"/api/enterprise/rbac/users/{other.id}/role")

    assert resp.status_code == 403


def test_member_can_read_my_permissions(
    seeded_repo: SqliteRbacRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``/my-permissions`` is gated by ``@require_auth`` only."""
    member = _FakeUser(id="member-1", system_role="user", roles=["member"])
    provider = _FakeProvider({member.id: member})
    auth = AuthContext(user=member, permissions=_member_perms())  # type: ignore[arg-type]
    app = _build_app(seeded_repo, provider, auth, monkeypatch)

    with TestClient(app) as client:
        resp = client.get("/api/enterprise/rbac/my-permissions")

    assert resp.status_code == 200
    body = resp.json()
    assert body["user_id"] == member.id
    assert body["roles"] == ["member"]
    assert sorted(body["permissions"]) == _member_perms()


# ── Unauthenticated: 401 across the board ──────────────────────────────


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("GET", "/api/enterprise/rbac/roles", None),
        ("GET", f"/api/enterprise/rbac/roles/{Role.MEMBER.value}", None),
        (
            "PUT",
            f"/api/enterprise/rbac/roles/{Role.VIEWER.value}/permissions",
            {"permissions": [Permission.DATA_READ.value]},
        ),
        ("GET", "/api/enterprise/rbac/permissions", None),
        ("GET", "/api/enterprise/rbac/users/anyone/role", None),
        (
            "PUT",
            "/api/enterprise/rbac/users/anyone/role",
            {"roles": ["member"]},
        ),
        ("GET", "/api/enterprise/rbac/my-permissions", None),
    ],
)
def test_unauthenticated_requests_return_401(
    seeded_repo: SqliteRbacRepository,
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    path: str,
    body: dict | None,
) -> None:
    """Every route must surface 401 (not 403) when auth is missing.

    The decorator distinguishes the two states deliberately: 401 means
    "we don't know who you are", 403 means "we know but you can't".
    Conflating them would let unauthenticated callers probe which routes
    exist.
    """
    provider = _FakeProvider({})
    app = _build_app(seeded_repo, provider, auth=None, monkeypatch=monkeypatch)

    with TestClient(app) as client:
        resp = client.request(method, path, json=body)

    assert resp.status_code == 401, f"{method} {path} returned {resp.status_code}"


# ── Helpers ────────────────────────────────────────────────────────────
# (no extra helpers — the route bodies themselves are end-to-end evidence)
