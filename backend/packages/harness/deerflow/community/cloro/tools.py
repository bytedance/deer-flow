"""
Web search tool powered by cloro (Google Search API).

cloro returns live Google results as JSON: the organic results and the
"People also ask" questions. Optionally, it also returns the Google AI
Overview text with its sources. An API key is required. Get one at
https://dashboard.cloro.dev/api-keys?utm_source=deer-flow&utm_medium=byok and
see https://cloro.dev/docs/api-reference/endpoint/monitor-google?utm_source=deer-flow&utm_medium=byok
for the endpoint reference.
"""

import json
import logging
import os
from urllib.parse import urlparse

import httpx
from langchain.tools import tool

from deerflow.community.search_max_results import coerce_max_results
from deerflow.community.url_safety import safe_public_result_url
from deerflow.config import get_app_config

logger = logging.getLogger(__name__)

_CLORO_GOOGLE_ENDPOINT = "https://api.cloro.dev/v1/monitor/google"
# One Google results page holds about 10 organic results. More pages cost more
# credits, so the tool requests one page and caps the result count at 10.
_CLORO_MAX_RESULTS = 10
_CLORO_TIMEOUT = 60
_DEFAULT_COUNTRY = "US"
# The AI Overview goes into the agent context on every call, so clip it.
_AI_OVERVIEW_MAX_CHARS = 4096
_api_key_warned: set[str] = set()


def _get_api_key(tool_name: str = "web_search") -> str | None:
    config = get_app_config().get_tool_config(tool_name)
    if config is not None:
        api_key = (config.model_extra or {}).get("api_key")
        if isinstance(api_key, str) and api_key.strip():
            return api_key.strip()
    env_key = os.getenv("CLORO_API_KEY")
    if isinstance(env_key, str) and env_key.strip():
        return env_key.strip()
    return None


def _count_for_request(value: object) -> int:
    """Coerce ``max_results`` through the shared owner, then apply the one-page cap."""
    return min(coerce_max_results(value, provider="cloro", logger=logger), _CLORO_MAX_RESULTS)


def _resolve_country(value: object) -> str:
    if value is None:
        return _DEFAULT_COUNTRY
    if isinstance(value, str) and len(value.strip()) == 2 and value.strip().isalpha():
        return value.strip().upper()
    logger.warning("Invalid cloro country=%r; using %r (expected an ISO 3166-1 alpha-2 code)", value, _DEFAULT_COUNTRY)
    return _DEFAULT_COUNTRY


def _resolve_ai_overview(value: object) -> bool:
    if value is None or isinstance(value, bool):
        return value is True
    logger.warning("Invalid cloro ai_overview=%r; AI Overview stays off (expected true or false)", value)
    return False


def _clean_query(query: str, *, max_length: int = 500) -> str:
    query = query.strip()
    if len(query) > max_length:
        query = query[:max_length]
    return query


def _missing_key_error(query: str, tool_name: str) -> str:
    if tool_name not in _api_key_warned:
        _api_key_warned.add(tool_name)
        logger.warning(
            "cloro API key is not set for '%s'. Set CLORO_API_KEY in your environment or provide api_key in config.yaml. Get a key at https://dashboard.cloro.dev/api-keys?utm_source=deer-flow&utm_medium=byok",
            tool_name,
        )
    return json.dumps({"error": "CLORO_API_KEY is not configured", "query": query}, ensure_ascii=False)


def _unexpected_format_error(query: str) -> str:
    return json.dumps({"error": "cloro returned an unexpected response format", "query": query}, ensure_ascii=False)


def _result_url(value: object) -> str:
    """Return a public result URL, or "" for an empty link or a Google /goto redirect."""
    url = safe_public_result_url(value)
    if not url:
        return ""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.path.startswith("/goto") and (host == "google.com" or host.endswith(".google.com")):
        return ""
    return url


