import json
import logging

from langchain.tools import tool
from tavily import AsyncTavilyClient

from deerflow.community.search_time_range import SearchTimeRange
from deerflow.config import get_app_config

logger = logging.getLogger(__name__)

_FORMAT_ERROR = "Tavily returned an unexpected response format"


def _get_tavily_client(tool_name: str = "web_search") -> AsyncTavilyClient:
    config = get_app_config().get_tool_config(tool_name)
    api_key = None
    if config is not None and "api_key" in config.model_extra:
        api_key = config.model_extra.get("api_key")
    return AsyncTavilyClient(api_key=api_key)


def _response_objects(data: object, container: str) -> list[dict] | None:
    """Return the object entries of a Tavily response container, or None if malformed.

    A missing or null container is empty; a container that is not a list, or a
    non-empty list holding no objects, is malformed: the caller reports a format
    error rather than returning a result the agent would misread.
    """
    if not isinstance(data, dict):
        logger.error("Tavily returned unexpected payload type: %s", type(data).__name__)
        return None
    value = data.get(container)
    if value is None:
        return []
    if not isinstance(value, list):
        logger.error("Tavily returned unexpected '%s' payload type: %s", container, type(value).__name__)
        return None
    objects = [item for item in value if isinstance(item, dict)]
    if value and not objects:
        logger.error("Tavily returned '%s' with no usable result objects", container)
        return None
    return objects


@tool("web_search", parse_docstring=True)
async def web_search_tool(query: str, time_range: SearchTimeRange | None = None) -> str:
    """Search the web.

    Args:
        query: The query to search for.
        time_range: Optional relative publication/update window. Use only when the request requires recent results.
    """
    config = get_app_config().get_tool_config("web_search")
    max_results = 5
    if config is not None and "max_results" in config.model_extra:
        max_results = config.model_extra.get("max_results")

    search_kwargs: dict[str, object] = {"max_results": max_results}
    if config is not None:
        for key in ("include_domains", "exclude_domains"):
            if key in config.model_extra:
                search_kwargs[key] = config.model_extra[key]
    if search_kwargs.get("include_domains"):
        search_kwargs["include_domains_mode"] = "filter"
    if time_range is not None:
        search_kwargs["time_range"] = time_range
    client = _get_tavily_client()
    try:
        res = await client.search(query, **search_kwargs)
    finally:
        await client.close()
    results = _response_objects(res, "results")
    if results is None:
        return json.dumps({"error": _FORMAT_ERROR, "query": query}, ensure_ascii=False)
    normalized_results = [
        {
            "title": result.get("title", ""),
            "url": result.get("url", ""),
            "snippet": result.get("content", ""),
        }
        for result in results
    ]
    json_results = json.dumps(normalized_results, indent=2, ensure_ascii=False)
    return json_results


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
    client = _get_tavily_client("web_fetch")
    try:
        res = await client.extract([url])
    finally:
        await client.close()
    failed = _response_objects(res, "failed_results")
    if failed is None:
        return f"Error: {_FORMAT_ERROR}"
    if failed:
        error = failed[0].get("error")
        return f"Error: {error}" if error else "Error: Extraction failed"
    results = _response_objects(res, "results")
    if results is None:
        return f"Error: {_FORMAT_ERROR}"
    if not results:
        return "Error: No results found"
    result = results[0]
    # Extract results guarantee a URL and content, but not a page title.
    title = result.get("title") or result.get("url") or url
    raw_content = result.get("raw_content")
    if not isinstance(raw_content, str):
        raw_content = "" if raw_content is None else str(raw_content)
    return f"# {title}\n\n{raw_content[:4096]}"
