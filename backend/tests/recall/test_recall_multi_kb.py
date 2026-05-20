"""L1 recall tests #4 / #5 / #6 / #7 / #9 — multi-KB merge behaviours.

#4 — **max_chunks_per_document**: a single document can't dominate the
merged top-K. Once ``RagConfig.max_chunks_per_document`` chunks from
the same ``document_id`` have landed, further chunks from that doc are
skipped — even if they outrank chunks from other docs.

#5 — **vector_metric_stale**: KBs whose Chroma metric drifted from
their embedding model are filtered upfront and surfaced in
``per_kb_stats`` with ``skipped_reason="vector_metric_stale"``. They
contribute zero chunks to the merged output even if the underlying
collection still has data — protecting against silently serving stale
vectors after an embedding-model swap.

#6 — **cross-tenant isolation**: tenant A indexes chunks into a KB.
Tenant B's context tries to retrieve from the same logical
collection name — should get zero hits because the vector store
namespaces collections by tenant. This is the recall-side
counterpart to test_kb_visibility.py (which only covers the DB
visibility layer); without this, a worker that lost its tenant
context would still leak vectors.

#7 — **embedder cache (Sprint B.3.4)**: when N KBs share the same
``embedding_model``, only one ``get_embedding_provider(spec)`` call
happens; when KBs use M distinct models, exactly M provider instances
are created. Without this each KB would re-instantiate a provider per
query — fine for the offline path, expensive at request time.

#9 — **absolute vs per_kb_minmax**: the same two KBs feed the
``multi_kb_retrieve`` merge under both strategies. Under
``absolute`` (default, called "raw" in docs/RAG.md §2), KB A's
high-confidence chunk outranks KB B's mediocre top hit. Under
``per_kb_minmax`` ("comparable" in docs), each KB is rescaled to
[0, 1] so the small KB no longer punches above its weight.

Tests teardown RagConfig to avoid bleeding into other tests.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from deerflow.config.rag_config import RagConfig, set_rag_config
from deerflow.config.tenant import _current_tenant_id, set_current_tenant_id
from deerflow.knowledge_base.retrieval import multi_kb_retrieve
from deerflow.rag.retrieval import DocumentRetriever, RetrievalResult
from deerflow.rag.vector_store import SearchResult

from .conftest import ControlledEmbedder


@pytest.fixture(autouse=True)
def _restore_rag_config():
    yield
    set_rag_config(RagConfig())


class TestCrossTenantIsolation:
    """Case #6 — tenant A's vectors are invisible from tenant B's context."""

    def test_tenant_b_cannot_retrieve_tenant_a_chunks(self, in_memory_store):
        # Tenant A indexes a chunk that the query would otherwise match
        # perfectly. The collection *name* is the same in both tenant
        # contexts — only the tenant prefix in the vector store
        # separates them.
        query = "how do I escalate a P1 incident?"
        target = "P1 incidents page the on-call lead immediately and open a war-room channel."
        embedder = ControlledEmbedder(target_text=target, query_text=query)
        collection = "kb_shared_name"

        token_a = set_current_tenant_id("tenant-a")
        try:
            in_memory_store.add(
                collection=collection,
                chunks=[{"content": target, "metadata": {"document_id": "doc-a"}}],
                embeddings=embedder.embed([target]),
            )
            # Sanity: the same context that wrote it can read it back.
            sanity = DocumentRetriever(embedder=embedder).retrieve(
                query=query, collection=collection, top_k=5
            )
            assert len(sanity.results) == 1
            assert sanity.results[0].score >= 0.99
        finally:
            _current_tenant_id.reset(token_a)

        # Switch to tenant B. Same collection name, same query, same
        # embedder — the store should report nothing because vectors
        # live under "tenant-a_kb_shared_name", not "tenant-b_*".
        token_b = set_current_tenant_id("tenant-b")
        try:
            cross = DocumentRetriever(embedder=embedder).retrieve(
                query=query, collection=collection, top_k=5
            )
            assert cross.results == [], (
                "Tenant B leaked into tenant A's collection — vector store "
                "tenant prefix is broken"
            )
        finally:
            _current_tenant_id.reset(token_b)

    def test_tenant_a_does_not_see_tenant_b_chunks_either(self, in_memory_store):
        """Symmetric check: isolation must work in both directions."""
        query = "what is the change-control sign-off process?"
        target_b = "Change requests require two reviewer sign-offs before deploy."
        embedder = ControlledEmbedder(target_text=target_b, query_text=query)
        collection = "kb_shared_name"

        token_b = set_current_tenant_id("tenant-b")
        try:
            in_memory_store.add(
                collection=collection,
                chunks=[{"content": target_b, "metadata": {"document_id": "doc-b"}}],
                embeddings=embedder.embed([target_b]),
            )
        finally:
            _current_tenant_id.reset(token_b)

        token_a = set_current_tenant_id("tenant-a")
        try:
            res = DocumentRetriever(embedder=embedder).retrieve(
                query=query, collection=collection, top_k=5
            )
            assert res.results == []
        finally:
            _current_tenant_id.reset(token_a)


