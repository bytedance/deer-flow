"""Tests for cross-KB score-strategy behaviour (Sprint A.5).

The default ``cross_kb_score_strategy="absolute"`` keeps raw vector
scores so a high-confidence chunk from a small KB still beats a weak
chunk from a noisier KB. Setting the strategy back to ``"per_kb_minmax"``
re-enables the legacy per-KB normalization.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from deerflow.config.rag_config import RagConfig, set_rag_config
from deerflow.knowledge_base.retrieval import multi_kb_retrieve
from deerflow.rag.retrieval import RetrievalResult
from deerflow.rag.vector_store import SearchResult


def _make_kb_result(scores: list[float], kb_name: str) -> RetrievalResult:
    return RetrievalResult(
        query="q",
        results=[
            SearchResult(
                chunk_id=f"{kb_name}-{i}",
                content=f"chunk-{kb_name}-{i}",
                metadata={"kb_name": kb_name, "title": f"doc-{kb_name}-{i}"},
                score=score,
            )
            for i, score in enumerate(scores)
        ],
    )


class TestCrossKbScoreStrategy:
    def teardown_method(self) -> None:
        set_rag_config(RagConfig())

    def test_absolute_strategy_preserves_relative_ranking(self) -> None:
        """KB A's 0.9 should outrank KB B's best 0.6 under 'absolute'."""
        set_rag_config(
            RagConfig(
                enabled=True,
                cross_kb_score_strategy="absolute",
                max_chunks_per_document=10,
            )
        )

        kb_a = {"id": "a", "name": "KB A", "collection_name": "col_a"}
        kb_b = {"id": "b", "name": "KB B", "collection_name": "col_b"}

        def fake_retrieve(query, collection, top_k):
            if collection == "col_a":
                return _make_kb_result([0.9, 0.85], "A")
            return _make_kb_result([0.6, 0.55], "B")

        with patch(
            "deerflow.knowledge_base.retrieval.DocumentRetriever"
        ) as mock_cls:
            inst = MagicMock()
            inst.retrieve.side_effect = fake_retrieve
            mock_cls.return_value = inst

            merged = multi_kb_retrieve([kb_a, kb_b], query="q", top_k=4)

        scores = [round(r.score, 4) for r in merged]
        assert scores == sorted(scores, reverse=True)
        assert merged[0].metadata["kb_name"] == "A"
        assert merged[0].score >= 0.9 - 1e-6

    def test_per_kb_minmax_normalizes_to_0_1(self) -> None:
        set_rag_config(
            RagConfig(
                enabled=True,
                cross_kb_score_strategy="per_kb_minmax",
                max_chunks_per_document=10,
            )
        )

        kb_a = {"id": "a", "name": "KB A", "collection_name": "col_a"}
        kb_b = {"id": "b", "name": "KB B", "collection_name": "col_b"}

        def fake_retrieve(query, collection, top_k):
            if collection == "col_a":
                return _make_kb_result([0.9, 0.5], "A")
            return _make_kb_result([0.6, 0.2], "B")

        with patch(
            "deerflow.knowledge_base.retrieval.DocumentRetriever"
        ) as mock_cls:
            inst = MagicMock()
            inst.retrieve.side_effect = fake_retrieve
            mock_cls.return_value = inst

            merged = multi_kb_retrieve([kb_a, kb_b], query="q", top_k=10)

        # Both KBs are normalized so the top of each is 1.0; the small
        # KB no longer punches above its weight in absolute terms.
        assert any(r.score == 1.0 for r in merged)

    def test_default_config_uses_absolute(self) -> None:
        assert RagConfig().cross_kb_score_strategy == "absolute"
