"""Tests for vector store factory (get_vector_store) and SearchResult dataclass."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from deerflow.rag.vector_store import SearchResult, get_vector_store


class TestSearchResult:
    def test_defaults(self):
        r = SearchResult(chunk_id="c1", content="hello")
        assert r.metadata == {}
        assert r.score == 0.0

    def test_all_fields(self):
        meta = {"kb_name": "KB1"}
        r = SearchResult(chunk_id="c1", content="text", metadata=meta, score=0.95)
        assert r.chunk_id == "c1"
        assert r.content == "text"
        assert r.metadata is meta
        assert r.score == 0.95


class TestGetVectorStore:
    @patch("deerflow.rag.vector_store.get_rag_config")
    @patch("deerflow.rag.backends.chroma.chromadb", create=True)
    def test_chroma_backend(self, _mock_chromadb, mock_cfg):
        cfg = MagicMock()
        cfg.vector_store_backend = "chroma"
        cfg.chroma_persist_dir = "/tmp/chroma-test"
        mock_cfg.return_value = cfg

        store = get_vector_store()
        from deerflow.rag.backends.chroma import ChromaVectorStore

        assert isinstance(store, ChromaVectorStore)

    @patch("deerflow.rag.vector_store.get_rag_config")
    def test_unknown_backend_raises(self, mock_cfg):
        cfg = MagicMock()
        cfg.vector_store_backend = "redis"
        mock_cfg.return_value = cfg

        with pytest.raises(ValueError, match="Unknown vector store backend"):
            get_vector_store()