class TestAbsoluteVsPerKbMinmax:
    """Case #9 — score strategy controls cross-KB ranking."""

    @staticmethod
    def _kb_result(scores: list[float], kb_name: str) -> RetrievalResult:
        return RetrievalResult(
            query="q",
            results=[
                SearchResult(
                    chunk_id=f"{kb_name}-{i}",
                    content=f"chunk-{kb_name}-{i}",
                    metadata={
                        "kb_name": kb_name,
                        "title": f"doc-{kb_name}-{i}",
                        "document_id": f"doc-{kb_name}-{i}",
                    },
                    score=score,
                )
                for i, score in enumerate(scores)
            ],
        )

    def _run(
        self,
        *,
        strategy: str,
        kb_a_scores: list[float],
        kb_b_scores: list[float],
    ) -> list[SearchResult]:
        set_rag_config(
            RagConfig(
                enabled=True,
                cross_kb_score_strategy=strategy,
                max_chunks_per_document=10,
            )
        )
        kb_a = {"id": "a", "name": "KB A", "collection_name": "col_a"}
        kb_b = {"id": "b", "name": "KB B", "collection_name": "col_b"}

        def fake_retrieve(query, collection, top_k):
            if collection == "col_a":
                return self._kb_result(kb_a_scores, "A")
            return self._kb_result(kb_b_scores, "B")

        with patch(
            "deerflow.knowledge_base.retrieval.DocumentRetriever"
        ) as mock_cls:
            inst = MagicMock(spec=DocumentRetriever)
            inst.retrieve.side_effect = fake_retrieve
            mock_cls.return_value = inst
            return multi_kb_retrieve([kb_a, kb_b], query="q", top_k=4)

    def test_absolute_lets_small_kb_win_with_high_confidence(self):
        """KB A's 0.92 should beat KB B's best 0.55 under 'absolute'."""
        merged = self._run(
            strategy="absolute",
            kb_a_scores=[0.92, 0.10],
            kb_b_scores=[0.55, 0.50, 0.45],
        )
        assert merged[0].metadata["kb_name"] == "A"
        assert merged[0].score >= 0.92 - 1e-6
        # Sorted by raw scores end-to-end.
        scores = [r.score for r in merged]
        assert scores == sorted(scores, reverse=True)

    def test_per_kb_minmax_normalizes_top_of_each_kb_to_one(self):
        """Both KBs' top results should land at score 1.0 after minmax."""
        merged = self._run(
            strategy="per_kb_minmax",
            kb_a_scores=[0.92, 0.10],
            kb_b_scores=[0.55, 0.50, 0.45],
        )
        # Each KB's top should appear with score 1.0 in the merged list.
        kb_top_scores: dict[str, float] = {}
        for r in merged:
            name = r.metadata["kb_name"]
            kb_top_scores[name] = max(kb_top_scores.get(name, 0.0), r.score)
        assert kb_top_scores.get("A") == pytest.approx(1.0)
        assert kb_top_scores.get("B") == pytest.approx(1.0)

    def test_per_kb_minmax_lets_large_kb_compete(self):
        """Under minmax, KB B's 0.55 hit (rescaled to 1.0) reaches rank 1
        territory even though A had a higher absolute score. The two
        strategies disagree about which KB wins — that's the whole
        point of having both.
        """
        absolute = self._run(
            strategy="absolute",
            kb_a_scores=[0.92, 0.10],
            kb_b_scores=[0.55, 0.50, 0.45],
        )
        minmax = self._run(
            strategy="per_kb_minmax",
            kb_a_scores=[0.92, 0.10],
            kb_b_scores=[0.55, 0.50, 0.45],
        )
        # absolute → KB A unambiguously on top.
        assert absolute[0].metadata["kb_name"] == "A"
        # minmax → both KBs have a 1.0-scoring chunk; the tiebreak
        # falls to ``kb_priority`` then ``document_id`` (see
        # ``multi_kb_retrieve`` sort key). So the *set* of top-scoring
        # entries is what changed, not necessarily which one is rank 1.
        top_minmax_scores = [r.score for r in minmax if r.score == pytest.approx(1.0)]
        assert len(top_minmax_scores) >= 2, (
            "Expected both KBs' top hits to be normalized to 1.0 under "
            "per_kb_minmax — got " + repr([r.score for r in minmax])
        )


