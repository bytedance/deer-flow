import asyncio
import logging

from langchain.tools import tool

from deerflow.config import get_app_config
from deerflow.utils.readability import ReadabilityExtractor

from .browserless_client import BrowserlessClient

logger = logging.getLogger(__name__)

# readability_extractor runs CPU-bound parsing; always call via asyncio.to_thread
_readability_extractor = ReadabilityExtractor()


def _get_tool_config(tool_name: str) -> dict | None:
    """Get tool config extras safely, returning None if not configured."""
    config = get_app_config().get_tool_config(tool_name)
    if config is None:
        return None
    extras = config.model_extra
    return extras if extras is not None else {}


def _get_browserless_client() -> BrowserlessClient:
    cfg = _get_tool_config("web_fetch")
    base_url = "http://localhost:3032"
    token = ""
    timeout_s = 30.0
    if cfg is not None:
        base_url = cfg.get("base_url", base_url)
        token = cfg.get("token", token)
        raw = cfg.get("timeout_s", timeout_s)
        timeout_s = float(raw) if not isinstance(raw, float) else raw
    return BrowserlessClient(base_url=base_url, token=token, timeout_s=timeout_s)


@tool("web_fetch", parse_docstring=True)
async def web_fetch_tool(url: str) -> str:
    """Fetch the contents of a web page at a given URL using Browserless (headless Chrome).
    Only fetch EXACT URLs that have been provided directly by the user or have been returned in results from the web_search and web_fetch tools.
    This tool can NOT access content that requires authentication, such as private Google Docs or pages behind login walls.
    Do NOT add www. to URLs that do NOT have them.
    URLs must include the schema: https://example.com is a valid URL while example.com is an invalid URL.

    Args:
        url: The URL to fetch the contents of.
    """
    try:
        cfg = _get_tool_config("web_fetch")

        wait_for_event = ""
        wait_for_timeout_ms = 0
        wait_for_selector = ""
        wait_for_selector_timeout_ms = 5000
        reject_resource_types: list[str] | None = None
        reject_request_pattern: list[str] | None = None

        if cfg is not None:
            wait_for_event = cfg.get("wait_for_event", wait_for_event)
            raw_wait = cfg.get("wait_for_timeout_ms", wait_for_timeout_ms)
            wait_for_timeout_ms = int(raw_wait) if not isinstance(raw_wait, int) else raw_wait
            wait_for_selector = cfg.get("wait_for_selector", wait_for_selector)

        client = _get_browserless_client()
        html = await client.fetch_html(
            url=url,
            wait_for_event=wait_for_event,
            wait_for_timeout_ms=wait_for_timeout_ms,
            wait_for_selector=wait_for_selector,
            wait_for_selector_timeout_ms=wait_for_selector_timeout_ms,
            reject_resource_types=reject_resource_types,
            reject_request_pattern=reject_request_pattern,
        )

        if html.startswith("Error:"):
            return html

        article = await asyncio.to_thread(_readability_extractor.extract_article, html)
        return article.to_markdown()[:4096]

    except Exception as e:
        logger.error(f"Error in web_fetch_tool: {e}")
        return f"Error: {str(e)}"
