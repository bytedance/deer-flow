"""
Web search tool powered by the Serply API.

Serply returns live Google results as JSON. One API key covers the regular
web SERP plus the Google News and Google Scholar verticals, so a research run
can be pointed at recent coverage or at papers by switching ``vertical`` in
config.yaml. An API key is required. Sign up at https://serply.io and see
https://serply.io/docs for the endpoint reference.
"""

import html
import json
import logging
import os
import re

import httpx
from langchain.tools import tool

from deerflow.config import get_app_config

logger = logging.getLogger(__name__)

_SERPLY_BASE_URL = "https://api.serply.io/v1"
_DEFAULT_MAX_RESULTS = 5
# Serply accepts ``num`` values from 1 to 100 per request.
_SERPLY_MAX_RESULTS = 100
_DEFAULT_VERTICAL = "search"
# vertical -> (URL path segment, response key that holds the result rows)
_VERTICALS: dict[str, tuple[str, str]] = {
    "search": ("search", "results"),
    "news": ("news", "entries"),
    "scholar": ("scholar", "articles"),
}
# Optional request parameters that are passed through from config.yaml as-is.
_PASSTHROUGH_PARAMS = ("gl", "hl")
_TAG_RE = re.compile(r"<[^>]+>")
_api_key_warned: set[str] = set()


def _get_api_key(tool_name: str = "web_search") -> str | None:
    config = get_app_config().get_tool_config(tool_name)
    if config is not None:
        api_key = (config.model_extra or {}).get("api_key")
        if isinstance(api_key, str) and api_key.strip():
            return api_key.strip()
    env_key = os.getenv("SERPLY_API_KEY")
    if isinstance(env_key, str) and env_key.strip():
        return env_key.strip()
    return None


def _coerce_max_results(
    value: object,
    *,
    default: int = _DEFAULT_MAX_RESULTS,
    max_allowed: int = _SERPLY_MAX_RESULTS,
) -> int:
    try:
        coerced = int(value)
    except (TypeError, ValueError):
        logger.warning("Invalid Serply max_results=%r; using default %s", value, default)
        coerced = default
    if coerced < 1:
        logger.warning("Invalid Serply max_results=%r; using default %s", value, default)
        coerced = default
    return min(coerced, max_allowed)


def _coerce_vertical(value: object) -> str:
    if value is None:
        return _DEFAULT_VERTICAL
    if isinstance(value, str) and value.strip().lower() in _VERTICALS:
        return value.strip().lower()
    logger.warning("Invalid Serply vertical=%r; using %r (one of %s)", value, _DEFAULT_VERTICAL, sorted(_VERTICALS))
    return _DEFAULT_VERTICAL


def _clean_query(query: str, *, max_length: int = 500) -> str:
    query = query.strip()
    if len(query) > max_length:
        query = query[:max_length]
    return query


def _clean_text(value: object) -> str:
    """Flatten a Serply text field to plain text (news summaries arrive as HTML)."""
    if not isinstance(value, str):
        return ""
    return html.unescape(_TAG_RE.sub("", value)).strip()


def _missing_key_error(query: str, tool_name: str) -> str:
    if tool_name not in _api_key_warned:
        _api_key_warned.add(tool_name)
        logger.warning(
            "Serply API key is not set for '%s'. Set SERPLY_API_KEY in your environment or provide api_key in config.yaml. Sign up at https://serply.io",
            tool_name,
        )
    return json.dumps({"error": "SERPLY_API_KEY is not configured", "query": query}, ensure_ascii=False)


def _unexpected_format_error(query: str) -> str:
    return json.dumps({"error": "Serply returned an unexpected response format", "query": query}, ensure_ascii=False)


