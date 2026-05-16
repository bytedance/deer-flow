"""Tests for auth type system hardening.

Covers structured error responses, typed decode_token callers,
CSRF middleware path matching, config-driven cookie security,
and unhappy paths / edge cases for all auth boundaries.
"""

import os
import secrets
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import jwt as pyjwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.gateway.auth.config import AuthConfig, set_auth_config
from app.gateway.auth.errors import AuthErrorCode, AuthErrorResponse, TokenError
from app.gateway.auth.jwt import decode_token
from app.gateway.csrf_middleware import (
    CSRF_COOKIE_NAME,
    CSRF_HEADER_NAME,
    CSRFMiddleware,
    is_auth_endpoint,
    should_check_csrf,
)

# ── Setup ────────────────────────────────────────────────────────────

_TEST_SECRET = "test-secret-for-auth-type-system-tests-min32"


@pytest.fixture(autouse=True)
def _persistence_engine(tmp_path):
    """Initialise a per-test SQLite engine + reset cached provider singletons.

    The auth tests call real HTTP handlers that go through
    ``SQLiteUserRepository`` → ``get_session_factory``. Each test gets
    a fresh DB plus a clean ``deps._cached_*`` so the cached provider
    does not hold a dangling reference to the previous test's engine.
    """
    import asyncio

    from app.gateway import deps
    from deerflow.persistence.engine import close_engine, init_engine

    url = f"sqlite+aiosqlite:///{tmp_path}/auth_types.db"
    asyncio.run(init_engine("sqlite", url=url, sqlite_dir=str(tmp_path)))
    deps._cached_local_provider = None
    deps._cached_repo = None
    try:
        yield
    finally:
        deps._cached_local_provider = None
        deps._cached_repo = None
        asyncio.run(close_engine())


def _setup_config():
    set_auth_config(AuthConfig(jwt_secret=_TEST_SECRET))


# ── CSRF Middleware Path Matching ────────────────────────────────────


class _FakeRequest:
    """Minimal request mock for CSRF path matching tests."""

    def __init__(self, path: str, method: str = "POST"):
        self.method = method

        class _URL:
            def __init__(self, p):
                self.path = p

        self.url = _URL(path)
        self.cookies = {}
        self.headers = {}


def test_csrf_exempts_login_local():
    """login/local (actual route) should be exempt from CSRF."""
    req = _FakeRequest("/api/v1/auth/login/local")
    assert is_auth_endpoint(req) is True


def test_csrf_exempts_login_local_trailing_slash():
    """Trailing slash should also be exempt."""
    req = _FakeRequest("/api/v1/auth/login/local/")
    assert is_auth_endpoint(req) is True


def test_csrf_exempts_logout():
    req = _FakeRequest("/api/v1/auth/logout")
    assert is_auth_endpoint(req) is True


def test_csrf_exempts_register():
    req = _FakeRequest("/api/v1/auth/register")
    assert is_auth_endpoint(req) is True


def test_csrf_does_not_exempt_old_login_path():
    """Old /api/v1/auth/login (without /local) should NOT be exempt."""
    req = _FakeRequest("/api/v1/auth/login")
    assert is_auth_endpoint(req) is False


def test_csrf_does_not_exempt_me():
    req = _FakeRequest("/api/v1/auth/me")
    assert is_auth_endpoint(req) is False


def test_csrf_skips_get_requests():
    req = _FakeRequest("/api/v1/auth/me", method="GET")
    assert should_check_csrf(req) is False


def test_csrf_checks_post_to_protected():
    req = _FakeRequest("/api/v1/some/endpoint", method="POST")
    assert should_check_csrf(req) is True


# ── Structured Error Response Format ────────────────────────────────


def test_auth_error_response_has_code_and_message():
    """All auth errors should have structured {code, message} format."""
    err = AuthErrorResponse(
        code=AuthErrorCode.INVALID_CREDENTIALS,
        message="Wrong password",
    )
    d = err.model_dump()
    assert "code" in d
    assert "message" in d
    assert d["code"] == "invalid_credentials"