def _result_for_doc(scores: list[float], document_id: str, kb_name: str = "A") -> RetrievalResult:
    """Build a RetrievalResult where every chunk shares the same document_id.

    Used by the max_chunks_per_document test to drive the per-doc cap
    without relying on the vector store layer.
    """
    return RetrievalResult(
        query="q",
        results=[
            SearchResult(
                chunk_id=f"{document_id}-c{i}",
                content=f"chunk-{document_id}-{i}",
                metadata={
                    "kb_name": kb_name,
                    "title": document_id,
                    "document_id": document_id,
                },
                score=score,
            )
            for i, score in enumerate(scores)
        ],
    )


class TestMaxChunksPerDocument:
    """Case #4 — one document can't dominate the merged top-K."""

    def _run(self, *, max_per_doc: int, doc_a_scores: list[float], doc_b_scores: list[float], top_k: int = 10):
        set_rag_config(
            RagConfig(
                enabled=True,
                max_chunks_per_document=max_per_doc,
                cross_kb_score_strategy="absolute",
            )
        )
        kb = {"id": "kb1", "name": "KB", "collection_name": "col_x"}

        def fake_retrieve(query, collection, top_k):  # noqa: ARG001
            # Single KB returning chunks from two distinct documents.
            return RetrievalResult(
                query=query,
                results=(
                    _result_for_doc(doc_a_scores, "doc-A").results
                    + _result_for_doc(doc_b_scores, "doc-B").results
                ),
            )

        with patch("deerflow.knowledge_base.retrieval.DocumentRetriever") as mock_cls:
            inst = MagicMock(spec=DocumentRetriever)
            inst.retrieve.side_effect = fake_retrieve
            mock_cls.return_value = inst
            return multi_kb_retrieve([kb], query="q", top_k=top_k)

    def test_caps_chunks_from_dominant_document(self):
        """doc-A wants 5 chunks; cap of 3 should truncate doc-A and let doc-B fill."""
        merged = self._run(
            max_per_doc=3,
            doc_a_scores=[0.95, 0.93, 0.91, 0.89, 0.87],
            doc_b_scores=[0.50, 0.48],
        )

        per_doc: dict[str, int] = {}
        for r in merged:
            per_doc[r.metadata["document_id"]] = per_doc.get(r.metadata["document_id"], 0) + 1

        assert per_doc.get("doc-A", 0) == 3, (
            f"doc-A should be capped at 3 chunks, got {per_doc.get('doc-A', 0)}"
        )
        # doc-B's two chunks survive — they fill out the budget below the cap.
        assert per_doc.get("doc-B", 0) == 2

    def test_cap_of_one_keeps_top_chunk_per_document(self):
        """``max_chunks_per_document=1`` keeps only the highest-scoring chunk per doc."""
        merged = self._run(
            max_per_doc=1,
            doc_a_scores=[0.95, 0.93, 0.91],
            doc_b_scores=[0.50, 0.48],
        )

        # One per document, ordered by best score: doc-A (0.95), doc-B (0.50).
        assert [r.metadata["document_id"] for r in merged] == ["doc-A", "doc-B"]
        assert [r.score for r in merged] == [0.95, 0.50]


class TestVectorMetricStale:
    """Case #5 — KBs flagged ``vector_metric_stale`` are skipped upfront."""

    def _make_kb(self, *, kb_id: str, stale: bool, name: str | None = None) -> dict:
        return {
            "id": kb_id,
            "name": name or f"KB-{kb_id}",
            "collection_name": f"col_{kb_id}",
            "vector_metric_stale": stale,
        }

    def test_stale_kb_contributes_zero_chunks(self, caplog):
        """Stale KB's collection is never queried; merged result is empty."""
        set_rag_config(RagConfig(enabled=True))
        stale_kb = self._make_kb(kb_id="stale", stale=True)
        retriever_calls: list[str] = []

        def fake_retrieve(query, collection, top_k):  # noqa: ARG001
            retriever_calls.append(collection)
            return RetrievalResult(query=query, results=[
                SearchResult(
                    chunk_id="x",
                    content="should never be returned",
                    metadata={"document_id": "d", "kb_name": "stale"},
                    score=0.99,
                )
            ])

        with caplog.at_level("INFO", logger="deerflow.knowledge_base.retrieval"):
            with patch("deerflow.knowledge_base.retrieval.DocumentRetriever") as mock_cls:
                inst = MagicMock(spec=DocumentRetriever)
                inst.retrieve.side_effect = fake_retrieve
                mock_cls.return_value = inst
                merged = multi_kb_retrieve([stale_kb], query="q", top_k=5)

        assert merged == []
        assert retriever_calls == [], (
            "Stale KB's collection was queried — vector_metric_stale guard is broken"
        )
        # The skip reason must surface in the per_kb_stats log line so
        # operators can diagnose why a KB returned nothing.
        assert any("vector_metric_stale" in rec.message for rec in caplog.records)

    def test_stale_kb_does_not_block_healthy_siblings(self):
        """One stale + one healthy KB → only the healthy KB's chunks come back."""
        set_rag_config(RagConfig(enabled=True))
        stale = self._make_kb(kb_id="stale", stale=True, name="Stale")
        fresh = self._make_kb(kb_id="fresh", stale=False, name="Fresh")

        def fake_retrieve(query, collection, top_k):  # noqa: ARG001
            if collection == "col_fresh":
                return RetrievalResult(
                    query=query,
                    results=[
                        SearchResult(
                            chunk_id="f1",
                            content="fresh chunk",
                            metadata={"document_id": "d-f", "kb_name": "Fresh"},
                            score=0.8,
                        )
                    ],
                )
            return RetrievalResult(
                query=query,
                results=[
                    SearchResult(
                        chunk_id="s1",
                        content="stale chunk",
                        metadata={"document_id": "d-s", "kb_name": "Stale"},
                        score=0.99,
                    )
                ],
            )

        with patch("deerflow.knowledge_base.retrieval.DocumentRetriever") as mock_cls:
            inst = MagicMock(spec=DocumentRetriever)
            inst.retrieve.side_effect = fake_retrieve
            mock_cls.return_value = inst
            merged = multi_kb_retrieve([stale, fresh], query="q", top_k=5)

        assert len(merged) == 1
        assert merged[0].metadata["kb_name"] == "Fresh"
        assert merged[0].chunk_id == "f1"


