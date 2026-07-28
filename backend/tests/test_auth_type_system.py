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


def test_api_auth_me_auth_disabled_returns_synthetic_user(monkeypatch):
    _setup_config()
    monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "1")
    client = _get_auth_client()

    resp = client.get("/api/v1/auth/me")

    assert resp.status_code == 200
    from app.gateway.auth_disabled import AUTH_DISABLED_USER_ID

    body = resp.json()
    assert body["id"] == AUTH_DISABLED_USER_ID
    assert body["oauth_provider"] is None


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


def _get_response_set_cookie_headers(resp) -> list[str]:
    return [v.decode("latin-1") for k, v in resp.raw_headers if k.lower() == b"set-cookie"]


def _make_request_scope(*, scheme: str = "http", host: str = "example.test", headers: dict[str, str] | None = None) -> dict:
    raw_headers = [(b"host", host.encode("ascii"))]
    for key, value in (headers or {}).items():
        raw_headers.append((key.lower().encode("ascii"), value.encode("ascii")))
    return {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/auth/login/local",
        "headers": raw_headers,
        "scheme": scheme,
        "server": (host.split(":", 1)[0], 80 if scheme == "http" else 443),
        "query_string": b"",
    }


def test_session_cookie_policy_persists_on_https():
    from starlette.requests import Request

    from app.gateway.auth.session_cookie import resolve_session_cookie_policy

    _setup_config()
    request = Request(_make_request_scope(scheme="http", host="internal:8000", headers={"x-forwarded-proto": "https", "x-forwarded-host": "deerflow.example"}))

    policy = resolve_session_cookie_policy(request, remember_me=True)

    assert policy.secure is True
    assert policy.max_age == 7 * 24 * 3600


def test_session_cookie_policy_persists_on_localhost_http():
    from starlette.requests import Request

    from app.gateway.auth.session_cookie import resolve_session_cookie_policy

    _setup_config()
    request = Request(_make_request_scope(scheme="http", host="localhost:2026"))

    policy = resolve_session_cookie_policy(request, remember_me=True)

    assert policy.secure is False
    assert policy.max_age == 7 * 24 * 3600


def test_session_cookie_policy_persists_on_ipv4_loopback_range():
    from starlette.requests import Request

    from app.gateway.auth.session_cookie import resolve_session_cookie_policy

    _setup_config()
    request = Request(_make_request_scope(scheme="http", host="127.1.2.3:2026"))

    policy = resolve_session_cookie_policy(request, remember_me=True)

    assert policy.secure is False
    assert policy.max_age == 7 * 24 * 3600


def test_session_cookie_policy_degrades_public_http_to_session_cookie():
    from starlette.requests import Request

    from app.gateway.auth.session_cookie import resolve_session_cookie_policy

    _setup_config()
    request = Request(_make_request_scope(scheme="http", host="sandbox.example"))

    policy = resolve_session_cookie_policy(request, remember_me=True)

    assert policy.secure is False
    assert policy.max_age is None


@pytest.mark.parametrize(
    "spoofed_headers",
    [
        {"x-forwarded-host": "localhost:2026"},
        {"forwarded": 'for=192.0.2.1;host="localhost:2026";proto=http'},
    ],
)
def test_session_cookie_policy_ignores_forwarded_localhost_on_public_http(spoofed_headers):
    from starlette.requests import Request

    from app.gateway.auth.session_cookie import resolve_session_cookie_policy

    _setup_config()
    request = Request(_make_request_scope(scheme="http", host="sandbox.example", headers=spoofed_headers))

    policy = resolve_session_cookie_policy(request, remember_me=True)

    assert policy.secure is False
    assert policy.max_age is None


def test_session_cookie_policy_remember_me_false_is_session_cookie():
    from starlette.requests import Request

    from app.gateway.auth.session_cookie import resolve_session_cookie_policy

    _setup_config()
    request = Request(_make_request_scope(scheme="http", host="localhost:2026"))

    policy = resolve_session_cookie_policy(request, remember_me=False)

    assert policy.secure is False
    assert policy.max_age is None


def test_session_cookie_policy_allows_operator_opt_in_for_public_http(monkeypatch):
    from starlette.requests import Request

    from app.gateway.auth.session_cookie import ALLOW_INSECURE_PERSISTENT_COOKIE_ENV, resolve_session_cookie_policy

    _setup_config()
    monkeypatch.setenv(ALLOW_INSECURE_PERSISTENT_COOKIE_ENV, "1")
    request = Request(_make_request_scope(scheme="http", host="sandbox.example"))

    policy = resolve_session_cookie_policy(request, remember_me=True)

    assert policy.secure is False
    assert policy.max_age == 7 * 24 * 3600


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


