"""Async adapter for the Perplexity Search API.

Sends ``POST https://api.perplexity.ai/search`` with a Bearer key and returns
the same ``title`` / ``url`` / ``snippet`` list the Tavily and You.com
providers return, so switching ``use:`` needs no prompt changes.

Configuration (``config.yaml`` ``tools:`` entry, all optional except the key):

- ``api_key``: Perplexity API key; falls back to ``PERPLEXITY_API_KEY``.
- ``max_results``: default result count when the agent omits it (default 5,
  clamped to 1-20 by the API).
- ``search_type``: ``web`` (default) or ``fast``.
- ``search_domain_filter``: up to 20 domains; prefix with ``-`` to exclude.

Uses only ``httpx`` (already a core dependency). Each request carries
``X-Pplx-Integration: deer-flow`` and a ``User-Agent`` naming DeerFlow so the
traffic is attributable; both are only ever sent to ``api.perplexity.ai``.
Config resolution (which stats the config file) runs on an executor thread.
"""

import asyncio
import json
import logging
import os
from functools import cache
from importlib.metadata import PackageNotFoundError, version

import httpx
from langchain.tools import tool

from deerflow.community.search_max_results import coerce_max_results
from deerflow.community.search_time_range import SearchTimeRange
from deerflow.community.url_safety import safe_public_result_url
from deerflow.config import get_app_config

logger = logging.getLogger(__name__)

_PERPLEXITY_SEARCH_ENDPOINT = "https://api.perplexity.ai/search"
_INTEGRATION_HEADER = "deer-flow"
_DEFAULT_MAX_RESULTS = 5
# The Search API accepts 1-20 results per request for web and fast searches.
_MAX_RESULTS_CAP = 20
_MAX_DOMAIN_FILTERS = 20
_DEFAULT_SEARCH_TYPE = "web"
_SEARCH_TYPES = ("web", "fast")
_TIMEOUT_S = 30.0
# Actionable hints for the failures an operator can actually fix. Any other
# status just reports its code.
_STATUS_HINTS = {
    401: "invalid PERPLEXITY_API_KEY",
    422: "request rejected by the Perplexity Search API validation",
    429: "rate limit reached",
}


@cache
def _user_agent() -> str:
    """Identify DeerFlow to Perplexity. Only ever sent to api.perplexity.ai."""
    try:
        harness_version = version("deerflow-harness")
    except PackageNotFoundError:  # pragma: no cover - source checkouts only
        harness_version = "unknown"
    return f"deerflow-harness/{harness_version} deer-flow/bytedance-deer-flow"


def _resolve_tool_settings(tool_name: str) -> tuple[str | None, object, str, list[str]]:
    """Resolve the key, `max_results`, `search_type` and domain filter in one config read.

    Config resolution stats the config file, so callers must run this off the
    agent event loop. Reading every option from a single resolution keeps the
    tool from touching the config file twice per call.
    """
    config = get_app_config().get_tool_config(tool_name)
    max_results = None
    api_key = None
    search_type = _DEFAULT_SEARCH_TYPE
    domain_filter: list[str] = []
    if config is not None:
        extra = config.model_extra or {}
        max_results = extra.get("max_results")
        candidate = extra.get("api_key")
        if isinstance(candidate, str) and candidate.strip():
            api_key = candidate.strip()
        configured_type = extra.get("search_type")
        if isinstance(configured_type, str) and configured_type.strip().lower() in _SEARCH_TYPES:
            search_type = configured_type.strip().lower()
        elif configured_type is not None:
            logger.warning("Invalid Perplexity search_type=%r; using default %r", configured_type, _DEFAULT_SEARCH_TYPE)
        configured_domains = extra.get("search_domain_filter")
        if isinstance(configured_domains, list):
            domain_filter = [d.strip() for d in configured_domains if isinstance(d, str) and d.strip()]
            if len(domain_filter) > _MAX_DOMAIN_FILTERS:
                logger.warning("Perplexity search_domain_filter accepts at most %d entries; truncating", _MAX_DOMAIN_FILTERS)
                domain_filter = domain_filter[:_MAX_DOMAIN_FILTERS]
        elif configured_domains is not None:
            logger.warning("Invalid Perplexity search_domain_filter=%r; expected a list of domains", configured_domains)
    if api_key is None:
        env_key = os.getenv("PERPLEXITY_API_KEY")
        if isinstance(env_key, str) and env_key.strip():
            api_key = env_key.strip()
    return api_key, max_results, search_type, domain_filter


