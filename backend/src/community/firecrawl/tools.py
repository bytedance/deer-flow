from firecrawl import AsyncFirecrawlApp
from langchain.tools import tool

from src.community.tool_utils import DEFAULT_CONTENT_LIMIT, DEFAULT_MAX_RESULTS, format_search_results, get_tool_extra


def _get_firecrawl_client() -> AsyncFirecrawlApp:
    api_key = get_tool_extra("web_search", "api_key")
    return AsyncFirecrawlApp(api_key=api_key)  # type: ignore[arg-type]


@tool("web_search", parse_docstring=True)
async def web_search_tool(query: str) -> str:
    """Search the web.

    Args:
        query: The query to search for.
    """
    try:
        max_results = get_tool_extra("web_search", "max_results", DEFAULT_MAX_RESULTS)
        client = _get_firecrawl_client()
        result = await client.search(query, limit=max_results)

        web_results = result.web or []
        normalized = [
            {
                "title": getattr(item, "title", "") or "",
                "url": getattr(item, "url", "") or "",
                "snippet": getattr(item, "description", "") or "",
            }
            for item in web_results
        ]
        return format_search_results(normalized)
    except Exception as e:
        return f"Error: {e}"


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
    try:
        client = _get_firecrawl_client()
        result = await client.scrape(url, formats=["markdown"])

        markdown_content = result.markdown or ""
        metadata = result.metadata
        title = metadata.title if metadata and metadata.title else "Untitled"

        if not markdown_content:
            return "Error: No content found"
    except Exception as e:
        return f"Error: {e}"

    return f"# {title}\n\n{markdown_content[:DEFAULT_CONTENT_LIMIT]}"
