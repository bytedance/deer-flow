"""MCP server providing FAQ retrieval tools.

Run as a stdio MCP server:
    uv run python -m deerflow.mcp.faq_server

Required environment variables:
    RAGFLOW_BASE_URL    - RAGFlow API base URL (e.g., http://localhost:9380)
    RAGFLOW_API_KEY     - RAGFlow API key (Bearer token)
    FAQ_DATASET_IDS     - Comma-separated FAQ dataset IDs
"""

import json
import logging
import os

from mcp.server.fastmcp import FastMCP

from deerflow.faq import FaqQuery, FaqService

logger = logging.getLogger(__name__)


def _load_service() -> FaqService:
    base_url = os.environ.get("RAGFLOW_BASE_URL", "http://localhost:9380")
    api_key = os.environ.get("RAGFLOW_API_KEY", "")
    return FaqService(base_url=base_url, api_key=api_key)


def _get_dataset_ids() -> list[str]:
    raw = os.environ.get("FAQ_DATASET_IDS", "")
    ids = [s.strip() for s in raw.split(",") if s.strip()]
    if not ids:
        logger.warning("[FAQ MCP] FAQ_DATASET_IDS is empty")
    return ids


mcp = FastMCP(
    name="faq",
    instructions="FAQ retrieval tool. Use faq_search to check if a user question matches any FAQ entry. Returns best FAQ answer and all matching candidates.",
)


@mcp.tool()
def faq_search(
    question: str,
    context: str | None = None,
    top_k: int = 3,
    doc_ids: list[str] | None = None,
    use_kg: bool = False,
    keyword: bool = False,
) -> str:
    """Search FAQ knowledge base for matching answers.

    Args:
        question: The user question to search against FAQ entries.
        context: Optional context to enhance matching (e.g. current topic or scenario).
        top_k: Maximum number of candidate results to return (default: 3).
        doc_ids: Limit search to specific document IDs.
        use_kg: Use knowledge graph for search.
        keyword: Enable keyword search mode.

    Returns:
        JSON string with best FAQ answer, score, and all matching candidates.
    """
    logger.info("[FAQ MCP] faq_search: question='%s', context=%s, top_k=%d", question, context, top_k)

    dataset_ids = _get_dataset_ids()
    if not dataset_ids:
        return json.dumps({"error": "FAQ_DATASET_IDS not configured"}, ensure_ascii=False)

    if not question or not question.strip():
        return json.dumps({"error": "question must not be empty"}, ensure_ascii=False)

    service = _load_service()
    query = FaqQuery(
        question=question.strip(),
        dataset_ids=dataset_ids,
        context=context,
        top_k=top_k,
        doc_ids=doc_ids,
        use_kg=use_kg,
        keyword=keyword,
    )

    try:
        result = service.search(query)
        response = {
            "user_question": result.user_question,
            "best_faq": {
                "question": result.best_faq.question,
                "answer": result.best_faq.answer,
                "score": result.best_faq.score,
                "faq_id": result.best_faq.faq_id,
            } if result.best_faq else None,
            "all_matches": [
                {
                    "question": m.question,
                    "answer": m.answer,
                    "score": m.score,
                    "faq_id": m.faq_id,
                }
                for m in result.all_matches
            ],
            "metadata": result.metadata,
        }
        logger.info(
            "[FAQ MCP] faq_search: score=%s, matches=%d",
            result.best_faq.score if result.best_faq else "N/A",
            len(result.all_matches),
        )
        return json.dumps(response, ensure_ascii=False)

    except Exception as e:
        logger.exception("[FAQ MCP] faq_search failed")
        return json.dumps({"error": f"{type(e).__name__}: {e}"}, ensure_ascii=False)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=__import__("sys").stderr,
    )
    mcp.run(transport="stdio")
