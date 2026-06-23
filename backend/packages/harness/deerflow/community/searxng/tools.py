import json
import logging

from langchain.tools import tool

from deerflow.config import get_app_config

from .searxng_client import SearxngClient

logger = logging.getLogger(__name__)


def _get_tool_config(tool_name: str) -> dict | None:
    """Get tool config extras safely, returning None if not configured."""
    config = get_app_config().get_tool_config(tool_name)
    if config is None:
        return None
    extras = config.model_extra
    return extras if extras is not None else {}


def _get_searxng_client() -> SearxngClient:
    cfg = _get_tool_config("web_search")
    base_url = "http://localhost:8088"
    if cfg is not None:
        base_url = cfg.get("base_url", base_url)
    return SearxngClient(base_url=base_url)


@tool("web_search", parse_docstring=True)
async def web_search_tool(query: str) -> str:
    """Search the web using SearXNG.

    Args:
        query: The query to search for.
    """
    try:
        cfg = _get_tool_config("web_search")
        max_results = 5
        if cfg is not None:
            raw = cfg.get("max_results", max_results)
            max_results = int(raw) if not isinstance(raw, int) else raw

        client = _get_searxng_client()
        results = await client.search(query, max_results=max_results)

        normalized = [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": r.get("content", ""),
            }
            for r in results
        ]
        return json.dumps(normalized, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error in web_search_tool: {e}")
        return json.dumps({"error": str(e), "query": query}, ensure_ascii=False)
