"""RAG tools for agent integration."""

from __future__ import annotations

import json
import logging

from langchain_core.tools import tool

from deerflow.config.rag_config import get_rag_config
from deerflow.rag.retrieval import DocumentRetriever

logger = logging.getLogger(__name__)


@tool
def search_knowledge_base(query: str, collection: str = "default") -> str:
    """Search the knowledge base for information relevant to the query.

    Use this tool to find documents, facts, or context that may have been
    previously ingested into the vector store. Returns the most relevant
    text chunks with their similarity scores and source metadata.

    Args:
        query: The search query string.
        collection: The knowledge base collection to search (default: "default").

    Returns:
        JSON string with search results including content, scores, and sources.
    """
    config = get_rag_config()
    if not config.enabled:
        return json.dumps({"error": "RAG subsystem is not enabled", "results": []})

    try:
        retriever = DocumentRetriever()
        result = retriever.retrieve(
            query=query,
            collection=collection,
            top_k=config.retrieval_top_k,
            score_threshold=config.score_threshold,
        )

        formatted = [
            {
                "rank": i + 1,
                "content": r.content,
                "score": round(r.score, 4),
                "source": r.metadata.get("source", "unknown"),
            }
            for i, r in enumerate(result.results)
        ]

        return json.dumps({"query": query, "collection": collection, "results": formatted}, ensure_ascii=False)
    except Exception as e:
        logger.error("search_knowledge_base failed: %s", e)
        return json.dumps({"error": str(e), "results": []})
