from langchain.tools import tool
from tavily import AsyncTavilyClient

from src.community.tool_utils import DEFAULT_CONTENT_LIMIT, DEFAULT_MAX_RESULTS, format_search_results, get_tool_extra


def _get_tavily_client() -> AsyncTavilyClient:
    api_key = get_tool_extra("web_search", "api_key")
    return AsyncTavilyClient(api_key=api_key)


@tool("web_search", parse_docstring=True)
async def web_search_tool(query: str) -> str:
    """Search the web.

    Args:
        query: The query to search for.
    """
    max_results = get_tool_extra("web_search", "max_results", DEFAULT_MAX_RESULTS)
    client = _get_tavily_client()
    res = await client.search(query, max_results=max_results)
    normalized = [{"title": r["title"], "url": r["url"], "snippet": r["content"]} for r in res["results"]]
    return format_search_results(normalized)


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
    client = _get_tavily_client()
    res = await client.extract([url])
    if "failed_results" in res and len(res["failed_results"]) > 0:
        return f"Error: {res['failed_results'][0]['error']}"
    elif "results" in res and len(res["results"]) > 0:
        result = res["results"][0]
        return f"# {result['title']}\n\n{result['raw_content'][:DEFAULT_CONTENT_LIMIT]}"
    else:
        return "Error: No results found"
