import logging
from langchain.tools import tool
from deerflow.config import get_app_config
from deerflow.utils.readability import ReadabilityExtractor
from .browserless_client import BrowserlessClient

logger = logging.getLogger(__name__)
readability_extractor = ReadabilityExtractor()


def _get_browserless_client() -> BrowserlessClient:
    config = get_app_config().get_tool_config("web_fetch")
    base_url = "http://localhost:3032"
    token = ""
    timeout_s = 30.0
    if config is not None and config.model_extra:
        base_url = config.model_extra.get("base_url", base_url)
        token = config.model_extra.get("token", token)
        timeout_s = float(config.model_extra.get("timeout_s", timeout_s))
    return BrowserlessClient(base_url=base_url, token=token, timeout_s=timeout_s)


@tool("web_fetch", parse_docstring=True)
def web_fetch_tool(url: str) -> str:
    """Fetch the contents of a web page at a given URL using Browserless (headless Chrome).
    Only fetch EXACT URLs that have been provided directly by the user or have been returned in results from the web_search and web_fetch tools.
    This tool can NOT access content that requires authentication, such as private Google Docs or pages behind login walls.
    Do NOT add www. to URLs that do NOT have them.
    URLs must include the schema: https://example.com is a valid URL while example.com is an invalid URL.

    Args:
        url: The URL to fetch the contents of.
    """
    try:
        config = get_app_config().get_tool_config("web_fetch")

        wait_until = "networkidle2"
        goto_timeout_ms = 30000
        wait_for_timeout_ms = 0
        wait_for_selector = ""
        wait_for_selector_timeout_ms = 5000
        best_attempt = True
        reject_resource_types: list[str] | None = None
        reject_request_pattern: list[str] | None = None

        if config is not None and config.model_extra:
            wait_until = config.model_extra.get("wait_until", wait_until)
            goto_timeout_ms = int(config.model_extra.get("goto_timeout_ms", goto_timeout_ms))
            wait_for_timeout_ms = int(config.model_extra.get("wait_for_timeout_ms", wait_for_timeout_ms))
            wait_for_selector = config.model_extra.get("wait_for_selector", wait_for_selector)
            best_attempt = bool(config.model_extra.get("best_attempt", best_attempt))

        client = _get_browserless_client()
        html = client.fetch_html(
            url=url,
            wait_until=wait_until,
            goto_timeout_ms=goto_timeout_ms,
            wait_for_timeout_ms=wait_for_timeout_ms,
            wait_for_selector=wait_for_selector,
            wait_for_selector_timeout_ms=wait_for_selector_timeout_ms,
            best_attempt=best_attempt,
            reject_resource_types=reject_resource_types,
            reject_request_pattern=reject_request_pattern,
        )

        if html.startswith("Error:"):
            return html

        article = readability_extractor.extract_article(html)
        return article.to_markdown()[:4096]

    except Exception as e:
        logger.error(f"Error in web_fetch_tool: {e}")
        return f"Error: {str(e)}"
