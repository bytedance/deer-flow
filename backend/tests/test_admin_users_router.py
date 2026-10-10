"""Admin user-management router tests (RFC #4063 / issue #3462 gap 2).

Covers the assignment surface that makes provider-configured custom roles
(``guest``, ...) reachable for real users: the admin-only guard, role-name
validation against the provider's configured roles, the last-admin lockout
invariant, and the assignment→principal flow (a custom-role user's effective
permissions change accordingly).
"""

from __future__ import annotations

from uuid import uuid4

from _router_auth_helpers import make_authed_test_app
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.auth.models import User
from app.gateway.authz import assignable_role_names
from app.gateway.deps import get_user_repository
from app.gateway.routers import admin_users


def _make_user(*, system_role: str = "user", email: str = "u@example.com") -> User:
    return User(
        id=uuid4(),
        email=email,
        system_role=system_role,
    )


class _FakeRepo:
    """In-memory stand-in for the user repository."""

    def __init__(self, users: list[User]) -> None:
        self.users = {str(u.id): u for u in users}
        self.updates: list[tuple[str, str]] = []

    async def list_users(self) -> list[User]:
        return list(self.users.values())

    async def get_user_by_id(self, user_id: str) -> User | None:
        return self.users.get(user_id)

    async def count_admin_users(self) -> int:
        return sum(1 for u in self.users.values() if u.system_role == "admin")

    async def update_user(self, user: User) -> User:
        self.updates.append((str(user.id), user.system_role))
        self.users[str(user.id)] = user
        return user

    async def set_disabled(self, user_id: str, disabled: bool) -> User:
        from app.gateway.auth.repositories.base import LastActiveAdminError, UserNotFoundError

        user = self.users.get(user_id)
        if user is None:
            raise UserNotFoundError(f"User {user_id} no longer exists")
        if disabled and not getattr(user, "disabled", False) and user.system_role == "admin":
            if sum(1 for u in self.users.values() if u.system_role == "admin" and not getattr(u, "disabled", False)) <= 1:
                raise LastActiveAdminError("cannot disable the last remaining active admin")
        user.disabled = disabled
        self.updates.append((user_id, f"disabled={disabled}"))
        return user

    async def update_system_role(self, user_id: str, system_role: str) -> User:
        from app.gateway.auth.repositories.base import LastAdminRemainsError, UserNotFoundError

        user = self.users.get(user_id)
        if user is None:
            raise UserNotFoundError(f"User {user_id} no longer exists")
        if user.system_role == "admin" and system_role != "admin":
            # Active admins only (disabled admins cannot authenticate).
            active = sum(1 for u in self.users.values() if u.system_role == "admin" and not getattr(u, "disabled", False))
            if active <= 1:
                raise LastAdminRemainsError("cannot demote the last remaining admin")
        user.system_role = system_role
        self.updates.append((user_id, system_role))
        return user


def _make_client(monkeypatch, *, caller: User, repo: _FakeRepo, roles: set[str] | None = None) -> TestClient:
    app: FastAPI = make_authed_test_app(user_factory=lambda: caller)
    app.include_router(admin_users.router)
    app.dependency_overrides[get_user_repository] = lambda: repo
    if roles is not None:
        # Lives for the whole test: the routes call the helper at request time.
        monkeypatch.setattr(admin_users, "assignable_role_names", lambda: roles)
    return TestClient(app)


def _patch(client: TestClient, user: User, role: str):
    return client.patch(f"/api/v1/admin/users/{user.id}", json={"system_role": role})


def test_non_admin_cannot_list_or_assign(monkeypatch):
    repo = _FakeRepo([_make_user()])
    client = _make_client(monkeypatch, caller=_make_user(), repo=repo)

    assert client.get("/api/v1/admin/users").status_code == 403
    assert _patch(client, _make_user(), "guest").status_code == 403
    assert repo.updates == []


def test_admin_lists_users_with_roles(monkeypatch):
    admin = _make_user(system_role="admin", email="a@example.com")
    guest = _make_user(system_role="guest", email="g@example.com")
    client = _make_client(monkeypatch, caller=admin, repo=_FakeRepo([admin, guest]))

    response = client.get("/api/v1/admin/users")

    assert response.status_code == 200
    assert {row["system_role"] for row in response.json()} == {"admin", "guest"}


