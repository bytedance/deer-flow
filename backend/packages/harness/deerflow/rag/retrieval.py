"""Query retrieval pipeline for RAG."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from deerflow.config.rag_config import get_rag_config
from deerflow.rag.embeddings import get_embedding_provider
from deerflow.rag.vector_store import SearchResult, get_vector_store

logger = logging.getLogger(__name__)


@dataclass
class RetrievalResult:
    """Result of a retrieval operation."""

    query: str
    results: list[SearchResult] = field(default_factory=list)
    collection: str = "default"


class DocumentRetriever:
    """Orchestrates embed → search → optional rerank for document retrieval."""

    def __init__(self) -> None:
        self._embedder = get_embedding_provider()
        self._store = get_vector_store()

    def retrieve(
        self,
        query: str,
        collection: str = "default",
        top_k: int | None = None,
        score_threshold: float | None = None,
    ) -> RetrievalResult:
        """Retrieve relevant chunks for a query."""
        config = get_rag_config()
        k = top_k if top_k is not None else config.retrieval_top_k
        threshold = score_threshold if score_threshold is not None else config.score_threshold

        try:
            query_embedding = self._embedder.embed_query(query)
            results = self._store.search(
                collection=collection,
                query_embedding=query_embedding,
                top_k=k,
                score_threshold=threshold,
            )
            return RetrievalResult(query=query, results=results, collection=collection)
        except Exception as e:
            logger.error("Retrieval failed for query %r: %s", query, e)
            return RetrievalResult(query=query, collection=collection)

    def retrieve_with_rerank(
        self,
        query: str,
        collection: str = "default",
        top_k: int | None = None,
        score_threshold: float | None = None,
    ) -> RetrievalResult:
        """Retrieve and rerank using cross-encoder."""
        result = self.retrieve(query, collection, top_k, score_threshold)
        if not result.results:
            return result

        try:
            from sentence_transformers import CrossEncoder

            model = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
            pairs = [(query, r.content) for r in result.results]
            scores = model.predict(pairs)
            for i, r in enumerate(result.results):
                r.score = float(scores[i])
            result.results.sort(key=lambda r: r.score, reverse=True)
        except ImportError:
            logger.warning("sentence-transformers not available, skipping rerank")
        except Exception as e:
            logger.warning("Reranking failed: %s", e)

        return result
