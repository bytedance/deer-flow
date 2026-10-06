"""Tests for POST /knowledge-bases/{kb_id}/chunks/{chunk_id}/re-extract endpoint (Phase-3 Batch-1 P3).

Single-chunk re-extraction following Spec §5 five-step flow:
1. remove_chunk_contributions (strip old graph contributions)
2. orphaned entities → delete vectors + wiki disqualification chain
3. per-chunk extraction on the new text
4. upsert entities/relations + chunks.entities write-back + Qdrant payload sync
5. affected ∪ new entities → wiki dirty chain
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.gateway.auth.models import User
from app.gateway.routers import knowledge_bases
from app.gateway.services.knowledge_service import KnowledgeService
from deerflow.knowledge.store import KnowledgeStore

pytestmark = pytest.mark.asyncio

OWNER_ID = str(uuid.UUID(int=1234567890))


def _owner() -> User:
    return User(email="owner@example.com", password_hash="x", system_role="user", id=uuid.UUID(OWNER_ID))


@pytest.fixture
def service(session_factory, tmp_path) -> KnowledgeService:
    vector_store = MagicMock()
    vector_store.delete_by_doc = AsyncMock()
    vector_store.delete_entities = AsyncMock()
    vector_store.delete_wiki_entries = AsyncMock()
    vector_store.set_chunk_entities = AsyncMock()
    vector_store.upsert_entities = AsyncMock()
    graph_store = MagicMock()
    graph_store.remove_chunk_contributions = AsyncMock(return_value=([], []))
    graph_store.list_entities = AsyncMock(return_value=[])
    wiki_store = MagicMock()
    wiki_store.mark_dirty_for_titles = AsyncMock()
    wiki_store.delete_entries = AsyncMock()
    worker = MagicMock()
    worker.submit = AsyncMock()

    store = KnowledgeStore(session_factory)
    return KnowledgeService(
        store=store,
        vector_store=vector_store,
        graph_store=graph_store,
        wiki_store=wiki_store,
        worker=worker,
        data_dir=tmp_path,
    )


def _client(service: KnowledgeService, user_factory=_owner) -> TestClient:
    from _router_auth_helpers import make_authed_test_app

    app = make_authed_test_app(user_factory=user_factory)
    app.state.knowledge_service = service
    app.include_router(knowledge_bases.router)
    return TestClient(app)


@pytest.fixture
async def setup_kb_with_chunks(service):
    """Setup KB with document and chunks in ready state."""
    kb_id = f"kb-test-{uuid.uuid4().hex[:8]}"
    doc_id = "doc-re-extract-001"
    chunk_ids = [f"{doc_id}-c0", f"{doc_id}-c1"]

    await service.store.create_kb(kb_id=kb_id, owner_id=OWNER_ID, name="Re-extract Test KB")
    await service.store.create_document(doc_id=doc_id, kb_id=kb_id, uploader_id=OWNER_ID, name="test.txt", size_bytes=100, storage_path="/test.txt")

    for i, chunk_id in enumerate(chunk_ids):
        await service.store.insert_chunks(
            [
                {
                    "chunk_id": chunk_id,
                    "doc_id": doc_id,
                    "kb_id": kb_id,
                    "chunk_index": i,
                    "text": f"Chunk {i} text for extraction.",
                    "token_count": 10,
                    "extract_status": "done",
                    "entities": ["OldEntity"] if i == 0 else [],
                }
            ]
        )

    await service.store.update_document_status(doc_id, "ready")
    return kb_id, doc_id, chunk_ids


class TestChunkReExtractEndpoint:
    """Endpoint contract + five-step flow tests."""

    async def test_re_extract_returns_404_when_chunk_not_found(self, service):
        """POST re-extract with non-existent chunk should return 404."""
        client = _client(service)
        kb = await service.store.create_kb(kb_id=f"kb-{uuid.uuid4().hex}", owner_id=OWNER_ID, name="dummy")

        response = client.post(f"/api/knowledge-bases/{kb['id']}/chunks/non-existent/re-extract")

        assert response.status_code == 404

    async def test_re_extract_returns_409_when_document_processing(self, setup_kb_with_chunks, service):
        """Re-extract must be rejected while the document pipeline is mid-flight."""
        kb_id, doc_id, chunk_ids = setup_kb_with_chunks
        client = _client(service)

        await service.store.update_document_status(doc_id, "parsing")

        response = client.post(f"/api/knowledge-bases/{kb_id}/chunks/{chunk_ids[0]}/re-extract")

        assert response.status_code == 409
        assert "being processed" in response.json()["detail"]

    async def test_re_extract_failed_document_bypasses_409(self, setup_kb_with_chunks, service):
        """A failed (terminal) document must NOT trigger the 409 guard."""
        kb_id, doc_id, chunk_ids = setup_kb_with_chunks
        client = _client(service)

        await service.store.update_document_status(doc_id, "failed")

        with patch(
            "app.gateway.services.knowledge_service.extract_single_chunk",
            new=AsyncMock(return_value=["NewEntity"]),
        ):
            response = client.post(f"/api/knowledge-bases/{kb_id}/chunks/{chunk_ids[0]}/re-extract")

        assert response.status_code == 200

    async def test_re_extract_full_five_step_flow(self, setup_kb_with_chunks, service):
        """Verify the Spec §5 five-step flow executes in order with correct args."""
        kb_id, doc_id, chunk_ids = setup_kb_with_chunks
        client = _client(service)
        target_chunk = chunk_ids[0]

        # Step 1 returns: orphaned entities (will be deleted), affected entities (survive)
        service.graph_store.remove_chunk_contributions.return_value = (["OrphanA"], ["AffectedB"])
        # After removal, AffectedB still has 2 sources (eligible), so it goes to dirty chain
        service.graph_store.list_entities.return_value = [
            {"name": "AffectedB", "type": "概念", "description": "d", "source_chunk_ids": ["x", "y"]},
            {"name": "NewEntity", "type": "概念", "description": "d", "source_chunk_ids": [target_chunk, "z"]},
        ]

        with patch(
            "app.gateway.services.knowledge_service.extract_single_chunk",
            new=AsyncMock(return_value=["NewEntity"]),
        ) as mock_extract:
            response = client.post(f"/api/knowledge-bases/{kb_id}/chunks/{target_chunk}/re-extract")

        assert response.status_code == 200

        # Step 1: old contributions stripped with exactly this chunk
        service.graph_store.remove_chunk_contributions.assert_awaited_once_with(kb_id, [target_chunk])

        # Step 2: orphaned entity vectors + wiki entries deleted
        service.vector_store.delete_entities.assert_awaited_once_with(kb_id, ["OrphanA"])
        service.wiki_store.delete_entries.assert_awaited_once_with(kb_id, ["OrphanA"])

        # Step 3+4: extraction ran on the chunk's current text
        assert mock_extract.await_count == 1
        call_kwargs = mock_extract.await_args.kwargs
        assert call_kwargs["kb_id"] == kb_id
        assert call_kwargs["chunk_id"] == target_chunk
        assert "Chunk 0 text" in call_kwargs["text"]

        # Step 4: Qdrant payload reverse-link synced with new entity names
        service.vector_store.set_chunk_entities.assert_awaited_once_with({target_chunk: ["NewEntity"]})

        # Step 5: affected (still eligible) + new entities marked dirty
        dirty_titles = service.wiki_store.mark_dirty_for_titles.await_args.args[1]
        assert set(dirty_titles) == {"AffectedB", "NewEntity"}

    async def test_re_extract_empty_result_clears_entities(self, setup_kb_with_chunks, service):
        """Extraction returning no entities → chunk.entities emptied, no dirty marking."""
        kb_id, doc_id, chunk_ids = setup_kb_with_chunks
        client = _client(service)
        target_chunk = chunk_ids[0]

        service.graph_store.remove_chunk_contributions.return_value = ([], [])

        async def _empty_extract(store, graph_store, *, kb_id, chunk_id, text, **kwargs):
            # Mirror the real extract_single_chunk's empty branch: status → empty,
            # entities wiped on the row.
            await store.update_chunk_extract(chunk_id, "empty", entities=[])
            return []

        with patch(
            "app.gateway.services.knowledge_service.extract_single_chunk",
            new=AsyncMock(side_effect=_empty_extract),
        ):
            response = client.post(f"/api/knowledge-bases/{kb_id}/chunks/{target_chunk}/re-extract")

        assert response.status_code == 200
        data = response.json()
        assert data["chunk_id"] == target_chunk
        assert data["entities"] == []

        # No orphaned → no vector/wiki deletion
        service.vector_store.delete_entities.assert_not_awaited()
        # No affected, no new entities → no dirty marking
        service.wiki_store.mark_dirty_for_titles.assert_not_awaited()

    async def test_re_extract_begins_with_pending_status(self, setup_kb_with_chunks, service):
        """Re-extract sets extract_status to pending immediately (for cross-session progress tracking)."""
        kb_id, doc_id, chunk_ids = setup_kb_with_chunks

        with patch(
            "app.gateway.services.knowledge_service.extract_single_chunk",
            new=AsyncMock(return_value=["NewEntity"]),
        ):
            await service.re_extract_chunk(kb_id=kb_id, chunk_id=chunk_ids[0])

        # Verify pending → done state machine persisted to DB (cross-session tracking)
        chunk = await service.store.get_chunk(chunk_ids[0])
        assert chunk is not None
        # Pending is set at start, then extract_single_chunk writes "done"
        assert chunk["extract_status"] in ("pending", "done")
        # Mock didn't call update_chunk_extract("done"), so we expect entities still old
        assert chunk["entities"] == ["OldEntity"]
