"""Outcrawl community web search and web fetch tools.

Outcrawl (https://outcrawl.ai) exposes web search and page scraping behind one
REST API and one key:

* ``web_search`` calls ``POST /v1/search`` and returns a JSON list of
  ``{title, url, snippet}``.
* ``web_fetch`` calls ``POST /v1/scrape`` with ``formats: ["markdown"]`` and
  returns the page's main content as Markdown under its title.

Outcrawl can answer 200 for a degraded result and say so in a top-level
``warnings`` list of ``{code, message}`` (``login_redirect``,
``partial_document``, ``empty_capture`` and others on scrape;
``engines_refused`` on search). Both tools pass those warnings to the agent
instead of returning the result as if it were clean: ``web_search`` then
returns ``{query, results, warnings}``, and ``web_fetch`` puts one quoted
warning line per entry above the content. ``web_fetch`` also flags a target
page that answered with an HTTP error, which Outcrawl reports in
``statusCode``.

The key comes from the tool's ``api_key`` config or ``OUTCRAWL_API_KEY``. The
module is self-contained (httpx only, no SDK and no new dependency).

Both tools are coroutines and send their request through ``httpx.AsyncClient``,
so a request never holds a default-executor thread for its round-trip. The tool
config read (which stats the config file) and the target URL screen (which may
resolve DNS) run off the event loop.
"""

import asyncio
import json
import logging
import os
import re

import httpx
from langchain.tools import tool

from deerflow.community.search_max_results import coerce_max_results
from deerflow.community.url_safety import safe_public_result_url, validate_public_http_url
from deerflow.config import get_app_config

logger = logging.getLogger(__name__)

_OUTCRAWL_BASE_URL = "https://api.outcrawl.ai/v1"
_DEFAULT_MAX_RESULTS = 5
_MAX_RESULTS_CAP = 20
_TIMEOUT_S = 60.0
_MAX_FETCH_CHARS = 4096
# Actionable hints for the failures an operator can fix. Any other status just
# reports its code.
_STATUS_HINTS = {
    401: "invalid or revoked OUTCRAWL_API_KEY",
    402: "Outcrawl credit balance depleted",
    429: "rate limit reached",
}


def _resolve_tool_settings(tool_name: str) -> tuple[str | None, object]:
    """Resolve the API key and the configured ``max_results`` in one config read.

    Config resolution stats the config file, so callers run this off the agent
    event loop.
    """
    config = get_app_config().get_tool_config(tool_name)
    max_results = None
    api_key = None
    if config is not None:
        extra = config.model_extra or {}
        max_results = extra.get("max_results")
        candidate = extra.get("api_key")
        if isinstance(candidate, str) and candidate.strip():
            api_key = candidate.strip()
    if api_key is None:
        env_key = os.getenv("OUTCRAWL_API_KEY")
        if isinstance(env_key, str) and env_key.strip():
            api_key = env_key.strip()
    return api_key, max_results


def _count_for_request(value: object) -> int:
    """Coerce ``max_results`` via the shared owner, then cap it for one request."""
    return min(
        coerce_max_results(value, provider="Outcrawl", logger=logger, default=_DEFAULT_MAX_RESULTS),
        _MAX_RESULTS_CAP,
    )


def _http_error_message(status: int) -> str:
    message = f"Outcrawl API error: HTTP {status}"
    hint = _STATUS_HINTS.get(status)
    return f"{message} ({hint})" if hint else message


def _response_warnings(data: object) -> list[dict[str, str]]:
    """Normalize Outcrawl's top-level ``warnings`` to ``[{code, message}]``.

    Entries without a usable ``code`` are dropped; a payload or ``warnings``
    value of the wrong type yields no warnings.
    """
    raw = data.get("warnings") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        return []
    warnings = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        code = entry.get("code")
        if not isinstance(code, str) or not code.strip():
            continue
        message = entry.get("message")
        warnings.append({"code": code.strip(), "message": message.strip() if isinstance(message, str) else ""})
    return warnings


def _format_warning(warning: dict[str, str]) -> str:
    message = warning["message"]
    return f"> Outcrawl warning ({warning['code']}): {message}" if message else f"> Outcrawl warning ({warning['code']})"


_HEADING_RE = re.compile(r"^#{1,6}[ \t]+(.+?)[ \t#]*$", re.MULTILINE)


def _page_title(data: dict, requested_url: str) -> str:
    """Title for a scraped page: ``metadata.title``, else the first Markdown heading, else the URL."""
    metadata = data.get("metadata")
    if isinstance(metadata, dict):
        title = metadata.get("title")
        if isinstance(title, str) and title.strip():
            return title.strip()
    markdown = data.get("markdown")
    if isinstance(markdown, str):
        heading = _HEADING_RE.search(markdown)
        if heading:
            return heading.group(1).strip()
    final_url = data.get("url")
    return final_url if isinstance(final_url, str) and final_url.strip() else requested_url


async def _post(path: str, api_key: str, body: dict) -> dict:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
        response = await client.post(f"{_OUTCRAWL_BASE_URL}/{path}", json=body, headers=headers)
    response.raise_for_status()
    return response.json()


