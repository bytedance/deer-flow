import json
import logging

from langchain.tools import tool
from tavily import TavilyClient

from deerflow.community.search_time_range import SearchTimeRange
from deerflow.config import get_app_config

logger = logging.getLogger(__name__)

DEFAULT_MAX_RESULTS = 5


def _coerce_max_results(value: object) -> int:
    """Normalize config values before passing them to the Tavily API."""
    if isinstance(value, bool) or (isinstance(value, float) and not value.is_integer()):
        # int() accepts booleans and silently truncates a YAML value such as 3.5;
        # int() on an out-of-range float (e.g. YAML .inf) raises OverflowError.
        count = 0
    else:
        try:
            count = int(value)  # type: ignore[call-overload]
        except (TypeError, ValueError, OverflowError):
            count = 0
    if count <= 0:
        logger.warning("Invalid Tavily max_results=%r; using default %s", value, DEFAULT_MAX_RESULTS)
        return DEFAULT_MAX_RESULTS
    return count


def _get_tavily_client(tool_name: str = "web_search") -> TavilyClient:
    config = get_app_config().get_tool_config(tool_name)
    api_key = None
    if config is not None and "api_key" in config.model_extra:
        api_key = config.model_extra.get("api_key")
    return TavilyClient(api_key=api_key)


@tool("web_search", parse_docstring=True)
def web_search_tool(query: str, time_range: SearchTimeRange | None = None) -> str:
    """Search the web.

    Args:
        query: The query to search for.
        time_range: Optional relative publication/update window. Use only when the request requires recent results.
    """
    config = get_app_config().get_tool_config("web_search")
    max_results = DEFAULT_MAX_RESULTS
    if config is not None and "max_results" in config.model_extra:
        max_results = _coerce_max_results(config.model_extra.get("max_results"))

    client = _get_tavily_client()
    search_kwargs: dict[str, object] = {"max_results": max_results}
    if config is not None:
        for key in ("include_domains", "exclude_domains"):
            if key in config.model_extra:
                search_kwargs[key] = config.model_extra[key]
    if search_kwargs.get("include_domains"):
        search_kwargs["include_domains_mode"] = "filter"
    if time_range is not None:
        search_kwargs["time_range"] = time_range
    res = client.search(query, **search_kwargs)
    normalized_results = [
        {
            "title": result["title"],
            "url": result["url"],
            "snippet": result["content"],
        }
        for result in res["results"]
    ]
    json_results = json.dumps(normalized_results, indent=2, ensure_ascii=False)
    return json_results


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
    client = _get_tavily_client("web_fetch")
    res = client.extract([url])
    if "failed_results" in res and len(res["failed_results"]) > 0:
        return f"Error: {res['failed_results'][0]['error']}"
    elif "results" in res and len(res["results"]) > 0:
        result = res["results"][0]
        # Extract results guarantee a URL and content, but not a page title.
        title = result.get("title") or result.get("url") or url
        return f"# {title}\n\n{result['raw_content'][:4096]}"
    else:
        return "Error: No results found"