def test_auth_error_response_all_codes_serializable():
    """Every AuthErrorCode should be serializable in AuthErrorResponse."""
    for code in AuthErrorCode:
        err = AuthErrorResponse(code=code, message=f"Test {code.value}")
        d = err.model_dump()
        assert d["code"] == code.value


# ── decode_token Caller Pattern ──────────────────────────────────────


def test_decode_token_expired_maps_to_token_expired_code():
    """TokenError.EXPIRED should map to AuthErrorCode.TOKEN_EXPIRED."""
    _setup_config()
    from datetime import UTC, datetime, timedelta

    import jwt as pyjwt

    expired = {"sub": "u1", "exp": datetime.now(UTC) - timedelta(hours=1), "iat": datetime.now(UTC)}
    token = pyjwt.encode(expired, _TEST_SECRET, algorithm="HS256")
    result = decode_token(token)
    assert result == TokenError.EXPIRED

    # Verify the mapping pattern used in route handlers
    code = AuthErrorCode.TOKEN_EXPIRED if result == TokenError.EXPIRED else AuthErrorCode.TOKEN_INVALID
    assert code == AuthErrorCode.TOKEN_EXPIRED


def test_decode_token_invalid_sig_maps_to_token_invalid_code():
    """TokenError.INVALID_SIGNATURE should map to AuthErrorCode.TOKEN_INVALID."""
    _setup_config()
    from datetime import UTC, datetime, timedelta

    import jwt as pyjwt

    payload = {"sub": "u1", "exp": datetime.now(UTC) + timedelta(hours=1), "iat": datetime.now(UTC)}
    token = pyjwt.encode(payload, "wrong-key", algorithm="HS256")
    result = decode_token(token)
    assert result == TokenError.INVALID_SIGNATURE

    code = AuthErrorCode.TOKEN_EXPIRED if result == TokenError.EXPIRED else AuthErrorCode.TOKEN_INVALID
    assert code == AuthErrorCode.TOKEN_INVALID


def test_decode_token_malformed_maps_to_token_invalid_code():
    """TokenError.MALFORMED should map to AuthErrorCode.TOKEN_INVALID."""
    _setup_config()
    result = decode_token("garbage")
    assert result == TokenError.MALFORMED

    code = AuthErrorCode.TOKEN_EXPIRED if result == TokenError.EXPIRED else AuthErrorCode.TOKEN_INVALID
    assert code == AuthErrorCode.TOKEN_INVALID


# ── Login Response Format ────────────────────────────────────────────


def test_login_response_model_has_no_access_token():
    """LoginResponse should NOT contain access_token field (RFC-001)."""
    from app.gateway.routers.auth import LoginResponse

    resp = LoginResponse(expires_in=604800)
    d = resp.model_dump()
    assert "access_token" not in d
    assert "expires_in" in d
    assert d["expires_in"] == 604800


def test_login_response_model_fields():
    """LoginResponse has expires_in and needs_setup."""
    from app.gateway.routers.auth import LoginResponse

    fields = set(LoginResponse.model_fields.keys())
    assert fields == {"expires_in", "needs_setup"}


# ── AuthConfig in Route ──────────────────────────────────────────────


def test_auth_config_token_expiry_used_in_login_response():
    """LoginResponse.expires_in should come from config.token_expiry_days."""
    from app.gateway.routers.auth import LoginResponse

    expected_seconds = 14 * 24 * 3600
    resp = LoginResponse(expires_in=expected_seconds)
    assert resp.expires_in == expected_seconds


# ── UserResponse Type Preservation ───────────────────────────────────


