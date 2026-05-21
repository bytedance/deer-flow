"""Integration tests for InsBase authentication flow.

Tests the full login/refresh/authenticate API endpoints with
a mocked ins-base-rpc backend.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.gateway.auth.config import AuthConfig, set_auth_config

_TEST_SECRET = "test-secret-for-ins-base-tests-min32-chars!!"


@pytest.fixture(scope="module")
def rsa_key_pair():
    """Generate a real RSA key pair for testing."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    return private_key, pub_pem


def _make_app():
    """Create a FastAPI app with all routers for integration testing."""
    from app.gateway.app import create_app

    return create_app()


def _make_client():
    """Create a TestClient for integration testing."""
    return TestClient(_make_app())


def _setup_config():
    """Set up auth config for testing."""
    set_auth_config(AuthConfig(jwt_secret=_TEST_SECRET))


@pytest.mark.asyncio
async def test_ins_base_login_endpoint(rsa_key_pair):
    """POST /api/v1/auth/ins-base/login calls ins-base-rpc and returns token."""
    _, pub_pem = rsa_key_pair

    _setup_config()
    client = _make_client()

    # Mock the provider functions
    mock_provider = MagicMock()
    mock_provider.authenticate = AsyncMock(return_value=type("obj", (), {
        "ins_base_token": "ins-base-jwt-token",
        "ins_base_refresh": "ins-base-refresh-token",
        "tenant_id": "default",
        "id": "test-id",
        "email": "test@ins-base",
        "password_hash": None,
        "system_role": "user",
        "needs_setup": False,
        "token_version": 0,
    })())
    mock_provider.refresh_token = AsyncMock(return_value="new-ins-base-token")

    with patch("app.gateway.routers.ins_base_auth.get_ins_base_provider", return_value=mock_provider):
        response = client.post(
            "/api/v1/auth/ins-base/login",
            json={"username": "testuser", "password": "testpass"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["token"] == "ins-base-jwt-token"
    assert data["refresh"] == "ins-base-refresh-token"
    assert data["tenant_id"] == "default"


@pytest.mark.asyncio
async def test_ins_base_refresh_endpoint():
    """POST /api/v1/auth/ins-base/refresh calls ins-base-rpc and returns new token."""
    _setup_config()
    client = _make_client()

    mock_provider = MagicMock()
    mock_provider.refresh_token = AsyncMock(return_value="new-ins-base-token")

    with patch("app.gateway.routers.ins_base_auth.get_ins_base_provider", return_value=mock_provider):
        response = client.post(
            "/api/v1/auth/ins-base/refresh",
            json={"refresh_token": "valid-refresh-token"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["token"] == "new-ins-base-token"
    assert data["tenant_id"] == "default"


@pytest.mark.asyncio
async def test_cookie_refresh_endpoint_allows_refresh_without_access_token():
    """POST /api/v1/auth/refresh reaches the handler with only refresh+CSRF cookies."""
    _setup_config()
    client = _make_client()

    class _DummyInsBaseProvider:
        refresh_token = AsyncMock(return_value="new-ins-base-token")

    with (
        patch("app.gateway.routers.auth.InsBaseAuthProvider", _DummyInsBaseProvider),
        patch("app.gateway.deps.get_ins_base_provider", return_value=_DummyInsBaseProvider()),
    ):
        response = client.post(
            "/api/v1/auth/refresh",
            cookies={
                "refresh_token": "valid-refresh-token",
                "csrf_token": "csrf-test-token",
            },
            headers={"X-CSRF-Token": "csrf-test-token"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["message"] == "Token refreshed"


@pytest.mark.asyncio
async def test_ins_base_refresh_failure():
    """Failed refresh returns 401."""
    _setup_config()
    client = _make_client()

    mock_provider = MagicMock()
    mock_provider.refresh_token = AsyncMock(return_value=None)

    with patch("app.gateway.routers.ins_base_auth.get_ins_base_provider", return_value=mock_provider):
        response = client.post(
            "/api/v1/auth/ins-base/refresh",
            json={"refresh_token": "invalid-refresh-token"},
        )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_ins_base_authenticate_success():
    """POST /api/v1/auth/ins-base/authenticate verifies token via ins-base-rpc."""
    _setup_config()
    client = _make_client()

    mock_provider = MagicMock()
    mock_provider.get_user = AsyncMock(return_value=type("obj", (), {
        "ins_base_permissions": ["read", "write"],
        "email": "user@example.com",
    })())

    with patch("app.gateway.routers.ins_base_auth.get_ins_base_provider", return_value=mock_provider):
        client.cookies = {"access_token": "valid-token"}
        response = client.post(
            "/api/v1/auth/ins-base/authenticate",
        )

    assert response.status_code == 200
    data = response.json()
    assert data["authenticated"] is True
    assert "read" in data["permissions"]


@pytest.mark.asyncio
async def test_ins_base_authenticate_failure():
    """Failed authentication returns 401."""
    _setup_config()
    client = _make_client()

    mock_provider = MagicMock()
    mock_provider.get_user = AsyncMock(return_value=None)

    with patch("app.gateway.routers.ins_base_auth.get_ins_base_provider", return_value=mock_provider):
        client.cookies = {"access_token": "invalid-token"}
        response = client.post(
            "/api/v1/auth/ins-base/authenticate",
        )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_ins_base_authenticate_upstream_unavailable_returns_503():
    """Upstream auth transport failures return 503 instead of 401."""
    from app.gateway.auth.ins_base_provider import AuthProviderUnavailableError

    _setup_config()
    client = _make_client()

    mock_provider = MagicMock()
    mock_provider.get_user = AsyncMock(
        side_effect=AuthProviderUnavailableError("ins-base auth service unavailable")
    )

    with patch("app.gateway.routers.ins_base_auth.get_ins_base_provider", return_value=mock_provider):
        client.cookies = {"access_token": "invalid-token"}
        response = client.post(
            "/api/v1/auth/ins-base/authenticate",
        )

    assert response.status_code == 503


@pytest.mark.asyncio
async def test_ins_base_authenticate_no_token():
    """Missing token returns 401."""
    _setup_config()
    client = _make_client()

    with patch("app.gateway.routers.ins_base_auth.get_ins_base_provider", return_value=MagicMock()):
        response = client.post("/api/v1/auth/ins-base/authenticate")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_ins_base_login_no_provider():
    """Login with no provider configured returns 503."""
    _setup_config()
    client = _make_client()

    with patch("app.gateway.routers.ins_base_auth.get_ins_base_provider", return_value=None):
        response = client.post(
            "/api/v1/auth/ins-base/login",
            json={"username": "test", "password": "test"},
        )

    assert response.status_code == 503


@pytest.mark.asyncio
async def test_ins_base_login_auth_failure():
    """Failed login returns 401."""
    _setup_config()
    client = _make_client()

    mock_provider = MagicMock()
    mock_provider.authenticate = AsyncMock(side_effect=RuntimeError("登录失败"))

    with patch("app.gateway.routers.ins_base_auth.get_ins_base_provider", return_value=mock_provider):
        response = client.post(
            "/api/v1/auth/ins-base/login",
            json={"username": "test", "password": "wrong"},
        )

    assert response.status_code == 401
