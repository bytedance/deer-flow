from langchain.tools import tool

from src.community.jina_ai.jina_client import JinaClient
from src.community.tool_utils import DEFAULT_CONTENT_LIMIT, get_tool_extra
from src.utils.readability import ReadabilityExtractor

readability_extractor = ReadabilityExtractor()


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
    jina_client = JinaClient()
    timeout = get_tool_extra("web_fetch", "timeout", 10)
    html_content = await jina_client.crawl(url, return_format="html", timeout=timeout)
    article = readability_extractor.extract_article(html_content)
    return article.to_markdown()[:DEFAULT_CONTENT_LIMIT]