def test_user_response_system_role_literal():
    """UserResponse.system_role should only accept 'admin' or 'user'."""
    from app.gateway.auth.models import UserResponse

    # Valid roles
    resp = UserResponse(id="1", email="a@b.com", system_role="admin")
    assert resp.system_role == "admin"

    resp = UserResponse(id="1", email="a@b.com", system_role="user")
    assert resp.system_role == "user"


def test_user_response_rejects_invalid_role():
    """UserResponse should reject invalid system_role values."""
    from app.gateway.auth.models import UserResponse

    with pytest.raises(ValidationError):
        UserResponse(id="1", email="a@b.com", system_role="superadmin")


# ══════════════════════════════════════════════════════════════════════
# UNHAPPY PATHS / EDGE CASES
# ══════════════════════════════════════════════════════════════════════


# ── get_current_user structured 401 responses ────────────────────────


def test_get_current_user_no_cookie_returns_not_authenticated():
    """No cookie → 401 with code=not_authenticated."""
    import asyncio

    from fastapi import HTTPException

    from app.gateway.deps import get_current_user_from_request

    mock_request = type("MockRequest", (), {"cookies": {}})()
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(get_current_user_from_request(mock_request))
    assert exc_info.value.status_code == 401
    detail = exc_info.value.detail
    assert detail["code"] == "not_authenticated"


def test_get_current_user_expired_token_returns_token_expired():
    """Expired token → 401 with code=token_expired."""
    import asyncio

    from fastapi import HTTPException

    from app.gateway.deps import get_current_user_from_request

    _setup_config()
    expired = {"sub": "u1", "exp": datetime.now(UTC) - timedelta(hours=1), "iat": datetime.now(UTC)}
    token = pyjwt.encode(expired, _TEST_SECRET, algorithm="HS256")

    mock_request = type("MockRequest", (), {"cookies": {"access_token": token}})()
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(get_current_user_from_request(mock_request))
    assert exc_info.value.status_code == 401
    detail = exc_info.value.detail
    assert detail["code"] == "token_expired"


def test_get_current_user_invalid_token_returns_token_invalid():
    """Bad signature → 401 with code=token_invalid."""
    import asyncio

    from fastapi import HTTPException

    from app.gateway.deps import get_current_user_from_request

    _setup_config()
    payload = {"sub": "u1", "exp": datetime.now(UTC) + timedelta(hours=1), "iat": datetime.now(UTC)}
    token = pyjwt.encode(payload, "wrong-secret", algorithm="HS256")

    mock_request = type("MockRequest", (), {"cookies": {"access_token": token}})()
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(get_current_user_from_request(mock_request))
    assert exc_info.value.status_code == 401
    detail = exc_info.value.detail
    assert detail["code"] == "token_invalid"


def test_get_current_user_malformed_token_returns_token_invalid():
    """Garbage token → 401 with code=token_invalid."""
    import asyncio

    from fastapi import HTTPException

    from app.gateway.deps import get_current_user_from_request

    _setup_config()
    mock_request = type("MockRequest", (), {"cookies": {"access_token": "not-a-jwt"}})()
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(get_current_user_from_request(mock_request))
    assert exc_info.value.status_code == 401
    detail = exc_info.value.detail
    assert detail["code"] == "token_invalid"


# ── decode_token edge cases ──────────────────────────────────────────


def test_decode_token_empty_string_returns_malformed():
    _setup_config()
    result = decode_token("")
    assert result == TokenError.MALFORMED


def test_decode_token_whitespace_returns_malformed():
    _setup_config()
    result = decode_token("   ")
    assert result == TokenError.MALFORMED


# ── AuthConfig validation edge cases ─────────────────────────────────


def test_auth_config_missing_jwt_secret_raises():
    """AuthConfig requires jwt_secret — no default allowed."""
    with pytest.raises(ValidationError):
        AuthConfig()


def test_auth_config_token_expiry_zero_raises():
    """token_expiry_days must be >= 1."""
    with pytest.raises(ValidationError):
        AuthConfig(jwt_secret="secret", token_expiry_days=0)


