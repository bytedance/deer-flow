"""
Web Search Tool - Search the web using Serper (Google Search API).

Serper provides real-time Google Search results via a JSON API.
An API key is required. Sign up at https://serper.dev to get one.
"""

import json
import logging
import os

import httpx
from langchain.tools import tool

from deerflow.config import get_app_config

logger = logging.getLogger(__name__)

_SERPER_ENDPOINT = "https://google.serper.dev/search"
_api_key_warned = False


def _get_api_key() -> str | None:
    config = get_app_config().get_tool_config("web_search")
    if config is not None:
        api_key = config.model_extra.get("api_key")
        if isinstance(api_key, str) and api_key.strip():
            return api_key
    return os.getenv("SERPER_API_KEY")


@tool("web_search", parse_docstring=True)
def web_search_tool(query: str, max_results: int = 5) -> str:
    """Search the web for information using Google Search via Serper.

    Args:
        query: Search keywords describing what you want to find. Be specific for better results.
        max_results: Maximum number of search results to return. Default is 5.
    """
    global _api_key_warned

    config = get_app_config().get_tool_config("web_search")
    if config is not None and "max_results" in config.model_extra:
        max_results = config.model_extra.get("max_results", max_results)

    api_key = _get_api_key()
    if not api_key:
        if not _api_key_warned:
            _api_key_warned = True
            logger.warning("Serper API key is not set. Set SERPER_API_KEY in your environment or provide api_key in config.yaml. Sign up at https://serper.dev")
        return json.dumps(
            {"error": "SERPER_API_KEY is not configured", "query": query},
            ensure_ascii=False,
        )

    headers = {
        "X-API-KEY": api_key,
        "Content-Type": "application/json",
    }
    payload = {"q": query, "num": max_results}

    try:
        with httpx.Client(timeout=30) as client:
            response = client.post(_SERPER_ENDPOINT, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
    except httpx.HTTPStatusError as e:
        logger.error(f"Serper API returned HTTP {e.response.status_code}: {e.response.text}")
        return json.dumps(
            {"error": f"Serper API error: HTTP {e.response.status_code}", "query": query},
            ensure_ascii=False,
        )
    except Exception as e:
        logger.error(f"Serper search failed: {type(e).__name__}: {e}")
        return json.dumps({"error": str(e), "query": query}, ensure_ascii=False)

    organic = data.get("organic", [])
    if not organic:
        return json.dumps({"error": "No results found", "query": query}, ensure_ascii=False)

    normalized_results = [
        {
            "title": r.get("title", ""),
            "url": r.get("link", ""),
            "content": r.get("snippet", ""),
        }
        for r in organic[:max_results]
    ]

    output = {
        "query": query,
        "total_results": len(normalized_results),
        "results": normalized_results,
    }
    return json.dumps(output, indent=2, ensure_ascii=False)
