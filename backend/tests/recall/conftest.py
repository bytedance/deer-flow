"""Shared fixtures for L1 recall tests.

L1 = engineering correctness, not retrieval quality. The point is to
prove the pipeline wires up, ranks deterministically, and respects the
tenant / score-strategy switches we shipped — not whether the
embedding model is "smart" enough to find a passage. So we never
actually call OpenAI here; we plug in deterministic fake embedders.

Three building blocks:

- ``HashEmbedder``: SHA-256 → seeded RNG → unit-norm gaussian vector.
  Same input → same vector forever, different inputs uncorrelated.
  Use when "ranking is stable and deterministic" is enough.

- ``ControlledEmbedder``: pin one specific text (the "target") to a
  shared vector with the query so cosine similarity for that pair is
  ~1.0 and everyone else is ~0. Use when the test asserts "this
  exact chunk should rank first".

- ``InMemoryVectorStore``: a hash-map-backed VectorStore that does
  exact cosine search. Lets us test the full embed → search → rank
  loop without bringing in chromadb.

- ``session_factory`` / ``repo`` / ``kb_factory``: same SQLite +
  KnowledgeBaseRepository setup as test_kb_visibility.py, so seeded
  KB rows look like the real thing.

Tests should restore RagConfig in teardown — copy the pattern from
test_multi_kb_score_strategy.py.
"""

from __future__ import annotations

import hashlib
from typing import Any

import numpy as np
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from deerflow.persistence.base import Base
from deerflow.persistence.knowledge_base.repository import KnowledgeBaseRepository
from deerflow.rag.embeddings import EmbeddingProvider
from deerflow.rag.vector_store import SearchResult, VectorStore

_DEFAULT_DIM = 64


def _hash_to_vector(text: str, dim: int) -> list[float]:
    """SHA-256 → seeded RNG → unit-norm gaussian vector of length ``dim``.

    Why seed an RNG instead of byte-reshaping: a 32-byte SHA-256 has
    to be tiled to fill larger ``dim`` values, which leaks structure
    (every 8th coord is identical). Seeding numpy's PCG64 with the
    digest gives us full-length uncorrelated coordinates while staying
    fully deterministic.
    """
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    seed = int.from_bytes(digest[:8], "big") % (2**32)
    rng = np.random.default_rng(seed)
    vec = rng.standard_normal(dim).astype(np.float32)
    norm = float(np.linalg.norm(vec))
    if norm == 0.0:
        vec[0] = 1.0
        norm = 1.0
    return (vec / norm).tolist()


class HashEmbedder(EmbeddingProvider):
    """Deterministic hash-based embedder for L1 tests."""

    def __init__(self, dim: int = _DEFAULT_DIM) -> None:
        self._dim = dim

    @property
    def dimension(self) -> int:
        return self._dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [_hash_to_vector(t, self._dim) for t in texts]


class ControlledEmbedder(EmbeddingProvider):
    """Embedder that pins a target text to the same vector as the query.

    Any text equal to ``target_text`` (after .strip()) shares the
    query's embedding, so cosine similarity is 1.0. Everything else
    falls back to the hash embedder, which gives uncorrelated
    near-orthogonal vectors. This lets tests say "the chunk containing
    the target snippet must be #1" without depending on an LLM.
    """

    def __init__(
        self,
        target_text: str,
        query_text: str,
        dim: int = _DEFAULT_DIM,
    ) -> None:
        self._target = target_text.strip()
        self._dim = dim
        self._shared = _hash_to_vector(query_text, dim)
        self._hash = HashEmbedder(dim=dim)

    @property
    def dimension(self) -> int:
        return self._dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for t in texts:
            if t.strip() == self._target:
                out.append(list(self._shared))
            else:
                out.append(self._hash.embed([t])[0])
        return out

    def embed_query(self, text: str) -> list[float]:
        # Query gets the shared vector unconditionally so cosine(query,
        # target) = 1.0. Other texts go through embed().
        return list(self._shared)


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sf = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield sf
    await engine.dispose()


@pytest_asyncio.fixture
async def repo(session_factory) -> KnowledgeBaseRepository:
    return KnowledgeBaseRepository(session_factory)


@pytest_asyncio.fixture
async def kb_factory(repo: KnowledgeBaseRepository):
    """Returns ``async create(**kwargs)`` that seeds a KB row.

    Caller-friendly defaults: tenant_id / owner_user_id / name /
    visibility default to sane values so a single-line call is enough
    for the common "I just need a private KB to point at" case.
    """

    async def _create(
        *,
        tenant_id: str = "tenant-recall",
        owner_user_id: str = "user-recall",
        name: str = "Recall KB",
        visibility: str = "private",
        embedding_model: str | None = None,
    ) -> dict[str, Any]:
        return await repo.create(
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
            name=name,
            visibility=visibility,
            embedding_model=embedding_model,
        )

    return _create


