"""End-to-end auth API tests for the main auth user journeys."""

from app.plugins.auth.security.csrf import CSRF_HEADER_NAME


def _initialize_payload(**overrides):
    return {
        "email": "admin@example.com",
        "password": "Str0ng!Pass99",
        **overrides,
    }


def _register_payload(**overrides):
    return {
        "email": "user@example.com",
        "password": "Str0ng!Pass99",
        **overrides,
    }


def _login(client, *, email="user@example.com", password="Str0ng!Pass99"):
    return client.post(
        "/api/v1/auth/login/local",
        data={"username": email, "password": password},
    )


def _csrf_headers(client) -> dict[str, str]:
    token = client.cookies.get("csrf_token")
    assert token, "csrf_token cookie is required before calling protected POST endpoints"
    return {CSRF_HEADER_NAME: token}


def test_initialize_returns_admin_and_sets_session_cookie(client):
    response = client.post("/api/v1/auth/initialize", json=_initialize_payload())

    assert response.status_code == 201
    assert response.json()["email"] == "admin@example.com"
    assert response.json()["system_role"] == "admin"
    assert "access_token" in response.cookies
    assert "access_token" in client.cookies


def test_me_returns_initialized_admin_identity(client):
    initialize = client.post("/api/v1/auth/initialize", json=_initialize_payload())
    assert initialize.status_code == 201

    response = client.get("/api/v1/auth/me")

    assert response.status_code == 200
    assert response.json() == {
        "id": response.json()["id"],
        "email": "admin@example.com",
        "system_role": "admin",
        "needs_setup": False,
    }


def test_setup_status_flips_after_initialize(client):
    before = client.get("/api/v1/auth/setup-status")
    assert before.status_code == 200
    assert before.json() == {"needs_setup": True}

    initialize = client.post("/api/v1/auth/initialize", json=_initialize_payload())
    assert initialize.status_code == 201

    after = client.get("/api/v1/auth/setup-status")
    assert after.status_code == 200
    assert after.json() == {"needs_setup": False}


def test_register_logs_in_user_and_me_returns_identity(client):
    response = client.post("/api/v1/auth/register", json=_register_payload())

    assert response.status_code == 201
    assert response.json()["email"] == "user@example.com"
    assert response.json()["system_role"] == "user"
    assert "access_token" in client.cookies
    assert "csrf_token" in client.cookies

    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "user@example.com"
    assert me.json()["system_role"] == "user"
    assert me.json()["needs_setup"] is False


def test_me_requires_authentication(client):
    response = client.get("/api/v1/auth/me")

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "not_authenticated"


def test_logout_clears_session_and_me_is_denied(client):
    register = client.post("/api/v1/auth/register", json=_register_payload())
    assert register.status_code == 201

    logout = client.post("/api/v1/auth/logout")
    assert logout.status_code == 200
    assert logout.json() == {"message": "Successfully logged out"}

    me = client.get("/api/v1/auth/me")
    assert me.status_code == 401
    assert me.json()["detail"]["code"] == "not_authenticated"


def test_login_local_restores_session_after_logout(client):
    register = client.post("/api/v1/auth/register", json=_register_payload())
    assert register.status_code == 201
    assert client.post("/api/v1/auth/logout").status_code == 200

    login = _login(client)
    assert login.status_code == 200
    assert login.json()["needs_setup"] is False
    assert "access_token" in client.cookies
    assert "csrf_token" in client.cookies

    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "user@example.com"


def test_change_password_updates_credentials_and_rotates_login(client):
    register = client.post("/api/v1/auth/register", json=_register_payload())
    assert register.status_code == 201

    change = client.post(
        "/api/v1/auth/change-password",
        json={
            "current_password": "Str0ng!Pass99",
            "new_password": "An0ther!Pass88",
            "new_email": "renamed@example.com",
        },
        headers=_csrf_headers(client),
    )
    assert change.status_code == 200
    assert change.json() == {"message": "Password changed successfully"}

    assert client.post("/api/v1/auth/logout").status_code == 200

    old_login = _login(client)
    assert old_login.status_code == 401
    assert old_login.json()["detail"]["code"] == "invalid_credentials"

    new_login = _login(client, email="renamed@example.com", password="An0ther!Pass88")
    assert new_login.status_code == 200

    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "renamed@example.com"


def test_oauth_endpoints_expose_current_placeholder_behavior(client):
    unsupported = client.get("/api/v1/auth/oauth/not-a-provider")
    assert unsupported.status_code == 400

    github = client.get("/api/v1/auth/oauth/github")
    assert github.status_code == 501

    callback = client.get("/api/v1/auth/callback/github", params={"code": "abc", "state": "xyz"})
    assert callback.status_code == 501
