"""Tests for DocumentIngestor: chunk → embed → store pipeline.

Covers: ingest_text, ingest_file, ingest_directory, embedding dim mismatch guard,
error surfacing, metadata merging, and result field correctness.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from deerflow.rag.chunking import Chunk
from deerflow.rag.errors import EmbeddingDimensionMismatchError
from deerflow.rag.ingestion import DocumentIngestor, IngestionResult


def _mock_config(
    chunk_strategy: str = "recursive",
    chunk_size: int = 100,
    chunk_overlap: int = 20,
) -> MagicMock:
    cfg = MagicMock()
    cfg.chunk_strategy = chunk_strategy
    cfg.chunk_size = chunk_size
    cfg.chunk_overlap = chunk_overlap
    return cfg


def _mock_embedder(dim: int = 8) -> MagicMock:
    embedder = MagicMock()
    embedder.embed = MagicMock(side_effect=lambda texts: [[0.1] * dim for _ in texts])
    return embedder


def _mock_store(returned_ids: list[str] | None = None) -> MagicMock:
    store = MagicMock()
    store.add = MagicMock(return_value=returned_ids or ["id-1", "id-2"])
    return store


def _build_chunks(n: int, content_prefix: str = "chunk") -> list[Chunk]:
    return [Chunk(content=f"{content_prefix}-{i}", metadata={}, chunk_index=i) for i in range(n)]


# ---------------------------------------------------------------------------
# ingest_text — happy path
# ---------------------------------------------------------------------------


class TestIngestText:
    @patch("deerflow.rag.ingestion.get_vector_store")
    @patch("deerflow.rag.ingestion.get_chunk_strategy")
    @patch("deerflow.rag.ingestion.get_rag_config")
    def test_happy_path_returns_chunk_count(self, mock_cfg_fn, mock_chunk_fn, mock_store_fn):
        mock_cfg_fn.return_value = _mock_config()
        chunks = _build_chunks(3)
        mock_chunk_fn.return_value = MagicMock(split=MagicMock(return_value=chunks))
        store = _mock_store(returned_ids=["c1", "c2", "c3"])
        mock_store_fn.return_value = store
        embedder = _mock_embedder(dim=8)

        ingestor = DocumentIngestor(embedder=embedder)
        result = ingestor.ingest_text("some text", source_name="doc.txt", collection="test-col")

        assert result.collection == "test-col"
        assert result.source == "doc.txt"
        assert result.chunk_count == 3
        assert result.chunk_ids == ["c1", "c2", "c3"]
        assert result.embedding_dim == 8
        assert result.error is None

        embedder.embed.assert_called_once()
        store.add.assert_called_once()
        call_kwargs = store.add.call_args
        assert call_kwargs.kwargs["collection"] == "test-col"

    @patch("deerflow.rag.ingestion.get_vector_store")
    @patch("deerflow.rag.ingestion.get_chunk_strategy")
    @patch("deerflow.rag.ingestion.get_rag_config")
    def test_metadata_merged_with_source(self, mock_cfg_fn, mock_chunk_fn, mock_store_fn):
        mock_cfg_fn.return_value = _mock_config()
        chunks = _build_chunks(1)
        mock_strategy = MagicMock()
        mock_strategy.split = MagicMock(return_value=chunks)
        mock_chunk_fn.return_value = mock_strategy
        mock_store_fn.return_value = _mock_store()

        ingestor = DocumentIngestor(embedder=_mock_embedder())
        ingestor.ingest_text("text", source_name="f.txt", metadata={"kb_name": "KB1"})

        call_meta = mock_strategy.split.call_args[0][1]
        assert call_meta["source"] == "f.txt"
        assert call_meta["kb_name"] == "KB1"

    @patch("deerflow.rag.ingestion.get_vector_store")
    @patch("deerflow.rag.ingestion.get_chunk_strategy")
    @patch("deerflow.rag.ingestion.get_rag_config")
    def test_empty_chunks_returns_zero_count(self, mock_cfg_fn, mock_chunk_fn, mock_store_fn):
        mock_cfg_fn.return_value = _mock_config()
        mock_chunk_fn.return_value = MagicMock(split=MagicMock(return_value=[]))
        store = _mock_store()
        mock_store_fn.return_value = store

        ingestor = DocumentIngestor(embedder=_mock_embedder())
        result = ingestor.ingest_text("", source_name="empty.txt")

        assert result.chunk_count == 0
        assert result.chunk_ids == []
        store.add.assert_not_called()


# ---------------------------------------------------------------------------
# ingest_text — error paths
# ---------------------------------------------------------------------------


class TestIngestTextErrors:
    @patch("deerflow.rag.ingestion.get_vector_store")
    @patch("deerflow.rag.ingestion.get_chunk_strategy")
    @patch("deerflow.rag.ingestion.get_rag_config")
    def test_embedding_dim_mismatch_raises_before_store_write(self, mock_cfg_fn, mock_chunk_fn, mock_store_fn):
        mock_cfg_fn.return_value = _mock_config()
        chunks = _build_chunks(2)
        mock_chunk_fn.return_value = MagicMock(split=MagicMock(return_value=chunks))
        store = _mock_store()
        mock_store_fn.return_value = store

        ingestor = DocumentIngestor(embedder=_mock_embedder(dim=16), expected_dim=8)

        with pytest.raises(EmbeddingDimensionMismatchError) as exc_info:
            ingestor.ingest_text("text", source_name="doc.txt", collection="col-x")

        assert exc_info.value.expected == 8
        assert exc_info.value.actual == 16
        assert exc_info.value.collection == "col-x"
        store.add.assert_not_called()

    @patch("deerflow.rag.ingestion.get_vector_store")
    @patch("deerflow.rag.ingestion.get_chunk_strategy")
    @patch("deerflow.rag.ingestion.get_rag_config")
    def test_embedding_failure_returns_error(self, mock_cfg_fn, mock_chunk_fn, mock_store_fn):
        mock_cfg_fn.return_value = _mock_config()
        chunks = _build_chunks(1)
        mock_chunk_fn.return_value = MagicMock(split=MagicMock(return_value=chunks))
        embedder = MagicMock()
        embedder.embed = MagicMock(side_effect=RuntimeError("API unreachable"))
        mock_store_fn.return_value = _mock_store()

        ingestor = DocumentIngestor(embedder=embedder)
        result = ingestor.ingest_text("text", source_name="doc.txt")

        assert result.chunk_count == 0
        assert result.error is not None
        assert "API unreachable" in result.error

    @patch("deerflow.rag.ingestion.get_vector_store")
    @patch("deerflow.rag.ingestion.get_chunk_strategy")
    @patch("deerflow.rag.ingestion.get_rag_config")
    def test_vector_store_add_failure_returns_error(self, mock_cfg_fn, mock_chunk_fn, mock_store_fn):
        mock_cfg_fn.return_value = _mock_config()
        chunks = _build_chunks(1)
        mock_chunk_fn.return_value = MagicMock(split=MagicMock(return_value=chunks))
        store = MagicMock()
        store.add = MagicMock(side_effect=ConnectionError("Chroma down"))
        mock_store_fn.return_value = store

        ingestor = DocumentIngestor(embedder=_mock_embedder())
        result = ingestor.ingest_text("text", source_name="doc.txt")

        assert result.chunk_count == 0
        assert result.error is not None
        assert "Chroma down" in result.error


# ---------------------------------------------------------------------------
# ingest_file
# ---------------------------------------------------------------------------


class TestIngestFile:
    @patch("deerflow.rag.ingestion.get_vector_store")
    @patch("deerflow.rag.ingestion.get_chunk_strategy")
    @patch("deerflow.rag.ingestion.get_rag_config")
    def test_reads_utf8_file_and_ingests(self, mock_cfg_fn, mock_chunk_fn, mock_store_fn, tmp_path: Path):
        mock_cfg_fn.return_value = _mock_config()
        chunks = _build_chunks(2)
        mock_chunk_fn.return_value = MagicMock(split=MagicMock(return_value=chunks))
        mock_store_fn.return_value = _mock_store(returned_ids=["f1", "f2"])

        doc = tmp_path / "readme.md"
        doc.write_text("Hello world content", encoding="utf-8")

        ingestor = DocumentIngestor(embedder=_mock_embedder())
        result = ingestor.ingest_file(doc, collection="file-col")

        assert result.source == "readme.md"
        assert result.chunk_count == 2
        assert result.error is None

    @patch("deerflow.rag.ingestion.get_vector_store")
    @patch("deerflow.rag.ingestion.get_chunk_strategy")
    @patch("deerflow.rag.ingestion.get_rag_config")
    def test_file_not_found(self, mock_cfg_fn, mock_chunk_fn, mock_store_fn, tmp_path: Path):
        mock_cfg_fn.return_value = _mock_config()
        mock_chunk_fn.return_value = MagicMock()
        mock_store_fn.return_value = _mock_store()

        ingestor = DocumentIngestor(embedder=_mock_embedder())
        result = ingestor.ingest_file(tmp_path / "nonexistent.txt")

        assert result.chunk_count == 0
        assert result.error == "File not found"

    @patch("deerflow.rag.ingestion.get_vector_store")
    @patch("deerflow.rag.ingestion.get_chunk_strategy")
    @patch("deerflow.rag.ingestion.get_rag_config")
    def test_non_utf8_file_returns_error(self, mock_cfg_fn, mock_chunk_fn, mock_store_fn, tmp_path: Path):
        mock_cfg_fn.return_value = _mock_config()
        mock_chunk_fn.return_value = MagicMock()
        mock_store_fn.return_value = _mock_store()

        binary = tmp_path / "image.bin"
        binary.write_bytes(bytes(range(256)))

        ingestor = DocumentIngestor(embedder=_mock_embedder())
        result = ingestor.ingest_file(binary)

        assert result.chunk_count == 0
        assert result.error is not None


# ---------------------------------------------------------------------------
# ingest_directory
# ---------------------------------------------------------------------------


class TestIngestDirectory:
    @patch("deerflow.rag.ingestion.get_vector_store")
    @patch("deerflow.rag.ingestion.get_chunk_strategy")
    @patch("deerflow.rag.ingestion.get_rag_config")
    def test_ingests_matching_files(self, mock_cfg_fn, mock_chunk_fn, mock_store_fn, tmp_path: Path):
        mock_cfg_fn.return_value = _mock_config()
        chunks = _build_chunks(1)
        mock_chunk_fn.return_value = MagicMock(split=MagicMock(return_value=chunks))
        mock_store_fn.return_value = _mock_store(returned_ids=["d1"])

        (tmp_path / "a.md").write_text("alpha", encoding="utf-8")
        (tmp_path / "b.md").write_text("beta", encoding="utf-8")
        (tmp_path / "c.txt").write_text("gamma", encoding="utf-8")

        ingestor = DocumentIngestor(embedder=_mock_embedder())
        results = ingestor.ingest_directory(tmp_path, glob_pattern="*.md")

        assert len(results) == 2
        sources = {r.source for r in results}
        assert sources == {"a.md", "b.md"}

    @patch("deerflow.rag.ingestion.get_vector_store")
    @patch("deerflow.rag.ingestion.get_chunk_strategy")
    @patch("deerflow.rag.ingestion.get_rag_config")
    def test_not_a_directory(self, mock_cfg_fn, mock_chunk_fn, mock_store_fn, tmp_path: Path):
        mock_cfg_fn.return_value = _mock_config()
        mock_store_fn.return_value = _mock_store()

        file_path = tmp_path / "file.txt"
        file_path.write_text("not a dir", encoding="utf-8")

        ingestor = DocumentIngestor(embedder=_mock_embedder())
        results = ingestor.ingest_directory(file_path)

        assert len(results) == 1
        assert results[0].chunk_count == 0
        assert results[0].error == "Not a directory"

    @patch("deerflow.rag.ingestion.get_vector_store")
    @patch("deerflow.rag.ingestion.get_chunk_strategy")
    @patch("deerflow.rag.ingestion.get_rag_config")
    def test_empty_directory_returns_empty_list(self, mock_cfg_fn, mock_chunk_fn, mock_store_fn, tmp_path: Path):
        mock_cfg_fn.return_value = _mock_config()
        mock_store_fn.return_value = _mock_store()

        ingestor = DocumentIngestor(embedder=_mock_embedder())
        results = ingestor.ingest_directory(tmp_path, glob_pattern="*.md")

        assert results == []


# ---------------------------------------------------------------------------
# IngestionResult dataclass
# ---------------------------------------------------------------------------


class TestIngestionResult:
    def test_defaults(self):
        r = IngestionResult(collection="c", source="s", chunk_count=0)
        assert r.chunk_ids == []
        assert r.embedding_dim == 0
        assert r.chunks_per_doc == 0
        assert r.error is None

    def test_fields_assignable(self):
        r = IngestionResult(
            collection="col",
            source="src",
            chunk_count=5,
            chunk_ids=["a", "b"],
            embedding_dim=1536,
        )
        assert r.collection == "col"
        assert r.chunk_count == 5
        assert r.embedding_dim == 1536


# ---------------------------------------------------------------------------
# Default embedder / vector store from config (no explicit args)
# ---------------------------------------------------------------------------


class TestDefaultDependencies:
    @patch("deerflow.rag.ingestion.get_vector_store")
    @patch("deerflow.rag.ingestion.get_embedding_provider")
    @patch("deerflow.rag.ingestion.get_chunk_strategy")
    @patch("deerflow.rag.ingestion.get_rag_config")
    def test_uses_factory_defaults_when_no_args(self, mock_cfg_fn, mock_chunk_fn, mock_embed_fn, mock_store_fn):
        mock_cfg_fn.return_value = _mock_config()
        mock_chunk_fn.return_value = MagicMock(split=MagicMock(return_value=_build_chunks(1)))
        mock_embed_fn.return_value = _mock_embedder()
        mock_store_fn.return_value = _mock_store()

        ingestor = DocumentIngestor()

        mock_embed_fn.assert_called_once()
        mock_store_fn.assert_called_once()
