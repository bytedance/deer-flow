"""Web search tool using the Desearch web search API.

An API key is required. Sign up at https://desearch.ai and see
https://desearch.ai/docs for documentation.
"""

import json
import logging
import os

import httpx
from langchain.tools import tool

from deerflow.community.search_max_results import coerce_max_results
from deerflow.community.url_safety import safe_public_result_url
from deerflow.config import get_app_config

logger = logging.getLogger(__name__)

_DESEARCH_URL = "https://api.desearch.ai/web"
_DESEARCH_MAX_RESULTS = 20
_api_key_warned: set[str] = set()


def _get_api_key(tool_name: str = "web_search") -> str | None:
    config = get_app_config().get_tool_config(tool_name)
    if config is not None:
        api_key = (config.model_extra or {}).get("api_key")
        if isinstance(api_key, str) and api_key.strip():
            return api_key.strip()
    env_key = os.getenv("DESEARCH_API_KEY")
    if isinstance(env_key, str) and env_key.strip():
        return env_key.strip()
    return None


def _count_for_request(value: object) -> int:
    """Coerce ``max_results`` via the shared owner, then apply Desearch's cap."""
    return min(
        coerce_max_results(value, provider="Desearch", logger=logger),
        _DESEARCH_MAX_RESULTS,
    )


def _clean_query(query: str, *, max_length: int = 500) -> str:
    query = query.strip()
    if len(query) > max_length:
        query = query[:max_length]
    return query


def _missing_key_error(query: str, tool_name: str) -> str:
    if tool_name not in _api_key_warned:
        _api_key_warned.add(tool_name)
        logger.warning(
            "Desearch API key is not set for '%s'. Set DESEARCH_API_KEY in your environment or provide api_key in config.yaml. Sign up at https://desearch.ai",
            tool_name,
        )
    return json.dumps({"error": "DESEARCH_API_KEY is not configured", "query": query}, ensure_ascii=False)


def _unexpected_format_error(query: str) -> str:
    return json.dumps({"error": "Desearch returned an unexpected response format", "query": query}, ensure_ascii=False)


def _response_rows(data: dict, rows_key: str, query: str) -> tuple[list[dict], str | None]:
    """Return object rows, or a structured format error."""
    rows = data.get(rows_key)
    if rows is None:
        return [], None
    if not isinstance(rows, list):
        logger.error("Desearch returned unexpected '%s' payload type: %s", rows_key, type(rows).__name__)
        return [], _unexpected_format_error(query)
    usable = [row for row in rows if isinstance(row, dict)]
    if rows and not usable:
        logger.error("Desearch returned '%s' with no usable result objects", rows_key)
        return [], _unexpected_format_error(query)
    return usable, None


def _error_details(response: httpx.Response) -> tuple[str | None, str | None]:
    try:
        body = response.json()
    except ValueError:
        return None, None
    if not isinstance(body, dict):
        return None, None
    detail = body.get("detail")
    code = body.get("error_code", detail.get("error_code") if isinstance(detail, dict) else None)
    message = detail.get("message") if isinstance(detail, dict) else detail
    return code if isinstance(code, str) else None, message if isinstance(message, str) else None


def _desearch_get(api_key: str, query: str, params: dict[str, object]) -> tuple[dict | None, str | None]:
    """Send a GET request to a Desearch endpoint.

    Returns a ``(data, error_json)`` tuple: on success ``data`` is the parsed
    JSON response and ``error_json`` is ``None``; on failure ``data`` is ``None``
    and ``error_json`` is a serialized structured error ready to return.
    """
    headers = {
        "Authorization": api_key,
        "Accept": "application/json",
        "User-Agent": "deerflow",
    }
    try:
        with httpx.Client(timeout=30) as client:
            response = client.get(_DESEARCH_URL, headers=headers, params=params)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            logger.error("Desearch returned an unexpected payload type: %s", type(data).__name__)
            return None, _unexpected_format_error(query)
        return data, None
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 503:
            code, message = _error_details(e.response)
            if code == "upstream_empty":
                return None, json.dumps({"error": "No results found", "query": query}, ensure_ascii=False)
            if message is not None:
                message = message.replace(api_key, "[redacted]")[:500]
            if code is not None:
                code = code.replace(api_key, "[redacted]")
            logger.error("Desearch API returned HTTP %s: error_code=%s, message=%s", e.response.status_code, code, message)
            return None, json.dumps({"error": "Desearch API error: HTTP 503", "error_code": code, "message": message, "query": query}, ensure_ascii=False)
        resp_text = (e.response.text or "")[:500]
        logger.error("Desearch API returned HTTP %s: %s", e.response.status_code, resp_text)
        return None, json.dumps({"error": f"Desearch API error: HTTP {e.response.status_code}", "query": query}, ensure_ascii=False)
    except Exception as e:
        logger.error("Desearch request failed: %s: %s", type(e).__name__, str(e)[:500])
        return None, json.dumps({"error": str(e)[:500], "query": query}, ensure_ascii=False)


@tool("web_search", parse_docstring=True)
def web_search_tool(query: str, max_results: int = 5) -> str:
    """Search the web for information using Desearch.

    Args:
        query: Search keywords describing what you want to find. Be specific for better results.
        max_results: Maximum number of search results to return. Default is 5, capped at 20.
    """
    config = get_app_config().get_tool_config("web_search")
    extra = (config.model_extra or {}) if config is not None else {}
    max_results = _count_for_request(extra.get("max_results", max_results))
    query = _clean_query(query)
    if not query:
        return json.dumps({"error": "Query must not be blank", "query": query}, ensure_ascii=False)

    api_key = _get_api_key("web_search")
    if not api_key:
        return _missing_key_error(query, "web_search")

    data, error_json = _desearch_get(api_key, query, {"query": query})
    if error_json is not None:
        return error_json
    rows, error_json = _response_rows(data, "data", query)
    if error_json is not None:
        return error_json
    if not rows:
        return json.dumps({"error": "No results found", "query": query}, ensure_ascii=False)

    normalized_results = [{"title": row.get("title", ""), "url": safe_public_result_url(row.get("link")), "content": row.get("snippet", "")} for row in rows[:max_results]]
    return json.dumps({"query": query, "total_results": len(normalized_results), "results": normalized_results}, indent=2, ensure_ascii=False)