class TestEmbedderCache:
    """Case #7 — providers are cached per ``embedding_model`` spec."""

    def _kb(self, kb_id: str, *, embedding_model: str | None) -> dict:
        return {
            "id": kb_id,
            "name": f"KB-{kb_id}",
            "collection_name": f"col_{kb_id}",
            "embedding_model": embedding_model,
        }

    def _patched_run(self, knowledge_bases: list[dict]):
        set_rag_config(RagConfig(enabled=True))
        provider_calls: list[str | None] = []

        def fake_get_provider(spec=None):
            provider_calls.append(spec)
            mock = MagicMock()
            mock.embed_query.return_value = [0.1, 0.2, 0.3]
            return mock

        def fake_retrieve(query, collection, top_k):  # noqa: ARG001
            return RetrievalResult(query=query, results=[])

        with patch(
            "deerflow.knowledge_base.retrieval.get_embedding_provider",
            side_effect=fake_get_provider,
        ):
            with patch(
                "deerflow.knowledge_base.retrieval.DocumentRetriever"
            ) as mock_cls:
                inst = MagicMock(spec=DocumentRetriever)
                inst.retrieve.side_effect = fake_retrieve
                mock_cls.return_value = inst
                multi_kb_retrieve(knowledge_bases, query="q", top_k=5)

        return provider_calls

    def test_shared_model_creates_one_provider(self):
        """Three KBs on one model → one ``get_embedding_provider`` call."""
        kbs = [
            self._kb("a", embedding_model="openai:text-embedding-3-small"),
            self._kb("b", embedding_model="openai:text-embedding-3-small"),
            self._kb("c", embedding_model="openai:text-embedding-3-small"),
        ]
        calls = self._patched_run(kbs)

        assert len(calls) == 1, f"Expected 1 provider call, got {len(calls)}: {calls}"
        assert calls[0] == "openai:text-embedding-3-small"

    def test_distinct_models_create_one_provider_each(self):
        """Three KBs across three models → exactly three provider calls."""
        kbs = [
            self._kb("a", embedding_model="openai:text-embedding-3-small"),
            self._kb("b", embedding_model="openai:text-embedding-3-large"),
            self._kb("c", embedding_model="local:bge-base-en"),
        ]
        calls = self._patched_run(kbs)

        assert len(calls) == 3
        assert set(calls) == {
            "openai:text-embedding-3-small",
            "openai:text-embedding-3-large",
            "local:bge-base-en",
        }

    def test_legacy_kbs_share_global_default(self):
        """Two KBs with ``embedding_model=None`` collapse onto a single global call."""
        kbs = [
            self._kb("a", embedding_model=None),
            self._kb("b", embedding_model=None),
        ]
        calls = self._patched_run(kbs)

        # Both legacy KBs route through ``get_embedding_provider(None)`` → one call.
        assert len(calls) == 1
        assert calls[0] is None

    def test_mix_of_legacy_and_explicit_models(self):
        """One legacy + one explicit → two distinct provider calls."""
        kbs = [
            self._kb("a", embedding_model=None),
            self._kb("b", embedding_model="openai:text-embedding-3-small"),
        ]
        calls = self._patched_run(kbs)

        assert len(calls) == 2
        assert set(calls) == {None, "openai:text-embedding-3-small"}
