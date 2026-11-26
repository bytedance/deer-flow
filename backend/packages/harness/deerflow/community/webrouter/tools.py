"""
Web search and fetch tools powered by WebRouter.

WebRouter (https://github.com/Nimbleway/webrouter) is an open-source library
that puts one interface in front of many search and extraction backends, with
fallback between them. With no API key it serves search and fetch from keyless
tiers. WebRouter reads each backend's own variable from the process environment
(``TAVILY_API_KEY``, ``EXA_API_KEY``, ``NIMBLE_API_KEY`` and so on); every key
it finds adds that backend, tried before the keyless ones and billed by that
backend.

Install the optional dependency with ``cd backend && uv sync --extra webrouter``.
"""

import asyncio
import json
import logging

from langchain.tools import tool

from deerflow.community.search_max_results import coerce_max_results
from deerflow.community.search_time_range import SearchTimeRange
from deerflow.community.url_safety import safe_public_result_url, validate_hosted_fetch_url
from deerflow.config import get_app_config
from deerflow.utils.file_io import await_drained

logger = logging.getLogger(__name__)

_DEFAULT_PROVIDER = "auto"
_DEFAULT_TIMEOUT_S = 60.0
_SNIPPET_MAX_CHARS = 2000
_FETCH_MAX_CHARS = 4096
_FORMAT_ERROR = "WebRouter returned an unexpected response format"
_NOT_INSTALLED = "webrouter is not installed. Run: cd backend && uv sync --extra webrouter"


class _NotInstalledError(RuntimeError):
    pass


def _tool_settings(tool_name: str) -> dict:
    config = get_app_config().get_tool_config(tool_name)
    return dict(config.model_extra or {}) if config is not None else {}


def _timeout(settings: dict) -> float:
    value = settings.get("timeout")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        return _DEFAULT_TIMEOUT_S
    return float(value)


def _build_router(provider: str):
    """Import WebRouter and build its backends with their HTTP clients (blocking: TLS setup)."""
    try:
        from web_router import AsyncWebRouter
    except ImportError as e:
        raise _NotInstalledError(_NOT_INSTALLED) from e
    router = AsyncWebRouter(provider)
    router.warmup()
    return router


async def _open_router(provider: str):
    """Build the router off the event loop and close it if construction is cancelled."""
    construction = asyncio.create_task(asyncio.to_thread(_build_router, provider))
    try:
        return await asyncio.shield(construction)
    except asyncio.CancelledError:

        async def close_after_construction() -> None:
            try:
                router = await construction
                await router.aclose()
            except Exception as exc:
                logger.error("WebRouter cleanup after cancellation failed (%s)", type(exc).__name__)

        await await_drained(close_after_construction())
        raise


async def _close(router) -> None:
    """Close the router, finishing even if the caller is cancelled again meanwhile."""
    await await_drained(router.aclose())


def _provider(settings: dict) -> str:
    provider = settings.get("provider")
    return provider.strip() if isinstance(provider, str) and provider.strip() else _DEFAULT_PROVIDER


def _response_list(response: object, field: str) -> list | None:
    """Return a response's list field, or None if the response is malformed."""
    value = getattr(response, field, None)
    if value is None:
        return []
    if not isinstance(value, list):
        logger.error("WebRouter returned unexpected '%s' payload type: %s", field, type(value).__name__)
        return None
    return value


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


@tool("web_search", parse_docstring=True)
async def web_search_tool(query: str, max_results: int | None = None, time_range: SearchTimeRange | None = None) -> str:
    """Search the web for information. Use this tool to find current information, news, articles, and facts from the internet.

    Args:
        query: Search keywords or a question describing what you want to find. Be specific for better results.
        max_results: Maximum number of results to return. If omitted, uses the configured value (default 5).
        time_range: Optional relative publication/update window. Use only when the request requires recent results.
    """
    settings = await asyncio.to_thread(_tool_settings, "web_search")
    if max_results is None:
        max_results = settings.get("max_results")
    max_results = coerce_max_results(max_results, provider="WebRouter", logger=logger)

    search_kwargs: dict[str, object] = {"max_results": max_results, "timeout": _timeout(settings), "data_apis": False}
    if time_range is not None:
        search_kwargs["recency"] = time_range
    try:
        router = await _open_router(_provider(settings))
        try:
            response = await router.search(query, **search_kwargs)
        finally:
            await _close(router)
    except _NotInstalledError as e:
        return json.dumps({"error": str(e), "query": query}, ensure_ascii=False)
    except Exception as e:
        logger.error("WebRouter search failed: %s", type(e).__name__)
        return json.dumps({"error": f"WebRouter search failed: {str(e)[:500]}", "query": query}, ensure_ascii=False)

    results = _response_list(response, "results")
    if results is None:
        return json.dumps({"error": _FORMAT_ERROR, "query": query}, ensure_ascii=False)
    normalized_results = [
        {
            "title": _text(getattr(result, "title", None)),
            "url": safe_public_result_url(getattr(result, "url", None)),
            "snippet": (_text(getattr(result, "description", None)) or _text(getattr(result, "content", None)))[:_SNIPPET_MAX_CHARS],
        }
        for result in results[:max_results]
    ]
    if not normalized_results:
        return json.dumps({"error": "No results found", "query": query}, ensure_ascii=False)

    output: dict[str, object] = {"query": query, "provider": _text(getattr(response, "provider", None))}
    answer = _text(getattr(response, "answer", None))
    if answer:
        output["answer"] = answer
    output["total_results"] = len(normalized_results)
    output["results"] = normalized_results
    return json.dumps(output, indent=2, ensure_ascii=False)


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
    target_error = validate_hosted_fetch_url(url)
    if target_error:
        return target_error
    settings = await asyncio.to_thread(_tool_settings, "web_fetch")
    try:
        router = await _open_router(_provider(settings))
        try:
            from web_router import UnsupportedFormatError

            extract_kwargs = {"provider": _provider(settings), "timeout": _timeout(settings), "data_apis": False}
            try:
                response = await router.extract(url, format="markdown", **extract_kwargs)
            except UnsupportedFormatError:
                response = await router.extract(url, format="text", **extract_kwargs)
        finally:
            await _close(router)
    except _NotInstalledError as e:
        return f"Error: {e}"
    except Exception as e:
        logger.error("WebRouter fetch failed: %s", type(e).__name__)
        return f"Error: WebRouter fetch failed: {str(e)[:500]}"

    documents = _response_list(response, "documents")
    if documents is None:
        return f"Error: {_FORMAT_ERROR}"
    if not documents:
        # WebRouter raises when no page came back, so this is a defensive check.
        return "Error: No results found"

    document = documents[0]
    content = _text(getattr(document, "content", None))[:_FETCH_MAX_CHARS]
    if not content:
        return "Error: No content found"
    title = _text(getattr(document, "title", None)) or url
    return f"# {title}\n\n{content}"
