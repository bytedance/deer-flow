"""Tests for cost management API router."""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from deerflow.config.auth_config import load_auth_config_from_dict, reset_auth_config
from deerflow.config.cost_config import load_cost_config_from_dict, reset_cost_config


@pytest.fixture(autouse=True)
def _reset_configs():
    reset_cost_config()
    reset_auth_config()
    yield
    reset_cost_config()
    reset_auth_config()


def _make_client():
    from app.gateway.app import create_app
    from app.gateway.auth.dependencies import get_current_user, require_admin

    app = create_app()
    mock_user = MagicMock()
    mock_user.username = "admin"
    mock_user.tenant_id = "default"
    mock_user.role = "admin"
    mock_user.auth_method = "jwt"
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[require_admin] = lambda: mock_user
    return TestClient(app)


def _make_unauth_client():
    """Create a client with auth enabled but no credentials — expects 401."""
    load_auth_config_from_dict({"enabled": True})
    return TestClient(__import__("app.gateway.app", fromlist=["create_app"]).create_app())


class TestCostSummary:
    def test_requires_auth(self):
        client = _make_unauth_client()
        response = client.get("/api/cost/summary")
        assert response.status_code == 401

    def test_disabled_cost_returns_400(self):
        response = _make_client().get("/api/cost/summary")
        assert response.status_code == 400
        assert "not enabled" in response.json()["detail"]

    def test_returns_summary_when_enabled(self):
        load_cost_config_from_dict({"enabled": True, "model_pricing": [], "budget": {}})
        response = _make_client().get("/api/cost/summary")
        assert response.status_code == 200
        data = response.json()
        assert "today_cost_usd" in data
        assert "month_cost_usd" in data
        assert "total_cost_usd" in data


class TestCostBreakdown:
    def test_requires_auth(self):
        client = _make_unauth_client()
        response = client.get("/api/cost/breakdown")
        assert response.status_code == 401

    def test_returns_breakdown_when_enabled(self):
        load_cost_config_from_dict({"enabled": True, "model_pricing": [], "budget": {}})
        response = _make_client().get("/api/cost/breakdown")
        assert response.status_code == 200


class TestBudgetStatus:
    def test_requires_auth(self):
        client = _make_unauth_client()
        response = client.get("/api/cost/budget")
        assert response.status_code == 401

    def test_returns_budget_when_enabled(self):
        load_cost_config_from_dict({"enabled": True, "model_pricing": [], "budget": {}})
        response = _make_client().get("/api/cost/budget")
        assert response.status_code == 200
        data = response.json()
        assert "daily_cost" in data
        assert "monthly_cost" in data
        assert "is_exceeded" in data


class TestUpdateBudget:
    def test_requires_auth(self):
        client = _make_unauth_client()
        response = client.put("/api/cost/budget", json={})
        assert response.status_code == 401

    def test_admin_can_update_budget(self):
        load_cost_config_from_dict({"enabled": True, "model_pricing": [], "budget": {}})
        response = _make_client().put("/api/cost/budget", json={"daily_limit_usd": 100.0})
        assert response.status_code == 200

    def test_non_admin_cannot_update_budget(self):
        from app.gateway.app import create_app
        from app.gateway.auth.dependencies import get_current_user

        load_cost_config_from_dict({"enabled": True, "model_pricing": [], "budget": {}})
        app = create_app()
        mock_user = MagicMock()
        mock_user.username = "user"
        mock_user.tenant_id = "default"
        mock_user.role = "member"
        mock_user.auth_method = "jwt"
        app.dependency_overrides[get_current_user] = lambda: mock_user
        client = TestClient(app)
        response = client.put("/api/cost/budget", json={"daily_limit_usd": 100.0})
        assert response.status_code == 403
