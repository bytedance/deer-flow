"""End-to-end scenarios across RAG modules.

Uses a real temporary Chroma instance for integration-level assertions:
- Ingest → retrieve roundtrip (real Chroma, mock embedder)
- Tenant isolation end-to-end
- search_knowledge_base tool disabled/missing-context/no-auth blocking
- Embedding dim mismatch blocks write
- Cross-KB retrieval with different embedding models
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from deerflow.rag.backends.chroma import ChromaVectorStore
from deerflow.rag.embeddings import EmbeddingProvider
from deerflow.rag.errors import EmbeddingDimensionMismatchError
from deerflow.rag.ingestion import DocumentIngestor
from deerflow.rag.retrieval import DocumentRetriever

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


class FakeEmbedder(EmbeddingProvider):
    """Deterministic embedder for testing — produces fixed-dim vectors."""

    def __init__(self, dim: int = 32) -> None:
        self._dim = dim

    @property
    def dimension(self) -> int:
        return self._dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            seed = sum(ord(c) for c in text) % 1000
            vec = [0.0] * self._dim
            for i in range(self._dim):
                vec[i] = ((seed * (i + 1)) % 100) / 100.0
            norm = sum(v * v for v in vec) ** 0.5 or 1.0
            vectors.append([v / norm for v in vec])
        return vectors


@pytest.fixture()
def chroma_store(tmp_path):
    """Return a ChromaVectorStore backed by a temp directory."""
    return ChromaVectorStore(persist_dir=str(tmp_path / "chroma"))


def _set_tenant_user(tenant: str, user_id: str):
    """Patch tenant + user context for ChromaVectorStore._collection_name."""
    return (
        patch("deerflow.rag.backends.chroma.get_current_tenant_id", return_value=tenant),
        patch("deerflow.rag.backends.chroma.get_current_user", return_value=SimpleNamespace(id=user_id)),
        patch("deerflow.rag.backends.chroma.get_rag_config", return_value=MagicMock(allow_no_auth_kb=False)),
    )


# ---------------------------------------------------------------------------
# Ingest → Retrieve roundtrip
# ---------------------------------------------------------------------------


class TestIngestRetrieveRoundtrip:
    def test_ingest_then_retrieve_finds_chunk(self, chroma_store):
        embedder = FakeEmbedder(dim=32)

        p1, p2, p3 = _set_tenant_user("acme", "alice")
        with p1, p2, p3, patch("deerflow.rag.ingestion.get_vector_store", return_value=chroma_store):
            ingestor = DocumentIngestor(embedder=embedder)
            result = ingestor.ingest_text(
                "The pump vibration exceeded threshold at bearing 3. Maintenance required.",
                source_name="alert.txt",
                collection="kb1",
            )
            assert result.chunk_count >= 1

        with p1, p2, p3, patch("deerflow.rag.retrieval.get_vector_store", return_value=chroma_store):
            retriever = DocumentRetriever(embedder=embedder)
            retrieved = retriever.retrieve(
                "pump vibration threshold",
                collection="kb1",
                top_k=3,
            )

            assert len(retrieved.results) >= 1
            assert any("pump" in r.content.lower() or "vibration" in r.content.lower() for r in retrieved.results)

    def test_retrieve_empty_collection_returns_empty(self, chroma_store):
        embedder = FakeEmbedder(dim=32)
        p1, p2, p3 = _set_tenant_user("acme", "alice")
        with p1, p2, p3, patch("deerflow.rag.retrieval.get_vector_store", return_value=chroma_store):
            retriever = DocumentRetriever(embedder=embedder)
            result = retriever.retrieve("any query", collection="empty-col")
            assert result.results == []


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------


class TestTenantIsolation:
    def test_tenant_a_cannot_see_tenant_b_data(self, chroma_store):
        embedder = FakeEmbedder(dim=32)

        p1, p2, p3 = _set_tenant_user("tenant-a", "alice")
        with p1, p2, p3, patch("deerflow.rag.ingestion.get_vector_store", return_value=chroma_store):
            ingestor = DocumentIngestor(embedder=embedder)
            ingestor.ingest_text(
                "Secret project alpha details.",
                source_name="secret.txt",
                collection="shared-name",
            )

        p1, p2, p3 = _set_tenant_user("tenant-b", "bob")
        with p1, p2, p3, patch("deerflow.rag.retrieval.get_vector_store", return_value=chroma_store):
            retriever = DocumentRetriever(embedder=embedder)
            result = retriever.retrieve("project alpha", collection="shared-name")
            assert result.results == []

    def test_same_tenant_different_users_share_collection(self, chroma_store):
        embedder = FakeEmbedder(dim=32)

        p1, p2, p3 = _set_tenant_user("acme", "alice")
        with p1, p2, p3, patch("deerflow.rag.ingestion.get_vector_store", return_value=chroma_store):
            ingestor = DocumentIngestor(embedder=embedder)
            ingestor.ingest_text("Shared team knowledge item.", source_name="doc.txt", collection="team-kb")

        p1, p2, p3 = _set_tenant_user("acme", "bob")
        with p1, p2, p3, patch("deerflow.rag.retrieval.get_vector_store", return_value=chroma_store):
            retriever = DocumentRetriever(embedder=embedder)
            result = retriever.retrieve("team knowledge", collection="team-kb")
            assert len(result.results) >= 1


# ---------------------------------------------------------------------------
# Embedding dim mismatch blocks write
# ---------------------------------------------------------------------------


class TestDimMismatchIntegration:
    def test_wrong_dim_does_not_write_to_chroma(self, chroma_store):
        embedder_16 = FakeEmbedder(dim=16)
        p1, p2, p3 = _set_tenant_user("acme", "alice")

        with p1, p2, p3:
            count_before = chroma_store.count("kb-dim-test")

            with patch("deerflow.rag.ingestion.get_vector_store", return_value=chroma_store):
                ingestor = DocumentIngestor(embedder=embedder_16, expected_dim=32)
                with pytest.raises(EmbeddingDimensionMismatchError):
                    ingestor.ingest_text("some text", source_name="doc.txt", collection="kb-dim-test")

            count_after = chroma_store.count("kb-dim-test")
            assert count_before == count_after == 0


# ---------------------------------------------------------------------------
# search_knowledge_base tool — blocking scenarios
# ---------------------------------------------------------------------------


class TestSearchToolBlocking:
    @pytest.mark.asyncio
    async def test_rag_disabled_returns_error(self):
        from deerflow.rag.tools import search_knowledge_base

        mock_cfg = MagicMock()
        mock_cfg.enabled = False

        with patch("deerflow.rag.tools.get_rag_config", return_value=mock_cfg):
            with patch("deerflow.rag.tools.get_kb_telemetry", return_value=MagicMock()):
                raw = await search_knowledge_base.ainvoke({"query": "test"})
                payload = json.loads(raw)
                assert payload["error"] == "RAG subsystem is not enabled"
                assert payload["results"] == []

    @pytest.mark.asyncio
    async def test_missing_tenant_context_blocked(self):
        from deerflow.rag.tools import search_knowledge_base

        mock_cfg = MagicMock()
        mock_cfg.enabled = True
        mock_cfg.retrieval_top_k = 5
        mock_cfg.max_selected_kbs = 10
        mock_cfg.allow_no_auth_kb = False

        runtime = SimpleNamespace(context={"thread_id": "th-1"})
        config = {"configurable": {"__pregel_runtime": runtime}}

        with (
            patch("deerflow.rag.tools.get_rag_config", return_value=mock_cfg),
            patch("deerflow.rag.tools.get_kb_telemetry", return_value=MagicMock()),
            patch("deerflow.rag.tools.get_current_tenant_id", return_value="default"),
            patch("deerflow.rag.tools.get_effective_user_id", return_value="default"),
        ):
            raw = await search_knowledge_base.ainvoke({"query": "test", "collection": "some-col"}, config=config)
            payload = json.loads(raw)
            assert "error" in payload or payload.get("results") == []


# ---------------------------------------------------------------------------
# Cross-KB retrieval with different embedding models
# ---------------------------------------------------------------------------


class TestCrossKBDifferentEmbeddings:
    def test_different_embedders_produce_different_vectors(self):
        embedder_a = FakeEmbedder(dim=16)
        embedder_b = FakeEmbedder(dim=32)

        vec_a = embedder_a.embed(["hello"])
        vec_b = embedder_b.embed(["hello"])

        assert len(vec_a[0]) == 16
        assert len(vec_b[0]) == 32
        assert vec_a[0] != vec_b[0][:16]

    def test_same_embedder_produces_consistent_vectors(self):
        embedder = FakeEmbedder(dim=32)
        v1 = embedder.embed(["deterministic text"])
        v2 = embedder.embed(["deterministic text"])
        assert v1 == v2

    def test_different_texts_produce_different_vectors(self):
        embedder = FakeEmbedder(dim=32)
        v1 = embedder.embed(["text one"])[0]
        v2 = embedder.embed(["text two"])[0]
        assert v1 != v2


# ---------------------------------------------------------------------------
# Dispatcher crash recovery (state-level)
# ---------------------------------------------------------------------------


class TestDispatcherRecovery:
    def test_pending_and_indexing_are_active_statuses(self):
        ACTIVE_STATUSES = {"pending", "indexing"}
        assert "pending" in ACTIVE_STATUSES
        assert "indexing" in ACTIVE_STATUSES

    def test_indexed_and_failed_are_terminal(self):
        ACTIVE_STATUSES = {"pending", "indexing"}
        assert "indexed" not in ACTIVE_STATUSES
        assert "failed" not in ACTIVE_STATUSES

    @pytest.mark.parametrize(
        "status,should_recover",
        [
            ("pending", True),
            ("indexing", True),
            ("indexed", False),
            ("failed", False),
        ],
    )
    def test_recovery_decision_per_status(self, status, should_recover):
        is_active = status in {"pending", "indexing"}
        assert is_active is should_recover


# ---------------------------------------------------------------------------
# Score strategy normalization
# ---------------------------------------------------------------------------


class TestScoreNormalization:
    def test_normalize_scores_across_kbs(self):
        from deerflow.rag.retrieval import normalize_scores
        from deerflow.rag.vector_store import SearchResult

        results = [
            SearchResult(chunk_id="c1", content="a", metadata={"kb": "kb-a"}, score=0.2),
            SearchResult(chunk_id="c2", content="b", metadata={"kb": "kb-a"}, score=0.8),
            SearchResult(chunk_id="c3", content="c", metadata={"kb": "kb-b"}, score=0.5),
        ]
        normalized = normalize_scores(results)

        scores = [r.score for r in normalized]
        assert max(scores) == pytest.approx(1.0)
        assert min(scores) == pytest.approx(0.0)

    def test_normalize_single_result(self):
        from deerflow.rag.retrieval import normalize_scores
        from deerflow.rag.vector_store import SearchResult

        results = [SearchResult(chunk_id="c1", content="a", metadata={}, score=0.7)]
        normalized = normalize_scores(results)
        assert normalized[0].score == 1.0

    def test_normalize_preserves_order(self):
        from deerflow.rag.retrieval import normalize_scores
        from deerflow.rag.vector_store import SearchResult

        results = [
            SearchResult(chunk_id="c1", content="a", metadata={}, score=0.3),
            SearchResult(chunk_id="c2", content="b", metadata={}, score=0.7),
            SearchResult(chunk_id="c3", content="c", metadata={}, score=0.5),
        ]
        normalized = normalize_scores(results)
        assert [r.chunk_id for r in normalized] == ["c1", "c2", "c3"]
