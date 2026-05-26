"""Tests for template marketplace API routes."""

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


@pytest.fixture
def admin_headers():
    """Mock tenant admin headers."""
    return {"X-User-Id": "admin-user", "X-Tenant-Id": "test-tenant", "X-System-Role": "tenant_admin"}


class TestListListings:
    """Tests for GET /api/template-marketplace"""

    def test_list_listings_success(self, client, auth_headers):
        """List marketplace listings."""
        response = client.get("/api/template-marketplace", headers=auth_headers)
        assert response.status_code == 200

        listings = response.json()
        assert isinstance(listings, list)

        if len(listings) > 0:
            listing = listings[0]
            assert "id" in listing
            assert "template_id" in listing
            assert "display_name" in listing
            assert "description" in listing
            assert "visibility" in listing
            assert "avg_rating" in listing
            assert "review_count" in listing
            assert "install_count" in listing

    def test_list_listings_filter_by_category(self, client, auth_headers):
        """Filter listings by category."""
        response = client.get("/api/template-marketplace?category=daily", headers=auth_headers)
        assert response.status_code == 200

        listings = response.json()
        assert all(
            listing.get("category") == "daily" or listing.get("category") is None
            for listing in listings
        )

    def test_list_listings_filter_by_visibility(self, client, auth_headers):
        """Filter listings by visibility."""
        response = client.get("/api/template-marketplace?visibility=tenant", headers=auth_headers)
        assert response.status_code == 200

        listings = response.json()
        assert all(listing["visibility"] == "tenant" for listing in listings)

    def test_list_listings_search(self, client, auth_headers):
        """Search listings by keyword."""
        response = client.get("/api/template-marketplace?search=report", headers=auth_headers)
        assert response.status_code == 200

        listings = response.json()
        assert isinstance(listings, list)

    def test_list_listings_sort_by_rating(self, client, auth_headers):
        """Sort listings by rating."""
        response = client.get("/api/template-marketplace?sort_by=avg_rating&sort_order=desc", headers=auth_headers)
        assert response.status_code == 200

        listings = response.json()
        if len(listings) > 1:
            ratings = [listing["avg_rating"] for listing in listings]
            assert ratings == sorted(ratings, reverse=True)

    def test_list_listings_pagination(self, client, auth_headers):
        """Test pagination with limit and offset."""
        response = client.get("/api/template-marketplace?limit=5&offset=0", headers=auth_headers)
        assert response.status_code == 200

        listings = response.json()
        assert len(listings) <= 5

    def test_list_listings_unauthenticated(self, client):
        """List listings without authentication."""
        response = client.get("/api/template-marketplace")
        assert response.status_code == 401


class TestGetListing:
    """Tests for GET /api/template-marketplace/{id}"""

    def test_get_listing_not_found(self, client, auth_headers):
        """Get a non-existent listing."""
        response = client.get("/api/template-marketplace/nonexistent", headers=auth_headers)
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_get_listing_unauthenticated(self, client):
        """Get listing without authentication."""
        response = client.get("/api/template-marketplace/some-id")
        assert response.status_code == 401


class TestListReviews:
    """Tests for GET /api/template-marketplace/{id}/reviews"""

    def test_list_reviews_success(self, client, auth_headers):
        """List reviews for a listing."""
        # First try to get a listing ID
        list_response = client.get("/api/template-marketplace", headers=auth_headers)
        if list_response.status_code != 200 or not list_response.json():
            pytest.skip("No listings available")

        listing_id = list_response.json()[0]["id"]
        response = client.get(f"/api/template-marketplace/{listing_id}/reviews", headers=auth_headers)
        assert response.status_code == 200

        reviews = response.json()
        assert isinstance(reviews, list)

        if len(reviews) > 0:
            review = reviews[0]
            assert "id" in review
            assert "listing_id" in review
            assert "user_id" in review
            assert "rating" in review
            assert "comment" in review

    def test_list_reviews_unauthenticated(self, client):
        """List reviews without authentication."""
        response = client.get("/api/template-marketplace/some-id/reviews")
        assert response.status_code == 401


