"""Tests for DELETE /knowledge-bases/{kb_id}/chunks/{chunk_id} (Task 5 收尾).

Single-chunk deletion runs the full cascade — graph contributions stripped,
orphan entities lose their vectors + wiki entries, affected entities are
re-checked against the ≥2-source eligibility bar (dirty vs disqualify), the
chunk vector point and the business row go last. Guarded by the same
terminal-state rule as re-extraction (409 while the pipeline is mid-flight).
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
from deerflow.knowledge.graph.store import GraphStore
from deerflow.knowledge.store import KnowledgeStore
from deerflow.knowledge.wiki.store import WikiStore

pytestmark = pytest.mark.asyncio

OWNER_ID = str(UUID(int=1234567890))


def _owner() -> User:
    return User(email="owner@example.com", password_hash="x", system_role="user", id=UUID(OWNER_ID))


@pytest.fixture
def service(session_factory, tmp_path) -> KnowledgeService:
    vector_store = MagicMock()
    vector_store.delete_by_doc = AsyncMock()
    vector_store.delete_entities = AsyncMock()
    vector_store.delete_wiki_entries = AsyncMock()
    vector_store.delete_chunks = AsyncMock()  # Task 5 收尾: new single-chunk delete
    return KnowledgeService(
        store=KnowledgeStore(session_factory),
        vector_store=vector_store,
        # Real graph/wiki stores: the cascade must run for real — only the
        # Qdrant boundary is mocked (assertion points).
        graph_store=GraphStore(session_factory),
        wiki_store=WikiStore(session_factory),
        worker=MagicMock(submit=AsyncMock()),
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


async def _setup_doc_with_graph(service: KnowledgeService, *, doc_status: str = "ready") -> tuple[str, str]:
    """KB + document + two chunks with graph contributions.

    c0: DeerFlow + Gateway; c1: DeerFlow + Qdrant → DeerFlow freq 2
    (eligible), Gateway/Qdrant freq 1.
    """
    kb_id = f"kb-test-{uuid.uuid4().hex[:8]}"
    doc_id = "doc-test"
    await service.store.create_kb(kb_id=kb_id, owner_id=OWNER_ID, name="Test KB")
    await service.store.create_document(doc_id=doc_id, kb_id=kb_id, uploader_id=OWNER_ID, name="test.txt", size_bytes=10, storage_path="/test.txt")
    await service.store.insert_chunks(
        [
            {
                "chunk_id": f"{doc_id}-c{i}",
                "doc_id": doc_id,
                "kb_id": kb_id,
                "chunk_index": i,
                "text": text,
                "token_count": 5,
                "extract_status": "done",
                "entities": entities,
            }
            for i, (text, entities) in enumerate(
                [
                    ("DeerFlow 包含 Gateway。", ["DeerFlow", "Gateway"]),
                    ("DeerFlow 使用 Qdrant。", ["DeerFlow", "Qdrant"]),
                ]
            )
        ]
    )
    for name, chunk_id in (("DeerFlow", "doc-test-c0"), ("Gateway", "doc-test-c0"), ("DeerFlow", "doc-test-c1"), ("Qdrant", "doc-test-c1")):
        await service.graph_store.upsert_entities(kb_id, [ExtractedEntity(name=name, type="概念", description=f"{name} 描述")], chunk_id=chunk_id)
    await service.store.update_document_status(doc_id, doc_status, chunk_count=2)
    return kb_id, doc_id


async def test_delete_chunk_404_when_missing(service):
    client = _client(service)
    kb = _create_kb(client)

    response = client.delete(f"/api/knowledge-bases/{kb['id']}/chunks/nonexistent")

    assert response.status_code == 404


async def test_delete_chunk_409_while_document_processing(service):
    """Same guard as re-extraction: deleting mid-pipeline would race the
    worker's graph/vector writes."""
    kb_id, _doc_id = await _setup_doc_with_graph(service, doc_status="indexing")
    client = _client(service)

    response = client.delete(f"/api/knowledge-bases/{kb_id}/chunks/doc-test-c0")

    assert response.status_code == 409


