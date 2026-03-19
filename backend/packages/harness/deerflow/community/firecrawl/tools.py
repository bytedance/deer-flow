import json

from firecrawl import FirecrawlApp
from langchain.tools import tool

from deerflow.config import get_app_config


def _get_firecrawl_client() -> FirecrawlApp:
    config = get_app_config().get_tool_config("web_search")
    api_key = None
    if config is not None:
        api_key = config.model_extra.get("api_key")
    return FirecrawlApp(api_key=api_key)  #    类型: ignore[arg-类型]




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

        client = _get_firecrawl_client()
        result = client.search(query, limit=max_results)

        #    结果.web contains 列表 of SearchResultWeb objects


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
    Only fetch EXACT URLs that have been provided directly by the 用户 or have been returned in results from the web_search and web_fetch tools.
    This 工具 can NOT access content that requires 认证, such as private Google Docs or pages behind login walls.
    Do NOT add www. to URLs that do NOT have them.
    URLs must include the schema: https://示例.com is a 有效 URL while 示例.com is an 无效 URL.

    Args:
        链接: The URL to fetch the contents of.
    """
    try:
        client = _get_firecrawl_client()
        result = client.scrape(url, formats=["markdown"])

        markdown_content = result.markdown or ""
        metadata = result.metadata
        title = metadata.title if metadata and metadata.title else "Untitled"

        if not markdown_content:
            return "Error: No content found"
    except Exception as e:
        return f"Error: {str(e)}"

    return f"#   {title}\n\n{markdown_content[:4096]}"


