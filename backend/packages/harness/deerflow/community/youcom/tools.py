"""
Web Search Tool - Search the web using You.com (free tier, no API key required).

You.com offers a keyless free tier (roughly 100 queries/day) and a keyed tier
with higher limits. The provider picks its endpoint by whether an API key is
configured:

- No key  -> ``https://api.you.com/v1/agents/search`` (free tier)
- Key set -> ``https://api.you.com/v1/search`` (``X-API-Key`` header)

The key is read from the tool config (``api_key``) or the ``YDC_API_KEY``
environment variable.
"""

import json
import logging
import os

import httpx
from langchain.tools import tool

from deerflow.config import get_app_config

logger = logging.getLogger(__name__)

_FREE_ENDPOINT = "https://api.you.com/v1/agents/search"
_KEYED_ENDPOINT = "https://api.you.com/v1/search"
_DEFAULT_MAX_RESULTS = 5


def _get_api_key() -> str | None:
    """Read the You.com API key from the tool config, then the environment."""
    config = get_app_config().get_tool_config("web_search")
    if config is not None:
        api_key = config.model_extra.get("api_key")
        if isinstance(api_key, str) and api_key.strip():
            return api_key.strip()
    env_key = os.getenv("YDC_API_KEY")
    if isinstance(env_key, str) and env_key.strip():
        return env_key.strip()
    return None


def _search(query: str, max_results: int, api_key: str | None) -> list[dict]:
    """Call the You.com search API and normalize results.

    The response shape is ``results.web[]`` (and ``results.news[]``), where each
    hit carries ``url`` / ``title`` / ``description`` plus one or more extracted
    page ``snippets``. Snippets give the agent usable context without a follow-up
    ``web_fetch``.
    """
    endpoint = _KEYED_ENDPOINT if api_key else _FREE_ENDPOINT
    headers = {"Accept": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key
    params = {"query": query, "count": max_results}
    try:
        with httpx.Client(timeout=30) as client:
            resp = client.get(endpoint, params=params, headers=headers)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.error(f"You.com search failed: {e}")
        return []

    normalized: list[dict] = []
    for section in ("web", "news"):
        for r in (data.get("results", {}).get(section) or []):
            url = r.get("url", "")
            if not url:
                continue
            title = r.get("title", "")
            description = r.get("description", "")
            snippets = r.get("snippets") or []
            content = "\n".join(snippets) if snippets else description
            normalized.append({"title": title, "url": url, "content": content})
    return normalized


@tool("web_search", parse_docstring=True)
def web_search_tool(query: str, max_results: int = _DEFAULT_MAX_RESULTS) -> str:
    """Search the web for information. Use this tool to find current information, news, articles, and facts from the internet.

    Args:
        query: Search keywords describing what you want to find. Be specific for better results.
        max_results: Maximum number of results to return. Default is 5.
    """
    config = get_app_config().get_tool_config("web_search")
    if config is not None:
        max_results = config.model_extra.get("max_results", max_results)

    api_key = _get_api_key()
    results = _search(query=query, max_results=max_results, api_key=api_key)

    if not results:
        return json.dumps({"error": "No results found", "query": query}, ensure_ascii=False)

    output = {
        "query": query,
        "total_results": len(results),
        "results": results,
    }
    return json.dumps(output, indent=2, ensure_ascii=False)
