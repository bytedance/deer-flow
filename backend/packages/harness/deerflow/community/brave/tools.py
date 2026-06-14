"""
Web Search Tool - Search the web using the Brave Search API.

Brave Search provides web results from an independent search index via a
REST API. An API key is required. Sign up at https://brave.com/search/api/
to get one.

Unlike the DuckDuckGo ``backend: brave`` option (which scrapes results via the
DDGS aggregator), this provider calls the official Brave Search API directly,
giving structured results, authenticated quota, and a documented SLA.
"""

import json
import logging
import os

import httpx
from langchain.tools import tool

from deerflow.config import get_app_config

logger = logging.getLogger(__name__)

_BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
_DEFAULT_MAX_RESULTS = 5
# Brave Search API caps the `count` parameter at 20 results per request.
_BRAVE_MAX_COUNT = 20
_api_key_warned = False


def _get_api_key() -> str | None:
    config = get_app_config().get_tool_config("web_search")
    if config is not None:
        api_key = (config.model_extra or {}).get("api_key")
        if isinstance(api_key, str) and api_key.strip():
            return api_key
    return os.getenv("BRAVE_SEARCH_API_KEY")


def _coerce_max_results(value: object, *, default: int = _DEFAULT_MAX_RESULTS) -> int:
    try:
        coerced = int(value)
    except (TypeError, ValueError):
        logger.warning(
            "Invalid Brave Search max_results=%r; using default %s",
            value,
            default,
        )
        coerced = default

    return max(1, min(coerced, _BRAVE_MAX_COUNT))


@tool("web_search", parse_docstring=True)
def web_search_tool(query: str, max_results: int = 5) -> str:
    """Search the web for information using Brave Search.

    Args:
        query: Search keywords describing what you want to find. Be specific for better results.
        max_results: Maximum number of search results to return. Default is 5.
    """
    global _api_key_warned

    config = get_app_config().get_tool_config("web_search")
    if config is not None and "max_results" in (config.model_extra or {}):
        max_results = config.model_extra["max_results"]

    count = _coerce_max_results(max_results)

    api_key = _get_api_key()
    if not api_key:
        if not _api_key_warned:
            _api_key_warned = True
            logger.warning("Brave Search API key is not set. Set BRAVE_SEARCH_API_KEY in your environment or provide api_key in config.yaml. Sign up at https://brave.com/search/api/")
        return json.dumps(
            {"error": "BRAVE_SEARCH_API_KEY is not configured", "query": query},
            ensure_ascii=False,
        )

    headers = {
        "X-Subscription-Token": api_key,
        "Accept": "application/json",
    }
    params = {"q": query, "count": count, "text_decorations": False}

    try:
        with httpx.Client(timeout=30) as client:
            response = client.get(_BRAVE_ENDPOINT, headers=headers, params=params)
        response.raise_for_status()
        data = response.json()
    except httpx.HTTPStatusError as e:
        logger.error(f"Brave Search API returned HTTP {e.response.status_code}: {e.response.text}")
        return json.dumps(
            {"error": f"Brave Search API error: HTTP {e.response.status_code}", "query": query},
            ensure_ascii=False,
        )
    except Exception as e:
        logger.error(f"Brave search failed: {type(e).__name__}: {e}")
        return json.dumps({"error": str(e), "query": query}, ensure_ascii=False)

    web_results = (data.get("web") or {}).get("results", [])
    if not web_results:
        return json.dumps({"error": "No results found", "query": query}, ensure_ascii=False)

    normalized_results = [
        {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "content": r.get("description", ""),
        }
        for r in web_results
    ]

    output = {
        "query": query,
        "total_results": len(normalized_results),
        "results": normalized_results,
    }
    return json.dumps(output, indent=2, ensure_ascii=False)
