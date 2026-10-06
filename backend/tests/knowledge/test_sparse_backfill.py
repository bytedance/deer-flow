"""Tests for the sparse backfill legs (spec 2026-09-14 §4.2).

Three ways to supply the sparse half of the dual-vector store, all of which must produce a
Qdrant ``SparseVector`` so the collection schema and the retrieval code stay untouched:

- ``provider`` — the embedding provider itself (DashScope today). Covered in
  ``test_embedder_providers.py``; here we only pin that composition *keeps* it.
- ``external`` — a separate sparse service. Shape pinned from upstream source
  (``huggingface/text-embeddings-inference``, ``router/src/http/types.rs``):
  ``POST /embed_sparse`` with ``{"inputs": [...]}`` → ``[[{"index", "value"}, ...], ...]``.
- ``bm25`` — local, zero-model, deterministic. **No idf and no corpus**: the index is built
  chunk-by-chunk, so the score is BM25's term-frequency saturation only, which is also why
  the query and document sides are exactly symmetric (the pair-consistency rule in §4.2).
  Chinese text is tokenised with deterministic character bigrams — deliberately *not* an
  optional jieba, because an optional tokenizer would make the index space depend on the
  environment, which is precisely what §4.2 forbids.

The interface is ``encode(texts, text_type) -> list[SparseVector]``; the composition adapter
zips it with the dense halves in input order.
"""

from __future__ import annotations

import json

import httpx
import pytest
from qdrant_client.models import SparseVector

from deerflow.knowledge.embedder import ComposedEmbedder, EmbedderAuthError, EmbedderError
from deerflow.knowledge.sparse import BM25SparseEncoder, TEISparseEncoder, _tokenize

SPARSE_BASE = "http://127.0.0.1:8081"


# ── BM25 (local, deterministic) ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bm25_is_deterministic_and_ignores_text_type():
    """同一文本在 query / document 两侧必须给出同一稀疏向量（§4.2 成对一致）。"""
    encoder = BM25SparseEncoder()

    (as_document,) = await encoder.encode(["风急天高猿啸哀"], text_type="document")
    (as_query,) = await encoder.encode(["风急天高猿啸哀"], text_type="query")

    assert as_document.indices == as_query.indices
    assert as_document.values == as_query.values
    assert as_document.indices, "中文长句必须切出词元"


@pytest.mark.asyncio
async def test_bm25_tokenizes_cjk_as_character_bigrams():
    """中文按字符二元切分（无 jieba 依赖 ⇒ indices 空间与运行环境无关）。"""
    assert _tokenize("南北") == ["南北"]
    assert _tokenize("风急天高") == ["风急", "急天", "天高"]
    assert _tokenize("DeerFlow 检索") == ["deerflow", "检索"]


@pytest.mark.asyncio
async def test_bm25_indices_are_unique_and_in_range():
    encoder = BM25SparseEncoder()
    (vector,) = await encoder.encode(["测试 测试 文本 abc abc " * 3])

    assert len(vector.indices) == len(set(vector.indices)), "Qdrant 要求 indices 唯一"
    assert all(0 <= index < 2**31 for index in vector.indices)


@pytest.mark.asyncio
async def test_bm25_weights_saturate_with_term_frequency():
    """BM25 的 tf 饱和：词频翻倍不等于权重翻倍（无 idf，因为索引时没有语料统计）。"""
    encoder = BM25SparseEncoder()
    (once,) = await encoder.encode(["风急"])
    (twice,) = await encoder.encode(["风急 风急"])

    once_weight = max(once.values)
    twice_weight = max(twice.values)
    assert twice_weight > once_weight, "出现两次要更重"
    assert twice_weight < 2 * once_weight, "但必须饱和（BM25 曲线）"


@pytest.mark.asyncio
async def test_bm25_empty_and_whitespace_yield_empty_vectors():
    encoder = BM25SparseEncoder()
    assert await encoder.encode([]) == []
    (blank,) = await encoder.encode(["   "])
    assert blank.indices == [] and blank.values == []


# ── external sparse service (TEI shape) ────────────────────────────────────


