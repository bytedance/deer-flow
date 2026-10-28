import asyncio
import json
import logging

from langchain.tools import tool

from deerflow.community.search_time_range import SearchTimeRange
from deerflow.community.url_safety import safe_public_result_url
from deerflow.config import get_app_config

from .searxng_client import SearxngClient, SearxngResponseError

logger = logging.getLogger(__name__)


def _unexpected_format_error(query: str) -> str:
    """Report a malformed instance payload without echoing the payload.

    A SearXNG instance that answers HTTP 200 with an error page, a non-list
    ``results`` container, or a non-empty list holding no objects is not an
    empty search: "No results found" would tell the agent the query legitimately
    matched nothing.

    The query is echoed back on purpose, matching the sibling providers, so the
    agent can tell which search the error belongs to; only the payload is
    withheld.
    """
    return json.dumps({"error": "SearXNG returned an unexpected response format", "query": query}, ensure_ascii=False)


def _get_tool_config(tool_name: str) -> dict | None:
    """Get tool config extras safely, returning None if not configured."""
    config = get_app_config().get_tool_config(tool_name)
    if config is None:
        return None
    extras = config.model_extra
    return extras if extras is not None else {}


_UNSET = object()


def _get_searxng_client(cfg: dict | None = _UNSET) -> SearxngClient:
    """Build a SearXNG client, from ``cfg`` when the caller already read it."""
    if cfg is _UNSET:
        cfg = _get_tool_config("web_search")
    base_url = "http://localhost:8088"
    if cfg is not None:
        base_url = cfg.get("base_url", base_url)
    return SearxngClient(base_url=base_url)


@tool("web_search", parse_docstring=True)
async def web_search_tool(query: str, time_range: SearchTimeRange | None = None) -> str:
    """Search the web using SearXNG.

    Args:
        query: The query to search for.
        time_range: Optional relative publication/update window. Use only when the request requires recent results.
    """
    try:
        # Config resolution stats and hashes the config files; keep it off the
        # event loop, and build the client from the same read.
        cfg = await asyncio.to_thread(_get_tool_config, "web_search")
        max_results = 5
        if cfg is not None:
            raw = cfg.get("max_results", max_results)
            if isinstance(raw, int):
                max_results = raw
            else:
                try:
                    max_results = int(raw)
                except (TypeError, ValueError, OverflowError):
                    logger.warning(
                        "Invalid SearXNG max_results=%r; using default %s",
                        raw,
                        max_results,
                    )

        client = _get_searxng_client(cfg)
        search_kwargs: dict[str, object] = {"max_results": max_results}
        if time_range is not None:
            search_kwargs["time_range"] = time_range
        results = await client.search(query, **search_kwargs)

        normalized = [
            {
                "title": r.get("title", ""),
                "url": safe_public_result_url(r.get("url")),
                "snippet": r.get("content", ""),
            }
            for r in results
        ]
        return json.dumps(normalized, indent=2, ensure_ascii=False)
    except SearxngResponseError:
        return _unexpected_format_error(query)
    except Exception as e:
        logger.error(f"Error in web_search_tool: {e}")
        return json.dumps({"error": str(e), "query": query}, ensure_ascii=False)
