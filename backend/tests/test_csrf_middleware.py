"""Tests for CSRF middleware."""

import pytest
from fastapi import FastAPI, Request
from starlette.testclient import TestClient
from uvicorn.config import Config
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.gateway import csrf_middleware
from app.gateway.csrf_middleware import CSRFMiddleware, _trusted_proxy_networks


def _make_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(CSRFMiddleware)

    @app.post("/api/v1/auth/login/local")
    async def login_local():
        return {"ok": True}

    @app.post("/api/v1/auth/register")
    async def register():
        return {"ok": True}

    @app.post("/api/threads/abc/runs/stream")
    async def protected_mutation():
        return {"ok": True}

    @app.post("/api/v1/auth/log{gap}in/local")
    async def control_gap(gap: str):
        return {"gap": gap}

    @app.post("/api/v1/auth/me{suffix}")
    async def delimiter_suffix(suffix: str):
        return {"suffix": suffix}

    return app


def test_invalid_trusted_proxy_entry_is_logged(monkeypatch, caplog):
    monkeypatch.setenv("AUTH_TRUSTED_PROXIES", "10.0.0.0/8,not-a-network")

    with caplog.at_level("WARNING", logger="app.gateway.csrf_middleware"):
        networks = _trusted_proxy_networks()

    assert [str(network) for network in networks] == ["10.0.0.0/8"]
    assert "Ignoring invalid AUTH_TRUSTED_PROXIES entry" in caplog.text


def test_trusted_proxy_network_parsing_is_cached_by_environment_value(monkeypatch):
    original_ip_network = csrf_middleware.ip_network
    parsed: list[str] = []

    def tracking_ip_network(entry, *, strict):
        parsed.append(entry)
        return original_ip_network(entry, strict=strict)

    csrf_middleware._parse_trusted_proxy_networks.cache_clear()
    monkeypatch.setattr(csrf_middleware, "ip_network", tracking_ip_network)

    monkeypatch.setenv("AUTH_TRUSTED_PROXIES", "10.0.0.0/8")
    assert _trusted_proxy_networks() == _trusted_proxy_networks()

    monkeypatch.setenv("AUTH_TRUSTED_PROXIES", "192.168.200.0/24")
    assert [str(network) for network in _trusted_proxy_networks()] == ["192.168.200.0/24"]
    assert parsed == ["10.0.0.0/8", "192.168.200.0/24"]


def test_url_reconstruction_cannot_create_a_csrf_exemption():
    client = TestClient(_make_app(), base_url="https://deerflow.example")

    for encoded_path in (
        "/api/v1/auth/log%0Ain/local",
        "/api/v1/auth/log%0Din/local",
        "/api/v1/auth/log%09in/local",
        "/api/v1/auth/me%23private",
        "/api/v1/auth/me%3Fprivate",
    ):
        response = client.post(encoded_path)
        assert response.status_code == 403, encoded_path


def test_csrf_uses_the_same_root_path_projection_as_the_router():
    child = FastAPI()
    child.add_middleware(CSRFMiddleware)

    @child.post("/api/v1/auth/login/local")
    async def login_local():
        return {"ok": True}

    parent = FastAPI()
    parent.mount("/prefix", child)

    response = TestClient(
        parent,
        base_url="https://deerflow.example",
    ).post("/prefix/api/v1/auth/login/local")

    assert response.status_code == 200


