"""SerpApi Google organic search and single-page Markdown extraction."""

import asyncio
import json
import logging
import os

import httpx
from langchain.tools import tool
from yaml import YAMLError

from deerflow.community.provider_credentials import resolve_api_key
from deerflow.community.search_max_results import DEFAULT_MAX_RESULTS, coerce_max_results
from deerflow.community.url_safety import safe_public_result_url, validate_hosted_fetch_url
from deerflow.config import get_app_config

logger = logging.getLogger(__name__)
_ENDPOINT = "https://serpapi.com/search.json"
_FETCH_LIMIT = 4096
_TRUNCATED = "\n\n[web_fetch: truncated]"


class _SerpApiError(Exception):
    """A diagnostic safe to return without upstream text, URLs or credentials."""


async def _safe_trace(event: str, info: dict) -> None:
    # httpcore formats these trace details for DEBUG after the per-request hook.
    # A server can echo the authenticated URL in response headers or a protocol error.
    if event.endswith("receive_response_headers.complete"):
        info.pop("return_value", None)
    elif event.endswith(".failed") and "exception" in info:
        info["exception"] = type(info["exception"]).__name__


class _KeyTransport(httpx.AsyncBaseTransport):
    """Attach query auth only at the wire boundary, outside HTTPX URL logging.

    HTTPX logs client-visible URLs at INFO, even on successful requests. Keep
    that request key-free; only the delegated transport sees the authenticated
    copy. Do not mutate global loggers or include raw exceptions/responses in
    diagnostics. Redirects are disabled by the caller.
    """

    def __init__(self, transport: httpx.AsyncBaseTransport, params: dict[str, str]) -> None:
        self._transport = transport
        self._params = params

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        authenticated = httpx.Request(
            request.method,
            request.url.copy_merge_params(self._params),
            headers=request.headers,
            stream=request.stream,
            extensions={**request.extensions, "trace": _safe_trace},
        )
        response = await self._transport.handle_async_request(authenticated)
        # HTTPX logs the upstream-controlled reason phrase next to the URL.
        response.extensions.pop("reason_phrase", None)
        return response


class _SerpApiClient(httpx.AsyncClient):
    def __init__(self, wire_params: dict[str, str], *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        super().__init__(transport=transport, follow_redirects=False, timeout=30.0)
        self._wire_params = wire_params

    def _transport_for_url(self, url: httpx.URL) -> httpx.AsyncBaseTransport:
        # HTTPX has no public post-routing hook. Let it select and own the pool;
        # putting an auth transport on the client itself disables environment proxies.
        return _KeyTransport(super()._transport_for_url(url), self._wire_params)


def _resolve_tool_settings(name: str) -> tuple[str | None, object]:
    try:
        config = get_app_config().get_tool_config(name)
    except (OSError, ValueError, YAMLError):
        raise _SerpApiError("SerpApi configuration could not be loaded") from None
    extra = (config.model_extra or {}) if config is not None else {}
    return resolve_api_key(extra.get("api_key")) or resolve_api_key(os.getenv("SERPAPI_API_KEY")), extra.get("max_results")


def _prepare(name: str, params: dict[str, str]) -> tuple[httpx.AsyncClient, object]:
    key, count = _resolve_tool_settings(name)
    if not key:
        raise _SerpApiError("SERPAPI_API_KEY is not configured")
    try:
        return _SerpApiClient({**params, "api_key": key}), count
    except (ValueError, httpx.InvalidURL, ImportError):
        raise _SerpApiError("SerpApi HTTP transport could not be configured") from None


def _format_error(field: str, value: object) -> _SerpApiError:
    logger.warning("SerpApi: unexpected %s (%s)", field, type(value).__name__)
    return _SerpApiError("SerpApi returned an unexpected response format")


def _is_empty_google_search(data: dict) -> bool:
    # SerpApi puts an "error" field on successful searches with no organic results.
    match data:
        case {"search_metadata": {"status": "Success"}, "search_information": {"organic_results_state": str(state)}}:
            return state.casefold() == "fully empty" and data.get("organic_results") in (None, [])
        case _:
            return False


async def _request(name: str, **params: str) -> tuple[dict, object]:
    try:
        client, count = await asyncio.to_thread(_prepare, name, params)
        async with client:
            response = await client.get(_ENDPOINT)
    except httpx.TimeoutException:
        raise _SerpApiError("SerpApi request timed out") from None
    except (httpx.RequestError, httpx.InvalidURL, OSError):
        raise _SerpApiError("SerpApi request failed") from None
    if not response.is_success:
        raise _SerpApiError(f"SerpApi API error: HTTP {response.status_code}")
    try:
        data = response.json()
    except ValueError:
        raise _SerpApiError("SerpApi returned invalid JSON") from None
    if not isinstance(data, dict):
        raise _format_error("response", data)
    if "error" in data and not (name == "web_search" and _is_empty_google_search(data)):
        raise _SerpApiError("SerpApi reported an error")
    return data, count


@tool("web_search", parse_docstring=True)
async def web_search_tool(query: str, max_results: int | None = None) -> str:
    """Search the web using SerpApi's Google Search API.

    Args:
        query: Nonblank search keywords describing what you want to find.
        max_results: Maximum results to return from one page. If omitted, uses config (default 5). Fewer results may be available; no automatic pagination.
    """
    if not query.strip():
        return json.dumps({"error": "Search query must not be empty"})
    try:
        data, configured_count = await _request("web_search", engine="google", q=query)
        rows = data.get("organic_results")
        if rows is None or rows == []:
            raise _SerpApiError("No results found")
        if not isinstance(rows, list):
            raise _format_error("organic_results", rows)
        results = [row for row in rows if isinstance(row, dict)]
        if not results:
            raise _format_error("organic_results entries (no objects)", rows)
    except _SerpApiError as exc:
        return json.dumps({"error": str(exc)})
    value = configured_count if max_results is None else max_results
    count = DEFAULT_MAX_RESULTS if value is None else coerce_max_results(value, provider="SerpApi", logger=logger)
    return json.dumps(
        [
            {
                "title": row["title"] if isinstance(row.get("title"), str) else "",
                "url": safe_public_result_url(row.get("link")),
                "snippet": row["snippet"] if isinstance(row.get("snippet"), str) else "",
            }
            for row in results[:count]
        ],
        ensure_ascii=False,
    )


@tool("web_fetch", parse_docstring=True)
async def web_fetch_tool(url: str) -> str:
    """Fetch a single public web page as Markdown. Use an exact URL supplied by the user or returned by web_search or web_fetch. Cannot access pages behind a login.

    Args:
        url: Absolute HTTP(S) URL of the page to fetch.
    """
    url_error = validate_hosted_fetch_url(url)
    if url_error:
        return url_error
    try:
        data, _ = await _request("web_fetch", engine="extract", mode="scrape", url=url)
        markdown = data.get("markdown")
        if markdown is not None and not isinstance(markdown, str):
            raise _format_error("markdown", markdown)
        if not markdown or markdown.isspace():
            raise _SerpApiError("No Markdown content found")
    except _SerpApiError as exc:
        return f"Error: {exc}"
    if len(markdown) > _FETCH_LIMIT:
        return markdown[: _FETCH_LIMIT - len(_TRUNCATED)] + _TRUNCATED
    return markdown