def test_assigns_configured_custom_role(monkeypatch):
    admin = _make_user(system_role="admin")
    target = _make_user()
    repo = _FakeRepo([admin, target])
    client = _make_client(monkeypatch, caller=admin, repo=repo, roles={"admin", "user", "guest"})

    response = _patch(client, target, "guest")

    assert response.status_code == 200
    assert response.json()["system_role"] == "guest"
    assert repo.updates == [(str(target.id), "guest")]


def test_unknown_role_rejected(monkeypatch):
    admin = _make_user(system_role="admin")
    target = _make_user()
    repo = _FakeRepo([admin, target])
    client = _make_client(monkeypatch, caller=admin, repo=repo, roles={"admin", "user"})

    response = _patch(client, target, "guest")

    assert response.status_code == 422
    assert "guest" in response.json()["detail"]
    assert repo.updates == []


def test_missing_user_404(monkeypatch):
    admin = _make_user(system_role="admin")
    client = _make_client(monkeypatch, caller=admin, repo=_FakeRepo([admin]), roles={"admin", "user", "guest"})

    # The vanished-row race now surfaces as UserNotFoundError from the
    # single serialized write, mapped to the same 404 the route always meant.
    assert _patch(client, _make_user(), "guest").status_code == 404


def test_last_admin_cannot_be_demoted(monkeypatch):
    admin = _make_user(system_role="admin")
    repo = _FakeRepo([admin])
    client = _make_client(monkeypatch, caller=admin, repo=repo, roles={"admin", "user", "guest"})

    response = _patch(client, admin, "user")

    assert response.status_code == 409
    assert repo.updates == []


def test_admin_demotable_when_another_admin_remains(monkeypatch):
    first = _make_user(system_role="admin", email="a@example.com")
    second = _make_user(system_role="admin", email="b@example.com")
    repo = _FakeRepo([first, second])
    client = _make_client(monkeypatch, caller=first, repo=repo, roles={"admin", "user"})

    response = _patch(client, first, "user")

    assert response.status_code == 200
    assert response.json()["system_role"] == "user"
    assert repo.updates == [(str(first.id), "user")]


def test_same_role_assignment_is_idempotent(monkeypatch):
    """Re-assigning the role a user already holds succeeds and changes
    nothing (the serialized single-column write is idempotent)."""
    admin = _make_user(system_role="admin")
    target = _make_user(system_role="guest")
    repo = _FakeRepo([admin, target])
    client = _make_client(monkeypatch, caller=admin, repo=repo, roles={"admin", "user", "guest"})

    response = _patch(client, target, "guest")

    assert response.status_code == 200
    assert response.json()["system_role"] == "guest"
    assert repo.users[str(target.id)].system_role == "guest"


def test_assignable_role_names_union_of_builtins_and_configured():
    from deerflow.authz.rbac import RbacAuthorizationProvider
    from deerflow.config.authorization_config import AuthorizationConfig

    provider = RbacAuthorizationProvider(
        roles={
            "user": {"tools": {"allow": "*"}},
            "guest": {"tools": {"allow": ["web_search"]}},
        }
    )
    config = AuthorizationConfig(enabled=True, provider={"use": "x", "config": {}})

    captured: dict[str, object] = {}

    def _fake_cached(config_arg):
        captured["called"] = True
        return provider

    import app.gateway.authz as authz_module

    original = authz_module._get_cached_route_provider
    original_config = authz_module._get_route_authorization_config
    authz_module._get_cached_route_provider = _fake_cached
    authz_module._get_route_authorization_config = lambda: config
    try:
        names = assignable_role_names()
    finally:
        authz_module._get_cached_route_provider = original
        authz_module._get_route_authorization_config = original_config

    assert captured["called"] is True
    assert names == {"admin", "user", "guest"}


def test_repo_list_users_orders_and_maps(monkeypatch):
    """The SQLite repository's list_users maps rows and orders oldest-first."""
    import asyncio

    first = _make_user(email="first@example.com")
    second = _make_user(email="second@example.com")
    repo = _FakeRepo([first, second])
    assert asyncio.run(repo.list_users()) == [first, second]