def test_auth_post_rejects_cross_origin_browser_request():
    """CSRF-exempt auth routes must not accept hostile browser origins.

    Login/register endpoints intentionally skip the double-submit token because
    first-time callers do not have a token yet. They still set an auth session,
    so a hostile cross-site form POST must be rejected to avoid login CSRF /
    session fixation.
    """
    client = TestClient(_make_app(), base_url="https://deerflow.example")

    response = client.post(
        "/api/v1/auth/login/local",
        headers={"Origin": "https://evil.example"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Cross-site auth request denied."


def test_auth_post_allows_same_origin_browser_request():
    client = TestClient(_make_app(), base_url="https://deerflow.example")

    response = client.post(
        "/api/v1/auth/login/local",
        headers={"Origin": "https://deerflow.example"},
    )

    assert response.status_code == 200
    assert response.cookies.get("csrf_token")


def test_auth_post_rejects_malformed_origin_with_path():
    client = TestClient(_make_app(), base_url="https://deerflow.example")

    response = client.post(
        "/api/v1/auth/login/local",
        headers={"Origin": "https://deerflow.example/path"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Cross-site auth request denied."
    assert response.cookies.get("csrf_token") is None


def test_auth_post_rejects_malformed_origin_with_invalid_port():
    client = TestClient(_make_app(), base_url="https://deerflow.example")

    response = client.post(
        "/api/v1/auth/login/local",
        headers={"Origin": "https://deerflow.example:bad"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Cross-site auth request denied."
    assert response.cookies.get("csrf_token") is None


def test_auth_post_allows_same_origin_default_port_equivalence():
    client = TestClient(_make_app(), base_url="https://deerflow.example")

    response = client.post(
        "/api/v1/auth/login/local",
        headers={"Origin": "https://deerflow.example:443"},
    )

    assert response.status_code == 200
    assert response.cookies.get("csrf_token")


def test_auth_post_allows_forwarded_same_origin(monkeypatch):
    monkeypatch.setenv("AUTH_TRUSTED_PROXIES", "10.0.0.0/8")
    client = TestClient(_make_app(), base_url="http://internal:8000", client=("10.0.0.2", 12345))

    response = client.post(
        "/api/v1/auth/login/local",
        headers={
            "Origin": "https://deerflow.example",
            "X-Forwarded-Proto": "https",
            "X-Forwarded-Host": "deerflow.example, internal:8000",
        },
    )

    assert response.status_code == 200
    assert response.cookies.get("csrf_token")


@pytest.mark.parametrize(
    ("proxy_headers", "expected_peer", "expected_scheme", "expected_auth_status"),
    [
        (True, "203.0.113.1", "https", 403),
        (False, "10.0.0.2", "http", 200),
    ],
)
def test_uvicorn_proxy_header_processing_preserves_gateway_trust_boundary(
    monkeypatch,
    proxy_headers,
    expected_peer,
    expected_scheme,
    expected_auth_status,
):
    monkeypatch.setenv("AUTH_TRUSTED_PROXIES", "10.0.0.0/8")
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "10.0.0.0/8")
    app = _make_app()

    @app.get("/_scope")
    async def scope(request: Request):
        return {"peer": request.client.host, "scheme": request.url.scheme}

    config = Config(app, proxy_headers=proxy_headers, log_config=None)
    config.load()
    assert isinstance(config.loaded_app, ProxyHeadersMiddleware) is proxy_headers

    client = TestClient(
        config.loaded_app,
        base_url="http://internal:8000",
        client=("10.0.0.2", 12345),
    )
    forwarded_headers = {
        "X-Forwarded-For": "203.0.113.1",
        "X-Forwarded-Proto": "https",
        "X-Forwarded-Host": "deerflow.example",
    }

    assert client.get("/_scope", headers=forwarded_headers).json() == {
        "peer": expected_peer,
        "scheme": expected_scheme,
    }

    response = client.post(
        "/api/v1/auth/login/local",
        headers={"Origin": "https://deerflow.example", **forwarded_headers},
    )

    assert response.status_code == expected_auth_status
    if proxy_headers:
        assert response.cookies.get("csrf_token") is None
    else:
        assert response.cookies.get("csrf_token")


def test_uvicorn_proxy_headers_cannot_override_the_default_off_auth_policy(monkeypatch):
    """FORWARDED_ALLOW_IPS must not alter Gateway auth requests on its own."""
    monkeypatch.delenv("AUTH_TRUSTED_PROXIES", raising=False)
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "*")
    config = Config(_make_app(), proxy_headers=False, log_config=None)
    config.load()

    client = TestClient(
        config.loaded_app,
        base_url="http://internal:8000",
        client=("203.0.113.1", 12345),
    )
    response = client.post(
        "/api/v1/auth/login/local",
        headers={"X-Forwarded-Proto": "https"},
    )

    assert response.status_code == 200
    assert "secure" not in response.headers["set-cookie"].lower()


def test_auth_post_rejects_spoofed_forwarded_same_origin_from_untrusted_peer(monkeypatch):
    monkeypatch.setenv("AUTH_TRUSTED_PROXIES", "10.0.0.0/8")
    client = TestClient(_make_app(), base_url="http://internal:8000", client=("203.0.113.1", 12345))

    response = client.post(
        "/api/v1/auth/login/local",
        headers={
            "Origin": "https://deerflow.example",
            "X-Forwarded-Proto": "https",
            "X-Forwarded-Host": "deerflow.example",
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Cross-site auth request denied."
    assert response.cookies.get("csrf_token") is None


def test_auth_post_allows_forwarded_same_origin_with_non_default_port(monkeypatch):
    monkeypatch.setenv("AUTH_TRUSTED_PROXIES", "10.0.0.0/8")
    client = TestClient(_make_app(), base_url="http://internal:8000", client=("10.0.0.2", 12345))

    response = client.post(
        "/api/v1/auth/login/local",
        headers={
            "Origin": "http://localhost:2026",
            "X-Forwarded-Proto": "http",
            "X-Forwarded-Host": "localhost:2026",
        },
    )

    assert response.status_code == 200
    assert response.cookies.get("csrf_token")


def test_auth_post_allows_rfc_forwarded_same_origin(monkeypatch):
    monkeypatch.setenv("AUTH_TRUSTED_PROXIES", "10.0.0.0/8")
    client = TestClient(_make_app(), base_url="http://internal:8000", client=("10.0.0.2", 12345))

    response = client.post(
        "/api/v1/auth/login/local",
        headers={
            "Origin": "https://deerflow.example",
            "Forwarded": "proto=https;host=deerflow.example",
        },
    )

    assert response.status_code == 200
    assert response.cookies.get("csrf_token")
    assert "secure" in response.headers["set-cookie"].lower()


def test_auth_post_allows_explicit_configured_origin(monkeypatch):
    monkeypatch.setenv("GATEWAY_CORS_ORIGINS", "https://app.example")
    client = TestClient(_make_app(), base_url="https://api.example")

    response = client.post(
        "/api/v1/auth/register",
        headers={"Origin": "https://app.example"},
    )

    assert response.status_code == 200
    assert response.cookies.get("csrf_token")


def test_auth_post_does_not_treat_wildcard_cors_as_allowed_origin(monkeypatch):
    monkeypatch.setenv("GATEWAY_CORS_ORIGINS", "*")
    client = TestClient(_make_app(), base_url="https://api.example")

    response = client.post(
        "/api/v1/auth/login/local",
        headers={"Origin": "https://evil.example"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Cross-site auth request denied."


def test_auth_post_sets_strict_samesite_csrf_cookie():
    client = TestClient(_make_app(), base_url="https://deerflow.example")

    response = client.post(
        "/api/v1/auth/login/local",
        headers={"Origin": "https://deerflow.example"},
    )

    assert response.status_code == 200
    set_cookie = response.headers["set-cookie"].lower()
    assert "csrf_token=" in set_cookie
    assert "samesite=strict" in set_cookie
    assert "secure" in set_cookie


def test_auth_post_without_origin_still_allows_non_browser_clients():
    client = TestClient(_make_app(), base_url="https://deerflow.example")

    response = client.post("/api/v1/auth/login/local")

    assert response.status_code == 200
    assert response.cookies.get("csrf_token")


def test_non_auth_mutation_still_requires_double_submit_token():
    client = TestClient(_make_app(), base_url="https://deerflow.example")

    response = client.post(
        "/api/threads/abc/runs/stream",
        headers={"Origin": "https://deerflow.example"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "CSRF token missing. Include X-CSRF-Token header."


def test_non_auth_mutation_allows_valid_double_submit_token():
    client = TestClient(_make_app(), base_url="https://deerflow.example")
    client.cookies.set("csrf_token", "known-token")

    response = client.post(
        "/api/threads/abc/runs/stream",
        headers={
            "Origin": "https://deerflow.example",
            "X-CSRF-Token": "known-token",
        },
    )

    assert response.status_code == 200


def test_non_auth_mutation_rejects_mismatched_double_submit_token():
    client = TestClient(_make_app(), base_url="https://deerflow.example")
    client.cookies.set("csrf_token", "cookie-token")

    response = client.post(
        "/api/threads/abc/runs/stream",
        headers={
            "Origin": "https://deerflow.example",
            "X-CSRF-Token": "header-token",
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "CSRF token mismatch."


def test_channel_posts_require_double_submit_csrf():
    client = TestClient(_make_app(), base_url="https://deerflow.example")

    response = client.post(
        "/api/channels/slack/connect",
        headers={"Origin": "https://deerflow.example"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "CSRF token missing. Include X-CSRF-Token header."
