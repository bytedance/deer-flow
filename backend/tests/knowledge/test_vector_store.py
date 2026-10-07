"""Integration tests for the Qdrant vector store (RAG knowledge base).

Require a reachable Qdrant (compose service or local container); they are
skipped automatically when the service is unavailable. Each test runs against
a unique collection prefix and tears its collections down afterwards.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Distance, FieldCondition, Filter, MatchValue, PayloadSchemaType, SparseVector

from deerflow.knowledge.vector_store import ChunkUpsert, KnowledgeVectorStore

from .conftest import QDRANT_TEST_URL, requires_qdrant

pytestmark = [pytest.mark.integration, requires_qdrant, pytest.mark.asyncio]


@pytest_asyncio.fixture
async def vector_store() -> AsyncIterator[tuple[KnowledgeVectorStore, AsyncQdrantClient]]:
    client = AsyncQdrantClient(QDRANT_TEST_URL, timeout=10.0)
    store = KnowledgeVectorStore(client=client, collection_prefix=f"test_{uuid.uuid4().hex[:12]}")
    await store.init_collections()
    try:
        yield store, client
    finally:
        for name in store.collection_names:
            await client.delete_collection(name)
        await client.close()


def _chunk(chunk_id: str, kb_id: str, doc_id: str, *, dense_seed: float = 0.01) -> ChunkUpsert:
    return ChunkUpsert(
        chunk_id=chunk_id,
        kb_id=kb_id,
        doc_id=doc_id,
        doc_name=f"{doc_id}.pdf",
        heading_path=["第1章"],
        page=3,
        entities=["广义相对论"],
        dense=[dense_seed] * 1024,
        sparse=SparseVector(indices=[1, 42], values=[0.5, 0.3]),
    )


async def test_init_collections_idempotent(vector_store):
    store, client = vector_store

    # Second call must be a no-op, not an error.
    await store.init_collections()

    for name in store.collection_names:
        assert await client.collection_exists(name), name


async def test_named_vectors_config(vector_store):
    store, client = vector_store

    info = await client.get_collection(store.chunks_collection)
    dense = info.config.params.vectors["dense"]
    assert dense.size == 1024
    assert dense.distance == Distance.COSINE
    # Sparse vectors in Qdrant always score by dot product (the schema carries
    # no distance field); presence of the "sparse" named vector pins the DOT path.
    assert "sparse" in info.config.params.sparse_vectors


async def test_kb_chunks_payload_indexes(vector_store):
    store, client = vector_store

    info = await client.get_collection(store.chunks_collection)
    assert set(info.payload_schema) >= {"kb_id", "doc_id", "entities"}
    for field in ("kb_id", "doc_id", "entities"):
        assert info.payload_schema[field].data_type == PayloadSchemaType.KEYWORD


async def test_upsert_chunks_payload_carries_pointer_not_text(vector_store):
    store, client = vector_store

    await store.upsert_chunks([_chunk("doc-1#0000", "kb-1", "doc-1")])

    records, _ = await client.scroll(
        store.chunks_collection,
        scroll_filter=Filter(must=[FieldCondition(key="chunk_id", match=MatchValue(value="doc-1#0000"))]),
        with_payload=True,
        with_vectors=False,
    )
    assert len(records) == 1
    payload = records[0].payload
    # chunk_id pointer + filter fields + unindexed display metadata (spec §3.3)…
    assert payload["chunk_id"] == "doc-1#0000"
    assert payload["kb_id"] == "kb-1"
    assert payload["doc_id"] == "doc-1"
    assert payload["entities"] == ["广义相对论"]
    assert payload["doc_name"] == "doc-1.pdf"
    assert payload["heading_path"] == ["第1章"]
    assert payload["page"] == 3
    # …but never the chunk text — that lives only in the business DB (spec §3.2).
    assert "text" not in payload


async def test_upsert_same_chunk_id_overwrites(vector_store):
    store, client = vector_store

    await store.upsert_chunks([_chunk("doc-1#0000", "kb-1", "doc-1")])
    await store.upsert_chunks([_chunk("doc-1#0000", "kb-1", "doc-1")])

    count = await client.count(store.chunks_collection, exact=True)
    assert count.count == 1


async def test_delete_chunks_removes_only_listed_points(vector_store):
    """Task 5 收尾: single-chunk deletion drops exactly those chunk points
    (payload filter), leaving siblings intact; idempotent on re-delete."""
    store, client = vector_store
    await store.upsert_chunks([_chunk("doc-1#0000", "kb-1", "doc-1"), _chunk("doc-1#0001", "kb-1", "doc-1")])

    await store.delete_chunks(["doc-1#0000"])

    records, _ = await client.scroll(store.chunks_collection, with_payload=True, with_vectors=False, limit=10)
    assert [r.payload["chunk_id"] for r in records] == ["doc-1#0001"]
    await store.delete_chunks(["doc-1#0000"])  # no-op, no error
    await store.delete_chunks([])  # empty list short-circuits


async def test_hybrid_query_filters_by_kb(vector_store):
    store, _ = vector_store
    await store.upsert_chunks(
        [
            _chunk("doc-1#0000", "kb-1", "doc-1", dense_seed=0.02),
            _chunk("doc-1#0001", "kb-1", "doc-1", dense_seed=0.03),
            _chunk("doc-9#0000", "kb-2", "doc-9", dense_seed=0.02),
        ]
    )

    results = await store.hybrid_query(
        dense=[0.02] * 1024,
        sparse=SparseVector(indices=[1, 42], values=[0.5, 0.3]),
        kb_id="kb-1",
        top_k=5,
    )

    chunk_ids = {point.payload["chunk_id"] for point in results}
    assert chunk_ids == {"doc-1#0000", "doc-1#0001"}
    assert all(point.payload["kb_id"] == "kb-1" for point in results)


async def test_delete_by_doc_removes_only_that_doc(vector_store):
    store, client = vector_store
    await store.upsert_chunks(
        [
            _chunk("doc-1#0000", "kb-1", "doc-1"),
            _chunk("doc-1#0001", "kb-1", "doc-1"),
            _chunk("doc-2#0000", "kb-1", "doc-2"),
        ]
    )

    await store.delete_by_doc("doc-1")

    remaining = await client.count(store.chunks_collection, exact=True)
    assert remaining.count == 1
    records, _ = await client.scroll(store.chunks_collection, with_payload=True, with_vectors=False)
    assert records[0].payload["doc_id"] == "doc-2"


async def test_delete_by_kb_wipes_points_across_collections(vector_store):
    store, client = vector_store
    await store.upsert_chunks([_chunk("doc-1#0000", "kb-1", "doc-1"), _chunk("doc-2#0000", "kb-1", "doc-2")])

    await store.delete_by_kb("kb-1")

    for name in store.collection_names:
        count = await client.count(name, exact=True)
        assert count.count == 0, name


async def test_scroll_collection_pages_and_filters_by_kb(vector_store):
    """``scroll_collection`` (vector-space projection P2): paged id+payload
    listing scoped to one kb — the fetcher's sampling candidate source."""
    store, client = vector_store
    await store.upsert_chunks(
        [
            _chunk("doc-1#0000", "kb-1", "doc-1"),
            _chunk("doc-1#0001", "kb-1", "doc-1"),
            _chunk("doc-1#0002", "kb-1", "doc-1"),
            _chunk("doc-9#0000", "kb-2", "doc-9"),
        ]
    )

    # batch_size=2 forces a second page for the three kb-1 points.
    records = await store.scroll_collection(store.chunks_collection, "kb-1", batch_size=2)

    assert len(records) == 3
    assert all(r.payload["kb_id"] == "kb-1" for r in records)
    # with_vectors=False: ids + payload only, no vector data on the wire.
    assert all(not r.vector for r in records)