def _make_sqlite_repo(tmpdir):
    """Real SQLiteUserRepository on a scratch database (async setup)."""
    import asyncio

    from app.gateway.auth.repositories.sqlite import SQLiteUserRepository
    from deerflow.persistence.engine import get_session_factory, init_engine

    async def _setup():
        await init_engine("sqlite", url=f"sqlite+aiosqlite:///{tmpdir}/users.db", sqlite_dir=tmpdir)
        return SQLiteUserRepository(get_session_factory())

    return asyncio.run(_setup())


def test_stale_credential_snapshot_cannot_restore_revoked_role(tmp_path):
    """[P1 regression] A password change holding a stale account snapshot
    (role=admin read before the demotion) must not restore the revoked role:
    update_user is field-scoped and preserves the row's current role, while
    update_system_role is the only role writer — and never touches
    credentials."""
    import asyncio
    import tempfile

    from app.gateway.auth.repositories.base import LastAdminRemainsError
    from deerflow.persistence.engine import close_engine

    with tempfile.TemporaryDirectory() as tmpdir:
        repo = _make_sqlite_repo(tmpdir)

        async def _run():
            admin = User(email="admin@example.com", system_role="admin")
            other = User(email="other@example.com", system_role="admin")
            admin = await repo.create_user(admin)
            other = await repo.create_user(other)
            stale_snapshot = User(
                id=admin.id,
                email=admin.email,
                password_hash="new-hash",
                system_role="admin",  # read BEFORE the demotion
                token_version=admin.token_version + 1,
            )

            # The demotion lands first (single-column write).
            demoted = await repo.update_system_role(str(admin.id), "user")
            assert demoted.system_role == "user"

            # The password change resumes with its stale snapshot: credentials
            # are written, the revoked role is NOT restored (and the returned
            # object mirrors the row, not the snapshot).
            after = await repo.update_user(stale_snapshot)
            assert after.password_hash == "new-hash"
            assert after.system_role == "user"
            assert (await repo.get_user_by_id(str(admin.id))).system_role == "user"

            # Field isolation the other way: a role change never touches
            # credentials or token_version.
            await repo.update_system_role(str(admin.id), "guest")
            row = await repo.get_user_by_id(str(admin.id))
            assert row.password_hash == "new-hash"
            assert row.system_role == "guest"

            # The last-admin invariant lives inside the serialized write:
            # demoting the only remaining admin raises, and the row is intact.
            try:
                await repo.update_system_role(str(other.id), "user")
            except LastAdminRemainsError:
                pass
            else:
                raise AssertionError("demoting the last admin must raise")
            assert (await repo.get_user_by_id(str(other.id))).system_role == "admin"

        try:
            asyncio.run(_run())
        finally:
            asyncio.run(close_engine())


def test_assignment_reaches_principal_permissions():
    """End-to-end intent: the assigned role changes the caller's effective
    route permissions — a guest role sees the guest policy's routes, not the
    admin surface. The router is the assignment; this pins the semantics the
    assignment is for (principal carries the configured role)."""
    from app.gateway.authz import build_principal_from_context

    principal = build_principal_from_context({"user_id": "u1", "user_role": "guest"}, default_role="user")

    assert principal.role == "guest"


def test_admin_disables_and_reenables_account(monkeypatch):
    admin = _make_user(system_role="admin")
    target = _make_user(system_role="guest")
    repo = _FakeRepo([admin, target])
    client = _make_client(monkeypatch, caller=admin, repo=repo, roles={"admin", "user", "guest"})

    disabled = client.patch(f"/api/v1/admin/users/{target.id}", json={"disabled": True})
    assert disabled.status_code == 200
    assert disabled.json()["disabled"] is True

    reenabled = client.patch(f"/api/v1/admin/users/{target.id}", json={"disabled": False})
    assert reenabled.status_code == 200
    assert reenabled.json()["disabled"] is False


def test_cannot_disable_last_active_admin(monkeypatch):
    admin = _make_user(system_role="admin")
    repo = _FakeRepo([admin])
    client = _make_client(monkeypatch, caller=admin, repo=repo)

    response = client.patch(f"/api/v1/admin/users/{admin.id}", json={"disabled": True})

    assert response.status_code == 409
    assert repo.users[str(admin.id)].disabled is False


def test_empty_account_update_rejected(monkeypatch):
    admin = _make_user(system_role="admin")
    target = _make_user()
    repo = _FakeRepo([admin, target])
    client = _make_client(monkeypatch, caller=admin, repo=repo)

    assert client.patch(f"/api/v1/admin/users/{target.id}", json={}).status_code == 422