def test_register_remember_me_false_keeps_access_and_csrf_session_only():
    _setup_config()
    client = TestClient(_make_auth_app(), base_url="https://deerflow.example")

    resp = client.post(
        "/api/v1/auth/register",
        json={"email": _unique_email("register-session"), "password": "Tr0ub4dor3a", "remember_me": False},
    )

    assert resp.status_code == 201
    set_cookies = _get_set_cookie_headers(resp)
    access_cookies = [h for h in set_cookies if "access_token=" in h]
    csrf_cookies = [h for h in set_cookies if "csrf_token=" in h]
    preference_cookies = [h for h in set_cookies if "deerflow_session_persistent=" in h]
    assert access_cookies and csrf_cookies and preference_cookies
    assert "secure" in access_cookies[0].lower()
    assert "secure" in csrf_cookies[0].lower()
    assert "max-age" not in access_cookies[0].lower()
    assert "max-age" not in csrf_cookies[0].lower()
    assert "deerflow_session_persistent=0" in preference_cookies[0].lower()


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


def test_login_remember_me_false_keeps_access_and_csrf_session_only():
    """remember_me=false should make both access_token and csrf_token session cookies."""
    _setup_config()
    client = TestClient(_make_auth_app(), base_url="http://localhost:2026")
    email = _unique_email("remember-false")
    client.post("/api/v1/auth/register", json={"email": email, "password": "Tr0ub4dor3a"})

    resp = client.post(
        "/api/v1/auth/login/local",
        data={"username": email, "password": "Tr0ub4dor3a", "remember_me": "false"},
    )

    assert resp.status_code == 200
    set_cookies = _get_set_cookie_headers(resp)
    access_cookies = [h for h in set_cookies if "access_token=" in h]
    csrf_cookies = [h for h in set_cookies if "csrf_token=" in h]
    assert access_cookies, "access_token cookie not set on login"
    assert csrf_cookies, "csrf_token cookie not set on login"
    assert "max-age" not in access_cookies[0].lower()
    assert "max-age" not in csrf_cookies[0].lower()


def test_login_remember_me_false_over_https_keeps_csrf_session_only():
    _setup_config()
    client = TestClient(_make_auth_app(), base_url="https://deerflow.example")
    email = _unique_email("remember-false-https")
    client.post("/api/v1/auth/register", json={"email": email, "password": "Tr0ub4dor3a"})

    resp = client.post(
        "/api/v1/auth/login/local",
        data={"username": email, "password": "Tr0ub4dor3a", "remember_me": "false"},
    )

    assert resp.status_code == 200
    set_cookies = _get_set_cookie_headers(resp)
    access_cookies = [h for h in set_cookies if "access_token=" in h]
    csrf_cookies = [h for h in set_cookies if "csrf_token=" in h]
    assert access_cookies and csrf_cookies
    assert "secure" in access_cookies[0].lower()
    assert "secure" in csrf_cookies[0].lower()
    assert "max-age" not in access_cookies[0].lower()
    assert "max-age" not in csrf_cookies[0].lower()


def test_login_failure_uses_csrf_fallback_cookie_lifetime_on_https():
    _setup_config()
    client = TestClient(_make_auth_app(), base_url="https://deerflow.example")

    resp = client.post(
        "/api/v1/auth/login/local",
        data={"username": "missing@example.com", "password": "wrong", "remember_me": "false"},
    )

    assert resp.status_code == 401
    csrf_cookies = [h for h in _get_set_cookie_headers(resp) if "csrf_token=" in h]
    assert csrf_cookies
    assert "secure" in csrf_cookies[0].lower()
    assert "max-age=604800" in csrf_cookies[0].lower()


def test_login_remember_me_true_keeps_access_and_csrf_max_age_in_lockstep_on_localhost():
    """localhost HTTP can persist, but access_token and csrf_token must share the same max_age."""
    _setup_config()
    client = TestClient(_make_auth_app(), base_url="http://localhost:2026")
    email = _unique_email("remember-true")
    client.post("/api/v1/auth/register", json={"email": email, "password": "Tr0ub4dor3a"})

    resp = client.post(
        "/api/v1/auth/login/local",
        data={"username": email, "password": "Tr0ub4dor3a", "remember_me": "true"},
    )

    assert resp.status_code == 200
    set_cookies = _get_set_cookie_headers(resp)
    access_cookies = [h for h in set_cookies if "access_token=" in h]
    csrf_cookies = [h for h in set_cookies if "csrf_token=" in h]
    assert access_cookies and csrf_cookies
    assert "max-age=604800" in access_cookies[0].lower()
    assert "max-age=604800" in csrf_cookies[0].lower()