async def test_delete_chunk_cascades_and_refreshes_chunk_count(service):
    """Deleting c1 drops DeerFlow to freq 1 → its wiki entry is pruned via the
    disqualification chain; the chunk point + business row go; count updates."""
    kb_id, doc_id = await _setup_doc_with_graph(service)
    await service.wiki_store.upsert_entry(kb_id, title="DeerFlow", content="条目", source_chunk_ids=["doc-test-c0", "doc-test-c1"])
    client = _client(service)

    response = client.delete(f"/api/knowledge-bases/{kb_id}/chunks/doc-test-c1")

    assert response.status_code == 204
    # Business row gone; document chunk_count refreshed 2 → 1.
    assert await service.store.get_chunk("doc-test-c1") is None
    document = await service.store.get_document(doc_id)
    assert document["chunk_count"] == 1
    # Chunk vector point dropped.
    service.vector_store.delete_chunks.assert_awaited_once_with(["doc-test-c1"])
    # DeerFlow fell below the ≥2-source bar → wiki entry + its vector pruned
    # (Qdrant is orphaned in the same run — its call is a harmless no-op).
    assert await service.wiki_store.list_entries(kb_id) == []
    called_titles = [call[0][1] for call in service.vector_store.delete_wiki_entries.call_args_list]
    assert ["DeerFlow"] in called_titles


async def test_delete_chunk_orphan_entity_loses_vector_and_wiki_entry(service):
    """Qdrant (only in c1) is orphaned by the delete → its kb_entities
    vector and wiki entry are removed; DeerFlow also drops to freq 1 and is
    pruned via the disqualification chain."""
    kb_id, _doc_id = await _setup_doc_with_graph(service)
    await service.wiki_store.upsert_entry(kb_id, title="Qdrant", content="条目", source_chunk_ids=["doc-test-c1"], status="dirty")
    client = _client(service)

    response = client.delete(f"/api/knowledge-bases/{kb_id}/chunks/doc-test-c1")

    assert response.status_code == 204
    service.vector_store.delete_entities.assert_awaited_once()
    deleted_names = set(service.vector_store.delete_entities.call_args[0][1])
    assert "Qdrant" in deleted_names
    # Both wiki entries pruned: Qdrant orphaned, DeerFlow disqualified (freq 1).
    assert await service.wiki_store.list_entries(kb_id) == []


async def test_delete_chunk_marks_still_eligible_affected_dirty(service):
    """An affected entity that KEEPS ≥2 sources is marked dirty for the next
    incremental wiki run instead of being deleted (while c1-only Qdrant is
    orphaned out in the same run)."""
    kb_id, _doc_id = await _setup_doc_with_graph(service)
    # DeerFlow gets a third contribution so deleting c1 leaves freq 2.
    await service.graph_store.upsert_entities(kb_id, [ExtractedEntity(name="DeerFlow", type="概念", description="d")], chunk_id="doc-test-c0-extra")
    await service.wiki_store.upsert_entry(kb_id, title="DeerFlow", content="条目", source_chunk_ids=["doc-test-c0", "doc-test-c0-extra"])
    client = _client(service)

    response = client.delete(f"/api/knowledge-bases/{kb_id}/chunks/doc-test-c1")

    assert response.status_code == 204
    entries = {e["title"]: e for e in await service.wiki_store.list_entries(kb_id)}
    assert entries["DeerFlow"]["status"] == "dirty"  # marked for re-generation, not pruned
    # Qdrant is orphaned (only in c1) — its entry delete is a harmless no-op;
    # the assertion that matters: DeerFlow's entry was never targeted.
    for call in service.vector_store.delete_wiki_entries.call_args_list:
        assert "DeerFlow" not in call[0][1]
