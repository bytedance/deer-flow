"""
Web search and fetch tools powered by Sofya.

Sofya is a hosted web API for agents. Search returns the content of the result
pages, not only their snippets, and fetch returns a single page as clean
markdown. An API key is required. Sign up at https://sofya.co to get one.
"""

import json
import logging
import os

import httpx
from langchain.tools import tool

from deerflow.community.search_time_range import SearchTimeRange
from deerflow.config import get_app_config

logger = logging.getLogger(__name__)

_SOFYA_BASE_URL = "https://sofya.co/v1"
_SOFYA_SEARCH_PATH = "/search"
_SOFYA_FETCH_PATH = "/fetch"
_SOFYA_MAX_RESULTS = 20
_SOFYA_TIMEOUT = 60
_SOFYA_FETCH_MAX_CHARS = 4096
_DEFAULT_SEARCH_DEPTH = "basic"
_DEFAULT_CONTENTS_MAX_CHARACTERS = 2000
_SEARCH_DEPTHS = ("basic", "snippets")
_api_key_warned: set[str] = set()


def _get_api_key(tool_name: str) -> str | None:
    config = get_app_config().get_tool_config(tool_name)
    if config is not None:
        api_key = config.model_extra.get("api_key")
        if isinstance(api_key, str) and api_key.strip():
            return api_key.strip()
    env_key = os.getenv("SOFYA_API_KEY")
    if isinstance(env_key, str) and env_key.strip():
        return env_key.strip()
    return None


def _coerce_max_results(value: object, default: int = 5, max_allowed: int = _SOFYA_MAX_RESULTS) -> int:
    """Coerce config/parameter input into a bounded positive result count."""
    try:
        count = int(value)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return default
    if count <= 0:
        return default
    return min(count, max_allowed)


def _coerce_content_limit(value: object, default: int = _DEFAULT_CONTENTS_MAX_CHARACTERS) -> int:
    """Coerce the per-result content limit. 0 means no limit; anything invalid falls back to the default."""
    try:
        limit = int(value)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return default
    return limit if limit >= 0 else default


def _resolve_search_depth(value: object) -> str:
    """Return a supported search depth, falling back to the default with a warning."""
    if value is None:
        return _DEFAULT_SEARCH_DEPTH
    depth = str(value).strip().lower()
    if depth in _SEARCH_DEPTHS:
        return depth
    logger.warning("Ignoring unsupported Sofya search_depth %r; using %r (supported: %s)", value, _DEFAULT_SEARCH_DEPTH, ", ".join(_SEARCH_DEPTHS))
    return _DEFAULT_SEARCH_DEPTH


def _missing_key_message(tool_name: str) -> str:
    if tool_name not in _api_key_warned:
        _api_key_warned.add(tool_name)
        logger.warning("Sofya API key is not set for '%s'. Set SOFYA_API_KEY in your environment or provide api_key in config.yaml. Sign up at https://sofya.co", tool_name)
    return "SOFYA_API_KEY is not configured"


