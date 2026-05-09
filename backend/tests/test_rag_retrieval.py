"""Tests for RAG retrieval pipeline: rerank() and normalize_scores()."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from deerflow.rag.retrieval import normalize_scores, rerank
from deerflow.rag.vector_store import SearchResult


class TestRerank:
    def test_empty_input(self):
        result = rerank("test query", [])
        assert result == []

    def test_returns_sorted_by_cross_encoder_scores(self):
        mock_ce = MagicMock()
        mock_model = MagicMock()
        mock_ce.CrossEncoder.return_value = mock_model
        mock_model.predict.return_value = [0.2, 0.9, 0.5]

        with patch.dict(sys.modules, {"sentence_transformers": mock_ce}):
            results = [
                SearchResult(chunk_id="c1", content="low relevance", metadata={}, score=0.8),
                SearchResult(chunk_id="c2", content="high relevance", metadata={}, score=0.6),
                SearchResult(chunk_id="c3", content="mid relevance", metadata={}, score=0.7),
            ]

            reranked = rerank("test query", results)

            assert len(reranked) == 3
            assert reranked[0].chunk_id == "c2"
            assert reranked[0].score == pytest.approx(0.9)
            assert reranked[1].chunk_id == "c3"
            assert reranked[1].score == pytest.approx(0.5)
            assert reranked[2].chunk_id == "c1"
            assert reranked[2].score == pytest.approx(0.2)

            mock_ce.CrossEncoder.assert_called_once_with("cross-encoder/ms-marco-MiniLM-L-6-v2")
            mock_model.predict.assert_called_once()
            pairs = mock_model.predict.call_args[0][0]
            assert pairs == [
                ("test query", "low relevance"),
                ("test query", "high relevance"),
                ("test query", "mid relevance"),
            ]

    def test_import_error_fallback(self):
        with patch.dict(sys.modules, {"sentence_transformers": None}):
            results = [
                SearchResult(chunk_id="c1", content="text", metadata={}, score=0.9),
            ]
            reranked = rerank("query", results)
            assert reranked == results

    def test_exception_fallback(self):
        mock_ce = MagicMock()
        mock_model = MagicMock()
        mock_ce.CrossEncoder.return_value = mock_model
        mock_model.predict.side_effect = RuntimeError("model error")

        with patch.dict(sys.modules, {"sentence_transformers": mock_ce}):
            results = [
                SearchResult(chunk_id="c1", content="text", metadata={}, score=0.9),
            ]
            reranked = rerank("query", results)
            assert reranked == results

    def test_preserves_metadata(self):
        mock_ce = MagicMock()
        mock_model = MagicMock()
        mock_ce.CrossEncoder.return_value = mock_model
        mock_model.predict.return_value = [0.8]

        with patch.dict(sys.modules, {"sentence_transformers": mock_ce}):
            meta = {"kb_name": "Test KB", "title": "Doc 1"}
            results = [
                SearchResult(chunk_id="c1", content="hello", metadata=meta, score=0.5),
            ]
            reranked = rerank("query", results)
            assert reranked[0].metadata == meta
            assert reranked[0].content == "hello"
            assert reranked[0].chunk_id == "c1"


class TestNormalizeScores:
    def test_empty_input(self):
        result = normalize_scores([])
        assert result == []

    def test_single_result(self):
        results = [
            SearchResult(chunk_id="c1", content="text", metadata={}, score=0.75),
        ]
        normalized = normalize_scores(results)
        assert len(normalized) == 1
        assert normalized[0].score == 1.0

    def test_equal_scores(self):
        results = [
            SearchResult(chunk_id="c1", content="a", metadata={}, score=0.5),
            SearchResult(chunk_id="c2", content="b", metadata={}, score=0.5),
            SearchResult(chunk_id="c3", content="c", metadata={}, score=0.5),
        ]
        normalized = normalize_scores(results)
        assert all(r.score == 1.0 for r in normalized)

    def test_min_max_normalization(self):
        results = [
            SearchResult(chunk_id="c1", content="best", metadata={}, score=1.0),
            SearchResult(chunk_id="c2", content="mid", metadata={}, score=0.5),
            SearchResult(chunk_id="c3", content="worst", metadata={}, score=0.0),
        ]
        normalized = normalize_scores(results)
        assert normalized[0].score == pytest.approx(1.0)
        assert normalized[1].score == pytest.approx(0.5)
        assert normalized[2].score == pytest.approx(0.0)

    def test_arbitrary_range(self):
        results = [
            SearchResult(chunk_id="c1", content="a", metadata={}, score=0.8),
            SearchResult(chunk_id="c2", content="b", metadata={}, score=0.6),
            SearchResult(chunk_id="c3", content="c", metadata={}, score=0.4),
        ]
        normalized = normalize_scores(results)
        assert normalized[0].score == pytest.approx(1.0)
        assert normalized[1].score == pytest.approx(0.5)
        assert normalized[2].score == pytest.approx(0.0)

    def test_preserves_metadata_and_content(self):
        meta = {"kb_name": "KB1", "title": "Doc"}
        results = [
            SearchResult(chunk_id="c1", content="hello", metadata=meta, score=0.9),
            SearchResult(chunk_id="c2", content="world", metadata={"other": "val"}, score=0.1),
        ]
        normalized = normalize_scores(results)
        assert normalized[0].chunk_id == "c1"
        assert normalized[0].content == "hello"
        assert normalized[0].metadata == meta
        assert normalized[1].chunk_id == "c2"
        assert normalized[1].content == "world"

    def test_does_not_mutate_original(self):
        results = [
            SearchResult(chunk_id="c1", content="a", metadata={}, score=0.8),
            SearchResult(chunk_id="c2", content="b", metadata={}, score=0.2),
        ]
        normalized = normalize_scores(results)
        assert results[0].score == 0.8
        assert results[1].score == 0.2
        assert normalized[0].score == pytest.approx(1.0)
        assert normalized[1].score == pytest.approx(0.0)
