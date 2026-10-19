"""Keenable community web search tool.

Keenable (https://keenable.ai) runs its own web index and exposes it as a
search API for AI agents: each hit carries the page title, URL, and an
extracted ``snippet`` of page text rather than a single meta description, so a
research loop gets usable context without a follow-up fetch.

The provider talks to two endpoints and picks between them by whether a key is
configured, so a research run works out of the box and scales up when the
operator adds a key:

* **No key**: ``POST /v1/search/public``, no auth header, rate limited per IP
  (currently 10 requests/second and 1000 requests/hour).
* **``KEENABLE_API_KEY`` set** (env var or the tool's ``api_key`` config):
  ``POST /v1/search`` with an ``X-API-Key`` header and higher limits.

Endpoint and headers are always chosen together, so a key is only ever sent to
the keyed endpoint. Every request carries ``X-Keenable-Title`` naming DeerFlow:
the keyless endpoint requires it (HTTP 400 without it), and it is sent only to
Keenable hosts.

Both endpoints return the same body, ``{"results": [...]}``, so one normalizer
covers both. ``web_search`` returns a JSON list of ``{title, url, snippet}``,
plus ``published_at`` when Keenable knows the publication date. Snippets can
run to several thousand characters, so each one is capped at 1500.

This module is self-contained (httpx only, no Keenable SDK and no new
dependency).
"""

import json
import logging
import os

import httpx
from langchain.tools import tool

from deerflow.community.search_max_results import coerce_max_results
from deerflow.config import get_app_config

logger = logging.getLogger(__name__)

# Keyed endpoint: higher limits, needs KEENABLE_API_KEY.
_KEENABLE_SEARCH_ENDPOINT = "https://api.keenable.ai/v1/search"
# Keyless endpoint: no auth header, rate limited per IP.
_KEENABLE_KEYLESS_ENDPOINT = "https://api.keenable.ai/v1/search/public"
# Identifies DeerFlow to Keenable. Required by the keyless endpoint.
_APP_TITLE = "deer-flow"
_DEFAULT_MAX_RESULTS = 5
# Keenable rejects `max_results` outside 1-50; clamp here so a larger value
# still returns results instead of an HTTP 400.
_MAX_RESULTS_CAP = 50
# Snippets are extracted page text and can run to several thousand characters.
# 1500 keeps a default five-result search under the 12000-character
# `tool_output.externalize_min_chars` default, so it stays inline.
_SNIPPET_MAX_CHARS = 1500
_TIMEOUT_S = 30.0
# Actionable hints for the failures an operator can actually fix. Any other
# status just reports its code.
_STATUS_HINTS = {
    401: "invalid or expired KEENABLE_API_KEY",
    429: "rate limit reached, set KEENABLE_API_KEY for higher limits",
}


def _get_api_key(tool_name: str = "web_search") -> str | None:
    """Resolve the Keenable key from the tool's config block, then the env var.

    Returns None when neither is set, which is not an error here: the caller
    falls back to the keyless endpoint.
    """
    config = get_app_config().get_tool_config(tool_name)
    if config is not None:
        api_key = (config.model_extra or {}).get("api_key")
        if isinstance(api_key, str) and api_key.strip():
            return api_key.strip()
    env_key = os.getenv("KEENABLE_API_KEY")
    if isinstance(env_key, str) and env_key.strip():
        return env_key.strip()
    return None


def _count_for_request(value: object) -> int:
    """Coerce ``max_results`` via the shared owner, then apply Keenable's cap.

    ``deerflow.community.search_max_results.coerce_max_results`` owns what
    "invalid" means (booleans, non-integral floats and ``OverflowError`` all
    fall back to the default); the 50-result cap stays here because clamping
    policy is deliberately per-provider.
    """
    return min(
        coerce_max_results(value, provider="Keenable", logger=logger, default=_DEFAULT_MAX_RESULTS),
        _MAX_RESULTS_CAP,
    )