async def _resolve_user_agent() -> str:
    """Return the DeerFlow User-Agent, keeping the cold metadata read off the loop."""
    if _user_agent.cache_info().currsize:
        return _user_agent()
    return await asyncio.to_thread(_user_agent)


def _count_for_request(value: object) -> int:
    """Coerce ``max_results`` via the shared owner, then apply the API's 1-20 cap.

    ``deerflow.community.search_max_results.coerce_max_results`` owns what
    "invalid" means; the 20-result cap stays here because clamping policy is
    deliberately per-provider.
    """
    return min(
        coerce_max_results(value, provider="Perplexity", logger=logger, default=_DEFAULT_MAX_RESULTS),
        _MAX_RESULTS_CAP,
    )


async def _search(
    api_key: str,
    query: str,
    count: int,
    search_type: str,
    domain_filter: list[str],
    time_range: SearchTimeRange | None,
) -> dict:
    payload: dict = {"query": query, "max_results": count, "search_type": search_type}
    if domain_filter:
        payload["search_domain_filter"] = domain_filter
    if time_range:
        payload["search_recency_filter"] = time_range
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "User-Agent": await _resolve_user_agent(),
        "X-Pplx-Integration": _INTEGRATION_HEADER,
    }
    async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
        response = await client.post(_PERPLEXITY_SEARCH_ENDPOINT, json=payload, headers=headers)
    response.raise_for_status()
    return response.json()


@tool("web_search", parse_docstring=True)
async def web_search_tool(query: str, max_results: int | None = None, time_range: SearchTimeRange | None = None) -> str:
    """Search the web for information using the Perplexity Search API.

    Args:
        query: Search keywords describing what you want to find. Be specific for better results.
        max_results: Maximum number of search results to return. If omitted, uses the configured value (default 5). Clamped to 1-20.
        time_range: Optional relative publication/update window. Use only when the request requires recent results.
    """
    # Config resolution can read files; keep it off the event loop.
    api_key, configured_max_results, search_type, domain_filter = await asyncio.to_thread(_resolve_tool_settings, "web_search")
    if not api_key:
        return json.dumps(
            {"error": "Perplexity API key is missing; configure api_key or PERPLEXITY_API_KEY", "query": query},
            ensure_ascii=False,
        )
    # Honor the caller-supplied max_results; fall back to config only when omitted.
    if max_results is None:
        max_results = configured_max_results
    count = _DEFAULT_MAX_RESULTS if max_results is None else _count_for_request(max_results)

    try:
        data = await _search(api_key, query, count, search_type, domain_filter, time_range)
    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        logger.error("Perplexity Search API returned HTTP %s: %s", status, e.response.text)
        hint = _STATUS_HINTS.get(status)
        message = f"Perplexity Search API error: HTTP {status}"
        if hint:
            message = f"{message} ({hint})"
        return json.dumps({"error": message, "query": query}, ensure_ascii=False)
    except Exception as e:
        logger.error("Perplexity search failed: %s: %s", type(e).__name__, e)
        return json.dumps({"error": str(e), "query": query}, ensure_ascii=False)

    if not isinstance(data, dict):
        logger.error("Perplexity returned an unexpected payload type: %s", type(data).__name__)
        return json.dumps(
            {"error": "Perplexity returned an unexpected response format", "query": query},
            ensure_ascii=False,
        )

    raw_results = data.get("results")
    results = [r for r in raw_results if isinstance(r, dict)] if isinstance(raw_results, list) else []
    if not results:
        return json.dumps({"error": "No results found", "query": query}, ensure_ascii=False)

    normalized_results = [
        {
            "title": r.get("title", ""),
            "url": safe_public_result_url(r.get("url")),
            "snippet": r.get("snippet", "") if isinstance(r.get("snippet"), str) else "",
        }
        for r in results[:count]
    ]
    return json.dumps(normalized_results, indent=2, ensure_ascii=False)
