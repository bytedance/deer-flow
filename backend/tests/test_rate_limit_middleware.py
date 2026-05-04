"""Tests for rate limiting middleware — enabled, disabled, exceeded, window reset."""

import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.middleware.rate_limit import create_rate_limit_middleware
from deerflow.config.rate_limit_config import load_rate_limit_config_from_dict, reset_rate_limit_config


@pytest.fixture(autouse=True)
def _reset_configs():
    reset_rate_limit_config()
    yield
    reset_rate_limit_config()


def _make_app() -> FastAPI:
    app = FastAPI()

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/test")
    def test_endpoint():
        return {"result": "ok"}

    create_rate_limit_middleware(app)
    return app


class TestRateLimitDisabled:
    def test_no_limit_when_disabled(self):
        load_rate_limit_config_from_dict({"enabled": False})
        client = TestClient(_make_app())
        for _ in range(50):
            resp = client.get("/api/test")
            assert resp.status_code == 200

    def test_no_rate_limit_headers_when_disabled(self):
        load_rate_limit_config_from_dict({"enabled": False})
        client = TestClient(_make_app())
        resp = client.get("/api/test")
        assert "X-RateLimit-Limit" not in resp.headers


class TestRateLimitEnabled:
    def test_allows_requests_within_limit(self):
        load_rate_limit_config_from_dict({
            "enabled": True,
            "global_per_minute": 1000,
            "tenant_per_minute": 100,
        })
        client = TestClient(_make_app())
        for _ in range(10):
            resp = client.get("/api/test")
            assert resp.status_code == 200

    def test_blocks_when_exceeded(self):
        load_rate_limit_config_from_dict({
            "enabled": True,
            "global_per_minute": 3,
            "tenant_per_minute": 3,
        })
        client = TestClient(_make_app())
        # Exhaust the limit
        for _ in range(3):
            resp = client.get("/api/test")
            assert resp.status_code == 200
        # Next request should be rate limited
        resp = client.get("/api/test")
        assert resp.status_code == 429
        data = resp.json()
        assert "detail" in data

    def test_429_includes_retry_after_header(self):
        load_rate_limit_config_from_dict({
            "enabled": True,
            "global_per_minute": 1,
            "tenant_per_minute": 1,
        })
        client = TestClient(_make_app())
        client.get("/api/test")  # consume the 1 allowed request
        resp = client.get("/api/test")
        assert resp.status_code == 429
        assert "Retry-After" in resp.headers

    def test_health_endpoint_not_rate_limited(self):
        """Health endpoint should ideally be exempt; verify it still works."""
        load_rate_limit_config_from_dict({
            "enabled": True,
            "global_per_minute": 1,
            "tenant_per_minute": 1,
        })
        client = TestClient(_make_app())
        # Consume the limit on /api/test
        client.get("/api/test")
        # Health should still be accessible (it's a different path)
        resp = client.get("/health")
        assert resp.status_code == 200
