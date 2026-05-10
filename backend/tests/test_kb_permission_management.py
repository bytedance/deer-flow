"""Integration tests for knowledge base permission management API endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.routers.knowledge_bases import router


def _make_app(kb_service_mock) -> FastAPI:
    app = FastAPI()
    app.state.kb_service = kb_service_mock
    app.include_router(router)
    return app


class FakeUser:
    def __init__(self, user_id: str = "user-1", tenant_id: str = "tenant-1", system_role: str = "superadmin"):
        self.id = user_id
        self.tenant_id = tenant_id
        self.system_role = system_role


@pytest.fixture
def kb_service():
    svc = AsyncMock()
    ac = MagicMock()
    ac.can_create.return_value = True
    svc.access_control = ac
    return svc


def _client_with_user(kb_service, user: FakeUser):
    app = _make_app(kb_service)
    with patch("app.gateway.routers.knowledge_bases.get_current_user_from_request", return_value=user):
        yield TestClient(app)


@pytest.fixture
def admin_client(kb_service):
    user = FakeUser(user_id="admin-1", tenant_id="tenant-1", system_role="superadmin")
    app = _make_app(kb_service)
    with patch("app.gateway.routers.knowledge_bases.get_current_user_from_request", return_value=user):
        yield TestClient(app)


@pytest.fixture
def tenant_admin_client(kb_service):
    user = FakeUser(user_id="tadmin-1", tenant_id="tenant-1", system_role="tenant_admin")
    app = _make_app(kb_service)
    with patch("app.gateway.routers.knowledge_bases.get_current_user_from_request", return_value=user):
        yield TestClient(app)


@pytest.fixture
def regular_client(kb_service):
    user = FakeUser(user_id="user-2", tenant_id="tenant-1", system_role="user")
    app = _make_app(kb_service)
    with patch("app.gateway.routers.knowledge_bases.get_current_user_from_request", return_value=user):
        yield TestClient(app)


SAMPLE_PERMISSION = {
    "id": "perm-1",
    "knowledge_base_id": "kb-1",
    "tenant_id": "tenant-1",
    "user_id": "user-2",
    "role": "editor",
    "granted_by": "admin-1",
    "created_at": "2026-05-10T00:00:00+00:00",
}


class TestListPermissions:
    def test_admin_can_list(self, admin_client, kb_service):
        kb_service.list_permissions.return_value = [SAMPLE_PERMISSION]
        resp = admin_client.get("/api/knowledge-bases/kb-1/permissions")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["user_id"] == "user-2"
        assert data[0]["role"] == "editor"

    def test_list_empty(self, admin_client, kb_service):
        kb_service.list_permissions.return_value = []
        resp = admin_client.get("/api/knowledge-bases/kb-1/permissions")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_non_admin_gets_403(self, regular_client, kb_service):
        kb_service.list_permissions.side_effect = PermissionError("Admin access required")
        resp = regular_client.get("/api/knowledge-bases/kb-1/permissions")
        assert resp.status_code == 403

    def test_kb_not_found_gets_404(self, admin_client, kb_service):
        kb_service.list_permissions.side_effect = ValueError("not found")
        resp = admin_client.get("/api/knowledge-bases/kb-1/permissions")
        assert resp.status_code == 404


class TestGrantPermission:
    def test_admin_can_grant(self, admin_client, kb_service):
        kb_service.grant_permission.return_value = SAMPLE_PERMISSION
        resp = admin_client.post(
            "/api/knowledge-bases/kb-1/permissions",
            json={"user_id": "user-2", "role": "editor"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["user_id"] == "user-2"
        assert data["role"] == "editor"
        assert data["granted_by"] == "admin-1"

    def test_non_admin_gets_403(self, regular_client, kb_service):
        kb_service.grant_permission.side_effect = PermissionError("Admin access required")
        resp = regular_client.post(
            "/api/knowledge-bases/kb-1/permissions",
            json={"user_id": "user-3", "role": "viewer"},
        )
        assert resp.status_code == 403

    def test_kb_not_found_gets_404(self, admin_client, kb_service):
        kb_service.grant_permission.side_effect = ValueError("Knowledge base not found")
        resp = admin_client.post(
            "/api/knowledge-bases/kb-1/permissions",
            json={"user_id": "user-2", "role": "editor"},
        )
        assert resp.status_code == 404

    def test_invalid_role_gets_422(self, admin_client, kb_service):
        resp = admin_client.post(
            "/api/knowledge-bases/kb-1/permissions",
            json={"user_id": "user-2", "role": "superuser"},
        )
        assert resp.status_code == 422

    def test_empty_user_id_gets_422(self, admin_client, kb_service):
        resp = admin_client.post(
            "/api/knowledge-bases/kb-1/permissions",
            json={"user_id": "", "role": "viewer"},
        )
        assert resp.status_code == 422

    def test_invalid_role_from_service_gets_400(self, admin_client, kb_service):
        kb_service.grant_permission.side_effect = ValueError("Invalid role: owner")
        resp = admin_client.post(
            "/api/knowledge-bases/kb-1/permissions",
            json={"user_id": "user-2", "role": "editor"},
        )
        assert resp.status_code == 400


class TestRevokePermission:
    def test_admin_can_revoke(self, admin_client, kb_service):
        kb_service.revoke_permission.return_value = True
        resp = admin_client.delete("/api/knowledge-bases/kb-1/permissions/user-2")
        assert resp.status_code == 204

    def test_non_admin_gets_403(self, regular_client, kb_service):
        kb_service.revoke_permission.side_effect = PermissionError("Admin access required")
        resp = regular_client.delete("/api/knowledge-bases/kb-1/permissions/user-2")
        assert resp.status_code == 403

    def test_kb_not_found_gets_404(self, admin_client, kb_service):
        kb_service.revoke_permission.side_effect = ValueError("not found")
        resp = admin_client.delete("/api/knowledge-bases/kb-1/permissions/user-2")
        assert resp.status_code == 404

    def test_permission_not_found_gets_404(self, admin_client, kb_service):
        kb_service.revoke_permission.return_value = False
        resp = admin_client.delete("/api/knowledge-bases/kb-1/permissions/user-99")
        assert resp.status_code == 404


SAMPLE_KB = {
    "id": "kb-1",
    "name": "Shared KB",
    "description": "A tenant-visible KB",
    "visibility": "tenant",
    "status": "active",
    "document_count": 5,
    "chunk_count": 20,
    "last_indexed_at": "2026-05-10T00:00:00+00:00",
    "last_search_at": None,
    "created_at": "2026-05-08T00:00:00+00:00",
    "updated_at": "2026-05-10T00:00:00+00:00",
}


class TestAdminView:
    def test_superadmin_can_list(self, admin_client, kb_service):
        kb_service.list_admin_knowledge_bases.return_value = [SAMPLE_KB]
        resp = admin_client.get("/api/knowledge-bases/admin/all")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["visibility"] == "tenant"

    def test_tenant_admin_can_list(self, tenant_admin_client, kb_service):
        kb_service.list_admin_knowledge_bases.return_value = [SAMPLE_KB]
        resp = tenant_admin_client.get("/api/knowledge-bases/admin/all")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_regular_user_gets_403(self, regular_client, kb_service):
        kb_service.list_admin_knowledge_bases.side_effect = PermissionError("Admin role required")
        resp = regular_client.get("/api/knowledge-bases/admin/all")
        assert resp.status_code == 403

    def test_visibility_filter(self, admin_client, kb_service):
        kb_service.list_admin_knowledge_bases.return_value = []
        resp = admin_client.get("/api/knowledge-bases/admin/all?visibility=public")
        assert resp.status_code == 200
        kb_service.list_admin_knowledge_bases.assert_called_once_with(
            tenant_id="tenant-1",
            role="superadmin",
            visibility_filter="public",
            limit=50,
            offset=0,
        )

    def test_pagination(self, admin_client, kb_service):
        kb_service.list_admin_knowledge_bases.return_value = []
        resp = admin_client.get("/api/knowledge-bases/admin/all?limit=10&offset=5")
        assert resp.status_code == 200
        kb_service.list_admin_knowledge_bases.assert_called_once_with(
            tenant_id="tenant-1",
            role="superadmin",
            visibility_filter=None,
            limit=10,
            offset=5,
        )

    def test_admin_all_not_captured_as_kb_id(self, admin_client, kb_service):
        """Verify /admin/all is not interpreted as /{kb_id} with kb_id='admin'."""
        kb_service.list_admin_knowledge_bases.return_value = []
        resp = admin_client.get("/api/knowledge-bases/admin/all")
        assert resp.status_code == 200
        kb_service.get_kb_with_permissions.assert_not_called()
