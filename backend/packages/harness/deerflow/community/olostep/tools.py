"""Olostep community web search and fetch tools.

Olostep (https://www.olostep.com) is web data infrastructure for AI agents:
live web search, scraping and crawling. This module uses two endpoints of its
API (https://docs.olostep.com):

* ``web_search`` sends ``POST /v1/searches`` and returns the response's
  ``result.links`` (``{url, title, description}``) as a JSON list of
  ``{title, url, snippet}``. Olostep accepts a ``limit`` of 1 to 25.
* ``web_fetch`` sends ``POST /v1/scrapes`` with ``formats: ["markdown"]`` and
  returns the page's ``result.markdown_content``.

An API key is required: ``OLOSTEP_API_KEY`` or the tool's ``api_key`` config.
Get one at https://www.olostep.com/dashboard/api-keys.

This module is self-contained (httpx only, no Olostep SDK and no new
dependency). Both tools are coroutines over ``httpx.AsyncClient``. The config
read and the client construction (TLS setup) run off the event loop; the
request itself is awaited on the loop.
"""

import asyncio
import json
import logging
import os

import httpx
from langchain.tools import tool

from deerflow.community.provider_credentials import redact_secret, resolve_api_key
from deerflow.community.search_max_results import coerce_max_results
from deerflow.community.url_safety import safe_public_result_url
from deerflow.config import get_app_config

logger = logging.getLogger(__name__)

_OLOSTEP_BASE_URL = "https://api.olostep.com"
_OLOSTEP_SEARCH_PATH = "/v1/searches"
_OLOSTEP_SCRAPE_PATH = "/v1/scrapes"
_DEFAULT_MAX_RESULTS = 5
# Olostep rejects a search `limit` outside 1-25 with HTTP 400; clamp here so a
# larger configured value still returns results.
_MAX_RESULTS_CAP = 25
_TIMEOUT_S = 60.0
_FETCH_MAX_CHARS = 4096
_STATUS_HINTS = {
    401: "invalid or missing OLOSTEP_API_KEY",
}
# Warn at most once per tool ("web_search" / "web_fetch") about a missing key.
_api_key_warned: set[str] = set()


def _resolve_tool_settings(tool_name: str) -> tuple[str | None, object]:
    """Resolve the API key and the configured `max_results` in one config read.

    Config resolution stats the config file, so callers run this off the event
    loop. `tool_name` selects the config section, so a setup that uses Olostep
    for only one of web_search and web_fetch still reads the right key.
    """
    tool_config = get_app_config().get_tool_config(tool_name)
    max_results = None
    api_key = None
    if tool_config is not None:
        extra = tool_config.model_extra or {}
        max_results = extra.get("max_results")
        api_key = resolve_api_key(extra.get("api_key"))
    if api_key is None:
        api_key = resolve_api_key(os.getenv("OLOSTEP_API_KEY"))
    return api_key, max_results


def _limit_for_request(value: object) -> int:
    """Coerce ``max_results`` via the shared owner, then apply Olostep's 25 cap."""
    return min(
        coerce_max_results(value, provider="Olostep", logger=logger, default=_DEFAULT_MAX_RESULTS),
        _MAX_RESULTS_CAP,
    )


def _missing_key_message(tool_name: str) -> str:
    if tool_name not in _api_key_warned:
        _api_key_warned.add(tool_name)
        logger.warning(
            "Olostep API key is not set for '%s'. Set OLOSTEP_API_KEY in your environment or provide api_key in config.yaml. Get a key at https://www.olostep.com/dashboard/api-keys",
            tool_name,
        )
    return "OLOSTEP_API_KEY is not configured"


async def _post(api_key: str, path: str, body: dict) -> object:
    async with await asyncio.to_thread(httpx.AsyncClient, timeout=_TIMEOUT_S) as client:
        response = await client.post(
            f"{_OLOSTEP_BASE_URL}{path}",
            json=body,
            headers={"Authorization": f"Bearer {api_key}"},
        )
    response.raise_for_status()
    return response.json()


async def _request(api_key: str, path: str, body: dict) -> tuple[object, str | None]:
    """Send one request. Returns ``(data, None)`` or ``(None, error message)``.

    Logs carry the status code or the exception type only: queries, URLs and
    response bodies stay out of them, and the key is redacted from any error
    text handed back to the model.
    """
    try:
        return await _post(api_key, path, body), None
    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        logger.error("Olostep API returned HTTP %s", status)
        message = f"Olostep API error: HTTP {status}"
        hint = _STATUS_HINTS.get(status)
        return None, f"{message} ({hint})" if hint else message
    except Exception as e:
        logger.error("Olostep request failed: %s", type(e).__name__)
        return None, redact_secret(f"Olostep request failed: {type(e).__name__}: {e}", api_key)