def test_change_password_preserves_session_only_preference():
    _setup_config()
    client = TestClient(_make_auth_app(), base_url="https://deerflow.example")
    email = _unique_email("change-password-session")
    client.post("/api/v1/auth/register", json={"email": email, "password": "Tr0ub4dor3a"})
    client.post(
        "/api/v1/auth/login/local",
        data={"username": email, "password": "Tr0ub4dor3a", "remember_me": "false"},
    )
    csrf_token = client.cookies.get("csrf_token")

    resp = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "Tr0ub4dor3a", "new_password": "An0therStrongPwd!"},
        headers={"X-CSRF-Token": csrf_token},
    )

    assert resp.status_code == 200
    set_cookies = _get_set_cookie_headers(resp)
    access_cookies = [h for h in set_cookies if "access_token=" in h]
    preference_cookies = [h for h in set_cookies if "deerflow_session_persistent=" in h]
    assert access_cookies and preference_cookies
    assert "max-age" not in access_cookies[0].lower()
    assert "deerflow_session_persistent=0" in preference_cookies[0].lower()


def test_change_password_reissues_access_and_csrf_in_lockstep_when_preference_changes():
    _setup_config()
    client = TestClient(_make_auth_app(), base_url="https://deerflow.example")
    email = _unique_email("change-password-persistent")
    client.post("/api/v1/auth/register", json={"email": email, "password": "Tr0ub4dor3a"})
    client.post(
        "/api/v1/auth/login/local",
        data={"username": email, "password": "Tr0ub4dor3a", "remember_me": "false"},
    )
    csrf_token = client.cookies.get("csrf_token")

    resp = client.post(
        "/api/v1/auth/change-password",
        json={
            "current_password": "Tr0ub4dor3a",
            "new_password": "An0therStrongPwd!",
            "remember_me": True,
        },
        headers={"X-CSRF-Token": csrf_token},
    )

    assert resp.status_code == 200
    set_cookies = _get_set_cookie_headers(resp)
    access_cookies = [h.lower() for h in set_cookies if "access_token=" in h]
    csrf_cookies = [h.lower() for h in set_cookies if "csrf_token=" in h]
    assert access_cookies and csrf_cookies
    assert "secure" in access_cookies[0]
    assert "secure" in csrf_cookies[0]
    assert "max-age=604800" in access_cookies[0]
    assert "max-age=604800" in csrf_cookies[0]


def test_initialize_remember_me_false_keeps_access_and_csrf_session_only():
    _setup_config()
    client = TestClient(_make_auth_app(), base_url="https://deerflow.example")

    resp = client.post(
        "/api/v1/auth/initialize",
        json={"email": _unique_email("init-session"), "password": "Tr0ub4dor3a", "remember_me": False},
    )

    assert resp.status_code == 201
    set_cookies = _get_set_cookie_headers(resp)
    access_cookies = [h for h in set_cookies if "access_token=" in h]
    csrf_cookies = [h for h in set_cookies if "csrf_token=" in h]
    preference_cookies = [h for h in set_cookies if "deerflow_session_persistent=" in h]
    assert access_cookies and csrf_cookies and preference_cookies
    assert "secure" in access_cookies[0].lower()
    assert "secure" in csrf_cookies[0].lower()
    assert "max-age" not in access_cookies[0].lower()
    assert "max-age" not in csrf_cookies[0].lower()
    assert "deerflow_session_persistent=0" in preference_cookies[0].lower()


def test_logout_clears_access_and_csrf_without_reissuing_csrf():
    _setup_config()
    client = TestClient(_make_auth_app(), base_url="https://deerflow.example")
    client.post(
        "/api/v1/auth/register",
        json={"email": _unique_email("logout-clear"), "password": "Tr0ub4dor3a"},
    )

    resp = client.post("/api/v1/auth/logout")

    assert resp.status_code == 200
    set_cookies = _get_set_cookie_headers(resp)
    access_cookies = [h for h in set_cookies if "access_token=" in h]
    csrf_cookies = [h for h in set_cookies if "csrf_token=" in h]
    preference_cookies = [h for h in set_cookies if "deerflow_session_persistent=" in h]
    assert access_cookies and "max-age=0" in access_cookies[0].lower()
    assert csrf_cookies and "max-age=0" in csrf_cookies[0].lower()
    assert preference_cookies and "max-age=0" in preference_cookies[0].lower()


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


