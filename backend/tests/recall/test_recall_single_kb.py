"""L1 recall tests #1 / #2 / #3 — single-KB hit ranking, top-K cap, score threshold.

Goal: prove the ``embed → vector_store.search → SearchResult`` pipeline
ranks the right chunk #1 when one chunk is the obvious match, respects
the requested ``top_k`` cap, and filters by ``score_threshold``.

Why this is L1: we are not measuring whether OpenAI's embedding model
is good. We are measuring whether the *plumbing* works — that the
DocumentRetriever embeds the query with the same provider it used to
embed the chunks, that the cosine math in the store matches what we
expect, and that the SearchResult ordering is by descending score.

Determinism: ``ControlledEmbedder`` pins the target chunk's vector to
the query's vector (cosine = 1.0). All other chunks go through the
hash embedder, which gives near-zero cosine to the query. So #1 is
guaranteed to be the target chunk regardless of dim or chunk order.
"""

from __future__ import annotations

import pytest

from deerflow.config.rag_config import RagConfig, set_rag_config
from deerflow.config.tenant import set_current_tenant_id
from deerflow.rag.retrieval import DocumentRetriever

from .conftest import ControlledEmbedder, HashEmbedder


@pytest.fixture(autouse=True)
def _restore_rag_config():
    yield
    set_rag_config(RagConfig())


class TestSingleKbRecall:
    def test_target_chunk_ranks_first(self, in_memory_store):
        """Insert 10 chunks; query targets chunk #7; expect chunk #7 at rank 1."""
        token = set_current_tenant_id("tenant-recall")
        try:
            query = "what is the diagnostic procedure for high motor vibration?"
            target = (
                "If motor vibration exceeds 4.5 mm/s RMS, isolate the bearing "
                "and run an FFT scan to localise the fault frequency."
            )
            distractors = [
                "Quarterly lubrication is performed on every fan bearing.",
                "Cooling water valves should be inspected during shutdown.",
                "Operator handover notes belong in the run book, not the log.",
                "Replacement gaskets are stored in cabinet B-12 of the warehouse.",
                "Emergency stop testing is documented in the safety binder.",
                "Compressor inlet filters are changed on a 2000-hour cycle.",
                "Refrigerant top-ups must be logged with mass and lot number.",
                "Conveyor belt tensioning uses a calibrated torque wrench.",
                "Annual thermography is scheduled by the reliability team.",
            ]
            chunks_in_order = (
                distractors[:7]
                + [target]
                + distractors[7:]
            )

            embedder = ControlledEmbedder(target_text=target, query_text=query)

            embeddings = embedder.embed(chunks_in_order)
            chunk_ids = in_memory_store.add(
                collection="kb_recall_single",
                chunks=[
                    {"content": c, "metadata": {"document_id": "doc-x", "chunk_index": i}}
                    for i, c in enumerate(chunks_in_order)
                ],
                embeddings=embeddings,
            )
            target_chunk_id = chunk_ids[7]

            retriever = DocumentRetriever(embedder=embedder)
            result = retriever.retrieve(
                query=query,
                collection="kb_recall_single",
                top_k=5,
            )

            assert len(result.results) == 5
            assert result.results[0].chunk_id == target_chunk_id, (
                "Target chunk did not land at rank 1 — pipeline wiring is wrong"
            )
            assert result.results[0].content == target
            assert result.results[0].score >= 0.99
            scores = [r.score for r in result.results]
            assert scores == sorted(scores, reverse=True), (
                "Results not sorted by descending score"
            )
        finally:
            from deerflow.config.tenant import _current_tenant_id
            _current_tenant_id.reset(token)


    def test_empty_collection_returns_empty(self, in_memory_store):
        """Querying a collection that has nothing in it returns []."""
        token = set_current_tenant_id("tenant-recall")
        try:
            embedder = ControlledEmbedder(target_text="x", query_text="y")
            retriever = DocumentRetriever(embedder=embedder)
            result = retriever.retrieve(
                query="anything",
                collection="kb_does_not_exist",
                top_k=5,
            )
            assert result.results == []
        finally:
            from deerflow.config.tenant import _current_tenant_id
            _current_tenant_id.reset(token)


