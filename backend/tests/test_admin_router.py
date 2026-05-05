"""Tests for admin API router."""

import uuid
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from deerflow.config.auth_config import load_auth_config_from_dict, reset_auth_config


@pytest.fixture(autouse=True)
def _reset_auth():
    reset_auth_config()
    yield
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

    # Mock checkpointer so admin stats/tenants endpoints don't return 503
    mock_checkpointer = MagicMock()
    mock_checkpointer.alist = MagicMock(return_value=AsyncIteratorWrapper([]))
    app.state.checkpointer = mock_checkpointer

    return TestClient(app)


class AsyncIteratorWrapper:
    """Wraps a list into an async iterator for mocking checkpointer.alist()."""

    def __init__(self, items):
        self._items = items

    def __aiter__(self):
        self._iter = iter(self._items)
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration


def _make_unauth_client():
    """Create a client with auth enabled but no credentials — expects 401."""
    load_auth_config_from_dict({"enabled": True})
    return TestClient(__import__("app.gateway.app", fromlist=["create_app"]).create_app())


class TestAdminStats:
    def test_requires_auth(self):
        client = _make_unauth_client()
        response = client.get("/api/admin/stats")
        assert response.status_code == 401

    def test_returns_stats_for_admin(self):
        response = _make_client().get("/api/admin/stats")
        assert response.status_code == 200
        data = response.json()
        assert "total_tenants" in data
        assert "total_cost_today" in data
        assert "total_cost_month" in data

    def test_rejects_non_admin(self):
        from app.gateway.app import create_app
        from app.gateway.auth.dependencies import get_current_user

        app = create_app()
        mock_user = MagicMock()
        mock_user.username = "user"
        mock_user.tenant_id = "default"
        mock_user.role = "member"
        mock_user.auth_method = "jwt"
        app.dependency_overrides[get_current_user] = lambda: mock_user
        client = TestClient(app)
        response = client.get("/api/admin/stats")
        assert response.status_code == 403


class TestListTenants:
    def test_requires_auth(self):
        client = _make_unauth_client()
        response = client.get("/api/admin/tenants")
        assert response.status_code == 401

    def test_returns_tenant_list(self):
        response = _make_client().get("/api/admin/tenants")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        tenant_ids = [t["tenant_id"] for t in data]
        assert "default" in tenant_ids


class TestCreateTenant:
    def test_requires_auth(self):
        client = _make_unauth_client()
        response = client.post("/api/admin/tenants", json={"tenant_id": "new-t", "name": "New"})
        assert response.status_code == 401

    def test_creates_tenant(self):
        client = _make_client()
        # Use unique ID to avoid conflicts with persisted state
        tid = f"test-{uuid.uuid4().hex[:8]}"
        response = client.post("/api/admin/tenants", json={"tenant_id": tid, "name": "New Tenant"})
        assert response.status_code == 200
        data = response.json()
        assert data["tenant_id"] == tid
        assert data["name"] == "New Tenant"
        # Clean up
        client.delete(f"/api/admin/tenants/{tid}")

    def test_rejects_invalid_tenant_id(self):
        response = _make_client().post("/api/admin/tenants", json={"tenant_id": "invalid id!", "name": "Bad"})
        assert response.status_code == 422


class TestUpdateTenant:
    def test_requires_auth(self):
        client = _make_unauth_client()
        response = client.put("/api/admin/tenants/t1", json={"name": "Updated"})
        assert response.status_code == 401

    def test_updates_tenant(self):
        client = _make_client()
        tid = f"test-{uuid.uuid4().hex[:8]}"
        # Ensure the tenant exists before updating
        client.post("/api/admin/tenants", json={"tenant_id": tid, "name": "Original Name"})
        response = client.put(f"/api/admin/tenants/{tid}", json={"name": "Updated Name"})
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Updated Name"
        # Clean up
        client.delete(f"/api/admin/tenants/{tid}")


class TestAdminUsage:
    def test_requires_auth(self):
        client = _make_unauth_client()
        response = client.get("/api/admin/usage")
        assert response.status_code == 401

    def test_returns_usage_data(self):
        response = _make_client().get("/api/admin/usage")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
