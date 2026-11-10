"""
Web search tool powered by the Autom SERP API.

Autom returns live Google results as JSON. The same key covers Google Search
and Google News, so a research run can be pointed at recent coverage by
switching ``vertical`` in config.yaml. An API key is required. Sign up at
https://app.autom.dev and see https://docs.autom.dev for the endpoint reference.
"""

import json
import logging
import os

import httpx
from langchain.tools import tool

from deerflow.community.provider_credentials import redact_secret, resolve_api_key
from deerflow.community.search_max_results import coerce_max_results
from deerflow.community.search_time_range import SearchTimeRange
from deerflow.community.url_safety import safe_public_result_url
from deerflow.config import get_app_config

logger = logging.getLogger(__name__)

_AUTOM_BASE_URL = "https://api.autom.dev/v1/google"
_DEFAULT_MAX_RESULTS = 5
# Autom returns one Google results page (about 10 rows) per request, so the
# cap is applied client-side.
_AUTOM_MAX_RESULTS = 10
_DEFAULT_VERTICAL = "search"
# vertical -> URL path segment. Both verticals return rows under ``organic_results``.
_VERTICALS: dict[str, str] = {
    "search": "search",
    "news": "news",
}
_ROWS_KEY = "organic_results"
# Optional request parameters that are passed through from config.yaml as-is.
_PASSTHROUGH_PARAMS = ("gl", "hl", "location", "tbs")
# Google ``tbs`` values for the shared ``time_range`` contract; a call-level
# ``time_range`` wins over a ``tbs`` set in config.yaml.
_AUTOM_TBS_BY_TIME_RANGE: dict[SearchTimeRange, str] = {
    "day": "qdr:d",
    "week": "qdr:w",
    "month": "qdr:m",
    "year": "qdr:y",
}
_api_key_warned: set[str] = set()


def _get_api_key(tool_name: str = "web_search") -> str | None:
    config = get_app_config().get_tool_config(tool_name)
    if config is not None:
        api_key = resolve_api_key((config.model_extra or {}).get("api_key"))
        if api_key:
            return api_key
    return resolve_api_key(os.getenv("AUTOM_API_KEY"))


def _count_for_request(value: object) -> int:
    """Coerce ``max_results`` via the shared owner, then apply Autom's page size.

    ``deerflow.community.search_max_results.coerce_max_results`` owns what
    "invalid" means; the cap of 10 stays here because clamping policy is
    per-provider.
    """
    return min(
        coerce_max_results(value, provider="Autom", logger=logger, default=_DEFAULT_MAX_RESULTS),
        _AUTOM_MAX_RESULTS,
    )


def _coerce_vertical(value: object) -> str:
    if value is None:
        return _DEFAULT_VERTICAL
    if isinstance(value, str) and value.strip().lower() in _VERTICALS:
        return value.strip().lower()
    logger.warning("Invalid Autom vertical=%r; using %r (one of %s)", value, _DEFAULT_VERTICAL, sorted(_VERTICALS))
    return _DEFAULT_VERTICAL


def _clean_query(query: str, *, max_length: int = 500) -> str:
    query = query.strip()
    if len(query) > max_length:
        query = query[:max_length]
    return query


def _missing_key_error(query: str, tool_name: str) -> str:
    if tool_name not in _api_key_warned:
        _api_key_warned.add(tool_name)
        logger.warning(
            "Autom API key is not set for '%s'. Set AUTOM_API_KEY in your environment or provide api_key in config.yaml. Sign up at https://app.autom.dev",
            tool_name,
        )
    return json.dumps({"error": "AUTOM_API_KEY is not configured", "query": query}, ensure_ascii=False)


def _unexpected_format_error(query: str) -> str:
    return json.dumps({"error": "Autom returned an unexpected response format", "query": query}, ensure_ascii=False)


