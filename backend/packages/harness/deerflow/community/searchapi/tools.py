"""
Web search tool powered by SearchApi.

SearchApi returns live Google results as JSON. One API key covers the regular
web SERP plus the Google News and Google Scholar verticals, so a research run
can be pointed at recent coverage or at papers by switching ``vertical`` in
config.yaml. An API key is required. Sign up at https://www.searchapi.io and
see https://www.searchapi.io/docs/google for the endpoint reference.
"""

import json
import logging
import os

import httpx
from langchain.tools import tool

from deerflow.community.search_max_results import coerce_max_results
from deerflow.community.search_time_range import SearchTimeRange
from deerflow.community.url_safety import safe_public_result_url
from deerflow.config import get_app_config

logger = logging.getLogger(__name__)

_SEARCHAPI_ENDPOINT = "https://www.searchapi.io/api/v1/search"
_DEFAULT_MAX_RESULTS = 5
# Google serves at most 100 organic results per request; News and Scholar
# return fewer rows than asked for, so the caller's limit is also applied here.
_SEARCHAPI_MAX_RESULTS = 100
_DEFAULT_VERTICAL = "search"
# vertical -> SearchApi engine. Every engine answers with ``organic_results``.
_ENGINES: dict[str, str] = {
    "search": "google",
    "news": "google_news",
    "scholar": "google_scholar",
}
_RESULTS_KEY = "organic_results"
# Optional request parameters that are passed through from config.yaml as-is.
_PASSTHROUGH_PARAMS = ("gl", "hl")
_TIME_PERIOD_BY_TIME_RANGE: dict[SearchTimeRange, str] = {
    "day": "last_day",
    "week": "last_week",
    "month": "last_month",
    "year": "last_year",
}
_api_key_warned: set[str] = set()


def _get_api_key(tool_name: str = "web_search") -> str | None:
    config = get_app_config().get_tool_config(tool_name)
    if config is not None:
        api_key = (config.model_extra or {}).get("api_key")
        if isinstance(api_key, str) and api_key.strip():
            return api_key.strip()
    env_key = os.getenv("SEARCHAPI_API_KEY")
    if isinstance(env_key, str) and env_key.strip():
        return env_key.strip()
    return None


def _count_for_request(value: object) -> int:
    """Coerce ``max_results`` via the shared owner, then apply SearchApi's cap.

    ``deerflow.community.search_max_results.coerce_max_results`` owns what
    "invalid" means; the 1-100 cap stays here because clamping policy is
    deliberately per-provider.
    """
    return min(
        coerce_max_results(value, provider="SearchApi", logger=logger, default=_DEFAULT_MAX_RESULTS),
        _SEARCHAPI_MAX_RESULTS,
    )


def _coerce_vertical(value: object) -> str:
    if value is None:
        return _DEFAULT_VERTICAL
    if isinstance(value, str) and value.strip().lower() in _ENGINES:
        return value.strip().lower()
    logger.warning("Invalid SearchApi vertical=%r; using %r (one of %s)", value, _DEFAULT_VERTICAL, sorted(_ENGINES))
    return _DEFAULT_VERTICAL


def _clean_query(query: str, *, max_length: int = 500) -> str:
    query = query.strip()
    if len(query) > max_length:
        query = query[:max_length]
    return query


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


def _missing_key_error(query: str, tool_name: str) -> str:
    if tool_name not in _api_key_warned:
        _api_key_warned.add(tool_name)
        logger.warning(
            "SearchApi key is not set for '%s'. Set SEARCHAPI_API_KEY in your environment or provide api_key in config.yaml. Sign up at https://www.searchapi.io",
            tool_name,
        )
    return json.dumps({"error": "SEARCHAPI_API_KEY is not configured", "query": query}, ensure_ascii=False)


def _unexpected_format_error(query: str) -> str:
    return json.dumps({"error": "SearchApi returned an unexpected response format", "query": query}, ensure_ascii=False)


def _response_rows(data: dict, query: str) -> tuple[list[dict], str | None]:
    """Return the object rows of ``organic_results``, or a format error.

    A missing or null container is an empty search. A container that is not a
    list, or a non-empty list holding no objects, is malformed: the caller
    reports the provider's format error rather than "No results found", which
    would tell the agent the query legitimately matched nothing (the
    containment rule the sibling providers apply). Non-object entries in an
    otherwise valid list are skipped in order so the valid rows survive.
    """
    rows = data.get(_RESULTS_KEY)
    if rows is None:
        return [], None
    if not isinstance(rows, list):
        logger.error("SearchApi returned unexpected '%s' payload type: %s", _RESULTS_KEY, type(rows).__name__)
        return [], _unexpected_format_error(query)
    usable = [row for row in rows if isinstance(row, dict)]
    if rows and not usable:
        logger.error("SearchApi returned '%s' with no usable result objects", _RESULTS_KEY)
        return [], _unexpected_format_error(query)
    return usable, None


