"""Tests for knowledge base REST API router."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

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
def mock_user():
    return FakeUser()


@pytest.fixture
def kb_service():
    svc = AsyncMock()
    from unittest.mock import MagicMock

    ac = MagicMock()
    ac.can_create.return_value = True
    svc.access_control = ac
    return svc


@pytest.fixture
def client(kb_service, mock_user):
    app = _make_app(kb_service)
    with patch("app.gateway.routers.knowledge_bases.get_current_user_from_request", return_value=mock_user):
        yield TestClient(app)


class TestKnowledgeBaseCRUD:
    def test_list_empty(self, client, kb_service):
        kb_service.list_knowledge_bases.return_value = []
        resp = client.get("/api/knowledge-bases")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_create(self, client, kb_service):
        kb_service.create_knowledge_base.return_value = {
            "id": "kb-1",
            "name": "Test KB",
            "description": None,
            "visibility": "private",
            "status": "active",
            "document_count": 0,
            "chunk_count": 0,
            "last_indexed_at": None,
            "last_search_at": None,
            "created_at": "2026-05-08T00:00:00+00:00",
            "updated_at": "2026-05-08T00:00:00+00:00",
        }
        resp = client.post("/api/knowledge-bases", json={"name": "Test KB"})
        assert resp.status_code == 201
        assert resp.json()["name"] == "Test KB"

    def test_get_not_found(self, client, kb_service):
        kb_service.get_kb_with_permissions.return_value = None
        resp = client.get("/api/knowledge-bases/nonexistent")
        assert resp.status_code == 404

    def test_get_found(self, client, kb_service):
        kb_service.get_kb_with_permissions.return_value = {
            "id": "kb-1",
            "name": "My KB",
            "description": "desc",
            "visibility": "private",
            "status": "active",
            "document_count": 2,
            "chunk_count": 10,
            "last_indexed_at": None,
            "last_search_at": None,
            "created_at": "2026-05-08T00:00:00+00:00",
            "updated_at": "2026-05-08T00:00:00+00:00",
        }
        resp = client.get("/api/knowledge-bases/kb-1")
        assert resp.status_code == 200
        assert resp.json()["id"] == "kb-1"

    def test_delete(self, client, kb_service):
        kb_service.check_admin_permission.return_value = None
        kb_service.delete_knowledge_base.return_value = True
        resp = client.delete("/api/knowledge-bases/kb-1")
        assert resp.status_code == 204

    def test_delete_not_found(self, client, kb_service):
        kb_service.check_admin_permission.side_effect = ValueError("not found")
        resp = client.delete("/api/knowledge-bases/kb-1")
        assert resp.status_code == 404


class TestDocumentCRUD:
    def test_create_document(self, client, kb_service):
        kb_service.create_document_with_access_check.return_value = {
            "id": "doc-1",
            "knowledge_base_id": "kb-1",
            "title": "Doc",
            "content": "Hello",
            "content_format": "markdown",
            "source_name": None,
            "content_length": 5,
            "content_hash": "abc",
            "version": 1,
            "chunk_count": 1,
            "index_status": "ready",
            "index_error": None,
            "last_indexed_at": "2026-05-08T00:00:00+00:00",
            "metadata_json": {},
            "created_at": "2026-05-08T00:00:00+00:00",
            "updated_at": "2026-05-08T00:00:00+00:00",
        }
        resp = client.post("/api/knowledge-bases/kb-1/documents", json={"title": "Doc", "content": "Hello"})
        assert resp.status_code == 201
        assert resp.json()["title"] == "Doc"

    def test_get_document_not_found(self, client, kb_service):
        kb_service.get_document_with_access_check.return_value = None
        resp = client.get("/api/knowledge-bases/kb-1/documents/doc-1")
        assert resp.status_code == 404

    def test_delete_document(self, client, kb_service):
        kb_service.delete_document_with_access_check.return_value = True
        resp = client.delete("/api/knowledge-bases/kb-1/documents/doc-1")
        assert resp.status_code == 204


class TestSearch:
    def test_search(self, client, kb_service):
        kb_service.search.return_value = [
            {"chunk_id": "c1", "content": "result text", "score": 0.9, "metadata": {}},
        ]
        resp = client.post("/api/knowledge-bases/kb-1/search", json={"query": "test"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["query"] == "test"
        assert len(data["results"]) == 1
        assert data["results"][0]["score"] == 0.9

    def test_search_kb_not_found(self, client, kb_service):
        kb_service.search.side_effect = ValueError("Knowledge base kb-1 not found")
        resp = client.post("/api/knowledge-bases/kb-1/search", json={"query": "test"})
        assert resp.status_code == 404
