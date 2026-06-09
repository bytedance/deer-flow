import asyncio
import json
import logging

from langchain.tools import tool

from deerflow.config import get_app_config
from deerflow.utils.readability import ReadabilityExtractor

from .searxng_client import SearxngClient

logger = logging.getLogger(__name__)

# readability_extractor runs CPU-bound parsing; always call via asyncio.to_thread
_readability_extractor = ReadabilityExtractor()


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


@tool("web_fetch", parse_docstring=True)
async def web_fetch_tool(url: str) -> str:
    """Fetch the contents of a web page at a given URL.
    Only fetch EXACT URLs that have been provided directly by the user or have been returned in results from the web_search and web_fetch tools.
    This tool can NOT access content that requires authentication, such as private Google Docs or pages behind login walls.
    Do NOT add www. to URLs that do NOT have them.
    URLs must include the schema: https://example.com is a valid URL while example.com is an invalid URL.

    Args:
        url: The URL to fetch the contents of.
    """
    try:
        cfg = _get_tool_config("web_fetch")
        timeout_s = 30
        if cfg is not None:
            raw = cfg.get("timeout_s", timeout_s)
            timeout_s = float(raw) if not isinstance(raw, float) else raw

        import httpx
        async with httpx.AsyncClient(timeout=timeout_s, follow_redirects=True) as client:
            resp = await client.get(
                url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; DeerFlow/1.0)"},
            )
            resp.raise_for_status()
            html_content = resp.text

        if not html_content.strip():
            return "Error: Empty response"

        article = await asyncio.to_thread(_readability_extractor.extract_article, html_content)
        return article.to_markdown()[:4096]
    except Exception as e:
        logger.error(f"Error in web_fetch_tool: {e}")
        return f"Error: {str(e)}"