def _response_rows(data: dict, query: str) -> tuple[list[dict], str | None]:
    """Return the object rows of ``organic_results``, or a format error.

    A missing or null container is an empty search (Autom omits the array when
    nothing matches). A container that is not a list, or a non-empty list
    holding no objects, is malformed and reported as a format error rather than
    "No results found". Non-object entries in an otherwise valid list are
    skipped in order so the valid rows survive.
    """
    rows = data.get(_ROWS_KEY)
    if rows is None:
        return [], None
    if not isinstance(rows, list):
        logger.error("Autom returned unexpected '%s' payload type: %s", _ROWS_KEY, type(rows).__name__)
        return [], _unexpected_format_error(query)
    usable = [row for row in rows if isinstance(row, dict)]
    if rows and not usable:
        logger.error("Autom returned '%s' with no usable result objects", _ROWS_KEY)
        return [], _unexpected_format_error(query)
    return usable, None


def _autom_get(path: str, api_key: str, query: str, params: dict[str, object]) -> tuple[dict | None, str | None]:
    """Send a GET request to an Autom Google endpoint.

    Returns a ``(data, error_json)`` tuple: on success ``data`` is the parsed
    JSON response and ``error_json`` is ``None``; on failure ``data`` is ``None``
    and ``error_json`` is a serialized structured error ready to return.
    """
    headers = {
        "x-api-key": api_key,
        "Accept": "application/json",
        "User-Agent": "deerflow",
    }
    try:
        with httpx.Client(timeout=60) as client:
            response = client.get(f"{_AUTOM_BASE_URL}/{path}", headers=headers, params=params)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            logger.error("Autom returned an unexpected payload type: %s", type(data).__name__)
            return None, _unexpected_format_error(query)
        return data, None
    except httpx.HTTPStatusError as e:
        resp_text = redact_secret((e.response.text or "")[:500], api_key)
        logger.error("Autom API returned HTTP %s: %s", e.response.status_code, resp_text)
        return None, json.dumps({"error": f"Autom API error: HTTP {e.response.status_code}", "query": query}, ensure_ascii=False)
    except Exception as e:
        message = redact_secret(str(e)[:500], api_key)
        logger.error("Autom request failed: %s: %s", type(e).__name__, message)
        return None, json.dumps({"error": message, "query": query}, ensure_ascii=False)


def _normalize_row(vertical: str, row: dict) -> dict:
    """Map one Autom row onto the common ``title``/``url``/``content`` shape.

    News rows also carry the publisher and a relative date.
    """
    result = {
        "title": row.get("title", ""),
        "url": safe_public_result_url(row.get("link")),
        "content": row.get("snippet", "") if isinstance(row.get("snippet"), str) else "",
    }
    if vertical == "news":
        result["source"] = row.get("source", "") if isinstance(row.get("source"), str) else ""
        result["published"] = row.get("date", "") if isinstance(row.get("date"), str) else ""
    return result


@tool("web_search", parse_docstring=True)
def web_search_tool(query: str, max_results: int = 5, time_range: SearchTimeRange | None = None) -> str:
    """Search the web for information using Google Search via Autom.

    Args:
        query: Search keywords describing what you want to find. Be specific for better results.
        max_results: Maximum number of search results to return. Default is 5, capped at 10.
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

    params: dict[str, object] = {"query": query}
    for key in _PASSTHROUGH_PARAMS:
        if key in extra:
            params[key] = extra[key]
    if time_range is not None:
        params["tbs"] = _AUTOM_TBS_BY_TIME_RANGE[time_range]

    data, error_json = _autom_get(_VERTICALS[vertical], api_key, query, params)
    if error_json is not None:
        return error_json

    rows, error_json = _response_rows(data, query)
    if error_json is not None:
        return error_json
    if not rows:
        return json.dumps({"error": "No results found", "query": query}, ensure_ascii=False)

    normalized_results = [_normalize_row(vertical, row) for row in rows[:max_results]]

    output = {
        "query": query,
        "total_results": len(normalized_results),
        "results": normalized_results,
    }
    return json.dumps(output, indent=2, ensure_ascii=False)
