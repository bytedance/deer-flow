"""Tests for DocumentRetriever: embed → search → rerank pipeline."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from deerflow.rag.retrieval import DocumentRetriever, RetrievalResult
from deerflow.rag.vector_store import SearchResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_embedder(query_vec: list[float] | None = None) -> MagicMock:
    """Mock embedder that returns a fixed vector for embed_query."""
    embedder = MagicMock()
    embedder.embed_query = MagicMock(return_value=query_vec or [0.1, 0.2, 0.3])
    return embedder


def _mock_store(results: list[SearchResult] | None = None) -> MagicMock:
    """Mock vector store that returns fixed search results."""
    store = MagicMock()
    store.search = MagicMock(return_value=results or [])
    return store


def _mock_config(top_k: int = 5, threshold: float = 0.0) -> MagicMock:
    cfg = MagicMock()
    cfg.retrieval_top_k = top_k
    cfg.score_threshold = threshold
    return cfg


# ---------------------------------------------------------------------------
# retrieve() — 正常流程
# ---------------------------------------------------------------------------


class TestRetrieveHappyPath:
    @patch("deerflow.rag.retrieval.get_rag_config")
    def test_retrieve_calls_embed_and_search(self, mock_cfg_fn):
        mock_cfg_fn.return_value = _mock_config(top_k=5, threshold=0.0)
        embedder = _mock_embedder(query_vec=[0.1, 0.2, 0.3])
        store = MagicMock()
        store.search = MagicMock(return_value=[
            SearchResult(chunk_id="c1", content="chunk 1", metadata={}, score=0.9),
            SearchResult(chunk_id="c2", content="chunk 2", metadata={}, score=0.8),
        ])

        retriever = DocumentRetriever(embedder=embedder)
        retriever._store = store

        result = retriever.retrieve("test query", collection="test-col", top_k=5)

        embedder.embed_query.assert_called_once_with("test query")
        store.search.assert_called_once_with(
            collection="test-col",
            query_embedding=[0.1, 0.2, 0.3],
            top_k=5,
            score_threshold=0.0,
        )
        assert result.query == "test query"
        assert result.collection == "test-col"
        assert len(result.results) == 2
        assert result.results[0].chunk_id == "c1"
        assert result.results[0].score == 0.9

    @patch("deerflow.rag.retrieval.get_rag_config")
    def test_retrieve_returns_empty_when_no_results(self, mock_cfg_fn):
        mock_cfg_fn.return_value = _mock_config()
        embedder = _mock_embedder()
        store = _mock_store(results=[])

        retriever = DocumentRetriever(embedder=embedder)
        retriever._store = store

        result = retriever.retrieve("no match query")

        assert result.results == []
        assert result.query == "no match query"

    @patch("deerflow.rag.retrieval.get_rag_config")
    def test_retrieve_preserves_metadata(self, mock_cfg_fn):
        mock_cfg_fn.return_value = _mock_config()
        embedder = _mock_embedder()
        meta = {"kb_name": "KB1", "title": "Doc 1", "source": "doc.pdf"}
        store = _mock_store(results=[
            SearchResult(chunk_id="c1", content="text", metadata=meta, score=0.85),
        ])

        retriever = DocumentRetriever(embedder=embedder)
        retriever._store = store

        result = retriever.retrieve("query")

        assert result.results[0].metadata == meta
        assert result.results[0].metadata["kb_name"] == "KB1"


# ---------------------------------------------------------------------------
# retrieve() — 配置与参数
# ---------------------------------------------------------------------------


class TestRetrieveConfig:
    @patch("deerflow.rag.retrieval.get_rag_config")
    def test_retrieve_uses_config_defaults(self, mock_cfg_fn):
        mock_cfg_fn.return_value = _mock_config(top_k=10, threshold=0.5)
        embedder = _mock_embedder()
        store = _mock_store()

        retriever = DocumentRetriever(embedder=embedder)
        retriever._store = store

        retriever.retrieve("query", collection="col")

        store.search.assert_called_once_with(
            collection="col",
            query_embedding=[0.1, 0.2, 0.3],
            top_k=10,
            score_threshold=0.5,
        )

    @patch("deerflow.rag.retrieval.get_rag_config")
    def test_retrieve_explicit_top_k_overrides_config(self, mock_cfg_fn):
        mock_cfg_fn.return_value = _mock_config(top_k=10)
        embedder = _mock_embedder()
        store = _mock_store()

        retriever = DocumentRetriever(embedder=embedder)
        retriever._store = store

        retriever.retrieve("query", top_k=3)

        call_kwargs = store.search.call_args.kwargs
        assert call_kwargs["top_k"] == 3

    @patch("deerflow.rag.retrieval.get_rag_config")
    def test_retrieve_explicit_threshold_overrides_config(self, mock_cfg_fn):
        mock_cfg_fn.return_value = _mock_config(threshold=0.0)
        embedder = _mock_embedder()
        store = _mock_store()

        retriever = DocumentRetriever(embedder=embedder)
        retriever._store = store

        retriever.retrieve("query", score_threshold=0.7)

        call_kwargs = store.search.call_args.kwargs
        assert call_kwargs["score_threshold"] == 0.7


# ---------------------------------------------------------------------------
# retrieve() — 异常处理
# ---------------------------------------------------------------------------


class TestRetrieveErrors:
    @patch("deerflow.rag.retrieval.get_rag_config")
    def test_retrieve_embed_failure_returns_empty(self, mock_cfg_fn):
        mock_cfg_fn.return_value = _mock_config()
        embedder = MagicMock()
        embedder.embed_query = MagicMock(side_effect=RuntimeError("Embed API down"))
        store = _mock_store()

        retriever = DocumentRetriever(embedder=embedder)
        retriever._store = store

        result = retriever.retrieve("query")

        assert result.results == []
        assert result.query == "query"
        store.search.assert_not_called()

    @patch("deerflow.rag.retrieval.get_rag_config")
    def test_retrieve_store_failure_returns_empty(self, mock_cfg_fn):
        mock_cfg_fn.return_value = _mock_config()
        embedder = _mock_embedder()
        store = MagicMock()
        store.search = MagicMock(side_effect=ConnectionError("Chroma unreachable"))

        retriever = DocumentRetriever(embedder=embedder)
        retriever._store = store

        result = retriever.retrieve("query")

        assert result.results == []
        assert result.query == "query"


# ---------------------------------------------------------------------------
# Embedder 绑定
# ---------------------------------------------------------------------------


class TestEmbedderBinding:
    @patch("deerflow.rag.retrieval.get_embedding_provider")
    @patch("deerflow.rag.retrieval.get_vector_store")
    @patch("deerflow.rag.retrieval.get_rag_config")
    def test_retriever_uses_default_embedder_when_none(self, mock_cfg_fn, mock_store_fn, mock_embed_fn):
        mock_cfg_fn.return_value = _mock_config()
        mock_store_fn.return_value = _mock_store()
        default_embedder = _mock_embedder(query_vec=[0.5, 0.5])
        mock_embed_fn.return_value = default_embedder

        retriever = DocumentRetriever()

        mock_embed_fn.assert_called_once()
        assert retriever._embedder is default_embedder

    @patch("deerflow.rag.retrieval.get_embedding_provider")
    @patch("deerflow.rag.retrieval.get_vector_store")
    @patch("deerflow.rag.retrieval.get_rag_config")
    def test_retriever_uses_provided_embedder(self, mock_cfg_fn, mock_store_fn, mock_embed_fn):
        mock_cfg_fn.return_value = _mock_config()
        mock_store_fn.return_value = _mock_store()
        custom_embedder = _mock_embedder(query_vec=[0.9, 0.9])

        retriever = DocumentRetriever(embedder=custom_embedder)

        mock_embed_fn.assert_not_called()
        assert retriever._embedder is custom_embedder


# ---------------------------------------------------------------------------
# retrieve_with_rerank()
# ---------------------------------------------------------------------------


class TestRetrieveWithRerank:
    @patch("deerflow.rag.retrieval.rerank")
    @patch("deerflow.rag.retrieval.get_rag_config")
    def test_rerank_called_when_results_exist(self, mock_cfg_fn, mock_rerank_fn):
        mock_cfg_fn.return_value = _mock_config()
        embedder = _mock_embedder()
        initial_results = [
            SearchResult(chunk_id="c1", content="text 1", metadata={}, score=0.9),
            SearchResult(chunk_id="c2", content="text 2", metadata={}, score=0.7),
        ]
        reranked_results = [
            SearchResult(chunk_id="c2", content="text 2", metadata={}, score=0.95),
            SearchResult(chunk_id="c1", content="text 1", metadata={}, score=0.85),
        ]
        store = _mock_store(results=initial_results)
        mock_rerank_fn.return_value = reranked_results

        retriever = DocumentRetriever(embedder=embedder)
        retriever._store = store

        result = retriever.retrieve_with_rerank("query")

        mock_rerank_fn.assert_called_once_with("query", initial_results)
        assert result.results == reranked_results
        assert result.results[0].chunk_id == "c2"

    @patch("deerflow.rag.retrieval.rerank")
    @patch("deerflow.rag.retrieval.get_rag_config")
    def test_rerank_not_called_when_empty(self, mock_cfg_fn, mock_rerank_fn):
        mock_cfg_fn.return_value = _mock_config()
        embedder = _mock_embedder()
        store = _mock_store(results=[])

        retriever = DocumentRetriever(embedder=embedder)
        retriever._store = store

        result = retriever.retrieve_with_rerank("query")

        mock_rerank_fn.assert_not_called()
        assert result.results == []

    @patch("deerflow.rag.retrieval.rerank")
    @patch("deerflow.rag.retrieval.get_rag_config")
    def test_rerank_preserves_query_and_collection(self, mock_cfg_fn, mock_rerank_fn):
        mock_cfg_fn.return_value = _mock_config()
        embedder = _mock_embedder()
        store = _mock_store(results=[
            SearchResult(chunk_id="c1", content="text", metadata={}, score=0.8),
        ])
        mock_rerank_fn.return_value = store.search.return_value

        retriever = DocumentRetriever(embedder=embedder)
        retriever._store = store

        result = retriever.retrieve_with_rerank("my query", collection="my-col", top_k=3)

        assert result.query == "my query"
        assert result.collection == "my-col"


# ---------------------------------------------------------------------------
# RetrievalResult 数据类
# ---------------------------------------------------------------------------


class TestRetrievalResult:
    def test_defaults(self):
        r = RetrievalResult(query="test")
        assert r.results == []
        assert r.collection == "default"

    def test_all_fields(self):
        results = [SearchResult(chunk_id="c1", content="text", metadata={}, score=0.9)]
        r = RetrievalResult(query="test", results=results, collection="my-col")
        assert r.query == "test"
        assert r.results == results
        assert r.collection == "my-col"

    def test_mutable_results(self):
        r = RetrievalResult(query="test")
        r.results.append(SearchResult(chunk_id="c1", content="text", metadata={}, score=0.5))
        assert len(r.results) == 1
