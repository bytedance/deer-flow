"""Conformance tests for the shared request-path projection.

``app.gateway.request_path.get_request_route_path()`` exists to answer one
question: *which path string is Starlette's router matching right now?* Auth
and CSRF classify that value, so the security predicates and the dispatcher
must agree on it exactly. When they disagree, a route mounted under a
public-looking prefix can be classified public while the router dispatches to
a protected handler.

These tests pin the agreement itself rather than the mechanism that produces
it, so they stay meaningful whether the projection keeps delegating to
Starlette or is ever reimplemented. Nothing here asserts *how* the value is
computed -- only that middleware and router see the same string.
"""

import pytest
from fastapi import FastAPI
from starlette.requests import Request
from starlette.testclient import TestClient

from app.gateway.auth_middleware import AuthMiddleware
from app.gateway.csrf_middleware import CSRFMiddleware, is_auth_endpoint, should_check_csrf
from app.gateway.request_path import get_request_route_path
from deerflow.config.authorization_config import AuthorizationConfig


@pytest.fixture(autouse=True)
def _default_route_authorization_config(monkeypatch):
    """Keep minimal middleware apps independent of a repository config.yaml."""
    monkeypatch.setattr(
        "app.gateway.authz._get_route_authorization_config",
        lambda: AuthorizationConfig(),
    )


@pytest.fixture(autouse=True)
def _auth_enabled(monkeypatch):
    """Every case here is about the enabled-auth path."""
    monkeypatch.delenv("DEER_FLOW_AUTH_DISABLED", raising=False)


def _request(path: str, root_path: str = "", method: str = "GET") -> Request:
    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "root_path": root_path,
            "query_string": b"",
            "headers": [],
        }
    )


# ── Projection edge cases ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("path", "root_path", "expected"),
    [
        # No mount: the raw ASGI path is already what the router matches.
        ("/api/models", "", "/api/models"),
        # Mounted: root_path is stripped on the segment boundary.
        ("/prefix/api/models", "/prefix", "/api/models"),
        # Nested mounts accumulate into root_path; strip all of it.
        ("/outer/inner/health", "/outer/inner", "/health"),
        # The mount itself was requested; the router matches the empty path.
        ("/prefix", "/prefix", ""),
        # root_path is not a prefix at all -- never strip.
        ("/other/models", "/prefix", "/other/models"),
        # Prefix collides mid-segment. Stripping here would produce "foo",
        # a string the router would never match.
        ("/apifoo/models", "/api", "/apifoo/models"),
        ("/apifoo", "/api", "/apifoo"),
    ],
)
def test_projection_strips_root_path_only_on_segment_boundaries(path: str, root_path: str, expected: str):
    assert get_request_route_path(_request(path, root_path)) == expected


# ── Agreement with the router ────────────────────────────────────────────────


def test_projection_matches_the_path_the_router_dispatched_on():
    """The middleware-visible string equals the route's declared path."""
    seen: dict[str, str] = {}

    child = FastAPI()

    @child.get("/health")
    async def health(request: Request):
        seen["projection"] = get_request_route_path(request)
        return {"ok": True}

    middle = FastAPI()
    middle.mount("/inner", child)
    parent = FastAPI()
    parent.mount("/outer", middle)

    assert TestClient(parent).get("/outer/inner/health").status_code == 200
    # The router matched the declared "/health", not the wire path.
    assert seen["projection"] == "/health"


def test_public_route_stays_public_under_nested_mounts():
    """Availability direction: a mounted /health must not start 401-ing."""
    child = FastAPI()
    child.add_middleware(AuthMiddleware)

    @child.get("/health")
    async def health():
        return {"ok": True}

    middle = FastAPI()
    middle.mount("/inner", child)
    parent = FastAPI()
    parent.mount("/outer", middle)

    assert TestClient(parent).get("/outer/inner/health").status_code == 200


# ── The bypass these predicates exist to prevent ─────────────────────────────


def test_mounting_under_a_public_prefix_does_not_expose_protected_routes():
    """Security direction: the mount prefix must not leak into classification.

    Classifying the raw wire path would see "/health/api/models", match the
    "/health" public prefix, and skip authentication entirely -- while the
    router dispatches to the protected "/api/models" handler.
    """
    child = FastAPI()
    child.add_middleware(AuthMiddleware)

    @child.get("/api/models")
    async def models():
        return {"models": []}

    parent = FastAPI()
    parent.mount("/health", child)

    assert TestClient(parent).get("/health/api/models").status_code == 401


def test_csrf_is_enforced_for_routes_mounted_under_the_webhook_prefix():
    """CSRF's webhook exemption keys off the projection, not the wire path."""
    child = FastAPI()
    child.add_middleware(CSRFMiddleware)

    @child.post("/action")
    async def action():
        return {"ok": True}

    parent = FastAPI()
    parent.mount("/api/webhooks", child)

    response = TestClient(parent).post("/api/webhooks/action")

    assert response.status_code == 403
    assert "CSRF token missing" in response.json()["detail"]


# ── CSRF predicates read the same projection ─────────────────────────────────


def test_csrf_exemptions_follow_the_projection():
    # Genuine host webhook: no mount, exempt.
    assert should_check_csrf(_request("/api/webhooks/github", method="POST")) is False
    # Same wire path, but the router is matching "/github" inside a mount --
    # not the host's webhook namespace, so CSRF still applies.
    assert should_check_csrf(_request("/api/webhooks/github", "/api/webhooks", method="POST")) is True


def test_auth_endpoint_detection_follows_the_projection():
    assert is_auth_endpoint(_request("/api/v1/auth/login/local", method="POST")) is True
    # A mount whose prefix is itself the auth namespace: the router matches
    # "/local", which is not the host's exempt endpoint.
    assert is_auth_endpoint(_request("/api/v1/auth/login/local", "/api/v1/auth/login", method="POST")) is False
    # The mount point itself was requested; the router matches the empty path.
    assert is_auth_endpoint(_request("/api/v1/auth/login/local", "/api/v1/auth/login/local", method="POST")) is False
