"""Tests for the DashScope embedder and the vector indexing stage.

Embedder tests mock the HTTP layer with ``httpx.MockTransport``; the API key
must come from the ``DASHSCOPE_EMBEDDING_API_KEY`` env var. Indexer tests run
against a throwaway SQLite DB plus the real local Qdrant, with a stub
embedder — the same split as parser/chunker tests.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from deerflow_knowledge.embedder import (
    DashScopeEmbedder,
    EmbedderAuthError,
    EmbedderError,
    EmbeddingResult,
)
from deerflow_knowledge.indexer import IndexStats, index_chunks
from deerflow_knowledge.store import KnowledgeStore
from deerflow_knowledge.vector_store import KnowledgeVectorStore
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchValue, SparseVector

from .conftest import QDRANT_TEST_URL, requires_qdrant

# ── embedder HTTP mock helpers ───────────────────────────────────────────────


def _embedding_item(i: int, *, dims: int = 4) -> dict:
    return {
        "embedding": [0.1 * (i + 1)] * dims,
        "sparse_embedding": [
            {"index": 7149 + i, "value": 0.829, "token": f"tok{i}a"},
            {"index": 111290 + i, "value": 0.9004, "token": f"tok{i}b"},
        ],
        "text_index": i,
    }


def _ok_response(n: int) -> dict:
    return {
        "status_code": 200,
        "request_id": "req-1",
        "code": "",
        "message": "",
        "output": {"embeddings": [_embedding_item(i) for i in range(n)]},
        "usage": {"total_tokens": 27},
    }


def _transport(recorded: list[httpx.Request], handler_fn) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        return handler_fn(request)

    return httpx.MockTransport(handler)


def _embedder(client: httpx.AsyncClient, **kwargs) -> DashScopeEmbedder:
    # Explicit so the stub never depends on the per-model cap table.
    kwargs.setdefault("batch_size", 20)
    kwargs.setdefault("retry_backoff_seconds", 0.001)
    return DashScopeEmbedder(model="qwen3.7-text-embedding", api_key="test-key", client=client, **kwargs)


# ── embedder tests ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_embed_parses_dense_and_sparse_pairs():
    recorded: list[httpx.Request] = []
    client = httpx.AsyncClient(transport=_transport(recorded, lambda req: httpx.Response(200, json=_ok_response(2))))

    results = await _embedder(client).embed(["风急天高猿啸哀", "渚清沙白鸟飞回"])

    assert len(results) == 2
    assert results[0].dense == [0.1] * 4
    assert results[1].dense == [0.2] * 4
    assert isinstance(results[0].sparse, SparseVector)
    assert results[0].sparse.indices == [7149, 111290]
    assert results[0].sparse.values == [0.829, 0.9004]
    assert results[1].sparse.indices == [7150, 111291]
    # Result order must follow the input order regardless of payload order.
    assert len(recorded) == 1


@pytest.mark.asyncio
async def test_embed_request_contract():
    recorded: list[httpx.Request] = []
    client = httpx.AsyncClient(transport=_transport(recorded, lambda req: httpx.Response(200, json=_ok_response(1))))

    await _embedder(client).embed(["入库文本"], text_type="document")

    assert len(recorded) == 1
    request = recorded[0]
    assert request.headers["Authorization"] == "Bearer test-key"
    assert request.url.path == "/api/v1/services/embeddings/text-embedding/text-embedding"
    body = __import__("json").loads(request.content)
    assert body["model"] == "qwen3.7-text-embedding"
    assert body["input"] == {"texts": ["入库文本"]}
    # Single call must request both paths at once (spec §3.3).
    assert body["parameters"]["output_type"] == "dense&sparse"
    assert body["parameters"]["text_type"] == "document"
    assert body["parameters"]["dimension"] == 1024


@pytest.mark.asyncio
async def test_embed_query_text_type():
    recorded: list[httpx.Request] = []
    client = httpx.AsyncClient(transport=_transport(recorded, lambda req: httpx.Response(200, json=_ok_response(1))))

    await _embedder(client).embed(["检索问题"], text_type="query")

    body = __import__("json").loads(recorded[0].content)
    assert body["parameters"]["text_type"] == "query"


@pytest.mark.asyncio
async def test_embed_batches_over_limit():
    """Inputs beyond the batch limit are split into sequential calls, order preserved."""
    recorded: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        n = len(__import__("json").loads(request.content)["input"]["texts"])
        return httpx.Response(200, json=_ok_response(n))

    client = httpx.AsyncClient(transport=_transport(recorded, handler))

    results = await _embedder(client, batch_size=2).embed(["t0", "t1", "t2", "t3", "t4"])

    assert len(recorded) == 3  # 2 + 2 + 1
    assert [len(__import__("json").loads(r.content)["input"]["texts"]) for r in recorded] == [2, 2, 1]
    assert len(results) == 5
    # text_index restarts per call; results must be re-aligned to input order.
    assert [r.dense[0] for r in results] == [0.1, 0.2, 0.1, 0.2, 0.1]


@pytest.mark.asyncio
async def test_embed_retries_on_server_error_then_succeeds():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(500, json={"code": "InternalError", "message": "boom"})
        return httpx.Response(200, json=_ok_response(1))

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    results = await _embedder(client, max_retries=3).embed(["文本"])

    assert calls["n"] == 2
    assert len(results) == 1


@pytest.mark.asyncio
async def test_embed_raises_after_retries_exhausted():
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(500, json={"code": "InternalError", "message": "boom"})))

    with pytest.raises(EmbedderError, match="500|InternalError|boom"):
        await _embedder(client, max_retries=2).embed(["文本"])


@pytest.mark.asyncio
async def test_embed_auth_error_on_401_not_retried():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(401, json={"code": "InvalidApiKey", "message": "Invalid API-key provided."})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    with pytest.raises(EmbedderAuthError):
        await _embedder(client, max_retries=3).embed(["文本"])
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_embed_business_error_code_in_200_body():
    """DashScope can signal failure via a non-empty ``code`` in the body."""
    payload = {"code": "InvalidApiKey", "message": "Invalid API-key provided.", "request_id": "x"}
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200, json=payload)))

    with pytest.raises(EmbedderAuthError, match="InvalidApiKey|Invalid API-key"):
        await _embedder(client).embed(["文本"])


@pytest.mark.asyncio
async def test_embed_missing_api_key(monkeypatch):
    monkeypatch.delenv("DASHSCOPE_EMBEDDING_API_KEY", raising=False)
    embedder = DashScopeEmbedder(model="qwen3.7-text-embedding", client=httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200))))

    with pytest.raises(EmbedderAuthError, match="DASHSCOPE_EMBEDDING_API_KEY"):
        await embedder.embed(["文本"])


# ── indexer tests ────────────────────────────────────────────────────────────


class _StubEmbedder:
    """Deterministic embedder stub: fixed vectors, optional per-call failures."""

    def __init__(self, *, batch_size: int = 2, fail_calls: set[int] | None = None) -> None:
        self.batch_size = batch_size
        self.calls: list[list[str]] = []
        self._fail_calls = fail_calls or set()

    async def embed(self, texts, *, text_type: str = "document") -> list[EmbeddingResult]:
        self.calls.append(list(texts))
        if len(self.calls) - 1 in self._fail_calls:
            raise EmbedderError("dashscope boom")
        return [EmbeddingResult(dense=[0.1 + 0.01 * i] * 1024, sparse=SparseVector(indices=[i + 1], values=[0.5])) for i, _ in enumerate(texts)]


@pytest_asyncio.fixture
async def kb_env(session_factory) -> AsyncIterator[tuple[KnowledgeStore, KnowledgeVectorStore, AsyncQdrantClient, str]]:
    """KB + document + 3 chunk rows, plus a uniquely-prefixed vector store."""
    import uuid

    store = KnowledgeStore(session_factory)
    kb_id, doc_id = "kb-idx", "doc-idx"
    await store.create_kb(kb_id=kb_id, owner_id="user-1", name="索引测试库")
    await store.create_document(doc_id=doc_id, kb_id=kb_id, uploader_id="user-1", name="手册.pdf", size_bytes=10, storage_path="/x.pdf")
    await store.insert_chunks(
        [
            {
                "chunk_id": f"{doc_id}-c{i}",
                "doc_id": doc_id,
                "kb_id": kb_id,
                "chunk_index": i,
                "text": f"第 {i} 个切片文本",
                "heading_path": ["第一章", f"1.{i}"],
                "page": i + 1,
                "token_count": 100,
                "entities": ["实体甲"] if i == 0 else [],
            }
            for i in range(3)
        ]
    )
    prefix = f"testidx{uuid.uuid4().hex[:10]}"
    client = AsyncQdrantClient(QDRANT_TEST_URL, timeout=10.0)
    vector_store = KnowledgeVectorStore(client=client, collection_prefix=prefix)
    await vector_store.init_collections()
    try:
        yield store, vector_store, client, doc_id
    finally:
        for name in vector_store.collection_names:
            await client.delete_collection(name)
        await client.close()


def _chunk_dicts(chunks: list[dict]) -> list[dict]:
    return chunks


@requires_qdrant
@pytest.mark.integration
@pytest.mark.asyncio
async def test_index_chunks_upserts_payload_and_updates_chunk_count(kb_env):
    store, vector_store, client, doc_id = kb_env
    chunks = await store.list_chunks(doc_id, limit=10)
    embedder = _StubEmbedder(batch_size=2)

    stats = await index_chunks(store, vector_store, embedder, kb_id="kb-idx", doc_id=doc_id, chunks=_chunk_dicts(chunks))

    assert isinstance(stats, IndexStats)
    assert stats.total == 3
    assert stats.indexed == 3
    assert stats.failed_chunk_ids == []
    # Embedder called per batch (2 + 1), in chunk order.
    assert embedder.calls == [["第 0 个切片文本", "第 1 个切片文本"], ["第 2 个切片文本"]]

    # Qdrant carries the spec §3.3 payload: pointer + filter fields + display metadata.
    points, _ = await client.scroll(
        vector_store.chunks_collection,
        scroll_filter=Filter(must=[FieldCondition(key="doc_id", match=MatchValue(value=doc_id))]),
        with_payload=True,
        with_vectors=True,
        limit=10,
    )
    assert len(points) == 3
    by_chunk = {p.payload["chunk_id"]: p for p in points}
    first = by_chunk[f"{doc_id}-c0"]
    assert first.payload["kb_id"] == "kb-idx"
    assert first.payload["doc_name"] == "手册.pdf"
    assert first.payload["heading_path"] == ["第一章", "1.0"]
    assert first.payload["page"] == 1
    assert first.payload["entities"] == ["实体甲"]
    assert "text" not in first.payload  # chunk text never leaves the business DB
    assert set(first.vector) == {"dense", "sparse"}
    assert len(first.vector["dense"]) == 1024

    # Document row reflects the indexed chunk count.
    doc = await store.get_document(doc_id)
    assert doc["chunk_count"] == 3


@requires_qdrant
@pytest.mark.integration
@pytest.mark.asyncio
async def test_failed_embed_marks_chunks_failed_without_aborting(kb_env):
    store, vector_store, client, doc_id = kb_env
    chunks = await store.list_chunks(doc_id, limit=10)
    # First batch (chunks 0+1) fails; the remaining batch must still index.
    embedder = _StubEmbedder(batch_size=2, fail_calls={0})

    stats = await index_chunks(store, vector_store, embedder, kb_id="kb-idx", doc_id=doc_id, chunks=_chunk_dicts(chunks))

    assert stats.total == 3
    assert stats.indexed == 1
    assert sorted(stats.failed_chunk_ids) == [f"{doc_id}-c0", f"{doc_id}-c1"]

    # Failed chunks carry the failure on their persisted state for resume.
    failed_rows = [c for c in await store.list_chunks(doc_id, limit=10) if c["chunk_id"] in stats.failed_chunk_ids]
    assert all(c["extract_status"] == "failed" for c in failed_rows)
    assert all("dashscope boom" in c["extract_error"] for c in failed_rows)

    # The surviving batch is in Qdrant; failed chunks are not.
    points, _ = await client.scroll(
        vector_store.chunks_collection,
        scroll_filter=Filter(must=[FieldCondition(key="doc_id", match=MatchValue(value=doc_id))]),
        with_payload=True,
        limit=10,
    )
    assert [p.payload["chunk_id"] for p in points] == [f"{doc_id}-c2"]
    doc = await store.get_document(doc_id)
    assert doc["chunk_count"] == 1


@pytest.mark.asyncio
async def test_index_empty_chunks_noop(session_factory):
    store = KnowledgeStore(session_factory)
    await store.create_kb(kb_id="kb-e", owner_id="user-1", name="空库")
    await store.create_document(doc_id="doc-e", kb_id="kb-e", uploader_id="user-1", name="空.md", size_bytes=0, storage_path="/e.md")
    embedder = _StubEmbedder()

    stats = await index_chunks(store, None, embedder, kb_id="kb-e", doc_id="doc-e", chunks=[])

    assert stats.total == 0 and stats.indexed == 0 and stats.failed_chunk_ids == []
    assert embedder.calls == []
    doc = await store.get_document("doc-e")
    assert doc["chunk_count"] == 0