def _sofya_post(path: str, api_key: str, payload: dict) -> tuple[dict | None, str | None]:
    """Send a POST request to a Sofya endpoint.

    Returns a ``(data, error)`` tuple: on success ``data`` is the parsed JSON
    object and ``error`` is ``None``; on failure ``data`` is ``None`` and
    ``error`` is a message the caller can hand back to the model.
    """
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        with httpx.Client(timeout=_SOFYA_TIMEOUT) as client:
            response = client.post(f"{_SOFYA_BASE_URL}{path}", headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
    except httpx.HTTPStatusError as e:
        logger.error("Sofya API returned HTTP %s: %s", e.response.status_code, (e.response.text or "")[:500])
        return None, f"Sofya API error: HTTP {e.response.status_code}"
    except Exception as e:
        logger.error("Sofya request failed: %s: %s", type(e).__name__, str(e)[:500])
        return None, str(e)[:500]

    if not isinstance(data, dict):
        logger.error("Sofya returned an unexpected payload type: %s", type(data).__name__)
        return None, "Sofya returned an unexpected response format"
    return data, None


def _clip(value: object, limit: int) -> str:
    """Coerce a result field to text and truncate it. A limit of 0 means no truncation."""
    text = value if isinstance(value, str) else str(value)
    return text if limit <= 0 else text[:limit]


def _response_results(data: dict) -> list[dict] | None:
    """Return the result dicts of a Sofya response, or None if malformed."""
    results = data.get("results")
    if results is None:
        return []
    if not isinstance(results, list):
        logger.error("Sofya returned an unexpected 'results' payload type: %s", type(results).__name__)
        return None
    return [item for item in results if isinstance(item, dict)]


@tool("web_search", parse_docstring=True)
def web_search_tool(query: str, max_results: int | None = None, time_range: SearchTimeRange | None = None) -> str:
    """Search the web for information. Use this tool to find current information, news, articles, and facts from the internet.

    Args:
        query: Search keywords describing what you want to find. Be specific for better results.
        max_results: Maximum number of results to return. If omitted, uses the configured value (default 5). Capped at 20.
        time_range: Optional relative publication/update window. Use only when the request requires recent results.
    """
    config = get_app_config().get_tool_config("web_search")
    config_extra = (config.model_extra or {}) if config is not None else {}
    # Honor the caller-supplied max_results; fall back to config only when omitted.
    if max_results is None:
        max_results = config_extra.get("max_results")
    max_results = _coerce_max_results(max_results)
    search_depth = _resolve_search_depth(config_extra.get("search_depth"))
    content_limit = _coerce_content_limit(config_extra.get("contents_max_characters"))

    api_key = _get_api_key("web_search")
    if not api_key:
        return json.dumps({"error": _missing_key_message("web_search"), "query": query}, ensure_ascii=False)

    payload: dict[str, object] = {
        "query": query,
        "max_results": max_results,
        "search_depth": search_depth,
    }
    if time_range is not None:
        payload["freshness"] = time_range

    data, error = _sofya_post(_SOFYA_SEARCH_PATH, api_key, payload)
    if error is not None:
        return json.dumps({"error": error, "query": query}, ensure_ascii=False)

    results = _response_results(data)
    if results is None:
        return json.dumps({"error": "Sofya returned an unexpected response format", "query": query}, ensure_ascii=False)
    if not results:
        return json.dumps({"error": "No results found", "query": query}, ensure_ascii=False)

    normalized_results = [
        {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            # Page content when the result was read, the search snippet otherwise.
            # Capped so a normal search stays inline rather than being written to disk.
            "content": _clip(r.get("content") or r.get("description") or "", content_limit),
        }
        for r in results[:max_results]
    ]

    output = {
        "query": query,
        "total_results": len(normalized_results),
        "results": normalized_results,
    }
    return json.dumps(output, indent=2, ensure_ascii=False)


@tool("web_fetch", parse_docstring=True)
def web_fetch_tool(url: str) -> str:
    """Fetch the contents of a web page at a given URL.
    Only fetch EXACT URLs that have been provided directly by the user or have been returned in results from the web_search and web_fetch tools.
    This tool can NOT access content that requires authentication, such as private Google Docs or pages behind login walls.
    Do NOT add www. to URLs that do NOT have them.
    URLs must include the schema: https://example.com is a valid URL while example.com is an invalid URL.

    Args:
        url: The URL to fetch the contents of.
    """
    api_key = _get_api_key("web_fetch")
    if not api_key:
        return f"Error: {_missing_key_message('web_fetch')}"

    data, error = _sofya_post(_SOFYA_FETCH_PATH, api_key, {"urls": [url]})
    if error is not None:
        return f"Error: {error}"

    results = _response_results(data)
    if results is None:
        return "Error: Sofya returned an unexpected response format"
    if not results:
        return "Error: No results found"

    result = results[0]
    if not result.get("success", True):
        return f"Error: {result.get('error') or 'Failed to fetch the URL'}"

    content = _clip(result.get("content") or "", _SOFYA_FETCH_MAX_CHARS)
    if not content:
        return "Error: No content found"

    title = result.get("title") or "Untitled"
    return f"# {title}\n\n{content}"