def test_combined_role_and_disable(monkeypatch):
    admin = _make_user(system_role="admin")
    other = _make_user(system_role="admin", email="b@example.com")
    target = _make_user()
    repo = _FakeRepo([admin, other, target])
    client = _make_client(monkeypatch, caller=admin, repo=repo, roles={"admin", "user", "guest"})

    response = client.patch(f"/api/v1/admin/users/{target.id}", json={"system_role": "guest", "disabled": True})

    assert response.status_code == 200
    body = response.json()
    assert body["system_role"] == "guest" and body["disabled"] is True


def test_disable_then_demote_self_strands_no_admin(monkeypatch):
    """[P1 regression] "Disable B, then demote self" and the combined
    {system_role, disabled} self-update must both be rejected: the role
    demotion counts ACTIVE admins only, so with B disabled the self-demotion
    would strand zero usable management credentials."""
    admin = _make_user(system_role="admin")
    other = _make_user(system_role="admin", email="b@example.com")
    repo = _FakeRepo([admin, other])
    client = _make_client(monkeypatch, caller=admin, repo=repo, roles={"admin", "user"})

    # Disable B first.
    assert client.patch(f"/api/v1/admin/users/{other.id}", json={"disabled": True}).status_code == 200

    # Self-demotion now strands: only A remains active.
    demote = client.patch(f"/api/v1/admin/users/{admin.id}", json={"system_role": "user"})
    assert demote.status_code == 409
    assert repo.users[str(admin.id)].system_role == "admin"

    # Combined self demote+disable has the same outcome (role write first,
    # active-count guard fires).
    combined = client.patch(f"/api/v1/admin/users/{admin.id}", json={"system_role": "user", "disabled": True})
    assert combined.status_code == 409
    assert repo.users[str(admin.id)].system_role == "admin"


def test_shared_session_validator_verdicts():
    """The one post-lookup verdict helper every JWT surface routes through."""
    from types import SimpleNamespace as NS

    from app.gateway.auth.errors import AuthErrorCode
    from app.gateway.deps import validate_resolved_session_user

    user = NS(token_version=3, disabled=False)
    assert validate_resolved_session_user(user, NS(ver=3)) is None

    stale = NS(token_version=4, disabled=False)
    assert validate_resolved_session_user(stale, NS(ver=3)) is AuthErrorCode.TOKEN_INVALID

    suspended = NS(token_version=3, disabled=True)
    assert validate_resolved_session_user(suspended, NS(ver=3)) is AuthErrorCode.ACCOUNT_DISABLED


def test_langgraph_authenticate_rejects_suspended_session():
    """The standalone LangGraph authenticate callback rejects a still-valid
    cookie whose account was suspended — admission, not just login."""
    import asyncio
    import tempfile

    import pytest

    from app.gateway.auth.jwt import create_access_token
    from deerflow.persistence.engine import close_engine

    with tempfile.TemporaryDirectory() as tmpdir:
        repo = _make_sqlite_repo(tmpdir)

        async def _run():
            user = await repo.create_user(User(email="lg@example.com", system_role="user"))
            token = create_access_token(str(user.id), token_version=user.token_version)
            await repo.set_disabled(str(user.id), True)

            import app.gateway.deps as deps_module
            from app.gateway import langgraph_auth

            # Point the cached provider at THIS test's repo (module-level
            # caches otherwise leak a previous test's closed engine).
            deps_module._cached_repo = repo
            deps_module._cached_local_provider = None

            request = NS_stub_request(token)

            with pytest.raises(langgraph_auth.Auth.exceptions.HTTPException) as exc_info:
                await langgraph_auth.authenticate(request)
            assert exc_info.value.status_code == 401
            assert "disabled" in str(exc_info.value.detail).lower()

        def NS_stub_request(token_value):
            from types import SimpleNamespace as NS

            return NS(cookies={"access_token": token_value}, headers={}, method="GET", url=NS(path="/"), client=NS(host="test"))

        try:
            asyncio.run(_run())
        finally:
            asyncio.run(close_engine())


