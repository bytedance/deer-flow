"""Tests for ``vector_metric_stale`` (Sprint A.10).

Two surfaces are exercised:

1. ``KnowledgeBaseService.startup_consistency_check`` — iterates active
   KBs, opens the underlying Chroma collection, and flips
   ``vector_metric_stale=true`` on any KB whose collection metric isn't
   cosine.
2. ``multi_kb_retrieve`` — must skip KBs flagged stale and surface the
   skip in ``per_kb_stats`` so operators see *why* they were dropped.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from deerflow.config.rag_config import RagConfig, set_rag_config
from deerflow.knowledge_base.retrieval import multi_kb_retrieve
from deerflow.knowledge_base.service import KnowledgeBaseService
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


class TestMultiKbRetrieveSkipsStale:
    def teardown_method(self) -> None:
        set_rag_config(RagConfig())

    def test_stale_kb_is_skipped_with_reason(self, caplog) -> None:
        set_rag_config(
            RagConfig(
                enabled=True,
                cross_kb_score_strategy="absolute",
                max_chunks_per_document=10,
            )
        )

        kb_ok = {
            "id": "ok",
            "name": "OK",
            "collection_name": "col_ok",
            "visibility": "private",
        }
        kb_stale = {
            "id": "bad",
            "name": "Stale",
            "collection_name": "col_bad",
            "visibility": "private",
            "vector_metric_stale": True,
        }

        def fake_retrieve(query, collection, top_k):
            assert collection != "col_bad", "stale KB must not be queried"
            return _make_kb_result([0.7], "OK")

        with patch(
            "deerflow.knowledge_base.retrieval.DocumentRetriever"
        ) as mock_cls:
            inst = MagicMock()
            inst.retrieve.side_effect = fake_retrieve
            mock_cls.return_value = inst

            with caplog.at_level("INFO", logger="deerflow.knowledge_base.retrieval"):
                merged = multi_kb_retrieve([kb_stale, kb_ok], query="q", top_k=4)

        assert [r.metadata["kb_name"] for r in merged] == ["OK"]
        log_text = " ".join(
            r.getMessage()
            for r in caplog.records
            if r.name == "deerflow.knowledge_base.retrieval"
        )
        assert "vector_metric_stale" in log_text

    def test_all_stale_returns_empty(self, caplog) -> None:
        set_rag_config(
            RagConfig(
                enabled=True,
                cross_kb_score_strategy="absolute",
                max_chunks_per_document=10,
            )
        )

        kb_a = {
            "id": "a",
            "name": "A",
            "collection_name": "col_a",
            "visibility": "tenant",
            "vector_metric_stale": True,
        }
        kb_b = {
            "id": "b",
            "name": "B",
            "collection_name": "col_b",
            "visibility": "tenant",
            "vector_metric_stale": True,
        }

        with patch(
            "deerflow.knowledge_base.retrieval.DocumentRetriever"
        ) as mock_cls:
            inst = MagicMock()
            inst.retrieve.side_effect = AssertionError("no KB should be queried")
            mock_cls.return_value = inst

            with caplog.at_level("INFO", logger="deerflow.knowledge_base.retrieval"):
                merged = multi_kb_retrieve([kb_a, kb_b], query="q", top_k=4)

        assert merged == []
        log_text = " ".join(
            r.getMessage()
            for r in caplog.records
            if r.name == "deerflow.knowledge_base.retrieval"
        )
        assert log_text.count("vector_metric_stale") >= 2


class TestStartupConsistencyCheck:
    @pytest.mark.asyncio
    async def test_marks_non_cosine_collection_stale(self) -> None:
        kb_repo = MagicMock()
        kb_repo.list_all_active_internal = AsyncMock(
            return_value=[
                {
                    "id": "kb1",
                    "tenant_id": "tenant-x",
                    "collection_name": "kb_abc",
                    "vector_metric_stale": False,
                }
            ]
        )
        kb_repo.set_vector_metric_stale = AsyncMock(return_value=True)
        doc_repo = MagicMock()
        job_repo = MagicMock()
        perm_repo = MagicMock()

        service = KnowledgeBaseService(
            kb_repo=kb_repo,
            doc_repo=doc_repo,
            job_repo=job_repo,
            permission_repo=perm_repo,
        )

        l2_collection = MagicMock()
        l2_collection.metadata = {"hnsw:space": "l2"}
        chroma_client = MagicMock()
        chroma_client.get_collection.return_value = l2_collection

        with patch(
            "deerflow.rag.backends.chroma.ChromaVectorStore._get_client",
            return_value=chroma_client,
        ):
            report = await service.startup_consistency_check()

        assert report["checked"] == 1
        assert report["marked_stale"] == 1
        assert report["errors"] == 0
        kb_repo.set_vector_metric_stale.assert_awaited_once_with("kb1", stale=True)

    @pytest.mark.asyncio
    async def test_skips_already_stale_and_cosine(self) -> None:
        kb_repo = MagicMock()
        kb_repo.list_all_active_internal = AsyncMock(
            return_value=[
                {
                    "id": "cos",
                    "tenant_id": "tenant-x",
                    "collection_name": "kb_cos",
                    "vector_metric_stale": False,
                },
                {
                    "id": "already",
                    "tenant_id": "tenant-x",
                    "collection_name": "kb_already",
                    "vector_metric_stale": True,
                },
            ]
        )
        kb_repo.set_vector_metric_stale = AsyncMock(return_value=True)

        service = KnowledgeBaseService(
            kb_repo=kb_repo,
            doc_repo=MagicMock(),
            job_repo=MagicMock(),
            permission_repo=MagicMock(),
        )

        cos_col = MagicMock()
        cos_col.metadata = {"hnsw:space": "cosine"}
        l2_col = MagicMock()
        l2_col.metadata = {"hnsw:space": "l2"}

        chroma_client = MagicMock()

        def fake_get(*, name: str):
            if name.endswith("kb_cos"):
                return cos_col
            return l2_col

        chroma_client.get_collection.side_effect = fake_get

        with patch(
            "deerflow.rag.backends.chroma.ChromaVectorStore._get_client",
            return_value=chroma_client,
        ):
            report = await service.startup_consistency_check()

        assert report["checked"] == 2
        # cosine → no flip; already-stale → no flip
        assert report["marked_stale"] == 0
        kb_repo.set_vector_metric_stale.assert_not_awaited()
