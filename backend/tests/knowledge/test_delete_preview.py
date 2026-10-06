"""Tests for POST /knowledge-bases/{kb_id}/chunks/delete-preview endpoint (Phase-3 Batch-1 P5).

Delete impact preview: calculate orphaned entities, affected entities, and relation
deletions WITHOUT actually deleting anything. Pure read-only operation.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.gateway.auth.models import User
from app.gateway.routers import knowledge_bases
from app.gateway.services.knowledge_service import KnowledgeService
from deerflow.knowledge.graph.extractor import ExtractedEntity
from deerflow.knowledge.store import KnowledgeStore

pytestmark = pytest.mark.asyncio

OWNER_ID = str(UUID(int=1234567890))


def _owner() -> User:
    return User(email="owner@example.com", password_hash="x", system_role="user", id=UUID(OWNER_ID))


@pytest.fixture
def service(session_factory, tmp_path) -> KnowledgeService:
    vector_store = MagicMock()
    vector_store.delete_by_doc = AsyncMock()
    vector_store.delete_by_kb = AsyncMock()
    vector_store.delete_entities = AsyncMock()
    vector_store.delete_wiki_entries = AsyncMock()
    worker = MagicMock()
    worker.submit = AsyncMock()
    return KnowledgeService(
        store=KnowledgeStore(session_factory),
        vector_store=vector_store,
        graph_store=None,
        wiki_store=None,
        worker=worker,
        data_dir=tmp_path,
    )


def _client(service: KnowledgeService, user_factory=_owner) -> TestClient:
    from _router_auth_helpers import make_authed_test_app

    app = make_authed_test_app(user_factory=user_factory)
    app.state.knowledge_service = service
    app.include_router(knowledge_bases.router)
    return TestClient(app)


def _create_kb(client: TestClient, name: str = "产品资料") -> dict:
    response = client.post("/api/knowledge-bases", json={"name": name, "description": "d"})
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
async def setup_graph_with_entities(service, session_factory):
    """Setup KB with chunks and entities for preview testing."""
    kb_id = f"kb-test-{uuid.uuid4().hex[:8]}"
    doc_id = "doc-test"

    # Create KB and document
    await service.store.create_kb(kb_id=kb_id, owner_id=OWNER_ID, name="Test KB")
    await service.store.create_document(doc_id=doc_id, kb_id=kb_id, uploader_id=OWNER_ID, name="test.txt", size_bytes=10, storage_path="/test.txt")

    # Insert chunks
    await service.store.insert_chunks(
        [
            {
                "chunk_id": f"{doc_id}-c0",
                "doc_id": doc_id,
                "kb_id": kb_id,
                "chunk_index": 0,
                "text": "Content 0",
                "token_count": 5,
                "extract_status": "done",
                "entities": [],
            },
            {
                "chunk_id": f"{doc_id}-c1",
                "doc_id": doc_id,
                "kb_id": kb_id,
                "chunk_index": 1,
                "text": "Content 1",
                "token_count": 5,
                "extract_status": "done",
                "entities": [],
            },
        ]
    )

    # Seed entities via graph_store
    from deerflow.knowledge.graph.store import GraphStore

    graph_store = GraphStore(session_factory)
    await graph_store.upsert_entities(
        kb_id,
        [
            ExtractedEntity(name="Alpha", type="概念", description="Alpha 描述"),
            ExtractedEntity(name="Beta", type="概念", description="Beta 描述"),
            ExtractedEntity(name="Gamma", type="概念", description="Gamma 描述"),
        ],
        chunk_id=f"{doc_id}-c0",
    )
    await graph_store.upsert_entities(
        kb_id,
        [ExtractedEntity(name="Beta", type="概念", description="Beta 描述")],
        chunk_id=f"{doc_id}-c1",  # Beta also in c1
    )

    return kb_id, doc_id


class TestDeletePreviewEndpoint:
    """RED tests: verify delete preview endpoint behavior."""

    async def test_delete_preview_returns_404_when_chunk_not_found(self, service):
        """POST delete-preview with non-existent chunk should return 404."""
        client = _client(service)
        kb = _create_kb(client)

        response = client.post(
            f"/api/knowledge-bases/{kb['id']}/chunks/delete-preview",
            json={"chunk_ids": ["non-existent-chunk"]},
        )

        assert response.status_code == 404

    async def test_delete_preview_returns_orphaned_entities(self, service, setup_graph_with_entities):
        """Preview should identify entities that will be orphaned after deletion."""
        kb_id, doc_id = setup_graph_with_entities
        client = _client(service)

        # Preview deleting c0 (which has Alpha, Beta, Gamma)
        response = client.post(
            f"/api/knowledge-bases/{kb_id}/chunks/delete-preview",
            json={"chunk_ids": [f"{doc_id}-c0"]},
        )

        assert response.status_code == 200
        data = response.json()

        # Alpha and Gamma should be orphaned (only in c0)
        assert "Alpha" in data["orphaned_entities"]
        assert "Gamma" in data["orphaned_entities"]

        # Beta should be affected but not orphaned (also in c1)
        assert "Beta" not in data["orphaned_entities"]
        assert "Beta" in data["affected_entities"]

    async def test_delete_preview_returns_affected_entities(self, service, setup_graph_with_entities):
        """Preview should identify entities that will lose sources but survive."""
        kb_id, doc_id = setup_graph_with_entities
        client = _client(service)

        # Preview deleting both chunks
        response = client.post(
            f"/api/knowledge-bases/{kb_id}/chunks/delete-preview",
            json={"chunk_ids": [f"{doc_id}-c0", f"{doc_id}-c1"]},
        )

        assert response.status_code == 200
        data = response.json()

        # All entities should be orphaned (no remaining sources)
        assert set(data["orphaned_entities"]) == {"Alpha", "Beta", "Gamma"}
        assert data["affected_entities"] == []

    async def test_delete_preview_returns_relation_deletions(self, service, setup_graph_with_entities):
        """Preview should identify relations that will be deleted."""
        kb_id, doc_id = setup_graph_with_entities
        client = _client(service)

        # Add a relation between Alpha and Beta
        from deerflow.knowledge.graph.extractor import ExtractedRelation
        from deerflow.knowledge.graph.store import GraphStore

        graph_store = GraphStore(service.store._sf)
        await graph_store.upsert_relations(
            kb_id,
            [ExtractedRelation(source="Alpha", target="Beta", relation="关联", description="")],
            chunk_id=f"{doc_id}-c0",
        )

        # Preview deleting c0
        response = client.post(
            f"/api/knowledge-bases/{kb_id}/chunks/delete-preview",
            json={"chunk_ids": [f"{doc_id}-c0"]},
        )

        assert response.status_code == 200
        data = response.json()

        # Relation should be deleted because Alpha is orphaned
        assert len(data["relation_deletions"]) > 0
        relation_names = [f"{r['source']}→{r['target']}" for r in data["relation_deletions"]]
        assert "Alpha→Beta" in relation_names

    async def test_delete_preview_does_not_modify_data(self, service, setup_graph_with_entities):
        """Preview should be pure read-only (no actual deletion)."""
        kb_id, doc_id = setup_graph_with_entities
        client = _client(service)

        # Get entity count before preview
        from deerflow.knowledge.graph.store import GraphStore

        graph_store = GraphStore(service.store._sf)
        entities_before = await graph_store.list_entities(kb_id)
        count_before = len(entities_before)

        # Run preview
        response = client.post(
            f"/api/knowledge-bases/{kb_id}/chunks/delete-preview",
            json={"chunk_ids": [f"{doc_id}-c0"]},
        )
        assert response.status_code == 200

        # Verify no actual deletion happened
        entities_after = await graph_store.list_entities(kb_id)
        count_after = len(entities_after)

        assert count_before == count_after  # No change

        # Verify all entities still exist
        entity_names = {e["name"] for e in entities_after}
        assert "Alpha" in entity_names
        assert "Beta" in entity_names
        assert "Gamma" in entity_names