class TestCreateReview:
    """Tests for POST /api/template-marketplace/{id}/reviews"""

    def test_create_review_listing_not_found(self, client, auth_headers):
        """Create review for non-existent listing."""
        payload = {"rating": 5, "comment": "Great template!"}
        response = client.post(
            "/api/template-marketplace/nonexistent/reviews",
            json=payload,
            headers=auth_headers
        )
        assert response.status_code == 404

    def test_create_review_invalid_rating(self, client, auth_headers):
        """Create review with invalid rating."""
        list_response = client.get("/api/template-marketplace", headers=auth_headers)
        if list_response.status_code != 200 or not list_response.json():
            pytest.skip("No listings available")

        listing_id = list_response.json()[0]["id"]
        payload = {"rating": 6, "comment": "Too high"}
        response = client.post(
            f"/api/template-marketplace/{listing_id}/reviews",
            json=payload,
            headers=auth_headers
        )
        assert response.status_code == 422

    def test_create_review_unauthenticated(self, client):
        """Create review without authentication."""
        payload = {"rating": 5, "comment": "Great!"}
        response = client.post(
            "/api/template-marketplace/some-id/reviews",
            json=payload
        )
        assert response.status_code == 401


class TestInstallTemplate:
    """Tests for POST /api/template-marketplace/{id}/install"""

    def test_install_listing_not_found(self, client, auth_headers):
        """Install from non-existent listing."""
        payload = {"target_visibility": "private"}
        response = client.post(
            "/api/template-marketplace/nonexistent/install",
            json=payload,
            headers=auth_headers
        )
        assert response.status_code == 404

    def test_install_invalid_target_visibility(self, client, auth_headers):
        """Install with invalid target visibility."""
        list_response = client.get("/api/template-marketplace", headers=auth_headers)
        if list_response.status_code != 200 or not list_response.json():
            pytest.skip("No listings available")

        listing_id = list_response.json()[0]["id"]
        payload = {"target_visibility": "invalid"}
        response = client.post(
            f"/api/template-marketplace/{listing_id}/install",
            json=payload,
            headers=auth_headers
        )
        assert response.status_code in (400, 422)

    def test_install_to_tenant_requires_admin(self, client, auth_headers):
        """Install to tenant space requires tenant_admin."""
        list_response = client.get("/api/template-marketplace", headers=auth_headers)
        if list_response.status_code != 200 or not list_response.json():
            pytest.skip("No listings available")

        listing_id = list_response.json()[0]["id"]
        payload = {"target_visibility": "tenant"}
        response = client.post(
            f"/api/template-marketplace/{listing_id}/install",
            json=payload,
            headers=auth_headers
        )
        assert response.status_code == 403
        assert "tenant_admin" in response.json()["detail"].lower()

    def test_install_to_tenant_as_admin(self, client, admin_headers):
        """Install to tenant space as admin."""
        list_response = client.get("/api/template-marketplace", headers=admin_headers)
        if list_response.status_code != 200 or not list_response.json():
            pytest.skip("No listings available")

        listing_id = list_response.json()[0]["id"]
        payload = {"target_visibility": "tenant", "target_name": "Installed Template"}
        response = client.post(
            f"/api/template-marketplace/{listing_id}/install",
            json=payload,
            headers=admin_headers
        )
        assert response.status_code == 200

        result = response.json()
        assert "id" in result
        assert "listing_id" in result
        assert "target_template_id" in result
        assert result["listing_id"] == listing_id

    def test_install_unauthenticated(self, client):
        """Install without authentication."""
        payload = {"target_visibility": "private"}
        response = client.post(
            "/api/template-marketplace/some-id/install",
            json=payload
        )
        assert response.status_code == 401


