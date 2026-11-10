"""
Web search and fetch tools powered by SpecStream.

SpecStream is a live web data engine with a Search API and an Extract API.
Search answers a question from the live web and returns the search results it
read, ranked, with a direct answer when the sources agree on one. Fetch returns
the main text of a page, PDF, Word or Excel file as markdown. An API key is
required. Sign up at https://specstream.ai to get one.
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

_SPECSTREAM_BASE_URL = "https://api.specstream.ai"
_SPECSTREAM_SEARCH_PATH = "/v1/web-search"
_SPECSTREAM_EXTRACT_PATH = "/v1/extract"
# The search API takes a question of 1 to 2000 characters.
_SPECSTREAM_MAX_QUERY_CHARS = 2000
# Each fetched URL gets up to 30 seconds on the SpecStream side.
_SPECSTREAM_TIMEOUT = 60
_SPECSTREAM_FETCH_MAX_CHARS = 4096
_api_key_warned: set[str] = set()


def _get_api_key(tool_name: str) -> str | None:
    config = get_app_config().get_tool_config(tool_name)
    if config is not None:
        api_key = config.model_extra.get("api_key")
        if isinstance(api_key, str) and api_key.strip():
            return api_key.strip()
    env_key = os.getenv("SPECSTREAM_API_KEY")
    if isinstance(env_key, str) and env_key.strip():
        return env_key.strip()
    return None


def _missing_key_message(tool_name: str) -> str:
    if tool_name not in _api_key_warned:
        _api_key_warned.add(tool_name)
        logger.warning("SpecStream API key is not set for '%s'. Set SPECSTREAM_API_KEY in your environment or provide api_key in config.yaml. Sign up at https://specstream.ai", tool_name)
    return "SPECSTREAM_API_KEY is not configured"


def _specstream_request(method: str, path: str, api_key: str, *, params: dict | None = None, payload: dict | None = None) -> tuple[dict | None, str | None]:
    """Send a request to a SpecStream endpoint.

    Returns a ``(data, error)`` tuple: on success ``data`` is the object inside
    the response's ``data`` envelope and ``error`` is ``None``; on failure
    ``data`` is ``None`` and ``error`` is a message the caller can hand back to
    the model.
    """
    headers = {"Authorization": f"Bearer {api_key}"}

    try:
        with httpx.Client(timeout=_SPECSTREAM_TIMEOUT) as client:
            response = client.request(method, f"{_SPECSTREAM_BASE_URL}{path}", headers=headers, params=params, json=payload)
        response.raise_for_status()
        body = response.json()
    except httpx.HTTPStatusError as e:
        logger.error("SpecStream API returned HTTP %s: %s", e.response.status_code, (e.response.text or "")[:500])
        return None, f"SpecStream API error: HTTP {e.response.status_code}"
    except Exception as e:
        logger.error("SpecStream request failed: %s: %s", type(e).__name__, str(e)[:500])
        return None, str(e)[:500]

    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, dict):
        logger.error("SpecStream returned an unexpected payload type: %s", type(body).__name__)
        return None, "SpecStream returned an unexpected response format"
    return data, None


def _response_objects(data: dict, container: str) -> list[dict] | None:
    """Return the object entries of a SpecStream response container, or None if malformed.

    A missing or null container is empty. A non-list container, or a non-empty
    list holding no objects, is malformed: the caller reports a format error
    rather than "No results found", which would tell the agent the query
    legitimately matched nothing.
    """
    value = data.get(container)
    if value is None:
        return []
    if not isinstance(value, list):
        logger.error("SpecStream returned an unexpected '%s' payload type: %s", container, type(value).__name__)
        return None
    usable = [item for item in value if isinstance(item, dict)]
    if value and not usable:
        logger.error("SpecStream returned '%s' with no usable result objects", container)
        return None
    return usable


def _normalize_answer(answer: object) -> dict | None:
    """Keep the direct answer with the page it was read from, or None when there is none."""
    if not isinstance(answer, dict) or not answer.get("value"):
        return None
    return {
        "value": answer.get("value"),
        "url": safe_public_result_url(answer.get("page")),
    }


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
    max_results = coerce_max_results(max_results, provider="SpecStream", logger=logger)

    api_key = _get_api_key("web_search")
    if not api_key:
        return json.dumps({"error": _missing_key_message("web_search"), "query": query}, ensure_ascii=False)

    data, error = _specstream_request("GET", _SPECSTREAM_SEARCH_PATH, api_key, params={"q": query.strip()[:_SPECSTREAM_MAX_QUERY_CHARS]})
    if error is not None:
        return json.dumps({"error": error, "query": query}, ensure_ascii=False)

    sources = _response_objects(data, "sources")
    if sources is None:
        return json.dumps({"error": "SpecStream returned an unexpected response format", "query": query}, ensure_ascii=False)
    answer = _normalize_answer(data.get("answer"))
    if not sources and answer is None:
        return json.dumps({"error": "No results found", "query": query}, ensure_ascii=False)

    output: dict[str, object] = {"query": query}
    if answer is not None:
        output["answer"] = answer
    results = [
        {
            "title": source.get("title") or "",
            "url": safe_public_result_url(source.get("url")),
            "snippet": source.get("snippet") or "",
        }
        for source in sources[:max_results]
    ]
    output["total_results"] = len(results)
    output["results"] = results
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

    data, error = _specstream_request("POST", _SPECSTREAM_EXTRACT_PATH, api_key, payload={"urls": [url], "format": "markdown"})
    if error is not None:
        return f"Error: {error}"

    results = _response_objects(data, "results")
    if results is None:
        return "Error: SpecStream returned an unexpected response format"
    if not results:
        return "Error: No results found"

    result = results[0]
    status = result.get("status")
    if status != "ok":
        return f"Error: SpecStream could not read the page ({status or 'unknown status'})"

    content = result.get("text")
    content = content[:_SPECSTREAM_FETCH_MAX_CHARS] if isinstance(content, str) else ""
    if not content:
        return "Error: No content found"

    title = result.get("title") or "Untitled"
    return f"# {title}\n\n{content}"
