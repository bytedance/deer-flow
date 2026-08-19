"""You.com community web search tool.

You.com (https://you.com) runs its own web index and exposes it as an
LLM-oriented Search API: each hit carries the page title, URL, and a set of
extracted snippets rather than a single meta description, so a research loop
gets usable context without a follow-up fetch.

The provider talks to two endpoints and picks between them by whether a key is
configured, so a research run works out of the box and scales up when the
operator adds a key:

* **No key** — ``/v1/agents/search``, no auth header, free tier (currently 100
  searches/day). This is what a fresh ``make setup`` install gets.
* **``YDC_API_KEY`` set** (env var or the tool's ``api_key`` config) —
  ``/v1/search`` with an ``X-API-Key`` header: higher limits and the full
  Search API surface.

Endpoint and headers are always chosen together: the keyless endpoint rejects an
``X-API-Key`` header, so a stale key must never be sent there.

Both endpoints return the same body — ``{"results": {"web": [...], "news":
[...]}}`` — so one normalizer covers both. ``web_search`` returns a JSON list of
``{title, url, snippet}``.

This module is self-contained (httpx only, no You.com SDK and no new
dependency). Requests to You.com carry a ``User-Agent`` identifying DeerFlow so
You.com can attribute integration traffic; it is sent only to You.com hosts.
"""

import json
import logging
import os
from functools import cache
from importlib.metadata import PackageNotFoundError, version

import httpx
from langchain.tools import tool

from deerflow.config import get_app_config

logger = logging.getLogger(__name__)

# Keyed Search API: full surface, higher limits, needs YDC_API_KEY.
_YOUCOM_SEARCH_ENDPOINT = "https://api.you.com/v1/search"
# Keyless endpoint: no auth header, free tier. Sending a key here is rejected.
_YOUCOM_KEYLESS_ENDPOINT = "https://api.you.com/v1/agents/search"
_DEFAULT_MAX_RESULTS = 5
# You.com clamps `count` to 1-100 server-side; clamp here too to mirror it.
_MAX_RESULTS_CAP = 100
_TIMEOUT_S = 30.0
# Actionable hints for the two failures an operator can actually fix. Any other
# status just reports its code.
_STATUS_HINTS = {
    401: "invalid or expired YDC_API_KEY",
    402: "You.com credit balance depleted",
}


@cache
def _user_agent() -> str:
    """Identify DeerFlow to You.com. Only ever sent to You.com hosts."""
    try:
        harness_version = version("deerflow-harness")
    except PackageNotFoundError:  # pragma: no cover - source checkouts only
        harness_version = "unknown"
    return f"deerflow-harness/{harness_version} youdotcom-integration/bytedance-deer-flow"


def _get_api_key(tool_name: str = "web_search") -> str | None:
    """Resolve the You.com key from the tool's config block, then the env var.

    Returns None when neither is set, which is not an error here: the caller
    falls back to the keyless endpoint.
    """
    config = get_app_config().get_tool_config(tool_name)
    if config is not None:
        api_key = (config.model_extra or {}).get("api_key")
        if isinstance(api_key, str) and api_key.strip():
            return api_key.strip()
    env_key = os.getenv("YDC_API_KEY")
    if isinstance(env_key, str) and env_key.strip():
        return env_key.strip()
    return None


def _coerce_max_results(value: object, *, default: int = _DEFAULT_MAX_RESULTS) -> int:
    try:
        coerced = int(value)
    except (TypeError, ValueError):
        logger.warning("Invalid You.com max_results=%r; using default %s", value, default)
        coerced = default
    return max(1, min(coerced, _MAX_RESULTS_CAP))


def _search(api_key: str | None, query: str, count: int) -> dict:
    """GET the keyed endpoint when a key is configured, else the keyless one."""
    headers = {"Accept": "application/json", "User-Agent": _user_agent()}
    if api_key:
        endpoint = _YOUCOM_SEARCH_ENDPOINT
        headers["X-API-Key"] = api_key
    else:
        endpoint = _YOUCOM_KEYLESS_ENDPOINT

    with httpx.Client(timeout=_TIMEOUT_S) as client:
        response = client.get(endpoint, params={"query": query, "count": count}, headers=headers)
    response.raise_for_status()
    return response.json()


def _snippet(result: dict) -> str:
    """Prefer the extracted snippets; fall back to the meta description.

    Web hits carry `snippets`; news hits only carry `description`.
    """
    snippets = result.get("snippets")
    if isinstance(snippets, list):
        joined = "\n".join(s for s in snippets if isinstance(s, str) and s.strip())
        if joined:
            return joined
    description = result.get("description")
    return description if isinstance(description, str) else ""


@tool("web_search", parse_docstring=True)
def web_search_tool(query: str, max_results: int | None = None) -> str:
    """Search the web for information using You.com.

    Each result carries extracted snippets from the page, not just a meta
    description, so the content is usable without fetching the page.

    Args:
        query: Search keywords describing what you want to find. Be specific for better results.
        max_results: Maximum number of search results to return. If omitted, uses the configured value (default 5). Clamped to 1-100.
    """
    # Honor the caller-supplied max_results; fall back to config only when omitted.
    if max_results is None:
        config = get_app_config().get_tool_config("web_search")
        if config is not None:
            max_results = (config.model_extra or {}).get("max_results")
    count = _DEFAULT_MAX_RESULTS if max_results is None else _coerce_max_results(max_results)

    api_key = _get_api_key("web_search")

    try:
        data = _search(api_key, query, count)
    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        logger.error("You.com API returned HTTP %s: %s", status, e.response.text)
        hint = _STATUS_HINTS.get(status)
        message = f"You.com API error: HTTP {status}"
        if hint:
            message = f"{message} ({hint})"
        return json.dumps({"error": message, "query": query}, ensure_ascii=False)
    except Exception as e:
        logger.error("You.com search failed: %s: %s", type(e).__name__, e)
        return json.dumps({"error": str(e), "query": query}, ensure_ascii=False)

    if not isinstance(data, dict):
        logger.error("You.com returned an unexpected payload type: %s", type(data).__name__)
        return json.dumps(
            {"error": "You.com returned an unexpected response format", "query": query},
            ensure_ascii=False,
        )

    sections = data.get("results")
    if not isinstance(sections, dict):
        sections = {}
    # `count` applies per section, so web + news together can exceed it. Web
    # results lead; the merged list is trimmed back to what the caller asked for.
    results = [r for section in ("web", "news") for r in (sections.get(section) or []) if isinstance(r, dict)]
    if not results:
        return json.dumps({"error": "No results found", "query": query}, ensure_ascii=False)

    normalized_results = [
        {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "snippet": _snippet(r),
        }
        for r in results[:count]
    ]
    return json.dumps(normalized_results, indent=2, ensure_ascii=False)
