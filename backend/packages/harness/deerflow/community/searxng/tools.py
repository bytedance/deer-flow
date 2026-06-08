import json
import logging
from langchain.tools import tool
from deerflow.config import get_app_config
from deerflow.utils.readability import ReadabilityExtractor
from .searxng_client import SearxngClient

logger = logging.getLogger(__name__)
readability_extractor = ReadabilityExtractor()


def _get_searxng_client() -> SearxngClient:
    config = get_app_config().get_tool_config("web_search")
    base_url = "http://localhost:8088"
    if config is not None and "base_url" in config.model_extra:
        base_url = config.model_extra.get("base_url")
    return SearxngClient(base_url=base_url)


@tool("web_search", parse_docstring=True)
def web_search_tool(query: str) -> str:
    """Search the web using SearXNG.

    Args:
        query: The query to search for.
    """
    try:
        config = get_app_config().get_tool_config("web_search")
        max_results = 5
        if config is not None and "max_results" in config.model_extra:
            max_results = config.model_extra.get("max_results")

        client = _get_searxng_client()
        results = client.search(query, max_results=max_results)

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
    except Exception as e:
        logger.error(f"Error in web_search_tool: {e}")
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
        client = _get_searxng_client()
        html_content = client.fetch(url)
        if html_content.startswith("Error:"):
            return html_content

        article = readability_extractor.extract_article(html_content)
        return article.to_markdown()[:4096]
    except Exception as e:
        logger.error(f"Error in web_fetch_tool: {e}")
        return f"Error: {str(e)}"
