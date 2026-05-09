"""Query retrieval pipeline for RAG."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from deerflow.config.rag_config import get_rag_config
from deerflow.rag.embeddings import get_embedding_provider
from deerflow.rag.vector_store import SearchResult, get_vector_store

logger = logging.getLogger(__name__)


def rerank(query: str, results: list[SearchResult]) -> list[SearchResult]:
    """Rerank search results using a cross-encoder model.

    Returns a new list sorted by cross-encoder scores. Falls back to the
    original list (unchanged) if sentence-transformers is unavailable.
    """
    if not results:
        return results

    try:
        from sentence_transformers import CrossEncoder

        model = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
        pairs = [(query, r.content) for r in results]
        scores = model.predict(pairs)
        reranked = []
        for i, r in enumerate(results):
            reranked.append(SearchResult(
                chunk_id=r.chunk_id,
                content=r.content,
                metadata=r.metadata,
                score=float(scores[i]),
            ))
        reranked.sort(key=lambda r: r.score, reverse=True)
        return reranked
    except ImportError:
        logger.warning("sentence-transformers not available, skipping rerank")
        return results
    except Exception as e:
        logger.warning("Reranking failed: %s", e)
        return results


def normalize_scores(results: list[SearchResult]) -> list[SearchResult]:
    """Normalize scores to [0, 1] using min-max scaling.

    Returns a new list with normalized scores. If all scores are equal,
    all normalized scores are set to 1.0.
    """
    if not results:
        return results

    scores = [r.score for r in results]
    min_score = min(scores)
    max_score = max(scores)
    score_range = max_score - min_score

    normalized = []
    for r in results:
        if score_range == 0:
            norm_score = 1.0
        else:
            norm_score = (r.score - min_score) / score_range
        normalized.append(SearchResult(
            chunk_id=r.chunk_id,
            content=r.content,
            metadata=r.metadata,
            score=norm_score,
        ))
    return normalized


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

        result.results = rerank(query, result.results)
        return result
