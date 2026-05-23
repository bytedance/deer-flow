"""Tests for GATEWAY_ENABLE_DOCS configuration toggle.

Verifies that Swagger UI (/docs), ReDoc (/redoc), and the OpenAPI schema
(/openapi.json) can be disabled via the GATEWAY_ENABLE_DOCS environment
variable for production deployments.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


def _reset_gateway_config():
    """Reset the cached gateway config so env changes take effect."""
    import app.gateway.config as cfg

    cfg._gateway_config = None


@pytest.fixture(autouse=True)
def _clean_config():
    """Ensure gateway config cache is cleared before and after each test."""
    _reset_gateway_config()
    yield
    _reset_gateway_config()


# ---------------------------------------------------------------------------
# Config parsing
# ---------------------------------------------------------------------------


def test_enable_docs_defaults_to_true():
    """When GATEWAY_ENABLE_DOCS is not set, enable_docs should be True."""
    with patch.dict(os.environ, {}, clear=False):
        if "GATEWAY_ENABLE_DOCS" in os.environ:
            del os.environ["GATEWAY_ENABLE_DOCS"]
        _reset_gateway_config()
        from app.gateway.config import get_gateway_config

        config = get_gateway_config()
        assert config.enable_docs is True


def test_enable_docs_false():
    """GATEWAY_ENABLE_DOCS=false should disable docs."""
    with patch.dict(os.environ, {"GATEWAY_ENABLE_DOCS": "false"}):
        _reset_gateway_config()
        from app.gateway.config import get_gateway_config

        config = get_gateway_config()
        assert config.enable_docs is False


def test_enable_docs_case_insensitive():
    """GATEWAY_ENABLE_DOCS is case-insensitive (FALSE, False, false)."""
    for value in ("FALSE", "False", "false"):
        with patch.dict(os.environ, {"GATEWAY_ENABLE_DOCS": value}):
            _reset_gateway_config()
            from app.gateway.config import get_gateway_config

            config = get_gateway_config()
            assert config.enable_docs is False, f"Expected False for GATEWAY_ENABLE_DOCS={value}"


def test_enable_docs_unexpected_value_disables():
    """Any non-'true' value should disable docs (fail-closed)."""
    for value in ("0", "no", "off", "anything"):
        with patch.dict(os.environ, {"GATEWAY_ENABLE_DOCS": value}):
            _reset_gateway_config()
            from app.gateway.config import get_gateway_config

            config = get_gateway_config()
            assert config.enable_docs is False, f"Expected False for GATEWAY_ENABLE_DOCS={value}"


# ---------------------------------------------------------------------------
# App-level endpoint visibility
# ---------------------------------------------------------------------------


def test_docs_endpoints_available_by_default():
    """With enable_docs=True (default), /docs, /redoc, /openapi.json return 200."""
    with patch.dict(os.environ, {}, clear=False):
        if "GATEWAY_ENABLE_DOCS" in os.environ:
            del os.environ["GATEWAY_ENABLE_DOCS"]
        _reset_gateway_config()
        from app.gateway.app import create_app

        app = create_app()
        client = TestClient(app)
        assert client.get("/docs").status_code == 200
        assert client.get("/redoc").status_code == 200
        assert client.get("/openapi.json").status_code == 200


def test_docs_endpoints_disabled_when_false():
    """With GATEWAY_ENABLE_DOCS=false, /docs, /redoc, /openapi.json return 404."""
    with patch.dict(os.environ, {"GATEWAY_ENABLE_DOCS": "false"}):
        _reset_gateway_config()
        from app.gateway.app import create_app

        app = create_app()
        client = TestClient(app)
        assert client.get("/docs").status_code == 404
        assert client.get("/redoc").status_code == 404
        assert client.get("/openapi.json").status_code == 404


def test_health_still_works_when_docs_disabled():
    """Disabling docs should NOT affect /health or other normal endpoints."""
    with patch.dict(os.environ, {"GATEWAY_ENABLE_DOCS": "false"}):
        _reset_gateway_config()
        from app.gateway.app import create_app

        app = create_app()
        client = TestClient(app)
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "healthy"


# ---------------------------------------------------------------------------
# Runtime CORS behavior
# ---------------------------------------------------------------------------


def _make_gateway_client(cors_origins: str) -> TestClient:
    with patch.dict(os.environ, {"GATEWAY_CORS_ORIGINS": cors_origins}):
        _reset_gateway_config()
        from app.gateway.app import create_app

        return TestClient(create_app())


def test_gateway_cors_allows_configured_origin():
    """GATEWAY_CORS_ORIGINS should control actual browser CORS responses."""
    client = _make_gateway_client("https://app.example")

    response = client.get("/health", headers={"Origin": "https://app.example"})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://app.example"
    assert response.headers["access-control-allow-credentials"] == "true"


def test_gateway_cors_rejects_unconfigured_origin():
    client = _make_gateway_client("https://app.example")

    response = client.get("/health", headers={"Origin": "https://evil.example"})

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_gateway_cors_normalizes_configured_default_port():
    client = _make_gateway_client("https://app.example:443")

    response = client.get("/health", headers={"Origin": "https://app.example"})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://app.example"
