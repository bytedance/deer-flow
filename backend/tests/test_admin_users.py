"""Admin user listing and role-management regression tests."""

from __future__ import annotations

import asyncio
import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("AUTH_JWT_SECRET", "test-secret-key-admin-users-min-32")

from app.gateway.auth.config import AuthConfig, set_auth_config

_TEST_SECRET = "test-secret-key-admin-users-min-32"
_ADMIN_PASSWORD = "Adm1n!Pass99"
_USER_PASSWORD = "Us3r!Pass99"


@pytest.fixture(autouse=True)
def _setup_auth(tmp_path):
    """Use a fresh shared SQLite database and auth singleton per test."""
    from app.gateway import deps
    from app.gateway.routers.auth import _SETUP_STATUS_CACHE, _SETUP_STATUS_INFLIGHT
    from deerflow.persistence.engine import close_engine, init_engine

    set_auth_config(AuthConfig(jwt_secret=_TEST_SECRET))
    url = f"sqlite+aiosqlite:///{tmp_path}/admin_users.db"
    asyncio.run(init_engine("sqlite", url=url, sqlite_dir=str(tmp_path)))
    deps._cached_local_provider = None
    deps._cached_repo = None
    _SETUP_STATUS_CACHE.clear()
    _SETUP_STATUS_INFLIGHT.clear()
    try:
        yield
    finally:
        deps._cached_local_provider = None
        deps._cached_repo = None
        _SETUP_STATUS_CACHE.clear()
        _SETUP_STATUS_INFLIGHT.clear()
        asyncio.run(close_engine())


@pytest.fixture()
def app_client(_setup_auth):
    from app.gateway.app import create_app

    app = create_app()
    client = TestClient(app)
    response = client.post(
        "/api/v1/auth/initialize",
        json={"email": "admin@example.com", "password": _ADMIN_PASSWORD},
    )
    assert response.status_code == 201
    return app, client, response.json()


def _create_user(
    email: str,
    *,
    password: str = _USER_PASSWORD,
    role: str = "user",
    oauth_provider: str | None = None,
):
    from app.gateway.deps import get_local_provider

    provider = get_local_provider()
    if oauth_provider:
        return asyncio.run(
            provider.create_oauth_user(
                email=email,
                oauth_provider=oauth_provider,
                oauth_id=f"subject-{email}",
                system_role=role,
            )
        )
    return asyncio.run(
        provider.create_user(
            email=email,
            password=password,
            system_role=role,
        )
    )


def _csrf_headers(client: TestClient) -> dict[str, str]:
    token = client.cookies.get("csrf_token")
    assert token
    return {"X-CSRF-Token": token}


def _login(app, email: str, password: str) -> TestClient:
    client = TestClient(app)
    response = client.post(
        "/api/v1/auth/login/local",
        data={"username": email, "password": password},
    )
    assert response.status_code == 200
    return client


def test_repository_lists_users_in_stable_order_and_pages():
    from app.gateway.deps import get_local_provider

    _create_user("actor@example.com", role="admin")
    first = _create_user("first@example.com")
    second = _create_user("second@example.com", oauth_provider="oidc")

    users, total = asyncio.run(get_local_provider().list_users(offset=1, limit=2))

    assert total == 3
    assert [str(user.id) for user in users] == [str(first.id), str(second.id)]


def test_repository_role_change_is_atomic_idempotent_and_revokes_sessions():
    from app.gateway.deps import get_local_provider

    provider = get_local_provider()
    actor = _create_user("actor@example.com", role="admin")
    target = _create_user("target@example.com")

    changed = asyncio.run(
        provider.change_user_role(
            actor_id=str(actor.id),
            user_id=str(target.id),
            system_role="admin",
        )
    )
    assert changed.previous_role == "user"
    assert changed.changed is True
    assert changed.user.system_role == "admin"
    assert changed.user.token_version == target.token_version + 1

    unchanged = asyncio.run(
        provider.change_user_role(
            actor_id=str(actor.id),
            user_id=str(target.id),
            system_role="admin",
        )
    )
    assert unchanged.changed is False
    assert unchanged.user.token_version == changed.user.token_version