def _cloro_post(api_key: str, query: str, payload: dict[str, object]) -> tuple[dict | None, str | None]:
    """Send a POST request to the cloro Google endpoint.

    Returns a ``(result, error_json)`` tuple: on success ``result`` is the
    ``result`` object of the response and ``error_json`` is ``None``; on failure
    ``result`` is ``None`` and ``error_json`` is a serialized structured error.
    """
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": "deerflow",
    }
    try:
        with httpx.Client(timeout=_CLORO_TIMEOUT) as client:
            response = client.post(_CLORO_GOOGLE_ENDPOINT, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
    except httpx.HTTPStatusError as e:
        logger.error("cloro API returned HTTP %s: %s", e.response.status_code, (e.response.text or "")[:500])
        return None, json.dumps({"error": f"cloro API error: HTTP {e.response.status_code}", "query": query}, ensure_ascii=False)
    except Exception as e:
        logger.error("cloro request failed: %s: %s", type(e).__name__, str(e)[:500])
        return None, json.dumps({"error": str(e)[:500], "query": query}, ensure_ascii=False)

    if not isinstance(data, dict):
        logger.error("cloro returned an unexpected payload type: %s", type(data).__name__)
        return None, _unexpected_format_error(query)
    result = data.get("result")
    if not isinstance(result, dict):
        logger.error("cloro returned an unexpected 'result' payload type: %s", type(result).__name__)
        return None, _unexpected_format_error(query)
    return result, None


def _organic_rows(result: dict, query: str) -> tuple[list[dict], str | None]:
    """Return the object rows of ``organicResults``, or a format error.

    A missing or null container is an empty search. A container that is not a
    list, or a non-empty list holding no objects, is malformed: the caller
    reports the provider's format error rather than "No results found". This is
    the containment rule of the sibling providers (brave, serper, serply, sofya).
    """
    rows = result.get("organicResults")
    if rows is None:
        return [], None
    if not isinstance(rows, list):
        logger.error("cloro returned unexpected 'organicResults' payload type: %s", type(rows).__name__)
        return [], _unexpected_format_error(query)
    usable = [row for row in rows if isinstance(row, dict)]
    if rows and not usable:
        logger.error("cloro returned 'organicResults' with no usable result objects")
        return [], _unexpected_format_error(query)
    return usable, None


def _people_also_ask(result: dict) -> list[str]:
    items = result.get("peopleAlsoAsk")
    if not isinstance(items, list):
        return []
    questions = [item.get("question") for item in items if isinstance(item, dict)]
    return [q.strip() for q in questions if isinstance(q, str) and q.strip()]


def _ai_overview(result: dict) -> dict | None:
    overview = result.get("aioverview")
    if not isinstance(overview, dict):
        return None
    text = overview.get("text")
    if not isinstance(text, str) or not text.strip():
        return None
    sources = []
    for source in overview.get("sources") or []:
        if not isinstance(source, dict):
            continue
        url = _result_url(source.get("url"))
        if url:
            sources.append({"title": source.get("label", ""), "url": url})
    return {"text": text.strip()[:_AI_OVERVIEW_MAX_CHARS], "sources": sources}


@tool("web_search", parse_docstring=True)
def web_search_tool(query: str, max_results: int = 5) -> str:
    """Search the web for information using Google Search via cloro.

    Args:
        query: Search keywords describing what you want to find. Be specific for better results.
        max_results: Maximum number of search results to return. Default is 5, capped at 10.
    """
    config = get_app_config().get_tool_config("web_search")
    extra = (config.model_extra or {}) if config is not None else {}
    if "max_results" in extra:
        max_results = extra["max_results"]
    max_results = _count_for_request(max_results)
    country = _resolve_country(extra.get("country"))
    include_ai_overview = _resolve_ai_overview(extra.get("ai_overview"))
    query = _clean_query(query)

    api_key = _get_api_key("web_search")
    if not api_key:
        return _missing_key_error(query, "web_search")

    payload: dict[str, object] = {"query": query, "country": country}
    if include_ai_overview:
        payload["include"] = {"aioverview": True}

    result, error_json = _cloro_post(api_key, query, payload)
    if error_json is not None:
        return error_json

    rows, error_json = _organic_rows(result, query)
    if error_json is not None:
        return error_json

    normalized_results = []
    for row in rows:
        url = _result_url(row.get("link"))
        if not url:
            continue
        normalized_results.append({"title": row.get("title", ""), "url": url, "content": row.get("snippet", "")})
        if len(normalized_results) == max_results:
            break

    overview = _ai_overview(result) if include_ai_overview else None
    if not normalized_results and overview is None:
        return json.dumps({"error": "No results found", "query": query}, ensure_ascii=False)

    output: dict[str, object] = {
        "query": query,
        "total_results": len(normalized_results),
        "results": normalized_results,
    }
    questions = _people_also_ask(result)
    if questions:
        output["people_also_ask"] = questions
    if overview is not None:
        output["ai_overview"] = overview
    return json.dumps(output, indent=2, ensure_ascii=False)