def _searchapi_get(api_key: str, query: str, params: dict[str, object]) -> tuple[dict | None, str | None]:
    """Send a GET request to the SearchApi endpoint.

    Returns a ``(data, error_json)`` tuple: on success ``data`` is the parsed
    JSON response and ``error_json`` is ``None``; on failure ``data`` is ``None``
    and ``error_json`` is a serialized structured error ready to return. The key
    travels in the Authorization header, never in the URL.
    """
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "User-Agent": "deerflow",
    }
    try:
        with httpx.Client(timeout=30) as client:
            response = client.get(_SEARCHAPI_ENDPOINT, headers=headers, params=params)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            logger.error("SearchApi returned an unexpected payload type: %s", type(data).__name__)
            return None, _unexpected_format_error(query)
        return data, None
    except httpx.HTTPStatusError as e:
        resp_text = (e.response.text or "")[:500]
        logger.error("SearchApi returned HTTP %s: %s", e.response.status_code, resp_text)
        return None, json.dumps({"error": f"SearchApi error: HTTP {e.response.status_code}", "query": query}, ensure_ascii=False)
    except Exception as e:
        logger.error("SearchApi request failed: %s: %s", type(e).__name__, str(e)[:500])
        return None, json.dumps({"error": str(e)[:500], "query": query}, ensure_ascii=False)


def _resource_url(value: object) -> str:
    """Screen a Scholar resource link; Google sometimes serves a ``javascript:`` stub glued to its host."""
    if not isinstance(value, str) or "javascript:" in value.lower():
        return ""
    return safe_public_result_url(value)


def _normalize_row(vertical: str, row: dict) -> dict:
    """Map one SearchApi row onto the common ``title``/``url``/``content`` shape.

    News and Scholar rows carry a few extra fields worth surfacing to the model.
    """
    result = {
        "title": _text(row.get("title")),
        "url": safe_public_result_url(row.get("link")),
        "content": _text(row.get("snippet")),
    }
    if vertical == "news":
        result["published"] = _text(row.get("iso_date")) or _text(row.get("date"))
        result["source"] = _text(row.get("source"))
    elif vertical == "scholar":
        authors = row.get("authors") if isinstance(row.get("authors"), list) else []
        result["authors"] = [_text(a.get("name")) for a in authors if isinstance(a, dict)]
        result["publication"] = _text(row.get("publication"))
        links = row.get("inline_links") if isinstance(row.get("inline_links"), dict) else {}
        cited_by = links.get("cited_by") if isinstance(links.get("cited_by"), dict) else {}
        total = cited_by.get("total")
        result["cited_by"] = total if isinstance(total, int) and not isinstance(total, bool) else 0
        resource = row.get("resource") if isinstance(row.get("resource"), dict) else {}
        result["pdf_url"] = _resource_url(resource.get("link"))
    return result


@tool("web_search", parse_docstring=True)
def web_search_tool(query: str, max_results: int = 5, time_range: SearchTimeRange | None = None) -> str:
    """Search the web for information using Google Search via SearchApi.

    Args:
        query: Search keywords describing what you want to find. Be specific for better results.
        max_results: Maximum number of search results to return. Default is 5, capped at 100.
        time_range: Optional relative publication/update window. Use only when the request requires recent results.
    """
    config = get_app_config().get_tool_config("web_search")
    extra = (config.model_extra or {}) if config is not None else {}
    if "max_results" in extra:
        max_results = extra["max_results"]
    max_results = _count_for_request(max_results)
    vertical = _coerce_vertical(extra.get("vertical"))
    query = _clean_query(query)

    api_key = _get_api_key("web_search")
    if not api_key:
        return _missing_key_error(query, "web_search")

    params: dict[str, object] = {"engine": _ENGINES[vertical], "q": query, "num": max_results}
    for key in _PASSTHROUGH_PARAMS:
        if key in extra:
            params[key] = extra[key]
    # Google Scholar has no relative time window on SearchApi; the other two engines take ``time_period``.
    if time_range is not None and vertical != "scholar":
        params["time_period"] = _TIME_PERIOD_BY_TIME_RANGE[time_range]

    data, error_json = _searchapi_get(api_key, query, params)
    if error_json is not None:
        return error_json

    rows, error_json = _response_rows(data, query)
    if error_json is not None:
        return error_json
    if not rows:
        return json.dumps({"error": "No results found", "query": query}, ensure_ascii=False)

    # ``num`` is a hint to Google: a page can carry more rows than asked for, so the cap is also applied here.
    normalized_results = [_normalize_row(vertical, row) for row in rows[:max_results]]

    output = {
        "query": query,
        "total_results": len(normalized_results),
        "results": normalized_results,
    }
    return json.dumps(output, indent=2, ensure_ascii=False)