class TestPublishToMarketplace:
    """Tests for POST /api/report-templates/{id}/publish-to-marketplace"""

    def test_publish_template_not_found(self, client, auth_headers):
        """Publish non-existent template to marketplace."""
        payload = {
            "display_name": "Test Template",
            "description": "A test template",
            "visibility": "tenant"
        }
        response = client.post(
            "/api/report-templates/nonexistent/publish-to-marketplace",
            json=payload,
            headers=auth_headers
        )
        assert response.status_code == 404

    def test_publish_missing_display_name(self, client, auth_headers):
        """Publish without display name."""
        payload = {
            "description": "A test template",
            "visibility": "tenant"
        }
        response = client.post(
            "/api/report-templates/some-id/publish-to-marketplace",
            json=payload,
            headers=auth_headers
        )
        assert response.status_code == 422

    def test_publish_invalid_visibility(self, client, auth_headers):
        """Publish with invalid visibility."""
        payload = {
            "display_name": "Test Template",
            "description": "A test template",
            "visibility": "invalid"
        }
        response = client.post(
            "/api/report-templates/some-id/publish-to-marketplace",
            json=payload,
            headers=auth_headers
        )
        assert response.status_code in (400, 422)

    def test_publish_unauthenticated(self, client):
        """Publish without authentication."""
        payload = {
            "display_name": "Test Template",
            "description": "A test template",
            "visibility": "tenant"
        }
        response = client.post(
            "/api/report-templates/some-id/publish-to-marketplace",
            json=payload
        )
        assert response.status_code == 401


class TestApproveListing:
    """Tests for POST /api/template-marketplace/{id}/approve"""

    def test_approve_requires_admin(self, client, auth_headers):
        """Approve listing requires tenant_admin."""
        payload = {"approved": True}
        response = client.post(
            "/api/template-marketplace/some-id/approve",
            json=payload,
            headers=auth_headers
        )
        assert response.status_code == 403
        assert "tenant_admin" in response.json()["detail"].lower() or "superadmin" in response.json()["detail"].lower()

    def test_approve_listing_not_found(self, client, admin_headers):
        """Approve non-existent listing."""
        payload = {"approved": True}
        response = client.post(
            "/api/template-marketplace/nonexistent/approve",
            json=payload,
            headers=admin_headers
        )
        assert response.status_code == 404

    def test_approve_listing_not_pending(self, client, admin_headers):
        """Approve listing that is not pending."""
        list_response = client.get("/api/template-marketplace", headers=admin_headers)
        if list_response.status_code != 200 or not list_response.json():
            pytest.skip("No listings available")

        listing_id = list_response.json()[0]["id"]
        payload = {"approved": True}
        response = client.post(
            f"/api/template-marketplace/{listing_id}/approve",
            json=payload,
            headers=admin_headers
        )
        assert response.status_code == 400
        assert "not pending" in response.json()["detail"].lower()

    def test_approve_unauthenticated(self, client):
        """Approve without authentication."""
        payload = {"approved": True}
        response = client.post(
            "/api/template-marketplace/some-id/approve",
            json=payload
        )
        assert response.status_code == 401


class TestMarketplaceIntegration:
    """Integration tests for marketplace workflow."""

    def test_full_workflow_list_get_reviews(self, client, auth_headers):
        """Test workflow: list → get detail → list reviews."""
        # Step 1: List marketplace
        list_response = client.get("/api/template-marketplace", headers=auth_headers)
        assert list_response.status_code == 200
        listings = list_response.json()

        if not listings:
            pytest.skip("No listings available for integration test")

        # Step 2: Get detail of first listing
        listing_id = listings[0]["id"]
        detail_response = client.get(f"/api/template-marketplace/{listing_id}", headers=auth_headers)
        assert detail_response.status_code == 200

        detail = detail_response.json()
        assert detail["id"] == listing_id

        # Step 3: List reviews
        reviews_response = client.get(f"/api/template-marketplace/{listing_id}/reviews", headers=auth_headers)
        assert reviews_response.status_code == 200
        assert isinstance(reviews_response.json(), list)

    def test_search_and_filter_combination(self, client, auth_headers):
        """Test combining search with filters."""
        response = client.get(
            "/api/template-marketplace?search=report&visibility=tenant&sort_by=install_count&sort_order=desc",
            headers=auth_headers
        )
        assert response.status_code == 200

        listings = response.json()
        assert isinstance(listings, list)

        if len(listings) > 0:
            assert all(listing["visibility"] == "tenant" for listing in listings)
