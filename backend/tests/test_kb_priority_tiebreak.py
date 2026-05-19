"""Tests for KB visibility priority tie-breaker (Sprint A.6).

When two chunks land on identical vector scores, the chunk that came
from a higher-visibility-priority KB (private > tenant > public) wins.
This guarantees a user's own private library can't be silently
pre-empted by a noisier shared/public KB.
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


class TestKbPriorityTiebreak:
    def teardown_method(self) -> None:
        set_rag_config(RagConfig())

    def test_private_outranks_tenant_on_tie(self) -> None:
        set_rag_config(
            RagConfig(
                enabled=True,
                cross_kb_score_strategy="absolute",
                max_chunks_per_document=10,
            )
        )

        kb_priv = {
            "id": "p",
            "name": "Private",
            "collection_name": "col_p",
            "visibility": "private",
        }
        kb_tenant = {
            "id": "t",
            "name": "Tenant",
            "collection_name": "col_t",
            "visibility": "tenant",
        }

        def fake_retrieve(query, collection, top_k):
            if collection == "col_p":
                return _make_kb_result([0.8], "Private")
            return _make_kb_result([0.8], "Tenant")

        with patch(
            "deerflow.knowledge_base.retrieval.DocumentRetriever"
        ) as mock_cls:
            inst = MagicMock()
            inst.retrieve.side_effect = fake_retrieve
            mock_cls.return_value = inst

            merged = multi_kb_retrieve([kb_tenant, kb_priv], query="q", top_k=4)

        assert merged[0].metadata["kb_name"] == "Private"

    def test_tenant_outranks_public_on_tie(self) -> None:
        set_rag_config(
            RagConfig(
                enabled=True,
                cross_kb_score_strategy="absolute",
                max_chunks_per_document=10,
            )
        )

        kb_pub = {
            "id": "u",
            "name": "Public",
            "collection_name": "col_u",
            "visibility": "public",
        }
        kb_tenant = {
            "id": "t",
            "name": "Tenant",
            "collection_name": "col_t",
            "visibility": "tenant",
        }

        def fake_retrieve(query, collection, top_k):
            if collection == "col_u":
                return _make_kb_result([0.5], "Public")
            return _make_kb_result([0.5], "Tenant")

        with patch(
            "deerflow.knowledge_base.retrieval.DocumentRetriever"
        ) as mock_cls:
            inst = MagicMock()
            inst.retrieve.side_effect = fake_retrieve
            mock_cls.return_value = inst

            merged = multi_kb_retrieve([kb_pub, kb_tenant], query="q", top_k=4)

        assert merged[0].metadata["kb_name"] == "Tenant"

    def test_higher_score_still_wins_over_priority(self) -> None:
        """Priority is *only* a tie-breaker — it never beats a higher score."""
        set_rag_config(
            RagConfig(
                enabled=True,
                cross_kb_score_strategy="absolute",
                max_chunks_per_document=10,
            )
        )

        kb_priv = {
            "id": "p",
            "name": "Private",
            "collection_name": "col_p",
            "visibility": "private",
        }
        kb_pub = {
            "id": "u",
            "name": "Public",
            "collection_name": "col_u",
            "visibility": "public",
        }

        def fake_retrieve(query, collection, top_k):
            if collection == "col_p":
                return _make_kb_result([0.6], "Private")
            return _make_kb_result([0.9], "Public")

        with patch(
            "deerflow.knowledge_base.retrieval.DocumentRetriever"
        ) as mock_cls:
            inst = MagicMock()
            inst.retrieve.side_effect = fake_retrieve
            mock_cls.return_value = inst

            merged = multi_kb_retrieve([kb_priv, kb_pub], query="q", top_k=4)

        assert merged[0].metadata["kb_name"] == "Public"
        assert merged[0].score >= 0.9 - 1e-6

    def test_kb_priority_metadata_attached(self) -> None:
        set_rag_config(RagConfig(enabled=True, max_chunks_per_document=10))

        kb = {
            "id": "p",
            "name": "Private",
            "collection_name": "col_p",
            "visibility": "private",
        }

        def fake_retrieve(query, collection, top_k):
            return _make_kb_result([0.7], "Private")

        with patch(
            "deerflow.knowledge_base.retrieval.DocumentRetriever"
        ) as mock_cls:
            inst = MagicMock()
            inst.retrieve.side_effect = fake_retrieve
            mock_cls.return_value = inst

            merged = multi_kb_retrieve([kb], query="q", top_k=4)

        assert merged[0].metadata["kb_priority"] == 3
