"""
Web Search Tool - Search the web using Serper (Google Search API).
"""

import json
import logging
import os

import httpx
from langchain.tools import tool

from deerflow.config import get_app_config

logger = logging.getLogger(__name__)

SERPER_ENDPOINT = "https://google.serper.dev/search"


def _get_api_key() -> str:
    config = get_app_config().get_tool_config("web_search")
    if config is not None and "api_key" in config.model_extra:
        return config.model_extra.get("api_key")
    return os.getenv("SERPER_API_KEY", "")


@tool("web_search", parse_docstring=True)
def web_search_tool(query: str) -> str:
    """Search the web for information using Google Search via Serper.

    Args:
        query: Search keywords describing what you want to find. Be specific for better results.
    """
    config = get_app_config().get_tool_config("web_search")
    max_results = 5
    if config is not None and "max_results" in config.model_extra:
        max_results = config.model_extra.get("max_results", max_results)

    api_key = _get_api_key()
    if not api_key:
        return json.dumps({"error": "SERPER_API_KEY is not set"}, ensure_ascii=False)

    headers = {
        "X-API-KEY": api_key,
        "Content-Type": "application/json",
    }
    payload = {"q": query, "num": max_results}

    try:
        with httpx.Client(timeout=30) as client:
            response = client.post(SERPER_ENDPOINT, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        logger.error(f"Serper search failed: {e}")
        return json.dumps({"error": str(e), "query": query}, ensure_ascii=False)

    organic = data.get("organic", [])
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
