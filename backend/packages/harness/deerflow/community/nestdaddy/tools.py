"""
Web search tool powered by NestDaddy.

NestDaddy is a search engine with its own crawler and index. Its Search & News
API returns ranked web results, with fresh news articles blended in for
current topics, as JSON. An API key is required. Sign up at
https://nestdaddy.com/serp-api to get one.
"""

import json
import logging
import os

import httpx
from langchain.tools import tool

from deerflow.community.provider_credentials import resolve_api_key
from deerflow.community.search_max_results import coerce_max_results
from deerflow.community.url_safety import safe_public_result_url
from deerflow.config import get_app_config

logger = logging.getLogger(__name__)

_NESTDADDY_SEARCH_ENDPOINT = "https://nestdaddy.com/api/v1/search"
# The API caps a single call at 50 results.
_NESTDADDY_MAX_RESULTS = 50
_NESTDADDY_MIN_QUERY_CHARS = 2
_NESTDADDY_MAX_QUERY_CHARS = 500
_NESTDADDY_TIMEOUT = 30
_api_key_warned: set[str] = set()


def _get_api_key(tool_name: str) -> str | None:
    config = get_app_config().get_tool_config(tool_name)
    configured = resolve_api_key(config.model_extra.get("api_key")) if config is not None else None
    return configured or resolve_api_key(os.getenv("NESTDADDY_API_KEY"))


def _missing_key_message(tool_name: str) -> str:
    if tool_name not in _api_key_warned:
        _api_key_warned.add(tool_name)
        logger.warning("NestDaddy API key is not set for '%s'. Set NESTDADDY_API_KEY in your environment or provide api_key in config.yaml. Sign up at https://nestdaddy.com/serp-api", tool_name)
    return "NESTDADDY_API_KEY is not configured"


def _nestdaddy_search(query: str, limit: int, api_key: str) -> tuple[dict | None, str | None]:
    """Call the NestDaddy search endpoint.

    Returns a ``(data, error)`` tuple: on success ``data`` is the decoded JSON
    object and ``error`` is ``None``; on failure ``data`` is ``None`` and
    ``error`` is a message the caller can hand back to the model.
    """
    try:
        with httpx.Client(timeout=_NESTDADDY_TIMEOUT) as client:
            response = client.get(
                _NESTDADDY_SEARCH_ENDPOINT,
                headers={"X-API-Key": api_key},
                params={"q": query, "limit": limit},
            )
        response.raise_for_status()
        body = response.json()
    except httpx.HTTPStatusError as e:
        # Status only: the response body may echo the query or other payload values.
        logger.error("NestDaddy API returned HTTP %s", e.response.status_code)
        return None, f"NestDaddy API error: HTTP {e.response.status_code}"
    except Exception as e:
        logger.error("NestDaddy request failed: %s", type(e).__name__)
        return None, f"NestDaddy request failed: {type(e).__name__}"

    if not isinstance(body, dict):
        logger.error("NestDaddy returned an unexpected payload type: %s", type(body).__name__)
        return None, "NestDaddy returned an unexpected response format"
    if body.get("success") is False:
        logger.error("NestDaddy reported an unsuccessful response")
        return None, "NestDaddy API error: the request was not successful"
    return body, None


def _response_results(data: dict) -> list[dict] | None:
    """Return the object entries of ``results``, or None if the container is malformed.

    A missing or null container is empty. A non-list container, or a non-empty
    list holding no objects, is malformed: the caller reports a format error
    rather than "No results found", which would tell the agent the query
    legitimately matched nothing.
    """
    value = data.get("results")
    if value is None:
        return []
    if not isinstance(value, list):
        logger.error("NestDaddy returned an unexpected 'results' payload type: %s", type(value).__name__)
        return None
    usable = [item for item in value if isinstance(item, dict)]
    if value and not usable:
        logger.error("NestDaddy returned 'results' with no usable result objects")
        return None
    return usable


@tool("web_search", parse_docstring=True)
def web_search_tool(query: str, max_results: int | None = None) -> str:
    """Search the web for information. Use this tool to find current information, news, articles, and facts from the internet.

    Args:
        query: Search keywords or a question describing what you want to find. Be specific for better results.
        max_results: Maximum number of results to return. If omitted, uses the configured value (default 5).
    """
    config = get_app_config().get_tool_config("web_search")
    config_extra = (config.model_extra or {}) if config is not None else {}
    # Honor the caller-supplied max_results; fall back to config only when omitted.
    if max_results is None:
        max_results = config_extra.get("max_results")
    max_results = min(coerce_max_results(max_results, provider="NestDaddy", logger=logger), _NESTDADDY_MAX_RESULTS)

    normalized_query = query.strip()[:_NESTDADDY_MAX_QUERY_CHARS]
    if len(normalized_query) < _NESTDADDY_MIN_QUERY_CHARS:
        return json.dumps(
            {"error": f"Query must contain at least {_NESTDADDY_MIN_QUERY_CHARS} characters after trimming whitespace", "query": query},
            ensure_ascii=False,
        )

    api_key = _get_api_key("web_search")
    if not api_key:
        return json.dumps({"error": _missing_key_message("web_search"), "query": query}, ensure_ascii=False)

    data, error = _nestdaddy_search(normalized_query, max_results, api_key)
    if error is not None:
        return json.dumps({"error": error, "query": query}, ensure_ascii=False)

    items = _response_results(data)
    if items is None:
        return json.dumps({"error": "NestDaddy returned an unexpected response format", "query": query}, ensure_ascii=False)
    if not items:
        return json.dumps({"error": "No results found", "query": query}, ensure_ascii=False)

    results = []
    for item in items[:max_results]:
        result = {
            "title": item.get("title") or "",
            "url": safe_public_result_url(item.get("url")),
            "snippet": item.get("snippet") or item.get("description") or "",
        }
        published = item.get("published_date") or item.get("published_timestamp")
        if published:
            result["published"] = published
        results.append(result)

    output = {"query": query, "total_results": len(results), "results": results}
    return json.dumps(output, indent=2, ensure_ascii=False)
