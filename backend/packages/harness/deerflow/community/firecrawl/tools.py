import json

from firecrawl import Firecrawl
from firecrawl.v2.types import ScrapeOptions
from langchain.tools import tool

from deerflow.config import get_app_config


def _get_firecrawl_client(tool_name: str = "web_search") -> Firecrawl:
    config = get_app_config().get_tool_config(tool_name)
    api_key = None
    if config is not None and "api_key" in config.model_extra:
        api_key = config.model_extra.get("api_key")
    return Firecrawl(api_key=api_key)  # type: ignore[arg-type]


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

        client = _get_firecrawl_client("web_search")
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
        config = get_app_config().get_tool_config("web_fetch")
        max_chars = 16384
        formats = ["markdown"]
        if config is not None:
            max_chars = config.model_extra.get("max_chars", max_chars)
            formats = config.model_extra.get("formats", formats)

        client = _get_firecrawl_client("web_fetch")
        result = client.scrape(url, formats=formats)

        markdown_content = result.markdown or ""
        metadata = result.metadata
        title = metadata.title if metadata and metadata.title else "Untitled"

        if not markdown_content:
            return "Error: No content found"
    except Exception as e:
        return f"Error: {str(e)}"

    return f"# {title}\n\n{markdown_content[:max_chars]}"


@tool("web_map", parse_docstring=True)
def web_map_tool(url: str) -> str:
    """Discover URLs on a website. Acts like a sitemap generator — given a URL,
    returns a list of URLs found on that site.

    Args:
        url: The website URL to map (e.g. https://example.com).
    """
    try:
        config = get_app_config().get_tool_config("web_map")
        limit = 100
        include_subdomains = True
        ignore_sitemap = False
        if config is not None:
            limit = config.model_extra.get("limit", limit)
            ignore_sitemap = config.model_extra.get("ignore_sitemap", ignore_sitemap)
            include_subdomains = config.model_extra.get("include_subdomains", include_subdomains)

        client = _get_firecrawl_client("web_map")
        result = client.map(
            url,
            limit=limit,
            include_subdomains=include_subdomains,
            sitemap="skip" if ignore_sitemap else None,
        )

        urls = getattr(result, "links", None) or []
        normalized = {
            "urls": urls,
            "total_count": len(urls),
        }
        return json.dumps(normalized, indent=2, ensure_ascii=False)
    except Exception as e:
        return f"Error: {str(e)}"


@tool("web_crawl", parse_docstring=True)
def web_crawl_tool(url: str) -> str:
    """Crawl a website starting from a given URL.

    Args:
        url: The starting URL to crawl from.
    """
    try:
        config = get_app_config().get_tool_config("web_crawl")
        max_discovery_depth = 2
        limit = 10
        allow_subdomains = True
        scrape_formats = ["markdown"]
        if config is not None:
            max_discovery_depth = config.model_extra.get("max_depth", max_discovery_depth)
            limit = config.model_extra.get("limit", limit)
            allow_subdomains = config.model_extra.get("allow_subdomains", allow_subdomains)
            scrape_formats = config.model_extra.get("scrape_formats", scrape_formats)

        client = _get_firecrawl_client("web_crawl")
        result = client.crawl(
            url,
            max_discovery_depth=max_discovery_depth,
            limit=limit,
            allow_subdomains=allow_subdomains,
            scrape_options=ScrapeOptions(formats=scrape_formats),  # type: ignore[arg-type]
        )

        pages = []
        for page in result.data or []:
            page_url = ""
            page_md = ""
            if isinstance(page, dict):
                page_url = page.get("url", "") or ""
                page_md = page.get("markdown", "") or ""
            else:
                page_url = getattr(page, "url", None) or ""
                page_md = getattr(page, "markdown", None) or ""
            pages.append(
                {
                    "url": page_url,
                    "markdown": page_md[:8192],
                }
            )

        return json.dumps(pages, indent=2, ensure_ascii=False)
    except Exception as e:
        return f"Error: {str(e)}"