def _serply_get(path: str, api_key: str, query: str, params: dict[str, object]) -> tuple[dict | None, str | None]:
    """Send a GET request to a Serply endpoint.

    Returns a ``(data, error_json)`` tuple: on success ``data`` is the parsed
    JSON response and ``error_json`` is ``None``; on failure ``data`` is ``None``
    and ``error_json`` is a serialized structured error ready to return.
    """
    headers = {
        "X-Api-Key": api_key,
        "Accept": "application/json",
        "User-Agent": "deerflow",
    }
    try:
        with httpx.Client(timeout=30) as client:
            response = client.get(f"{_SERPLY_BASE_URL}/{path}/", headers=headers, params=params)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            logger.error("Serply returned an unexpected payload type: %s", type(data).__name__)
            return None, _unexpected_format_error(query)
        return data, None
    except httpx.HTTPStatusError as e:
        resp_text = (e.response.text or "")[:500]
        logger.error("Serply API returned HTTP %s: %s", e.response.status_code, resp_text)
        return None, json.dumps({"error": f"Serply API error: HTTP {e.response.status_code}", "query": query}, ensure_ascii=False)
    except Exception as e:
        logger.error("Serply request failed: %s: %s", type(e).__name__, str(e)[:500])
        return None, json.dumps({"error": str(e)[:500], "query": query}, ensure_ascii=False)


def _normalize_row(vertical: str, row: dict) -> dict:
    """Map one Serply row onto the common ``title``/``url``/``content`` shape.

    News and Scholar rows carry a few extra fields worth surfacing to the model.
    """
    result = {"title": row.get("title", ""), "url": row.get("link", "")}
    if vertical == "news":
        result["content"] = _clean_text(row.get("summary"))
        result["published"] = row.get("published", "")
        source = row.get("source") if isinstance(row.get("source"), dict) else {}
        result["source"] = source.get("title", "")
    elif vertical == "scholar":
        result["content"] = row.get("description", "")
        author = row.get("author") if isinstance(row.get("author"), dict) else {}
        authors = author.get("authors") if isinstance(author.get("authors"), list) else []
        result["authors"] = [a.get("name", "") for a in authors if isinstance(a, dict)]
        extras = row.get("extras") if isinstance(row.get("extras"), dict) else {}
        citations = extras.get("citations") if isinstance(extras.get("citations"), dict) else {}
        result["cited_by"] = citations.get("count", 0)
        doc = row.get("doc") if isinstance(row.get("doc"), dict) else {}
        result["pdf_url"] = doc.get("link", "")
    else:
        result["content"] = row.get("description", "")
    return result


@tool("web_search", parse_docstring=True)
def web_search_tool(query: str, max_results: int = 5) -> str:
    """Search the web for information using Google Search via Serply.

    Args:
        query: Search keywords describing what you want to find. Be specific for better results.
        max_results: Maximum number of search results to return. Default is 5, capped at 100.
    """
    config = get_app_config().get_tool_config("web_search")
    extra = (config.model_extra or {}) if config is not None else {}
    if "max_results" in extra:
        max_results = extra["max_results"]
    max_results = _coerce_max_results(max_results)
    vertical = _coerce_vertical(extra.get("vertical"))
    query = _clean_query(query)

    api_key = _get_api_key("web_search")
    if not api_key:
        return _missing_key_error(query, "web_search")

    path, rows_key = _VERTICALS[vertical]
    params: dict[str, object] = {"q": query, "num": max_results}
    for key in _PASSTHROUGH_PARAMS:
        if key in extra:
            params[key] = extra[key]

    data, error_json = _serply_get(path, api_key, query, params)
    if error_json is not None:
        return error_json

    rows = data.get(rows_key)
    if rows is None:
        rows = []
    if not isinstance(rows, list):
        logger.error("Serply returned unexpected '%s' payload type: %s", rows_key, type(rows).__name__)
        return _unexpected_format_error(query)
    rows = [row for row in rows if isinstance(row, dict)]
    if not rows:
        return json.dumps({"error": "No results found", "query": query}, ensure_ascii=False)

    # The news feed ignores ``num`` server-side, so the cap is also applied here.
    normalized_results = [_normalize_row(vertical, row) for row in rows[:max_results]]

    output = {
        "query": query,
        "total_results": len(normalized_results),
        "results": normalized_results,
    }
    return json.dumps(output, indent=2, ensure_ascii=False)