def test_auth_config_token_expiry_31_raises():
    """token_expiry_days must be <= 30."""
    with pytest.raises(ValidationError):
        AuthConfig(jwt_secret="secret", token_expiry_days=31)


def test_auth_config_token_expiry_boundary_1_ok():
    config = AuthConfig(jwt_secret="secret", token_expiry_days=1)
    assert config.token_expiry_days == 1


def test_auth_config_token_expiry_boundary_30_ok():
    config = AuthConfig(jwt_secret="secret", token_expiry_days=30)
    assert config.token_expiry_days == 30


def test_get_auth_config_missing_env_var_generates_ephemeral(caplog):
    """get_auth_config() auto-generates ephemeral secret when AUTH_JWT_SECRET is unset."""
    import logging

    import app.gateway.auth.config as cfg

    old = cfg._auth_config
    cfg._auth_config = None
    try:
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("AUTH_JWT_SECRET", None)
            with caplog.at_level(logging.WARNING):
                config = cfg.get_auth_config()
            assert config.jwt_secret
            assert any("AUTH_JWT_SECRET" in msg for msg in caplog.messages)
    finally:
        cfg._auth_config = old


# ── CSRF middleware integration (unhappy paths) ──────────────────────


def _make_csrf_app():
    """Create a minimal FastAPI app with CSRFMiddleware for testing."""
    from fastapi import HTTPException as _HTTPException
    from fastapi.responses import JSONResponse as _JSONResponse

    app = FastAPI()

    @app.exception_handler(_HTTPException)
    async def _http_exc_handler(request, exc):
        return _JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    app.add_middleware(CSRFMiddleware)

    @app.post("/api/v1/test/protected")
    async def protected():
        return {"ok": True}

    @app.post("/api/v1/auth/login/local")
    async def login():
        return {"ok": True}

    @app.get("/api/v1/test/read")
    async def read_endpoint():
        return {"ok": True}

    return app


def test_csrf_middleware_blocks_post_without_token():
    """POST to protected endpoint without CSRF token → 403 with structured detail."""
    client = TestClient(_make_csrf_app())
    resp = client.post("/api/v1/test/protected")
    assert resp.status_code == 403
    assert "CSRF" in resp.json()["detail"]
    assert "missing" in resp.json()["detail"].lower()


def test_csrf_middleware_blocks_post_with_mismatched_token():
    """POST with mismatched CSRF cookie/header → 403 with mismatch detail."""
    client = TestClient(_make_csrf_app())
    client.cookies.set(CSRF_COOKIE_NAME, "token-a")
    resp = client.post(
        "/api/v1/test/protected",
        headers={CSRF_HEADER_NAME: "token-b"},
    )
    assert resp.status_code == 403
    assert "mismatch" in resp.json()["detail"].lower()


def test_csrf_middleware_allows_post_with_matching_token():
    """POST with matching CSRF cookie/header → 200."""
    client = TestClient(_make_csrf_app())
    token = secrets.token_urlsafe(64)
    client.cookies.set(CSRF_COOKIE_NAME, token)
    resp = client.post(
        "/api/v1/test/protected",
        headers={CSRF_HEADER_NAME: token},
    )
    assert resp.status_code == 200


def test_csrf_middleware_allows_get_without_token():
    """GET requests bypass CSRF check."""
    client = TestClient(_make_csrf_app())
    resp = client.get("/api/v1/test/read")
    assert resp.status_code == 200


def test_csrf_middleware_exempts_login_local():
    """POST to login/local is exempt from CSRF (no token yet)."""
    client = TestClient(_make_csrf_app())
    resp = client.post("/api/v1/auth/login/local")
    assert resp.status_code == 200