def test_csrf_cookie_persistent_on_https():
    """HTTPS register → csrf_token cookie is persistent (has max_age), like access_token.

    Regression for iOS Safari home-screen PWAs. When iOS terminates a
    standalone web app it evicts *session* cookies but keeps *persistent*
    ones. The access_token cookie is persistent over HTTPS (carries
    max_age), so the user still appears logged in after reopening — but a
    session-only csrf_token cookie is dropped, so the first state-changing
    request fails with 403 "CSRF token missing. Include X-CSRF-Token
    header." The two cookies represent one session and must share a lifetime.
    """
    _setup_config()
    client = _get_auth_client()
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": _unique_email("csrf-persist"), "password": "Tr0ub4dor3a"},
        headers={"x-forwarded-proto": "https"},
    )
    assert resp.status_code == 201
    set_cookies = _get_set_cookie_headers(resp)
    csrf_cookies = [h for h in set_cookies if "csrf_token=" in h]
    assert csrf_cookies, "csrf_token cookie not set on HTTPS register"
    assert "max-age" in csrf_cookies[0].lower(), "csrf_token must be persistent over HTTPS so iOS PWAs don't drop it as a session cookie"
    # It must pair with the access_token's lifetime: both persistent on HTTPS.
    access_cookies = [h for h in set_cookies if "access_token=" in h]
    assert access_cookies and "max-age" in access_cookies[0].lower()


def test_csrf_cookie_session_only_on_http():
    """HTTP register → csrf_token cookie has NO max_age (session cookie).

    Mirrors the access_token's ``... if is_https else None`` guard so the
    pair stays symmetric: persistent together over HTTPS, session-only
    together over plain HTTP (local dev). Keeping them in lockstep is what
    avoids the "logged in but csrf_token gone" state.
    """
    _setup_config()
    client = _get_auth_client()
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": _unique_email("csrf-session"), "password": "Tr0ub4dor3a"},
    )
    assert resp.status_code == 201
    csrf_cookies = [h for h in _get_set_cookie_headers(resp) if "csrf_token=" in h]
    assert csrf_cookies, "csrf_token cookie not set on HTTP register"
    assert "max-age" not in csrf_cookies[0].lower()


def test_oidc_callback_access_and_csrf_cookie_lifetime_match_on_https():
    """The OIDC-callback cookie helpers keep access/csrf attributes in lockstep.

    ``routers.auth._set_csrf_cookie`` is the second place a csrf_token cookie
    is minted (GET OIDC callback, which CSRFMiddleware does not cover). It has
    the same session-vs-persistent asymmetry and the same iOS PWA failure
    mode, so it must also carry max_age over HTTPS.
    """
    from starlette.requests import Request
    from starlette.responses import Response

    from app.gateway.routers.auth import _set_csrf_cookie, _set_session_cookie

    _setup_config()
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/auth/callback/example",
        "headers": [(b"x-forwarded-proto", b"https")],
        "scheme": "http",
        "server": ("internal", 8000),
        "query_string": b"",
    }
    response = Response()
    request = Request(scope)
    _set_session_cookie(response, "token", request, remember_me=True)
    _set_csrf_cookie(response, request)
    set_cookies = [h.lower() for h in _get_response_set_cookie_headers(response)]
    access_cookies = [h for h in set_cookies if "access_token=" in h]
    csrf_cookies = [h for h in set_cookies if "csrf_token=" in h]
    assert access_cookies and csrf_cookies
    assert "secure" in access_cookies[0]
    assert "secure" in csrf_cookies[0]
    assert "max-age=604800" in access_cookies[0]
    assert "max-age=604800" in csrf_cookies[0]


def test_oidc_callback_access_and_csrf_cookie_stay_session_only():
    from starlette.requests import Request
    from starlette.responses import Response

    from app.gateway.routers.auth import _set_csrf_cookie, _set_session_cookie

    _setup_config()
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/auth/callback/example",
        "headers": [(b"x-forwarded-proto", b"https")],
        "scheme": "http",
        "server": ("internal", 8000),
        "query_string": b"",
    }
    response = Response()
    request = Request(scope)
    _set_session_cookie(response, "token", request, remember_me=False)
    _set_csrf_cookie(response, request)
    set_cookies = [h.lower() for h in _get_response_set_cookie_headers(response)]
    access_cookies = [h for h in set_cookies if "access_token=" in h]
    csrf_cookies = [h for h in set_cookies if "csrf_token=" in h]
    assert access_cookies and csrf_cookies
    assert "secure" in access_cookies[0]
    assert "secure" in csrf_cookies[0]
    assert "max-age" not in access_cookies[0]
    assert "max-age" not in csrf_cookies[0]