def _result_object(data: object) -> dict | None:
    """Return the ``result`` object of an Olostep response, or None if malformed.

    A missing or null ``result`` reads as empty.
    """
    if not isinstance(data, dict):
        logger.error("Olostep returned an unexpected payload type: %s", type(data).__name__)
        return None
    result = data.get("result")
    if result is None:
        return {}
    if not isinstance(result, dict):
        logger.error("Olostep returned an unexpected 'result' payload type: %s", type(result).__name__)
        return None
    return result


def _search_links(data: object) -> list[dict] | None:
    """Return the link objects of a search response, or None if malformed.

    A missing, null or empty ``links`` list is an empty search. A non-list
    container, or a non-empty list holding no objects, is a format error, so
    the agent is not told that the query legitimately matched nothing.
    """
    result = _result_object(data)
    if result is None:
        return None
    links = result.get("links")
    if links is None:
        return []
    if not isinstance(links, list):
        logger.error("Olostep returned an unexpected 'links' payload type: %s", type(links).__name__)
        return None
    usable = [link for link in links if isinstance(link, dict)]
    if links and not usable:
        logger.error("Olostep returned 'links' with no usable result objects")
        return None
    return usable


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


@tool("web_search", parse_docstring=True)
async def web_search_tool(query: str, max_results: int | None = None) -> str:
    """Search the web for information using Olostep.

    Args:
        query: Search keywords describing what you want to find. Be specific for better results.
        max_results: Maximum number of search results to return. If omitted, uses the configured value (default 5). Clamped to 1-25.
    """
    # Config resolution can read files; keep it off the event loop.
    api_key, configured_max_results = await asyncio.to_thread(_resolve_tool_settings, "web_search")
    # Honor the caller-supplied max_results; fall back to config only when omitted.
    if max_results is None:
        max_results = configured_max_results
    limit = _DEFAULT_MAX_RESULTS if max_results is None else _limit_for_request(max_results)

    if not api_key:
        return json.dumps({"error": _missing_key_message("web_search"), "query": query}, ensure_ascii=False)

    data, error = await _request(api_key, _OLOSTEP_SEARCH_PATH, {"query": query, "limit": limit})
    if error is not None:
        return json.dumps({"error": error, "query": query}, ensure_ascii=False)

    links = _search_links(data)
    if links is None:
        return json.dumps({"error": "Olostep returned an unexpected response format", "query": query}, ensure_ascii=False)
    if not links:
        return json.dumps({"error": "No results found", "query": query}, ensure_ascii=False)

    normalized_results = [
        {
            "title": _text(link.get("title")),
            "url": safe_public_result_url(link.get("url")),
            "snippet": _text(link.get("description")),
        }
        for link in links[:limit]
    ]
    return json.dumps(normalized_results, indent=2, ensure_ascii=False)


@tool("web_fetch", parse_docstring=True)
async def web_fetch_tool(url: str) -> str:
    """Fetch the contents of a web page at a given URL via Olostep.
    Only fetch EXACT URLs that have been provided directly by the user or have been returned in results from the web_search and web_fetch tools.
    This tool can NOT access content that requires authentication, such as private Google Docs or pages behind login walls.
    Do NOT add www. to URLs that do NOT have them.
    URLs must include the schema: https://example.com is a valid URL while example.com is an invalid URL.

    Args:
        url: The URL to fetch the contents of.
    """
    api_key, _ = await asyncio.to_thread(_resolve_tool_settings, "web_fetch")
    if not api_key:
        return f"Error: {_missing_key_message('web_fetch')}"

    data, error = await _request(api_key, _OLOSTEP_SCRAPE_PATH, {"url_to_scrape": url, "formats": ["markdown"]})
    if error is not None:
        return f"Error: {error}"

    result = _result_object(data)
    if result is None:
        return "Error: Olostep returned an unexpected response format"

    content = _text(result.get("markdown_content"))
    if not content.strip():
        return "Error: No content found"

    metadata = result.get("page_metadata")
    title = _text(metadata.get("title")).strip() if isinstance(metadata, dict) else ""
    return f"# {title or 'Untitled'}\n\n{content[:_FETCH_MAX_CHARS]}"