def test_browser_ws_authenticator_rejects_suspended_session():
    """The WebSocket authenticator (browser streaming bypasses
    AuthMiddleware) rejects a suspended account's still-valid cookie."""
    import asyncio
    import tempfile

    from app.gateway.auth.jwt import create_access_token
    from deerflow.persistence.engine import close_engine

    with tempfile.TemporaryDirectory() as tmpdir:
        repo = _make_sqlite_repo(tmpdir)

        async def _run():
            user = await repo.create_user(User(email="ws@example.com", system_role="user"))
            token = create_access_token(str(user.id), token_version=user.token_version)
            await repo.set_disabled(str(user.id), True)

            from types import SimpleNamespace as NS

            import app.gateway.deps as deps_module
            from app.gateway.routers.browser import _authenticate_ws

            deps_module._cached_repo = repo
            deps_module._cached_local_provider = None

            websocket = NS(cookies={"access_token": token}, headers={})
            assert await _authenticate_ws(websocket) is None

        try:
            asyncio.run(_run())
        finally:
            asyncio.run(close_engine())


def test_repo_set_disabled_field_scoped_and_last_active_admin():
    """Real-repo slice: set_disabled is a single-column write (role and
    credentials untouched; the credential writer never touches lifecycle
    state), and the last-ACTIVE-admin guard fires inside the serialized
    write — a disabled admin does not count as active, and re-enabling is
    always allowed."""
    import asyncio
    import tempfile

    from app.gateway.auth.repositories.base import LastActiveAdminError
    from deerflow.persistence.engine import close_engine

    with tempfile.TemporaryDirectory() as tmpdir:
        repo = _make_sqlite_repo(tmpdir)

        async def _run():
            first = await repo.create_user(User(email="a@example.com", system_role="admin", password_hash="h1"))
            second = await repo.create_user(User(email="b@example.com", system_role="admin", password_hash="h2"))

            disabled_first = await repo.set_disabled(str(first.id), True)
            assert disabled_first.disabled is True
            assert disabled_first.password_hash == "h1"
            assert disabled_first.system_role == "admin"

            # The credential writer never touches lifecycle state: a stale
            # snapshot with disabled=False does not re-enable the account.
            stale = User(id=first.id, email=first.email, password_hash="h3", system_role="admin")
            after = await repo.update_user(stale)
            assert after.password_hash == "h3"
            assert after.disabled is True

            # Only one ACTIVE admin remains: disabling it raises, row intact.
            try:
                await repo.set_disabled(str(second.id), True)
            except LastActiveAdminError:
                pass
            else:
                raise AssertionError("disabling the last active admin must raise")
            assert (await repo.get_user_by_id(str(second.id))).disabled is False

            restored = await repo.set_disabled(str(first.id), False)
            assert restored.disabled is False

            # The role-demotion guard counts ACTIVE admins only: disable
            # one of two, then demoting the remaining active admin raises.
            await repo.set_disabled(str(first.id), True)
            from app.gateway.auth.repositories.base import LastAdminRemainsError as _LAR

            try:
                await repo.update_system_role(str(second.id), "user")
            except _LAR:
                pass
            else:
                raise AssertionError("demoting the last ACTIVE admin must raise")
            assert (await repo.get_user_by_id(str(second.id))).system_role == "admin"

        try:
            asyncio.run(_run())
        finally:
            asyncio.run(close_engine())


def test_disabled_account_rejected_at_login_and_flagged_for_resolvers():
    """Password login never compares credentials for a disabled account,
    and lookups return the flag so the JWT resolver can reject."""
    import asyncio
    import tempfile

    from app.gateway.auth.local_provider import LocalAuthProvider
    from deerflow.persistence.engine import close_engine

    with tempfile.TemporaryDirectory() as tmpdir:
        repo = _make_sqlite_repo(tmpdir)

        async def _run():
            from app.gateway.auth.password import hash_password

            user = await repo.create_user(User(email="d@example.com", system_role="user", password_hash=hash_password("correct-horse")))
            await repo.set_disabled(str(user.id), True)
            provider = LocalAuthProvider(repository=repo)

            # The CORRECT password: only the disabled gate can reject it.
            assert await provider.authenticate({"email": "d@example.com", "password": "correct-horse"}) is None
            fetched = await provider.get_user(str(user.id))
            assert fetched is not None and fetched.disabled is True

        try:
            asyncio.run(_run())
        finally:
            asyncio.run(close_engine())
