import json
import urllib.request
import urllib.parse

from langchain.tools import tool

from src.config import get_app_config


def _get_base_url() -> str:
    config = get_app_config().get_tool_config("web_search")
    if config is not None and "base_url" in config.model_extra:
        return config.model_extra.get("base_url")
    return "http://127.0.0.1:8080"


@tool("web_search", parse_docstring=True)
def web_search_tool(query: str) -> str:
    """Search the web.

    Args:
        query: The query to search for.
    """
    config = get_app_config().get_tool_config("web_search")
    max_results = 5
    if config is not None and "max_results" in config.model_extra:
        max_results = config.model_extra.get("max_results")

    base_url = _get_base_url()
    params = urllib.parse.urlencode({"q": query, "format": "json"})
    url = f"{base_url}/search?{params}"

    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())

    results = data.get("results", [])[:max_results]
    normalized = [
        {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "snippet": r.get("content", ""),
        }
        for r in results
    ]
    return json.dumps(normalized, indent=2, ensure_ascii=False)


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
    config = get_app_config().get_tool_config("web_fetch")
    timeout = 10
    if config is not None and "timeout" in config.model_extra:
        timeout = config.model_extra.get("timeout")
    max_content_chars = 16384
    if config is not None and "max_content_chars" in config.model_extra:
        max_content_chars = config.model_extra.get("max_content_chars")

    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; DeerFlow/2.0)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        content_type = resp.headers.get("Content-Type", "")
        raw = resp.read()

    if "text/html" in content_type:
        try:
            from src.utils.readability import ReadabilityExtractor
            extractor = ReadabilityExtractor()
            article = extractor.extract_article(raw.decode("utf-8", errors="replace"))
            return article.to_markdown()[:max_content_chars]
        except Exception:
            pass

    text = raw.decode("utf-8", errors="replace")
    return text[:max_content_chars]