@pytest.fixture
def chroma_tmpdir(tmp_path):
    """Ephemeral Chroma persist dir — one per test, auto-cleaned."""
    persist = tmp_path / "chroma"
    persist.mkdir(parents=True, exist_ok=True)
    return str(persist)


class InMemoryVectorStore(VectorStore):
    """Trivial in-memory cosine-search store for L1 recall tests.

    Why not Chroma: chromadb pulls in an HNSW C extension and a
    persistent client per test; for L1 we only need the contract
    (``add(collection, chunks, embeddings)`` and ``search(collection,
    query_embedding, top_k)`` returning SearchResult sorted by cosine
    similarity). Exact-cosine over a few dozen vectors is plenty.

    Tenant scoping: collections are namespaced by the current tenant
    id, mirroring ChromaVectorStore. Tests can swap tenant context
    via ``deerflow.config.tenant.set_current_tenant_id`` and observe
    the same isolation behaviour without going through chromadb.
    """

    def __init__(self) -> None:
        self._collections: dict[str, list[dict[str, Any]]] = {}

    def _scoped(self, collection: str) -> str:
        from deerflow.config.tenant import get_current_tenant_id

        return f"{get_current_tenant_id()}_{collection}"

    def add(
        self,
        collection: str,
        chunks: list[dict[str, Any]],
        embeddings: list[list[float]],
    ) -> list[str]:
        scoped = self._scoped(collection)
        bucket = self._collections.setdefault(scoped, [])
        ids: list[str] = []
        for i, (chunk, vec) in enumerate(zip(chunks, embeddings)):
            cid = chunk.get("id") or f"{scoped}-{len(bucket)}-{i}"
            bucket.append(
                {
                    "id": cid,
                    "content": chunk["content"],
                    "metadata": dict(chunk.get("metadata", {})),
                    "embedding": list(vec),
                }
            )
            ids.append(cid)
        return ids

    def search(
        self,
        collection: str,
        query_embedding: list[float],
        top_k: int = 5,
        score_threshold: float = 0.0,
    ) -> list[SearchResult]:
        scoped = self._scoped(collection)
        bucket = self._collections.get(scoped, [])
        if not bucket:
            return []
        q = np.asarray(query_embedding, dtype=np.float32)
        q_norm = float(np.linalg.norm(q)) or 1.0
        scored: list[SearchResult] = []
        for item in bucket:
            v = np.asarray(item["embedding"], dtype=np.float32)
            v_norm = float(np.linalg.norm(v)) or 1.0
            cos = float(np.dot(q, v) / (q_norm * v_norm))
            score = max(0.0, min(1.0, (cos + 1.0) / 2.0))
            if score < score_threshold:
                continue
            scored.append(
                SearchResult(
                    chunk_id=item["id"],
                    content=item["content"],
                    metadata=dict(item["metadata"]),
                    score=score,
                )
            )
        scored.sort(key=lambda r: r.score, reverse=True)
        return scored[:top_k]

    def delete(self, collection: str, chunk_ids: list[str]) -> int:
        scoped = self._scoped(collection)
        bucket = self._collections.get(scoped, [])
        before = len(bucket)
        self._collections[scoped] = [b for b in bucket if b["id"] not in set(chunk_ids)]
        return before - len(self._collections[scoped])

    def list_collections(self) -> list[str]:
        from deerflow.config.tenant import get_current_tenant_id

        prefix = f"{get_current_tenant_id()}_"
        return [c[len(prefix):] for c in self._collections if c.startswith(prefix)]

    def delete_collection(self, collection: str) -> bool:
        scoped = self._scoped(collection)
        return self._collections.pop(scoped, None) is not None

    def count(self, collection: str) -> int:
        return len(self._collections.get(self._scoped(collection), []))


@pytest.fixture
def in_memory_store(monkeypatch):
    """Replace ``get_vector_store`` with an InMemoryVectorStore singleton.

    Patched at the import sites that ``DocumentRetriever`` and the
    chunk writer reach for. Returns the store so tests can pre-seed
    chunks before invoking retrieval.
    """
    store = InMemoryVectorStore()
    monkeypatch.setattr("deerflow.rag.vector_store.get_vector_store", lambda: store)
    monkeypatch.setattr("deerflow.rag.retrieval.get_vector_store", lambda: store)
    return store
