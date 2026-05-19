"""Tests for Chroma cosine enforcement + metric-aware similarity (Sprint A.8 + A.9).

* New collections must be created with ``metadata={"hnsw:space":"cosine"}``
  so all newly-indexed data uses the same distance metric.
* When chromadb returns distances from an existing collection, the score
  conversion must respect that collection's actual metric — the legacy
  ``1 - distance/2`` formula is wrong for L2 / inner product.
"""

from __future__ import annotations

from unittest.mock import patch

from deerflow.rag.backends.chroma import (
    CHROMA_COSINE_METADATA,
    ChromaVectorStore,
)


class _FakeCollection:
    def __init__(self, *, distances=None, metadata=None):
        self._distances = distances or []
        self.metadata = metadata or {}
        self.added: list[dict] = []

    def query(self, query_embeddings, n_results):
        n = min(n_results, len(self._distances))
        return {
            "ids": [[f"id-{i}" for i in range(n)]],
            "documents": [[f"doc-{i}" for i in range(n)]],
            "metadatas": [[{"i": i} for i in range(n)]],
            "distances": [self._distances[:n]],
        }

    def add(self, ids, documents, metadatas, embeddings):
        self.added.append(
            {
                "ids": ids,
                "documents": documents,
                "metadatas": metadatas,
                "embeddings": embeddings,
            }
        )


class _FakeClient:
    def __init__(self, *, collection: _FakeCollection | None = None):
        self._col = collection
        self.last_create_kwargs: dict | None = None

    def get_collection(self, name):
        if self._col is None:
            raise RuntimeError("not found")
        return self._col

    def get_or_create_collection(self, **kwargs):
        self.last_create_kwargs = kwargs
        return _FakeCollection(distances=[], metadata=kwargs.get("metadata"))


class TestChromaCosineEnforcement:
    def test_add_creates_collection_with_cosine_metadata(self):
        store = ChromaVectorStore(persist_dir="d:/tmp/chroma-test")
        client = _FakeClient()
        store._client = client

        with patch(
            "deerflow.rag.backends.chroma.get_current_tenant_id",
            return_value="tenant-x",
        ):
            store.add(
                collection="kb_abc",
                chunks=[{"content": "hi", "metadata": {}}],
                embeddings=[[0.1] * 4],
            )

        assert client.last_create_kwargs is not None
        assert client.last_create_kwargs["name"] == "tenant-x_kb_abc"
        assert client.last_create_kwargs["metadata"] == CHROMA_COSINE_METADATA


class TestChromaMetricAwareSearch:
    def test_cosine_distance_to_similarity(self):
        col = _FakeCollection(distances=[0.0, 0.5, 1.0, 2.0], metadata={"hnsw:space": "cosine"})
        store = ChromaVectorStore()
        store._client = _FakeClient(collection=col)

        with patch(
            "deerflow.rag.backends.chroma.get_current_tenant_id",
            return_value="tx",
        ):
            results = store.search("kb_abc", query_embedding=[0.0] * 4, top_k=4)

        scores = [round(r.score, 4) for r in results]
        assert scores[0] == 1.0
        assert 0.7 <= scores[1] <= 0.8
        assert scores[-1] == 0.0

    def test_l2_distance_to_similarity_uses_inverse_formula(self):
        col = _FakeCollection(distances=[0.0, 1.0, 4.0], metadata={"hnsw:space": "l2"})
        store = ChromaVectorStore()
        store._client = _FakeClient(collection=col)

        with patch(
            "deerflow.rag.backends.chroma.get_current_tenant_id",
            return_value="tx",
        ):
            results = store.search("kb_abc", query_embedding=[0.0] * 4, top_k=3)

        scores = [round(r.score, 4) for r in results]
        assert scores[0] == 1.0
        assert abs(scores[1] - 0.5) < 1e-3
        assert abs(scores[2] - 0.2) < 1e-3

    def test_legacy_collection_without_metric_falls_back_to_l2(self):
        col = _FakeCollection(distances=[0.0, 1.0], metadata={})
        store = ChromaVectorStore()
        store._client = _FakeClient(collection=col)

        with patch(
            "deerflow.rag.backends.chroma.get_current_tenant_id",
            return_value="tx",
        ):
            results = store.search("kb_abc", query_embedding=[0.0] * 4, top_k=2)

        # Legacy collection (no metric) should NOT be treated as cosine —
        # otherwise the operator would see plausible-looking but wrong scores.
        # L2 inverse: distance=1 → 0.5
        assert abs(results[1].score - 0.5) < 1e-3
