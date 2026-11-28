"""Built-in web search backed by the public Parallel MCP server."""

from __future__ import annotations

import asyncio
import json
import logging

import httpx
from langchain.tools import tool
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from deerflow.community.search_max_results import DEFAULT_MAX_RESULTS, coerce_max_results
from deerflow.community.search_time_range import SearchTimeRange
from deerflow.community.url_safety import safe_public_result_url
from deerflow.config import get_app_config
from deerflow.utils.file_io import await_drained

logger = logging.getLogger(__name__)

_ENDPOINT = "https://mcp.parallel.ai/mcp?tools=web_search"
_TIMEOUT = 20


@tool("web_search", parse_docstring=True)
async def web_search_tool(query: str, max_results: int = DEFAULT_MAX_RESULTS, time_range: SearchTimeRange | None = None) -> str:
    """Search the web for information, news, articles, and facts.

    Args:
        query: Search keywords describing what you want to find.
        max_results: Maximum number of results to return. Default is 5.
        time_range: Optional recency preference. Use only when the request requires recent results.
    """
    config = (await asyncio.to_thread(get_app_config)).get_tool_config("web_search")
    if config is not None:
        max_results = (config.model_extra or {}).get("max_results", max_results)
    limit = coerce_max_results(max_results, provider="Parallel Search", logger=logger)
    objective = f"{query}. Prioritize results from the past {time_range}." if time_range else query

    client: httpx.AsyncClient | None = None
    rate_limited = False

    async def record_rate_limit(response: httpx.Response) -> None:
        nonlocal rate_limited
        if response.status_code == 429:
            rate_limited = True

    async def open_client() -> None:
        nonlocal client
        client = await asyncio.to_thread(
            httpx.AsyncClient,
            headers={"User-Agent": "deer-flow"},
            timeout=_TIMEOUT,
            event_hooks={"response": [record_rate_limit]},
        )

    def error(message: str) -> str:
        return json.dumps({"query": query, "error": message}, ensure_ascii=False)

    try:
        # TLS trust loading runs in a worker. Drain construction on cancellation
        # so the finally block can close a client returned after cancellation.
        async with asyncio.timeout(_TIMEOUT):
            await await_drained(open_client())
            async with (
                streamable_http_client(_ENDPOINT, http_client=client) as (read, write, _),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                reply = await session.call_tool("web_search", {"objective": objective, "search_queries": [query]})
    except Exception as exc:
        logger.warning("Parallel Search request failed (%s)", type(exc).__name__)
        if rate_limited:
            return error("Parallel Search rate limit reached. Try again later or choose another web search provider.")
        if isinstance(exc, TimeoutError):
            return error("Parallel Search request timed out.")
        return error("Parallel Search request failed.")
    finally:
        if client is not None:
            await await_drained(client.aclose())

    if reply.isError:
        return error("Parallel Search reported a search error.")

    payload = reply.structuredContent
    if not isinstance(payload, dict):
        logger.warning("Invalid Parallel Search structuredContent type: %s", type(payload).__name__)
        return error("Invalid Parallel Search response.")
    rows = payload.get("results")
    if rows is None:
        rows = []
    if not isinstance(rows, list):
        logger.warning("Invalid Parallel Search results type: %s", type(rows).__name__)
        return error("Invalid Parallel Search response.")
    results = []
    for row in rows:
        if not isinstance(row, dict):
            logger.warning("Invalid Parallel Search result type: %s", type(row).__name__)
            continue
        title = row.get("title")
        excerpts = row.get("excerpts")
        results.append(
            {
                "title": title if isinstance(title, str) else "",
                "url": safe_public_result_url(row.get("url")),
                "content": "\n\n".join(excerpt for excerpt in excerpts if isinstance(excerpt, str)) if isinstance(excerpts, list) else "",
            }
        )
        if len(results) == limit:
            break
    if rows and not results:
        return error("Invalid Parallel Search response.")
    return json.dumps({"query": query, "total_results": len(results), "results": results}, ensure_ascii=False)
