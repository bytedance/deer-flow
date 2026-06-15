"""Tests for ChromaVectorStore backend.

Covers: tenant-scoped collection naming, no-auth guard, add/search/delete
operations via mocked chromadb client, distance-to-similarity conversion,
metric-aware scoring, and error resilience.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from deerflow.rag.backends.chroma import CHROMA_COSINE_METADATA, ChromaVectorStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_store() -> ChromaVectorStore:
    return ChromaVectorStore(persist_dir="")


def _mock_client_and_collection():
    """Return (client, collection) mocks wired together."""
    collection = MagicMock()
    collection.metadata = dict(CHROMA_COSINE_METADATA)
    client = MagicMock()
    client.get_or_create_collection = MagicMock(return_value=collection)
    client.get_collection = MagicMock(return_value=collection)
    return client, collection


# ---------------------------------------------------------------------------
# Collection naming / tenant isolation
# ---------------------------------------------------------------------------


class TestCollectionNaming:
    @patch("deerflow.rag.backends.chroma.get_rag_config")
    @patch("deerflow.rag.backends.chroma.get_current_user")
    @patch("deerflow.rag.backends.chroma.get_current_tenant_id")
    def test_scoped_name(self, mock_tid, mock_user, mock_cfg):
        mock_tid.return_value = "acme-corp"
        mock_user.return_value = SimpleNamespace(id="user-1")
        store = _make_store()
        assert store._collection_name("my-kb") == "acme-corp_my-kb"

    @patch("deerflow.rag.backends.chroma.get_rag_config")
    @patch("deerflow.rag.backends.chroma.get_current_user")
    @patch("deerflow.rag.backends.chroma.get_current_tenant_id")
    def test_default_tenant_no_auth_blocked(self, mock_tid, mock_user, mock_cfg):
        mock_tid.return_value = "default"
        mock_user.return_value = None
        cfg = MagicMock()
        cfg.allow_no_auth_kb = False
        mock_cfg.return_value = cfg

        store = _make_store()
        with pytest.raises(RuntimeError, match="refusing to resolve collection name"):
            store._collection_name("any-collection")

    @patch("deerflow.rag.backends.chroma.get_rag_config")
    @patch("deerflow.rag.backends.chroma.get_current_user")
    @patch("deerflow.rag.backends.chroma.get_current_tenant_id")
    def test_default_tenant_no_auth_allowed_when_configured(self, mock_tid, mock_user, mock_cfg):
        mock_tid.return_value = "default"
        mock_user.return_value = None
        cfg = MagicMock()
        cfg.allow_no_auth_kb = True
        mock_cfg.return_value = cfg

        store = _make_store()
        name = store._collection_name("my-kb")
        assert name == "default_my-kb"

    @patch("deerflow.rag.backends.chroma.get_rag_config")
    @patch("deerflow.rag.backends.chroma.get_current_user")
    @patch("deerflow.rag.backends.chroma.get_current_tenant_id")
    def test_default_tenant_with_auth_ok(self, mock_tid, mock_user, mock_cfg):
        mock_tid.return_value = "default"
        mock_user.return_value = SimpleNamespace(id="real-user")
        store = _make_store()
        assert store._collection_name("kb") == "default_kb"


# ---------------------------------------------------------------------------
# add
# ---------------------------------------------------------------------------


class TestAdd:
    @patch("deerflow.rag.backends.chroma.get_rag_config")
    @patch("deerflow.rag.backends.chroma.get_current_user")
    @patch("deerflow.rag.backends.chroma.get_current_tenant_id")
    def test_add_returns_generated_ids(self, mock_tid, mock_user, mock_cfg):
        mock_tid.return_value = "tenant-a"
        mock_user.return_value = SimpleNamespace(id="u1")
        mock_cfg.return_value = MagicMock(allow_no_auth_kb=False)

        client, collection = _mock_client_and_collection()
        store = _make_store()
        store._client = client

        chunks = [
            {"content": "chunk-1", "metadata": {"src": "a.txt"}},
            {"content": "chunk-2", "metadata": {"src": "b.txt"}},
        ]
        embeddings = [[0.1] * 8, [0.2] * 8]
        ids = store.add("kb1", chunks, embeddings)

        assert len(ids) == 2
        collection.add.assert_called_once()
        call_kwargs = collection.add.call_args.kwargs
        assert call_kwargs["ids"] == ids
        assert call_kwargs["documents"] == ["chunk-1", "chunk-2"]
        assert call_kwargs["embeddings"] == embeddings
        client.get_or_create_collection.assert_called_once_with(
            name="tenant-a_kb1",
            metadata=dict(CHROMA_COSINE_METADATA),
        )


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------


class TestSearch:
    @patch("deerflow.rag.backends.chroma.get_rag_config")
    @patch("deerflow.rag.backends.chroma.get_current_user")
    @patch("deerflow.rag.backends.chroma.get_current_tenant_id")
    def test_search_returns_results(self, mock_tid, mock_user, mock_cfg):
        mock_tid.return_value = "t1"
        mock_user.return_value = SimpleNamespace(id="u1")
        mock_cfg.return_value = MagicMock()

        client, collection = _mock_client_and_collection()
        collection.query = MagicMock(return_value={
            "ids": [["id1", "id2"]],
            "documents": [["doc1", "doc2"]],
            "metadatas": [[{"src": "a"}, {"src": "b"}]],
            "distances": [[0.2, 0.8]],
        })
        store = _make_store()
        store._client = client

        results = store.search("kb1", [0.1] * 8, top_k=5, score_threshold=0.0)

        assert len(results) == 2
        assert results[0].chunk_id == "id1"
        assert results[0].content == "doc1"
        assert results[0].metadata == {"src": "a"}
        assert results[0].score >= 0.0

    @patch("deerflow.rag.backends.chroma.get_rag_config")
    @patch("deerflow.rag.backends.chroma.get_current_user")
    @patch("deerflow.rag.backends.chroma.get_current_tenant_id")
    def test_search_score_threshold_filters(self, mock_tid, mock_user, mock_cfg):
        mock_tid.return_value = "t1"
        mock_user.return_value = SimpleNamespace(id="u1")
        mock_cfg.return_value = MagicMock()

        client, collection = _mock_client_and_collection()
        collection.query = MagicMock(return_value={
            "ids": [["id1", "id2"]],
            "documents": [["doc1", "doc2"]],
            "metadatas": [[{}, {}]],
            "distances": [[0.1, 1.9]],
        })
        store = _make_store()
        store._client = client

        results = store.search("kb1", [0.1] * 8, top_k=5, score_threshold=0.5)

        assert len(results) == 1
        assert results[0].chunk_id == "id1"

    @patch("deerflow.rag.backends.chroma.get_rag_config")
    @patch("deerflow.rag.backends.chroma.get_current_user")
    @patch("deerflow.rag.backends.chroma.get_current_tenant_id")
    def test_search_collection_not_found_returns_empty(self, mock_tid, mock_user, mock_cfg):
        mock_tid.return_value = "t1"
        mock_user.return_value = SimpleNamespace(id="u1")
        mock_cfg.return_value = MagicMock()

        client = MagicMock()
        client.get_collection = MagicMock(side_effect=Exception("not found"))
        store = _make_store()
        store._client = client

        results = store.search("missing", [0.1] * 8)
        assert results == []


# ---------------------------------------------------------------------------
# delete / delete_collection / count / list_collections
# ---------------------------------------------------------------------------


class TestCollectionOps:
    @patch("deerflow.rag.backends.chroma.get_rag_config")
    @patch("deerflow.rag.backends.chroma.get_current_user")
    @patch("deerflow.rag.backends.chroma.get_current_tenant_id")
    def test_delete_returns_count(self, mock_tid, mock_user, mock_cfg):
        mock_tid.return_value = "t1"
        mock_user.return_value = SimpleNamespace(id="u1")
        mock_cfg.return_value = MagicMock()

        client, collection = _mock_client_and_collection()
        store = _make_store()
        store._client = client

        count = store.delete("kb1", ["id1", "id2"])
        assert count == 2
        collection.delete.assert_called_once_with(ids=["id1", "id2"])

    @patch("deerflow.rag.backends.chroma.get_rag_config")
    @patch("deerflow.rag.backends.chroma.get_current_user")
    @patch("deerflow.rag.backends.chroma.get_current_tenant_id")
    def test_delete_error_returns_zero(self, mock_tid, mock_user, mock_cfg):
        mock_tid.return_value = "t1"
        mock_user.return_value = SimpleNamespace(id="u1")
        mock_cfg.return_value = MagicMock()

        client = MagicMock()
        client.get_collection = MagicMock(side_effect=Exception("gone"))
        store = _make_store()
        store._client = client

        assert store.delete("kb1", ["id1"]) == 0

    @patch("deerflow.rag.backends.chroma.get_rag_config")
    @patch("deerflow.rag.backends.chroma.get_current_user")
    @patch("deerflow.rag.backends.chroma.get_current_tenant_id")
    def test_delete_collection_success(self, mock_tid, mock_user, mock_cfg):
        mock_tid.return_value = "t1"
        mock_user.return_value = SimpleNamespace(id="u1")
        mock_cfg.return_value = MagicMock()

        client = MagicMock()
        store = _make_store()
        store._client = client

        assert store.delete_collection("kb1") is True
        client.delete_collection.assert_called_once_with(name="t1_kb1")

    @patch("deerflow.rag.backends.chroma.get_rag_config")
    @patch("deerflow.rag.backends.chroma.get_current_user")
    @patch("deerflow.rag.backends.chroma.get_current_tenant_id")
    def test_delete_collection_error_returns_false(self, mock_tid, mock_user, mock_cfg):
        mock_tid.return_value = "t1"
        mock_user.return_value = SimpleNamespace(id="u1")
        mock_cfg.return_value = MagicMock()

        client = MagicMock()
        client.delete_collection = MagicMock(side_effect=Exception("fail"))
        store = _make_store()
        store._client = client

        assert store.delete_collection("kb1") is False

    @patch("deerflow.rag.backends.chroma.get_rag_config")
    @patch("deerflow.rag.backends.chroma.get_current_user")
    @patch("deerflow.rag.backends.chroma.get_current_tenant_id")
    def test_count_returns_collection_count(self, mock_tid, mock_user, mock_cfg):
        mock_tid.return_value = "t1"
        mock_user.return_value = SimpleNamespace(id="u1")
        mock_cfg.return_value = MagicMock()

        client, collection = _mock_client_and_collection()
        collection.count = MagicMock(return_value=42)
        store = _make_store()
        store._client = client

        assert store.count("kb1") == 42

    @patch("deerflow.rag.backends.chroma.get_rag_config")
    @patch("deerflow.rag.backends.chroma.get_current_user")
    @patch("deerflow.rag.backends.chroma.get_current_tenant_id")
    def test_count_error_returns_zero(self, mock_tid, mock_user, mock_cfg):
        mock_tid.return_value = "t1"
        mock_user.return_value = SimpleNamespace(id="u1")
        mock_cfg.return_value = MagicMock()

        client = MagicMock()
        client.get_collection = MagicMock(side_effect=Exception("err"))
        store = _make_store()
        store._client = client

        assert store.count("kb1") == 0

    @patch("deerflow.rag.backends.chroma.get_rag_config")
    @patch("deerflow.rag.backends.chroma.get_current_tenant_id")
    def test_list_collections_filters_by_tenant(self, mock_tid, mock_cfg):
        mock_tid.return_value = "t1"
        mock_cfg.return_value = MagicMock()

        col_a = SimpleNamespace(name="t1_kb1")
        col_b = SimpleNamespace(name="t1_kb2")
        col_other = SimpleNamespace(name="t2_kb3")
        client = MagicMock()
        client.list_collections = MagicMock(return_value=[col_a, col_b, col_other])
        store = _make_store()
        store._client = client

        result = store.list_collections()
        assert sorted(result) == ["kb1", "kb2"]


# ---------------------------------------------------------------------------
# distance → similarity conversion
# ---------------------------------------------------------------------------


class TestDistanceToSimilarity:
    def test_cosine_zero_distance(self):
        score = ChromaVectorStore._distance_to_similarity(0.0, "cosine")
        assert score == pytest.approx(1.0)

    def test_cosine_max_distance(self):
        score = ChromaVectorStore._distance_to_similarity(2.0, "cosine")
        assert score == pytest.approx(0.0)

    def test_cosine_mid_distance(self):
        score = ChromaVectorStore._distance_to_similarity(1.0, "cosine")
        assert score == pytest.approx(0.5)

    def test_l2_zero_distance(self):
        score = ChromaVectorStore._distance_to_similarity(0.0, "l2")
        assert score == pytest.approx(1.0)

    def test_l2_large_distance(self):
        score = ChromaVectorStore._distance_to_similarity(100.0, "l2")
        assert 0.0 <= score < 0.1

    def test_l2_negative_distance_clamped(self):
        score = ChromaVectorStore._distance_to_similarity(-1.0, "l2")
        assert score == pytest.approx(1.0)

    def test_unknown_metric_uses_l2(self):
        score = ChromaVectorStore._distance_to_similarity(0.0, "unknown_metric")
        assert score == pytest.approx(1.0)

    def test_ip_metric_returns_valid_range(self):
        score = ChromaVectorStore._distance_to_similarity(0.0, "ip")
        assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# resolve_metric
# ---------------------------------------------------------------------------


class TestResolveMetric:
    def test_cosine_from_metadata(self):
        col = MagicMock()
        col.metadata = {"hnsw:space": "cosine"}
        store = _make_store()
        assert store._resolve_metric(col) == "cosine"

    def test_empty_metadata_defaults_to_l2(self):
        col = MagicMock()
        col.metadata = {}
        store = _make_store()
        assert store._resolve_metric(col) == "l2"

    def test_none_metadata_defaults_to_l2(self):
        col = MagicMock()
        col.metadata = None
        store = _make_store()
        assert store._resolve_metric(col) == "l2"
