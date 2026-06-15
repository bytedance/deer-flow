"""Tests for /health, /health/live, /health/ready, /health/metrics endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient


def _make_app_client(monkeypatch: pytest.MonkeyPatch):
    """Create a fresh FastAPI app with mocked health-check helpers."""
    import app.gateway.app as app_module
    monkeypatch.setattr(app_module, "_check_postgres", AsyncMock(return_value=(True, {"status": "ok", "latency_ms": 1})))
    monkeypatch.setattr(app_module, "_check_redis", AsyncMock(return_value=(True, {"status": "ok", "latency_ms": 1})))

    from app.gateway.app import create_app
    app = create_app()
    return TestClient(app)


class TestHealthLive:
    def test_returns_alive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _make_app_client(monkeypatch)
        resp = client.get("/health/live")
        assert resp.status_code == 200
        assert resp.json() == {"status": "alive"}

    def test_no_caching(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Liveness must never cache — each call is independent."""
        client = _make_app_client(monkeypatch)
        for _ in range(3):
            resp = client.get("/health/live")
            assert resp.status_code == 200
            assert resp.json() == {"status": "alive"}


class TestHealthLegacy:
    def test_returns_healthy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _make_app_client(monkeypatch)
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert data["service"] == "deer-flow-gateway"


class TestHealthReady:
    def test_all_backends_ok_returns_200(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _make_app_client(monkeypatch)
        resp = client.get("/health/ready")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ready"
        assert data["cached"] is False
        assert data["checks"]["postgres"]["status"] == "ok"
        assert data["checks"]["redis"]["status"] == "ok"

    def test_postgres_down_returns_503(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import app.gateway.app as app_module
        monkeypatch.setattr(app_module, "_check_postgres", AsyncMock(return_value=(False, {"status": "error", "message": "connection refused"})))
        monkeypatch.setattr(app_module, "_check_redis", AsyncMock(return_value=(True, {"status": "ok", "latency_ms": 1})))

        from app.gateway.app import create_app
        app = create_app()
        client = TestClient(app)
        resp = client.get("/health/ready")
        assert resp.status_code == 503
        assert resp.json()["status"] == "not_ready"

    def test_redis_down_returns_503(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import app.gateway.app as app_module
        monkeypatch.setattr(app_module, "_check_postgres", AsyncMock(return_value=(True, {"status": "ok", "latency_ms": 1})))
        monkeypatch.setattr(app_module, "_check_redis", AsyncMock(return_value=(False, {"status": "timeout", "message": "5s timeout"})))

        from app.gateway.app import create_app
        app = create_app()
        client = TestClient(app)
        resp = client.get("/health/ready")
        assert resp.status_code == 503
        assert resp.json()["status"] == "not_ready"

    def test_caching_within_ttl(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Second call within TTL should return cached result."""
        import app.gateway.app as app_module
        pg_mock = AsyncMock(return_value=(True, {"status": "ok", "latency_ms": 1}))
        redis_mock = AsyncMock(return_value=(True, {"status": "ok", "latency_ms": 1}))
        monkeypatch.setattr(app_module, "_check_postgres", pg_mock)
        monkeypatch.setattr(app_module, "_check_redis", redis_mock)

        from app.gateway.app import create_app
        app = create_app()
        client = TestClient(app)

        resp1 = client.get("/health/ready")
        assert resp1.json()["cached"] is False
        assert pg_mock.call_count == 1

        resp2 = client.get("/health/ready")
        assert resp2.json()["cached"] is True
        assert pg_mock.call_count == 1


class TestHealthMetrics:
    def test_returns_prometheus_format(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.gateway.health_metrics import record_health_check, reset_health_metrics
        reset_health_metrics()
        record_health_check("postgres", "ok")
        record_health_check("redis", "timeout")

        client = _make_app_client(monkeypatch)
        resp = client.get("/health/metrics")
        assert resp.status_code == 200
        assert "text/plain" in resp.headers["content-type"]
        body = resp.text
        assert 'health_check_total{backend="postgres",status="ok"}' in body
        assert 'health_check_total{backend="redis",status="timeout"}' in body
        reset_health_metrics()