def _search(api_key: str | None, query: str, count: int) -> dict:
    """POST to the keyed endpoint when a key is configured, else the keyless one."""
    headers = {"Accept": "application/json", "X-Keenable-Title": _APP_TITLE}
    if api_key:
        endpoint = _KEENABLE_SEARCH_ENDPOINT
        headers["X-API-Key"] = api_key
    else:
        endpoint = _KEENABLE_KEYLESS_ENDPOINT

    with httpx.Client(timeout=_TIMEOUT_S) as client:
        response = client.post(endpoint, json={"query": query, "max_results": count}, headers=headers)
    response.raise_for_status()
    return response.json()


def _response_results(data: dict) -> list[dict] | None:
    """Return the usable result objects, or None when the payload is malformed.

    A missing or null ``results`` is an empty search. A non-list container, or a
    non-empty list holding no objects, is malformed: the caller reports a format
    error rather than "No results found", which would tell the agent the query
    legitimately matched nothing. Non-object entries in an otherwise valid list
    are skipped in order.
    """
    results = data.get("results")
    if results is None:
        return []
    if not isinstance(results, list):
        logger.error("Keenable returned an unexpected 'results' payload type: %s", type(results).__name__)
        return None
    usable = [item for item in results if isinstance(item, dict)]
    if results and not usable:
        logger.error("Keenable returned 'results' with no usable result objects")
        return None
    return usable


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


def _snippet(result: dict) -> str:
    """Read the extracted ``snippet``, capped at ``_SNIPPET_MAX_CHARS``.

    ``description`` is only a fallback for a hit without a snippet.
    """
    snippet = _text(result.get("snippet")).strip() or _text(result.get("description")).strip()
    return snippet[:_SNIPPET_MAX_CHARS]


def _normalize(result: dict) -> dict:
    normalized = {
        "title": _text(result.get("title")),
        "url": _text(result.get("url")),
        "snippet": _snippet(result),
    }
    published_at = result.get("published_at")
    if isinstance(published_at, str) and published_at:
        normalized["published_at"] = published_at
    return normalized


@tool("web_search", parse_docstring=True)
def web_search_tool(query: str, max_results: int | None = None) -> str:
    """Search the web for information using Keenable.

    Each result carries an extracted snippet of the page text, not just a meta
    description, so the content is usable without fetching the page.

    Args:
        query: Search keywords describing what you want to find. Be specific for better results.
        max_results: Maximum number of search results to return. If omitted, uses the configured value (default 5). Capped at 50.
    """
    # Honor the caller-supplied max_results; fall back to config only when omitted.
    if max_results is None:
        config = get_app_config().get_tool_config("web_search")
        if config is not None:
            max_results = (config.model_extra or {}).get("max_results")
    count = _DEFAULT_MAX_RESULTS if max_results is None else _count_for_request(max_results)

    api_key = _get_api_key("web_search")

    try:
        data = _search(api_key, query, count)
    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        logger.error("Keenable API returned HTTP %s: %s", status, e.response.text)
        hint = _STATUS_HINTS.get(status)
        message = f"Keenable API error: HTTP {status}"
        if hint:
            message = f"{message} ({hint})"
        return json.dumps({"error": message, "query": query}, ensure_ascii=False)
    except Exception as e:
        logger.error("Keenable search failed: %s: %s", type(e).__name__, e)
        return json.dumps({"error": str(e), "query": query}, ensure_ascii=False)

    if not isinstance(data, dict):
        logger.error("Keenable returned an unexpected payload type: %s", type(data).__name__)
        return json.dumps(
            {"error": "Keenable returned an unexpected response format", "query": query},
            ensure_ascii=False,
        )

    results = _response_results(data)
    if results is None:
        return json.dumps(
            {"error": "Keenable returned an unexpected response format", "query": query},
            ensure_ascii=False,
        )
    if not results:
        return json.dumps({"error": "No results found", "query": query}, ensure_ascii=False)

    normalized_results = [_normalize(r) for r in results[:count]]
    return json.dumps(normalized_results, indent=2, ensure_ascii=False)
