import json
import os

from firecrawl import FirecrawlApp
from langchain.tools import tool

from deerflow.config import get_app_config

# fastCRW is a Firecrawl-compatible web data engine (single Rust binary; self-host
# or cloud). Because the REST API is Firecrawl-compatible, this provider reuses the
# Firecrawl client and only swaps the base URL. Cloud default points at the managed
# service; override `base_url` in the tool config (or set CRW_API_URL) for self-host.
DEFAULT_BASE_URL = "https://fastcrw.com/api"


def _get_fastcrw_client(tool_name: str = "web_search") -> FirecrawlApp:
    config = get_app_config().get_tool_config(tool_name)
    api_key = None
    base_url = None
    if config is not None:
        if "api_key" in config.model_extra:
            api_key = config.model_extra.get("api_key")
        if "base_url" in config.model_extra:
            base_url = config.model_extra.get("base_url")
    if api_key is None:
        api_key = os.getenv("CRW_API_KEY")
    if base_url is None:
        base_url = os.getenv("CRW_API_URL", DEFAULT_BASE_URL)
    return FirecrawlApp(api_key=api_key, api_url=base_url)  # type: ignore[arg-type]


@tool("web_search", parse_docstring=True)
def web_search_tool(query: str) -> str:
    """Search the web.

    Args:
        query: The query to search for.
    """
    try:
        config = get_app_config().get_tool_config("web_search")
        max_results = 5
        if config is not None:
            max_results = config.model_extra.get("max_results", max_results)

        client = _get_fastcrw_client("web_search")
        result = client.search(query, limit=max_results)

        # result.web contains list of SearchResultWeb objects
        web_results = result.web or []
        normalized_results = [
            {
                "title": getattr(item, "title", "") or "",
                "url": getattr(item, "url", "") or "",
                "snippet": getattr(item, "description", "") or "",
            }
            for item in web_results
        ]
        json_results = json.dumps(normalized_results, indent=2, ensure_ascii=False)
        return json_results
    except Exception as e:
        return f"Error: {str(e)}"


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
    try:
        client = _get_fastcrw_client("web_fetch")
        result = client.scrape(url, formats=["markdown"])

        markdown_content = result.markdown or ""
        metadata = result.metadata
        title = metadata.title if metadata and metadata.title else "Untitled"

        if not markdown_content:
            return "Error: No content found"
    except Exception as e:
        return f"Error: {str(e)}"

    return f"# {title}\n\n{markdown_content[:4096]}"