def _tei_transport(recorded: list[httpx.Request], *, status: int = 200) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        if status != 200:
            return httpx.Response(status, json={"error": "nope"})
        texts = json.loads(request.content.decode())["inputs"]
        return httpx.Response(200, json=[[{"index": 10 + i, "value": 0.5}, {"index": 20 + i, "value": 0.25}] for i, _ in enumerate(texts)])

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_tei_encoder_pins_the_upstream_request_and_response_shape():
    recorded: list[httpx.Request] = []
    async with httpx.AsyncClient(transport=_tei_transport(recorded)) as client:
        encoder = TEISparseEncoder(base_url=SPARSE_BASE, client=client)
        vectors = await encoder.encode(["甲", "乙"], text_type="document")

    request = recorded[0]
    assert str(request.url) == f"{SPARSE_BASE}/embed_sparse"
    assert request.headers["content-type"].startswith("application/json")
    assert json.loads(request.content.decode()) == {"inputs": ["甲", "乙"]}, "TEI 请求只有 inputs（单实例单模型，不带 model）"
    assert [vector.indices for vector in vectors] == [[10, 20], [11, 21]]
    assert [vector.values for vector in vectors] == [[0.5, 0.25], [0.5, 0.25]]


@pytest.mark.asyncio
async def test_tei_encoder_sends_bearer_token_only_when_configured():
    recorded: list[httpx.Request] = []
    async with httpx.AsyncClient(transport=_tei_transport(recorded)) as client:
        await TEISparseEncoder(base_url=SPARSE_BASE, client=client).encode(["甲"])
        await TEISparseEncoder(base_url=SPARSE_BASE, api_key="sk-sparse", client=client).encode(["甲"])

    assert recorded[0].headers.get("authorization") is None, "无鉴权的自建服务不该收到空 Bearer"
    assert recorded[1].headers["authorization"] == "Bearer sk-sparse"


@pytest.mark.asyncio
async def test_tei_encoder_reports_auth_and_server_failures():
    recorded: list[httpx.Request] = []
    async with httpx.AsyncClient(transport=_tei_transport(recorded, status=401)) as client:
        with pytest.raises(EmbedderAuthError):
            await TEISparseEncoder(base_url=SPARSE_BASE, client=client).encode(["甲"])

    async with httpx.AsyncClient(transport=_tei_transport(recorded, status=503)) as client:
        with pytest.raises(EmbedderError):
            await TEISparseEncoder(base_url=SPARSE_BASE, client=client, max_retries=2, retry_backoff_seconds=0).encode(["甲"])


# ── composition (甲) ───────────────────────────────────────────────────────


class _DenseOnly:
    """Stands in for a generic embedding provider: dense vectors, no sparse half."""

    batch_size = 2

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def embed(self, texts, *, text_type: str = "document"):
        from deerflow.knowledge.embedder import EmbeddingResult

        self.calls.append(list(texts))
        return [EmbeddingResult(dense=[float(len(text))], sparse=SparseVector(indices=[], values=[])) for text in texts]


class _FakeSparse:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], str]] = []

    async def encode(self, texts, *, text_type: str = "document"):
        self.calls.append((list(texts), text_type))
        return [SparseVector(indices=[len(text)], values=[1.0]) for text in texts]


@pytest.mark.asyncio
async def test_composition_zips_dense_and_sparse_in_input_order():
    dense, sparse = _DenseOnly(), _FakeSparse()
    embedder = ComposedEmbedder(dense=dense, sparse=sparse)

    results = await embedder.embed(["一", "二三"], text_type="query")

    assert [r.dense for r in results] == [[1.0], [2.0]]
    assert [r.sparse.indices for r in results] == [[1], [2]]
    assert embedder.batch_size == 2, "批大小取自 dense 源"
    assert sparse.calls == [(["一", "二三"], "query")], "text_type 同样要透传给稀疏源"


@pytest.mark.asyncio
async def test_composition_short_circuits_on_empty_input():
    dense, sparse = _DenseOnly(), _FakeSparse()
    embedder = ComposedEmbedder(dense=dense, sparse=sparse)

    assert await embedder.embed([]) == []
    assert dense.calls == [] and sparse.calls == [], "空批次一次请求都不发"
