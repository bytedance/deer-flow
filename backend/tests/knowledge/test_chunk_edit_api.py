"""Tests for PATCH /knowledge-bases/{kb_id}/chunks/{chunk_id} endpoint (Phase-3 Batch-1 P2).

Slice text editing: update chunk text, recalculate token count, re-embed to Qdrant.
Entities JSON column remains unchanged (ID 引用 preserved).
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.gateway.auth.models import User
from app.gateway.routers import knowledge_bases
from app.gateway.services import knowledge_service as ks_module
from app.gateway.services.knowledge_service import KnowledgeService
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
    vector_store.upsert_chunks = AsyncMock()  # P2: new method for chunk upsert
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


def _client_no_raise(service: KnowledgeService, user_factory=_owner) -> TestClient:
    """Same as ``_client`` but surfaces 5xx as responses instead of raising
    (``raise_server_exceptions`` is an ASGI-transport init arg — assigning it
    on an existing client has no effect)."""
    from _router_auth_helpers import make_authed_test_app

    app = make_authed_test_app(user_factory=user_factory)
    app.state.knowledge_service = service
    app.include_router(knowledge_bases.router)
    return TestClient(app, raise_server_exceptions=False)


def _create_kb(client: TestClient, name: str = "产品资料") -> dict:
    response = client.post("/api/knowledge-bases", json={"name": name, "description": "d"})
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
async def setup_chunk(service, session_factory):
    """Setup a test chunk and return (kb_id, chunk_id)."""
    kb_id = f"kb-test-{uuid.uuid4().hex[:8]}"
    doc_id = "doc-test"
    await service.store.create_kb(kb_id=kb_id, owner_id=OWNER_ID, name="Test KB")
    await service.store.create_document(doc_id=doc_id, kb_id=kb_id, uploader_id=OWNER_ID, name="test.txt", size_bytes=10, storage_path="/test.txt")
    await service.store.insert_chunks(
        [
            {
                "chunk_id": f"{doc_id}-c0",
                "doc_id": doc_id,
                "kb_id": kb_id,
                "chunk_index": 0,
                "text": "Original content",
                "token_count": 5,
                "extract_status": "done",
                "entities": ["entity1"],
            }
        ]
    )
    return (kb_id, f"{doc_id}-c0")


class TestPatchChunkEndpoint:
    """RED tests: verify endpoint behavior before implementation."""

    async def test_patch_chunk_returns_404_when_chunk_not_found(self, service):
        """PATCH non-existent chunk should return 404."""
        client = _client(service)
        kb = _create_kb(client)

        response = client.patch(
            f"/api/knowledge-bases/{kb['id']}/chunks/non-existent-chunk",
            json={"text": "New chunk content"},
        )

        assert response.status_code == 404
        assert "detail" in response.json()

    async def test_patch_chunk_returns_422_when_text_empty(self, service, setup_chunk):
        """PATCH with empty text should return 422 validation error."""
        kb_id, chunk_id = setup_chunk
        client = _client(service)

        response = client.patch(
            f"/api/knowledge-bases/{kb_id}/chunks/{chunk_id}",
            json={"text": ""},  # Empty text
        )

        assert response.status_code == 422
        assert "detail" in response.json()

    async def test_patch_chunk_updates_text_successfully(self, service, setup_chunk):
        """PATCH existing chunk with valid text should succeed and return updated data."""
        kb_id, chunk_id = setup_chunk
        client = _client(service)

        new_text = "Updated chunk content"
        response = client.patch(
            f"/api/knowledge-bases/{kb_id}/chunks/{chunk_id}",
            json={"text": new_text},
        )

        # Initially this will fail (endpoint not implemented) - RED state
        assert response.status_code == 200
        data = response.json()
        assert data["text"] == new_text
        assert data["kb_id"] == kb_id
        assert data["chunk_id"] == chunk_id

        # Verify last_edited_at is set (P2 requirement)
        assert "last_edited_at" in data
        assert data["last_edited_at"] is not None

    async def test_patch_chunk_recalculates_token_count(self, service, setup_chunk):
        """P2: editing chunk should recalculate token_count."""
        kb_id, chunk_id = setup_chunk
        client = _client(service)

        new_text = "This is a much longer chunk content that should have more tokens than the original five tokens."
        response = client.patch(
            f"/api/knowledge-bases/{kb_id}/chunks/{chunk_id}",
            json={"text": new_text},
        )

        assert response.status_code == 200
        data = response.json()
        # Token count should be recalculated (not the original 5)
        assert data["token_count"] != 5
        assert data["token_count"] > 5

    async def test_patch_chunk_preserves_entities_unchanged(self, service, setup_chunk):
        """P2: entities JSON column remains unchanged after text edit (ID 引用 preserved)."""
        kb_id, chunk_id = setup_chunk
        client = _client(service)

        # Original entities were ["entity1"]
        new_text = "Updated text but entities should not change"
        response = client.patch(
            f"/api/knowledge-bases/{kb_id}/chunks/{chunk_id}",
            json={"text": new_text},
        )

        assert response.status_code == 200
        data = response.json()
        # Entities should remain the same (no re-extraction)
        assert data["entities"] == ["entity1"]

    async def test_patch_chunk_reembeds_vector_with_same_point_id(self, service, setup_chunk, monkeypatch):
        """Task 4 收尾 (2026-08-14): editing chunk text re-embeds and overwrites
        the SAME Qdrant point (same chunk_id → same point id) so retrieval
        sees the new text — the TODO previously left the stale vector in
        place, silently serving the pre-edit content."""
        from qdrant_client.models import SparseVector

        from deerflow.knowledge.embedder import EmbeddingResult

        embedder = MagicMock()
        embedder.embed = AsyncMock(return_value=[EmbeddingResult(dense=[0.25] * 1024, sparse=SparseVector(indices=[3], values=[0.7]))])
        monkeypatch.setattr(ks_module, "build_embedder", lambda: embedder)
        kb_id, chunk_id = setup_chunk
        client = _client(service)

        response = client.patch(
            f"/api/knowledge-bases/{kb_id}/chunks/{chunk_id}",
            json={"text": "brand new text"},
        )

        assert response.status_code == 200
        embedder.embed.assert_awaited_once_with(["brand new text"])
        service.vector_store.upsert_chunks.assert_awaited_once()
        upserted = list(service.vector_store.upsert_chunks.call_args[0][0])
        assert [c.chunk_id for c in upserted] == [chunk_id]
        assert upserted[0].dense == [0.25] * 1024
        assert upserted[0].entities == ["entity1"]  # payload preserved (ID 引用)

    async def test_patch_chunk_embed_failure_surfaces_500_and_leaves_db_untouched(self, service, setup_chunk, monkeypatch):
        """Embed runs BEFORE the DB write: an embedder outage surfaces as 500
        with the stored text unchanged, so a retry converges cleanly (no
        silent DB/vector divergence)."""
        from deerflow.knowledge.embedder import EmbedderError

        embedder = MagicMock()
        embedder.embed = AsyncMock(side_effect=EmbedderError("quota exhausted"))
        monkeypatch.setattr(ks_module, "build_embedder", lambda: embedder)
        kb_id, chunk_id = setup_chunk
        client = _client_no_raise(service)

        response = client.patch(
            f"/api/knowledge-bases/{kb_id}/chunks/{chunk_id}",
            json={"text": "brand new text"},
        )

        assert response.status_code == 500
        service.vector_store.upsert_chunks.assert_not_called()
        chunk = await service.store.get_chunk(chunk_id)
        assert chunk["text"] == "Original content"

    async def test_patch_chunk_upsert_failure_surfaces_500_after_db_write(self, service, setup_chunk, monkeypatch):
        """The upsert leg runs after the DB write; a Qdrant outage surfaces as
        500 (visible failure, retry converges) instead of silently leaving a
        stale vector behind a fresh text."""
        from qdrant_client.models import SparseVector

        from deerflow.knowledge.embedder import EmbeddingResult

        embedder = MagicMock()
        embedder.embed = AsyncMock(return_value=[EmbeddingResult(dense=[0.25] * 1024, sparse=SparseVector(indices=[3], values=[0.7]))])
        monkeypatch.setattr(ks_module, "build_embedder", lambda: embedder)
        service.vector_store.upsert_chunks = AsyncMock(side_effect=RuntimeError("qdrant down"))
        kb_id, chunk_id = setup_chunk
        client = _client_no_raise(service)

        response = client.patch(
            f"/api/knowledge-bases/{kb_id}/chunks/{chunk_id}",
            json={"text": "brand new text"},
        )

        assert response.status_code == 500
        chunk = await service.store.get_chunk(chunk_id)
        assert chunk["text"] == "brand new text"
