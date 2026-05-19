"""Tests for IndexingService KB-bound embedding (Sprint B.3.2 + B.3.3).

Verifies:
- IndexingService resolves the embedding provider from the KB row's
  ``embedding_model`` (not the global config), so a tenant flipping
  the global default doesn't poison existing KBs.
- After the first successful ingest, ``embedding_dim`` is backfilled
  on the KB row.
- A subsequent ingest whose dim doesn't match the bound dim raises
  ``EmbeddingDimensionMismatchError`` and the job is marked
  ``failed``; the vector store is NEVER written into in that case.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from deerflow.config.rag_config import RagConfig, set_rag_config
from deerflow.knowledge_base.indexing import IndexingService


def _make_doc(**overrides: Any) -> dict[str, Any]:
    base = {
        "id": "doc-1",
        "tenant_id": "tenant-a",
        "owner_user_id": "user-1",
        "title": "Doc",
        "content": "alpha beta gamma",
        "source_name": "doc.md",
        "version": 1,
        "chunk_ids": [],
    }
    base.update(overrides)
    return base


def _make_kb(**overrides: Any) -> dict[str, Any]:
    base = {
        "id": "kb-1",
        "tenant_id": "tenant-a",
        "name": "KB",
        "collection_name": "kb_abc",
        "embedding_model": "openai:text-embedding-3-small",
        "embedding_dim": 0,
    }
    base.update(overrides)
    return base


def _make_repos(*, doc_version: int = 1):
    kb_repo = MagicMock()
    kb_repo.update_embedding_binding = AsyncMock(return_value=True)
    kb_repo.get_by_id_internal = AsyncMock(
        return_value={"id": "kb-1", "name": "KB"}
    )
    kb_repo.update_stats = AsyncMock()

    doc_repo = MagicMock()
    doc_repo.update_index_status = AsyncMock()
    doc_repo.get_by_id_internal = AsyncMock(
        return_value={"id": "doc-1", "version": doc_version}
    )
    sf = MagicMock()
    doc_repo._sf = sf

    job_repo = MagicMock()
    job_repo.create = AsyncMock(return_value={"id": "job-1"})
    job_repo.update_status = AsyncMock()
    job_repo.get = AsyncMock(return_value={"id": "job-1", "status": "completed"})

    return kb_repo, doc_repo, job_repo


class TestKbBoundEmbedding:
    def teardown_method(self) -> None:
        set_rag_config(RagConfig())

    @pytest.mark.asyncio
    async def test_uses_kb_embedding_model_not_global(self) -> None:
        set_rag_config(
            RagConfig(
                enabled=True,
                embedding_model="openai:text-embedding-3-large",
            )
        )
        kb_repo, doc_repo, job_repo = _make_repos()
        service = IndexingService(kb_repo, doc_repo, job_repo)

        captured_spec: list[str | None] = []

        def fake_factory(spec: str | None = None):
            captured_spec.append(spec)
            embedder = MagicMock()
            embedder.embed.return_value = [[0.1] * 1536]
            embedder.dimension = 1536
            return embedder

        # Patch chroma stats query path that runs after a successful job.
        async def _fake_update_kb_stats(kb_id):
            return None

        with patch(
            "deerflow.rag.embeddings.get_embedding_provider",
            side_effect=fake_factory,
        ), patch(
            "deerflow.rag.ingestion.get_vector_store"
        ) as mock_store_factory, patch.object(
            service, "_update_kb_stats", side_effect=_fake_update_kb_stats
        ):
            mock_store = MagicMock()
            mock_store.add.return_value = ["c1"]
            mock_store_factory.return_value = mock_store

            kb = _make_kb(embedding_model="openai:text-embedding-3-small")
            doc = _make_doc()

            await service.execute_index_job(doc, kb)

        assert captured_spec == ["openai:text-embedding-3-small"], (
            "indexing must use KB row embedding, ignoring global default"
        )

    @pytest.mark.asyncio
    async def test_backfills_embedding_dim_on_first_ingest(self) -> None:
        set_rag_config(RagConfig(enabled=True))
        kb_repo, doc_repo, job_repo = _make_repos()
        service = IndexingService(kb_repo, doc_repo, job_repo)

        embedder = MagicMock()
        embedder.embed.return_value = [[0.2] * 1024, [0.3] * 1024]
        embedder.dimension = 1024

        async def _noop_stats(kb_id):
            return None

        with patch(
            "deerflow.rag.embeddings.get_embedding_provider",
            return_value=embedder,
        ), patch(
            "deerflow.rag.ingestion.get_vector_store"
        ) as mock_store_factory, patch(
            "deerflow.rag.chunking.RecursiveChunkStrategy.split"
        ) as mock_split, patch.object(
            service, "_update_kb_stats", side_effect=_noop_stats
        ):
            from deerflow.rag.chunking import Chunk

            mock_split.return_value = [
                Chunk(content="a", metadata={}),
                Chunk(content="b", metadata={}),
            ]
            mock_store = MagicMock()
            mock_store.add.return_value = ["c1", "c2"]
            mock_store_factory.return_value = mock_store

            kb = _make_kb(embedding_dim=0)
            await service.execute_index_job(_make_doc(), kb)

        kb_repo.update_embedding_binding.assert_awaited_once_with(
            "kb-1", embedding_dim=1024
        )

    @pytest.mark.asyncio
    async def test_skips_backfill_when_dim_already_bound(self) -> None:
        set_rag_config(RagConfig(enabled=True))
        kb_repo, doc_repo, job_repo = _make_repos()
        service = IndexingService(kb_repo, doc_repo, job_repo)

        embedder = MagicMock()
        embedder.embed.return_value = [[0.5] * 1536]
        embedder.dimension = 1536

        async def _noop_stats(kb_id):
            return None

        with patch(
            "deerflow.rag.embeddings.get_embedding_provider",
            return_value=embedder,
        ), patch(
            "deerflow.rag.ingestion.get_vector_store"
        ) as mock_store_factory, patch(
            "deerflow.rag.chunking.RecursiveChunkStrategy.split"
        ) as mock_split, patch.object(
            service, "_update_kb_stats", side_effect=_noop_stats
        ):
            from deerflow.rag.chunking import Chunk

            mock_split.return_value = [Chunk(content="a", metadata={})]
            mock_store = MagicMock()
            mock_store.add.return_value = ["c1"]
            mock_store_factory.return_value = mock_store

            kb = _make_kb(embedding_dim=1536)
            await service.execute_index_job(_make_doc(), kb)

        kb_repo.update_embedding_binding.assert_not_awaited()


class TestDimMismatchRaises:
    def teardown_method(self) -> None:
        set_rag_config(RagConfig())

    @pytest.mark.asyncio
    async def test_dim_mismatch_marks_job_failed_without_writing_store(self) -> None:
        set_rag_config(RagConfig(enabled=True))
        kb_repo, doc_repo, job_repo = _make_repos()
        service = IndexingService(kb_repo, doc_repo, job_repo)

        embedder = MagicMock()
        embedder.embed.return_value = [[0.1] * 1024]  # actual=1024
        embedder.dimension = 1024

        with patch(
            "deerflow.rag.embeddings.get_embedding_provider",
            return_value=embedder,
        ), patch(
            "deerflow.rag.ingestion.get_vector_store"
        ) as mock_store_factory, patch(
            "deerflow.rag.chunking.RecursiveChunkStrategy.split"
        ) as mock_split:
            from deerflow.rag.chunking import Chunk

            mock_split.return_value = [Chunk(content="a", metadata={})]
            mock_store = MagicMock()
            mock_store_factory.return_value = mock_store

            kb = _make_kb(embedding_dim=1536)  # bound=1536, actual=1024
            await service.execute_index_job(_make_doc(), kb)

            # Vector store add MUST NOT be called — the dim guard runs
            # before the write.
            mock_store.add.assert_not_called()

        # Doc + job marked failed with a recognizable error string.
        failed_calls = [
            call
            for call in doc_repo.update_index_status.await_args_list
            if call.kwargs.get("index_status") == "failed"
        ]
        assert failed_calls
        assert any(
            "1536" in str(call.kwargs.get("index_error", ""))
            for call in failed_calls
        )
        failed_job_calls = [
            call
            for call in job_repo.update_status.await_args_list
            if call.kwargs.get("status") == "failed"
        ]
        assert failed_job_calls