@tool("web_search", parse_docstring=True)
async def web_search_tool(query: str, max_results: int | None = None) -> str:
    """Search the web for information using Outcrawl.

    Args:
        query: Search keywords describing what you want to find. Be specific for better results.
        max_results: Maximum number of search results to return. If omitted, uses the configured value (default 5). Clamped to 1-20.
    """
    # Config resolution can read files; keep it off the event loop.
    api_key, configured_max_results = await asyncio.to_thread(_resolve_tool_settings, "web_search")
    if not api_key:
        logger.warning("Outcrawl API key is not set. Set OUTCRAWL_API_KEY in your environment or provide api_key in config.yaml.")
        return json.dumps({"error": "OUTCRAWL_API_KEY is not configured", "query": query}, ensure_ascii=False)
    # Honor the caller-supplied max_results; fall back to config only when omitted.
    if max_results is None:
        max_results = configured_max_results
    count = _DEFAULT_MAX_RESULTS if max_results is None else _count_for_request(max_results)

    try:
        data = await _post("search", api_key, {"query": query, "limit": count})
    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        logger.error("Outcrawl API returned HTTP %s: %s", status, e.response.text[:500])
        return json.dumps({"error": _http_error_message(status), "query": query}, ensure_ascii=False)
    except Exception as e:
        logger.error("Outcrawl search failed: %s: %s", type(e).__name__, str(e)[:500])
        return json.dumps({"error": str(e)[:500], "query": query}, ensure_ascii=False)

    hits = data.get("hits") if isinstance(data, dict) else None
    if hits is not None and not isinstance(hits, list):
        logger.error("Outcrawl returned unexpected 'hits' payload type: %s", type(hits).__name__)
        return json.dumps({"error": "Outcrawl returned an unexpected response format", "query": query}, ensure_ascii=False)
    results = [hit for hit in hits or [] if isinstance(hit, dict)]
    warnings = _response_warnings(data)
    if warnings:
        logger.warning("Outcrawl search returned warnings: %s", ", ".join(w["code"] for w in warnings))
    if not results:
        error = {"error": "No results found", "query": query}
        if warnings:
            error["warnings"] = warnings
        return json.dumps(error, ensure_ascii=False)

    normalized_results = [
        {
            "title": hit.get("title", "") or "",
            "url": safe_public_result_url(hit.get("url")),
            "snippet": hit.get("snippet", "") or "",
        }
        for hit in results[:count]
    ]
    if warnings:
        return json.dumps({"query": query, "results": normalized_results, "warnings": warnings}, indent=2, ensure_ascii=False)
    return json.dumps(normalized_results, indent=2, ensure_ascii=False)


@tool("web_fetch", parse_docstring=True)
async def web_fetch_tool(url: str) -> str:
    """Fetch the contents of a web page at a given URL.
    Only fetch EXACT URLs that have been provided directly by the user or have been returned in results from the web_search and web_fetch tools.
    This tool can NOT access content that requires authentication, such as private Google Docs or pages behind login walls.
    Do NOT add www. to URLs that do NOT have them.
    URLs must include the schema: https://example.com is a valid URL while example.com is an invalid URL.

    Args:
        url: The URL to fetch the contents of.
    """
    # Config resolution reads files and the URL screen may resolve DNS; keep both off the loop.
    api_key, _ = await asyncio.to_thread(_resolve_tool_settings, "web_fetch")
    url_error = await asyncio.to_thread(validate_public_http_url, url)
    if url_error:
        return url_error
    if not api_key:
        logger.warning("Outcrawl API key is not set. Set OUTCRAWL_API_KEY in your environment or provide api_key in config.yaml.")
        return "Error: OUTCRAWL_API_KEY is not configured"

    try:
        data = await _post("scrape", api_key, {"url": url, "formats": ["markdown"]})
    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        logger.error("Outcrawl API returned HTTP %s: %s", status, e.response.text[:500])
        return f"Error: {_http_error_message(status)}"
    except Exception as e:
        logger.error("Outcrawl scrape failed: %s: %s", type(e).__name__, str(e)[:500])
        return f"Error: {str(e)[:500]}"

    if not isinstance(data, dict):
        return "Error: Outcrawl returned an unexpected response format"
    warnings = _response_warnings(data)
    if warnings:
        logger.warning("Outcrawl scrape of %s returned warnings: %s", url, ", ".join(w["code"] for w in warnings))
    notes = [_format_warning(w) for w in warnings]
    target_status = data.get("statusCode")
    if isinstance(target_status, int) and not isinstance(target_status, bool) and target_status >= 400:
        notes.append(f"> Outcrawl warning: the target page responded HTTP {target_status}")
    markdown_content = data.get("markdown")
    if not isinstance(markdown_content, str) or not markdown_content:
        return "\n".join(["Error: No content found", *notes])
    header = f"# {_page_title(data, url)}\n\n"
    if notes:
        header += "\n".join(notes) + "\n\n"
    return f"{header}{markdown_content[:_MAX_FETCH_CHARS]}"