def test_repository_rejects_last_admin_demotion_without_side_effects():
    from app.gateway.auth.repositories.base import LastAdminError
    from app.gateway.deps import get_local_provider

    provider = get_local_provider()
    actor = _create_user("actor@example.com", role="admin")

    with pytest.raises(LastAdminError):
        asyncio.run(
            provider.change_user_role(
                actor_id=str(actor.id),
                user_id=str(actor.id),
                system_role="user",
            )
        )

    current = asyncio.run(provider.get_user(str(actor.id)))
    assert current is not None
    assert current.system_role == "admin"
    assert current.token_version == actor.token_version


def test_repository_concurrent_self_demotions_keep_one_admin():
    from app.gateway.auth.repositories.base import LastAdminError
    from app.gateway.deps import get_local_provider

    provider = get_local_provider()
    first = _create_user("first-admin@example.com", role="admin")
    second = _create_user("second-admin@example.com", role="admin")

    async def _demote_both():
        return await asyncio.gather(
            provider.change_user_role(
                actor_id=str(first.id),
                user_id=str(first.id),
                system_role="user",
            ),
            provider.change_user_role(
                actor_id=str(second.id),
                user_id=str(second.id),
                system_role="user",
            ),
            return_exceptions=True,
        )

    results = asyncio.run(_demote_both())
    assert sum(result.changed is True for result in results if not isinstance(result, BaseException)) == 1
    assert sum(isinstance(result, LastAdminError) for result in results) == 1
    assert asyncio.run(provider.count_admin_users()) == 1


def test_generic_update_cannot_restore_a_stale_role_or_token_version():
    from app.gateway.deps import get_local_provider

    provider = get_local_provider()
    actor = _create_user("actor@example.com", role="admin")
    target = _create_user("stale@example.com")
    stale = asyncio.run(provider.get_user(str(target.id)))
    assert stale is not None

    changed = asyncio.run(
        provider.change_user_role(
            actor_id=str(actor.id),
            user_id=str(target.id),
            system_role="admin",
        )
    )
    stale.password_hash = "new-hash"
    asyncio.run(provider.update_user(stale))

    current = asyncio.run(provider.get_user(str(target.id)))
    assert current is not None
    assert current.password_hash == "new-hash"
    assert current.system_role == "admin"
    assert current.token_version == changed.user.token_version


def test_admin_list_is_safe_and_includes_local_and_oidc_users(app_client):
    _app, client, _admin = app_client
    local = _create_user("local@example.com")
    oidc = _create_user("oidc@example.com", oauth_provider="keycloak")

    response = client.get("/api/v1/admin/users")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    by_id = {item["id"]: item for item in body["users"]}
    assert by_id[str(local.id)]["oauth_provider"] is None
    assert by_id[str(oidc.id)]["oauth_provider"] == "keycloak"
    assert set(by_id[str(local.id)]) == {
        "id",
        "email",
        "system_role",
        "created_at",
        "needs_setup",
        "oauth_provider",
    }


def test_admin_can_promote_an_existing_oidc_user(app_client):
    from app.gateway.deps import get_local_provider

    _app, client, _admin = app_client
    target = _create_user("managed-oidc@example.com", oauth_provider="keycloak")

    response = client.patch(
        f"/api/v1/admin/users/{target.id}/role",
        json={"system_role": "admin"},
        headers=_csrf_headers(client),
    )

    assert response.status_code == 200
    assert response.json()["user"]["system_role"] == "admin"
    assert response.json()["user"]["oauth_provider"] == "keycloak"
    current = asyncio.run(get_local_provider().get_user(str(target.id)))
    assert current is not None
    assert current.oauth_id == f"subject-{target.email}"


def test_regular_user_cannot_list_users_or_promote_itself(app_client):
    from app.gateway.deps import get_local_provider

    app, _admin_client, _admin = app_client
    target = _create_user("regular@example.com")
    user_client = _login(app, target.email, _USER_PASSWORD)

    listed = user_client.get("/api/v1/admin/users")
    promoted = user_client.patch(
        f"/api/v1/admin/users/{target.id}/role",
        json={"system_role": "admin"},
        headers=_csrf_headers(user_client),
    )

    assert listed.status_code == 403
    assert promoted.status_code == 403
    current = asyncio.run(get_local_provider().get_user(str(target.id)))
    assert current is not None
    assert current.system_role == "user"