@tool("web_interact", parse_docstring=True)
def web_interact_tool(url: str, actions: str) -> str:
    """Interact with a web page using browser automation. Opens a browser, performs
    the described actions, and returns the final page content.

    Use this tool to fill forms, click buttons, navigate dynamic pages, or any
    other browser-based interaction that requires simulating user behavior.

    ``actions`` must be a JSON array of action objects. Each object has a ``type``
    field and type-specific fields:

    - ``{"type": "wait", "milliseconds": 2000}`` — wait N ms
    - ``{"type": "click", "selector": "#login-btn"}`` — click an element
    - ``{"type": "write", "selector": "#search", "text": "hello"}`` — type text
    - ``{"type": "press", "key": "Enter"}`` — press a key
    - ``{"type": "scroll", "direction": "down", "amount": 300}`` — scroll
    - ``{"type": "screenshot", "full_page": true}`` — take a screenshot
    - ``{"type": "execute_javascript", "code": "..."}`` — run JS
    - ``{"type": "scrape", "selector": "body"}`` — extract HTML from a selector

    Args:
        url: The starting URL to open in the browser.
        actions: JSON array of browser action objects to perform on the page.
    """
    try:
        config = get_app_config().get_tool_config("web_interact")
        timeout = 30000
        wait_for = 2000
        formats = ["markdown"]
        if config is not None:
            timeout = config.model_extra.get("timeout", timeout)
            wait_for = config.model_extra.get("wait_for", wait_for)
            formats = config.model_extra.get("formats", formats)

        # Parse the action objects from JSON
        action_dicts = json.loads(actions)
        if not isinstance(action_dicts, list):
            return "Error: actions must be a JSON array of action objects"

        # Build structured action objects
        parsed_actions = []
        for act in action_dicts:
            act_type = act.get("type", "")
            if act_type == "wait":
                parsed_actions.append({"type": "wait", "milliseconds": act.get("milliseconds", 1000)})
            elif act_type == "click":
                parsed_actions.append({"type": "click", "selector": act["selector"]})
            elif act_type == "write":
                parsed_actions.append({"type": "write", "selector": act["selector"], "text": act["text"]})
            elif act_type == "press":
                parsed_actions.append({"type": "press", "key": act["key"]})
            elif act_type == "scroll":
                parsed_actions.append({"type": "scroll", "direction": act.get("direction", "down"), "amount": act.get("amount", 300)})
            elif act_type == "screenshot":
                parsed_actions.append({"type": "screenshot", "full_page": act.get("full_page", False)})
            elif act_type == "execute_javascript":
                parsed_actions.append({"type": "executeJavascript", "code": act["code"]})
            elif act_type == "scrape":
                parsed_actions.append({"type": "scrape", "selector": act.get("selector", "body")})
            else:
                return f"Error: unknown action type '{act_type}'"

        client = _get_firecrawl_client("web_interact")
        result = client.scrape(
            url,
            formats=formats,  # type: ignore[arg-type]
            actions=parsed_actions,  # type: ignore[arg-type]
            timeout=timeout,
            wait_for=wait_for,
        )

        markdown_content = getattr(result, "markdown", None) or ""
        if not markdown_content:
            return "Error: No content returned"

        return markdown_content
    except json.JSONDecodeError:
        return "Error: actions must be valid JSON"
    except Exception as e:
        return f"Error: {str(e)}"


@tool("structured_extract", parse_docstring=True)
def structured_extract_tool(
    urls: list[str],
    prompt: str,
    schema: dict | None = None,
) -> str:
    """Extract structured data from web pages using an LLM-powered schema.

    Provide a list of URLs and a prompt describing what data to extract. Optionally
    supply a JSON schema dict to enforce a specific output structure; if omitted,
    Firecrawl will infer the schema from the prompt.

    Args:
        urls: List of URLs to extract data from.
        prompt: Natural-language description of the data to extract (e.g. "Extract product name, price, and rating for each product").
        schema: Optional JSON schema dict defining the expected output structure.
    """
    try:
        config = get_app_config().get_tool_config("structured_extract")
        max_urls = 10
        if config is not None:
            max_urls = config.model_extra.get("max_urls", max_urls)

        client = _get_firecrawl_client("structured_extract")

        trimmed_urls = urls[:max_urls]
        kwargs = {
            "urls": trimmed_urls,
            "prompt": prompt,
        }
        if schema is not None:
            kwargs["schema"] = schema

        result = client.extract(**kwargs)

        data = getattr(result, "data", None)
        if data is None:
            return json.dumps(
                {"error": "No data returned from extraction", "success": False},
                indent=2,
                ensure_ascii=False,
            )

        return json.dumps(data, indent=2, ensure_ascii=False)
    except Exception as e:
        return f"Error: {str(e)}"