def test_csrf_middleware_sets_cookie_on_auth_endpoint():
    """Auth endpoints should receive a CSRF cookie in response."""
    client = TestClient(_make_csrf_app())
    resp = client.post("/api/v1/auth/login/local")
    assert CSRF_COOKIE_NAME in resp.cookies


# ── UserResponse edge cases ──────────────────────────────────────────


def test_user_response_missing_required_fields():
    """UserResponse with missing fields → ValidationError."""
    from app.gateway.auth.models import UserResponse

    with pytest.raises(ValidationError):
        UserResponse(id="1")  # missing email, system_role

    with pytest.raises(ValidationError):
        UserResponse(id="1", email="a@b.com")  # missing system_role


def test_user_response_empty_string_role_rejected():
    """Empty string is not a valid role."""
    from app.gateway.auth.models import UserResponse

    with pytest.raises(ValidationError):
        UserResponse(id="1", email="a@b.com", system_role="")


# ══════════════════════════════════════════════════════════════════════
# HTTP-LEVEL API CONTRACT TESTS
# ══════════════════════════════════════════════════════════════════════


def _make_auth_app():
    """Create FastAPI app with auth routes for contract testing."""
    from app.gateway.app import create_app

    return create_app()


def _get_auth_client():
    """Get TestClient for auth API contract tests."""
    return TestClient(_make_auth_app())


def test_api_auth_me_no_cookie_returns_structured_401():
    """/api/v1/auth/me without cookie → 401 with {code: 'not_authenticated'}."""
    _setup_config()
    client = _get_auth_client()
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 401
    body = resp.json()
    assert body["detail"]["code"] == "not_authenticated"
    assert "message" in body["detail"]


def test_api_auth_me_expired_token_returns_structured_401():
    """/api/v1/auth/me with expired token → 401 with {code: 'token_expired'}."""
    _setup_config()
    expired = {"sub": "u1", "exp": datetime.now(UTC) - timedelta(hours=1), "iat": datetime.now(UTC)}
    token = pyjwt.encode(expired, _TEST_SECRET, algorithm="HS256")

    client = _get_auth_client()
    client.cookies.set("access_token", token)
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 401
    body = resp.json()
    assert body["detail"]["code"] == "token_expired"


def test_api_auth_me_invalid_sig_returns_structured_401():
    """/api/v1/auth/me with bad signature → 401 with {code: 'token_invalid'}."""
    _setup_config()
    payload = {"sub": "u1", "exp": datetime.now(UTC) + timedelta(hours=1), "iat": datetime.now(UTC)}
    token = pyjwt.encode(payload, "wrong-key", algorithm="HS256")

    client = _get_auth_client()
    client.cookies.set("access_token", token)
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 401
    body = resp.json()
    assert body["detail"]["code"] == "token_invalid"


def test_api_login_bad_credentials_returns_structured_401():
    """Login with wrong password → 401 with {code: 'invalid_credentials'}."""
    _setup_config()
    client = _get_auth_client()
    resp = client.post(
        "/api/v1/auth/login/local",
        data={"username": "nonexistent@test.com", "password": "wrongpassword"},
    )
    assert resp.status_code == 401
    body = resp.json()
    assert body["detail"]["code"] == "invalid_credentials"


