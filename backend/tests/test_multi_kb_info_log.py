"""Tests for the multi_kb_retrieve INFO log (Sprint A.7).

Each ``multi_kb_retrieve`` call must emit a single INFO line containing
``per_kb=[{kb_id, kb_name, raw_max, raw_min, returned}]`` so operators
can grep server logs to diagnose retrieval quality without enabling
TRACE on the whole RAG stack.
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


class TestMultiKbInfoLog:
    def teardown_method(self) -> None:
        set_rag_config(RagConfig())

    def test_logs_per_kb_summary(self, caplog) -> None:
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
                return _make_kb_result([0.9, 0.6], "A")
            return _make_kb_result([0.5], "B")

        with patch(
            "deerflow.knowledge_base.retrieval.DocumentRetriever"
        ) as mock_cls:
            inst = MagicMock()
            inst.retrieve.side_effect = fake_retrieve
            mock_cls.return_value = inst

            with caplog.at_level("INFO", logger="deerflow.knowledge_base.retrieval"):
                multi_kb_retrieve([kb_a, kb_b], query="q", top_k=4)

        info_lines = [
            r.getMessage()
            for r in caplog.records
            if r.name == "deerflow.knowledge_base.retrieval" and r.levelname == "INFO"
        ]
        assert any("multi_kb_retrieve:" in m for m in info_lines)
        joined = " ".join(info_lines)
        assert "per_kb=" in joined
        assert "raw_max" in joined
        assert "returned" in joined
        assert "strategy=absolute" in joined

    def test_log_records_kb_failure(self, caplog) -> None:
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
            if collection == "col_b":
                raise RuntimeError("boom")
            return _make_kb_result([0.7], "A")

        with patch(
            "deerflow.knowledge_base.retrieval.DocumentRetriever"
        ) as mock_cls:
            inst = MagicMock()
            inst.retrieve.side_effect = fake_retrieve
            mock_cls.return_value = inst

            with caplog.at_level("INFO", logger="deerflow.knowledge_base.retrieval"):
                multi_kb_retrieve([kb_a, kb_b], query="q", top_k=4)

        joined = " ".join(
            r.getMessage()
            for r in caplog.records
            if r.name == "deerflow.knowledge_base.retrieval"
        )
        assert "RuntimeError" in joined