class TestTopKCap:
    """Case #2 — ``top_k`` strictly caps how many SearchResults come back.

    Why L1: protects against off-by-one slicing in the store and
    ``compute_effective_top_k`` math elsewhere. Without an explicit
    cap test, a regression that returns *all* hits would still pass
    "target is rank 1" — and then blow injection budgets in prod.
    """

    def _seed_chunks(self, store, n: int, embedder: HashEmbedder, collection: str) -> list[str]:
        chunks = [
            {
                "content": f"chunk content number {i} — independent text",
                "metadata": {"document_id": f"doc-{i // 3}", "chunk_index": i},
            }
            for i in range(n)
        ]
        embeddings = embedder.embed([c["content"] for c in chunks])
        return store.add(collection=collection, chunks=chunks, embeddings=embeddings)

    def test_top_k_smaller_than_corpus(self, in_memory_store):
        """12 chunks, ``top_k=5`` → exactly 5 results, all sorted desc."""
        token = set_current_tenant_id("tenant-recall")
        try:
            embedder = HashEmbedder()
            self._seed_chunks(in_memory_store, n=12, embedder=embedder, collection="kb_topk")

            retriever = DocumentRetriever(embedder=embedder)
            result = retriever.retrieve(query="any query", collection="kb_topk", top_k=5)

            assert len(result.results) == 5
            scores = [r.score for r in result.results]
            assert scores == sorted(scores, reverse=True)
            # The top-5 must dominate the omitted ones — i.e. there is no
            # chunk in the store with a score > result.results[-1].score
            # that we failed to surface. Re-query with top_k=12 to confirm.
            full = retriever.retrieve(query="any query", collection="kb_topk", top_k=12)
            full_scores = [r.score for r in full.results]
            assert full_scores[:5] == scores

        finally:
            from deerflow.config.tenant import _current_tenant_id
            _current_tenant_id.reset(token)

    def test_top_k_larger_than_corpus(self, in_memory_store):
        """3 chunks, ``top_k=10`` → 3 results, no padding, no error."""
        token = set_current_tenant_id("tenant-recall")
        try:
            embedder = HashEmbedder()
            self._seed_chunks(in_memory_store, n=3, embedder=embedder, collection="kb_small")

            retriever = DocumentRetriever(embedder=embedder)
            result = retriever.retrieve(query="any query", collection="kb_small", top_k=10)

            assert len(result.results) == 3

        finally:
            from deerflow.config.tenant import _current_tenant_id
            _current_tenant_id.reset(token)

    def test_top_k_falls_back_to_config_default(self, in_memory_store):
        """Omitting ``top_k`` uses ``RagConfig.retrieval_top_k`` (default 5)."""
        token = set_current_tenant_id("tenant-recall")
        try:
            set_rag_config(RagConfig(enabled=True, retrieval_top_k=4))
            embedder = HashEmbedder()
            self._seed_chunks(in_memory_store, n=8, embedder=embedder, collection="kb_default_k")

            retriever = DocumentRetriever(embedder=embedder)
            result = retriever.retrieve(query="any query", collection="kb_default_k")

            assert len(result.results) == 4
        finally:
            from deerflow.config.tenant import _current_tenant_id
            _current_tenant_id.reset(token)


class TestScoreThreshold:
    """Case #3 — ``score_threshold`` filters out low-confidence hits.

    The InMemoryVectorStore (and ChromaVectorStore) shifts cosine into
    [0, 1] via ``(cos + 1) / 2``, so the target chunk lands at ~1.0
    and distractors cluster around 0.5 (cos ≈ 0). Setting threshold
    above 0.5 should drop every distractor; setting it above 1.0
    should drop everything including the target.
    """

    def test_threshold_drops_distractors(self, in_memory_store):
        """Threshold = 0.9 keeps only the target, even with 5 distractors."""
        token = set_current_tenant_id("tenant-recall")
        try:
            query = "what triggers an SLA breach alert?"
            target = "SLA breach alerts fire when MTTR exceeds 4 hours on a P1 ticket."
            distractors = [
                "Quarterly KPI reviews are scheduled by the ops team.",
                "Lunch is provided in the cafeteria from 11:30 to 13:30.",
                "Conference room bookings reset at midnight on Sundays.",
                "Door access cards expire 24 months after issuance.",
                "Fire drill participation is mandatory for all employees.",
            ]
            chunks = distractors + [target]
            embedder = ControlledEmbedder(target_text=target, query_text=query)
            embeddings = embedder.embed(chunks)
            in_memory_store.add(
                collection="kb_threshold",
                chunks=[
                    {"content": c, "metadata": {"document_id": "doc-thr", "chunk_index": i}}
                    for i, c in enumerate(chunks)
                ],
                embeddings=embeddings,
            )

            retriever = DocumentRetriever(embedder=embedder)
            result = retriever.retrieve(
                query=query,
                collection="kb_threshold",
                top_k=10,
                score_threshold=0.9,
            )

            assert len(result.results) == 1
            assert result.results[0].content == target
            assert result.results[0].score >= 0.9
        finally:
            from deerflow.config.tenant import _current_tenant_id
            _current_tenant_id.reset(token)

    def test_threshold_above_one_drops_everything(self, in_memory_store):
        """Threshold = 1.01 (impossible to clear) → empty result."""
        token = set_current_tenant_id("tenant-recall")
        try:
            query = "anything"
            target = "exact match content"
            embedder = ControlledEmbedder(target_text=target, query_text=query)
            in_memory_store.add(
                collection="kb_thr_high",
                chunks=[{"content": target, "metadata": {"document_id": "doc-x"}}],
                embeddings=embedder.embed([target]),
            )

            retriever = DocumentRetriever(embedder=embedder)
            result = retriever.retrieve(
                query=query,
                collection="kb_thr_high",
                top_k=5,
                score_threshold=1.01,
            )

            assert result.results == []
        finally:
            from deerflow.config.tenant import _current_tenant_id
            _current_tenant_id.reset(token)

    def test_threshold_falls_back_to_config(self, in_memory_store):
        """Omitting ``score_threshold`` reads ``RagConfig.score_threshold``."""
        token = set_current_tenant_id("tenant-recall")
        try:
            set_rag_config(RagConfig(enabled=True, score_threshold=0.95))
            query = "hello"
            target = "hello world"
            embedder = ControlledEmbedder(target_text=target, query_text=query)
            distractors = ["nothing relevant", "completely off topic"]
            chunks = distractors + [target]
            in_memory_store.add(
                collection="kb_thr_cfg",
                chunks=[{"content": c, "metadata": {"document_id": "d"}} for c in chunks],
                embeddings=embedder.embed(chunks),
            )

            retriever = DocumentRetriever(embedder=embedder)
            result = retriever.retrieve(query=query, collection="kb_thr_cfg", top_k=10)

            assert len(result.results) == 1
            assert result.results[0].content == target
        finally:
            from deerflow.config.tenant import _current_tenant_id
            _current_tenant_id.reset(token)