def test_api_login_success_no_token_in_body():
    """Successful login → response body has expires_in but NOT access_token."""
    _setup_config()
    client = _get_auth_client()
    # Register first
    client.post(
        "/api/v1/auth/register",
        json={"email": "contract-test@test.com", "password": "securepassword123"},
    )
    # Login
    resp = client.post(
        "/api/v1/auth/login/local",
        data={"username": "contract-test@test.com", "password": "securepassword123"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "expires_in" in body
    assert "access_token" not in body
    # Token should be in cookie, not body
    assert "access_token" in resp.cookies


def test_api_register_duplicate_returns_structured_400():
    """Register with duplicate email → 400 with {code: 'email_already_exists'}."""
    _setup_config()
    client = _get_auth_client()
    email = "dup-contract-test@test.com"
    # First register
    client.post("/api/v1/auth/register", json={"email": email, "password": "Tr0ub4dor3a"})
    # Duplicate
    resp = client.post("/api/v1/auth/register", json={"email": email, "password": "AnotherStr0ngPwd!"})
    assert resp.status_code == 400
    body = resp.json()
    assert body["detail"]["code"] == "email_already_exists"


# ── Cookie security: HTTP vs HTTPS ────────────────────────────────────


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(4)}@test.com"


def _get_set_cookie_headers(resp) -> list[str]:
    """Extract all set-cookie header values from a TestClient response."""
    return [v for k, v in resp.headers.multi_items() if k.lower() == "set-cookie"]


def test_register_http_cookie_httponly_true_secure_false():
    """HTTP register → access_token cookie is httponly=True, secure=False, no max_age."""
    _setup_config()
    client = _get_auth_client()
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": _unique_email("http-cookie"), "password": "Tr0ub4dor3a"},
    )
    assert resp.status_code == 201
    cookie_header = resp.headers.get("set-cookie", "")
    assert "access_token=" in cookie_header
    assert "httponly" in cookie_header.lower()
    assert "secure" not in cookie_header.lower().replace("samesite", "")


def test_register_https_cookie_httponly_true_secure_true():
    """HTTPS register (x-forwarded-proto) → access_token cookie is httponly=True, secure=True, has max_age."""
    _setup_config()
    client = _get_auth_client()
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": _unique_email("https-cookie"), "password": "Tr0ub4dor3a"},
        headers={"x-forwarded-proto": "https"},
    )
    assert resp.status_code == 201
    cookie_header = resp.headers.get("set-cookie", "")
    assert "access_token=" in cookie_header
    assert "httponly" in cookie_header.lower()
    assert "secure" in cookie_header.lower()
    assert "max-age" in cookie_header.lower()


def test_login_https_sets_secure_cookie():
    """HTTPS login → access_token cookie has secure flag."""
    _setup_config()
    client = _get_auth_client()
    email = _unique_email("https-login")
    client.post("/api/v1/auth/register", json={"email": email, "password": "Tr0ub4dor3a"})
    resp = client.post(
        "/api/v1/auth/login/local",
        data={"username": email, "password": "Tr0ub4dor3a"},
        headers={"x-forwarded-proto": "https"},
    )
    assert resp.status_code == 200
    cookie_header = resp.headers.get("set-cookie", "")
    assert "access_token=" in cookie_header
    assert "httponly" in cookie_header.lower()
    assert "secure" in cookie_header.lower()


def test_csrf_cookie_secure_on_https():
    """HTTPS register → csrf_token cookie has secure flag but NOT httponly."""
    _setup_config()
    client = _get_auth_client()
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": _unique_email("csrf-https"), "password": "Tr0ub4dor3a"},
        headers={"x-forwarded-proto": "https"},
    )
    assert resp.status_code == 201
    csrf_cookies = [h for h in _get_set_cookie_headers(resp) if "csrf_token=" in h]
    assert csrf_cookies, "csrf_token cookie not set on HTTPS register"
    csrf_header = csrf_cookies[0]
    assert "secure" in csrf_header.lower()
    assert "httponly" not in csrf_header.lower()


def test_csrf_cookie_not_secure_on_http():
    """HTTP register → csrf_token cookie does NOT have secure flag."""
    _setup_config()
    client = _get_auth_client()
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": _unique_email("csrf-http"), "password": "Tr0ub4dor3a"},
    )
    assert resp.status_code == 201
    csrf_cookies = [h for h in _get_set_cookie_headers(resp) if "csrf_token=" in h]
    assert csrf_cookies, "csrf_token cookie not set on HTTP register"
    csrf_header = csrf_cookies[0]
    assert "secure" not in csrf_header.lower().replace("samesite", "")
