"""Tests for blueprint API routes."""

import pytest
from fastapi.testclient import TestClient

from app.gateway.app import create_app


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


@pytest.fixture
def auth_headers():
    """Mock authenticated user headers."""
    return {"X-User-Id": "test-user", "X-Tenant-Id": "test-tenant"}


class TestListBlueprints:
    """Tests for GET /api/blueprints"""

    def test_list_blueprints_success(self, client, auth_headers):
        """List all available blueprints."""
        response = client.get("/api/blueprints", headers=auth_headers)
        assert response.status_code == 200

        blueprints = response.json()
        assert isinstance(blueprints, list)
        assert len(blueprints) > 0

        # Check structure of first blueprint
        bp = blueprints[0]
        assert "id" in bp
        assert "name" in bp
        assert "description" in bp
        assert "category" in bp
        assert "icon" in bp or bp.get("icon") is None
        assert "tags" in bp

    def test_list_blueprints_filter_by_category(self, client, auth_headers):
        """Filter blueprints by category."""
        response = client.get("/api/blueprints?category=daily", headers=auth_headers)
        assert response.status_code == 200

        blueprints = response.json()
        assert all(bp["category"] == "daily" for bp in blueprints)

    def test_list_blueprints_unauthenticated(self, client):
        """List blueprints without authentication."""
        response = client.get("/api/blueprints")
        assert response.status_code == 401


class TestGetBlueprint:
    """Tests for GET /api/blueprints/{blueprint_id}"""

    def test_get_blueprint_success(self, client, auth_headers):
        """Get full details of a blueprint."""
        # First list to get a valid blueprint ID
        list_response = client.get("/api/blueprints", headers=auth_headers)
        assert list_response.status_code == 200
        blueprints = list_response.json()
        blueprint_id = blueprints[0]["id"]

        # Now get details
        response = client.get(f"/api/blueprints/{blueprint_id}", headers=auth_headers)
        assert response.status_code == 200

        detail = response.json()
        assert detail["id"] == blueprint_id
        assert "base_dsl" in detail
        assert isinstance(detail["base_dsl"], dict)
        assert "user_configurable" in detail
        assert "recommended_scripts" in detail
        assert "preview_sections" in detail

    def test_get_blueprint_not_found(self, client, auth_headers):
        """Get a non-existent blueprint."""
        response = client.get("/api/blueprints/nonexistent", headers=auth_headers)
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_get_blueprint_unauthenticated(self, client):
        """Get blueprint without authentication."""
        response = client.get("/api/blueprints/daily")
        assert response.status_code == 401


class TestCreateFromBlueprint:
    """Tests for POST /api/blueprints/{blueprint_id}/create-template"""

    def test_create_from_blueprint_success(self, client, auth_headers):
        """Create a new template from a blueprint."""
        # First list to get a valid blueprint ID
        list_response = client.get("/api/blueprints", headers=auth_headers)
        assert list_response.status_code == 200
        blueprints = list_response.json()
        blueprint_id = blueprints[0]["id"]

        # Create template
        payload = {
            "name": "My Custom Daily Report",
            "visibility": "private"
        }
        response = client.post(
            f"/api/blueprints/{blueprint_id}/create-template",
            json=payload,
            headers=auth_headers
        )
        assert response.status_code == 200

        result = response.json()
        assert "template_id" in result
        assert "message" in result
        assert blueprint_id in result["message"]

    def test_create_from_blueprint_not_found(self, client, auth_headers):
        """Create template from non-existent blueprint."""
        payload = {
            "name": "My Custom Report",
            "visibility": "private"
        }
        response = client.post(
            "/api/blueprints/nonexistent/create-template",
            json=payload,
            headers=auth_headers
        )
        assert response.status_code == 404

    def test_create_from_blueprint_invalid_visibility(self, client, auth_headers):
        """Create template with invalid visibility."""
        # First list to get a valid blueprint ID
        list_response = client.get("/api/blueprints", headers=auth_headers)
        blueprints = list_response.json()
        blueprint_id = blueprints[0]["id"]

        payload = {
            "name": "My Custom Report",
            "visibility": "invalid"
        }
        response = client.post(
            f"/api/blueprints/{blueprint_id}/create-template",
            json=payload,
            headers=auth_headers
        )
        assert response.status_code == 400

    def test_create_from_blueprint_missing_name(self, client, auth_headers):
        """Create template without name field."""
        # First list to get a valid blueprint ID
        list_response = client.get("/api/blueprints", headers=auth_headers)
        blueprints = list_response.json()
        blueprint_id = blueprints[0]["id"]

        payload = {"visibility": "private"}
        response = client.post(
            f"/api/blueprints/{blueprint_id}/create-template",
            json=payload,
            headers=auth_headers
        )
        assert response.status_code == 422  # Validation error

    def test_create_from_blueprint_unauthenticated(self, client):
        """Create template without authentication."""
        payload = {
            "name": "My Custom Report",
            "visibility": "private"
        }
        response = client.post(
            "/api/blueprints/daily/create-template",
            json=payload
        )
        assert response.status_code == 401


class TestBlueprintIntegration:
    """Integration tests for blueprint workflow."""

    def test_full_workflow_list_get_create(self, client, auth_headers):
        """Test the full workflow: list → get details → create template."""
        # Step 1: List blueprints
        list_response = client.get("/api/blueprints", headers=auth_headers)
        assert list_response.status_code == 200
        blueprints = list_response.json()
        assert len(blueprints) > 0

        # Step 2: Get details of first blueprint
        blueprint_id = blueprints[0]["id"]
        detail_response = client.get(f"/api/blueprints/{blueprint_id}", headers=auth_headers)
        assert detail_response.status_code == 200
        detail = detail_response.json()

        # Step 3: Create template from blueprint
        payload = {
            "name": f"Custom {detail['name']}",
            "visibility": "private"
        }
        create_response = client.post(
            f"/api/blueprints/{blueprint_id}/create-template",
            json=payload,
            headers=auth_headers
        )
        assert create_response.status_code == 200

        result = create_response.json()
        assert result["template_id"].startswith("tpl_")