def test_role_change_revokes_target_session_and_relogin_sees_new_role(
    app_client,
    caplog,
):
    import logging

    app, admin_client, _admin = app_client
    target = _create_user("session@example.com")
    target_client = _login(app, target.email, _USER_PASSWORD)
    assert target_client.get("/api/v1/auth/me").status_code == 200
    caplog.set_level(logging.INFO, logger="app.gateway.routers.admin_users")

    changed = admin_client.patch(
        f"/api/v1/admin/users/{target.id}/role",
        json={"system_role": "admin"},
        headers=_csrf_headers(admin_client),
    )

    assert changed.status_code == 200
    assert changed.json()["previous_role"] == "user"
    assert changed.json()["sessions_invalidated"] is True
    assert any(f"target_user_id={target.id}" in record.getMessage() and "previous_role=user" in record.getMessage() and "new_role=admin" in record.getMessage() for record in caplog.records)
    assert target_client.get("/api/v1/auth/me").status_code == 401

    refreshed = _login(app, target.email, _USER_PASSWORD)
    me = refreshed.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["system_role"] == "admin"


def test_admin_demotion_revokes_target_session_and_relogin_sees_user(app_client):
    app, admin_client, _admin = app_client
    target = _create_user("demoted@example.com", role="admin")
    target_client = _login(app, target.email, _USER_PASSWORD)

    changed = admin_client.patch(
        f"/api/v1/admin/users/{target.id}/role",
        json={"system_role": "user"},
        headers=_csrf_headers(admin_client),
    )

    assert changed.status_code == 200
    assert changed.json()["previous_role"] == "admin"
    assert changed.json()["user"]["system_role"] == "user"
    assert changed.json()["sessions_invalidated"] is True
    assert target_client.get("/api/v1/auth/me").status_code == 401

    refreshed = _login(app, target.email, _USER_PASSWORD)
    assert refreshed.get("/api/v1/auth/me").json()["system_role"] == "user"


def test_role_change_requires_csrf_token(app_client):
    _app, client, _admin = app_client
    target = _create_user("csrf-target@example.com")

    response = client.patch(
        f"/api/v1/admin/users/{target.id}/role",
        json={"system_role": "admin"},
    )

    assert response.status_code == 403
    assert response.json()["detail"].startswith("CSRF token")


def test_auth_disabled_mode_rejects_a_retained_real_admin_session(
    app_client,
    monkeypatch,
):
    _app, client, _admin = app_client
    target = _create_user("auth-disabled-target@example.com")
    monkeypatch.delenv("DEER_FLOW_ENV", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "1")

    # Auth-disabled mode skips global CSRF checks, so the route itself must be
    # unavailable even when this client retains a valid real admin cookie.
    response = client.patch(
        f"/api/v1/admin/users/{target.id}/role",
        json={"system_role": "admin"},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "admin_required"


def test_api_returns_404_and_protects_last_admin(app_client):
    _app, client, admin = app_client
    missing = client.patch(
        "/api/v1/admin/users/00000000-0000-0000-0000-000000000000/role",
        json={"system_role": "admin"},
        headers=_csrf_headers(client),
    )
    last_admin = client.patch(
        f"/api/v1/admin/users/{admin['id']}/role",
        json={"system_role": "user"},
        headers=_csrf_headers(client),
    )

    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "user_not_found"
    assert last_admin.status_code == 409
    assert last_admin.json()["detail"]["code"] == "last_admin"


def test_repository_rechecks_actor_role_inside_role_change_transaction():
    from app.gateway.auth.repositories.base import AdminRoleRequiredError
    from app.gateway.deps import get_local_provider

    provider = get_local_provider()
    stale_actor = _create_user("former-admin@example.com", role="user")
    target = _create_user("other@example.com")

    with pytest.raises(AdminRoleRequiredError):
        asyncio.run(
            provider.change_user_role(
                actor_id=str(stale_actor.id),
                user_id=str(target.id),
                system_role="admin",
            )
        )

    current = asyncio.run(provider.get_user(str(target.id)))
    assert current is not None
    assert current.system_role == "user"
