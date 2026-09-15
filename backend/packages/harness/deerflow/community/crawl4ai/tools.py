import logging

from langchain.tools import tool

from deerflow.community.url_safety import validate_public_http_url
from deerflow.config import get_app_config

from .crawl4ai_client import Crawl4AiClient

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://localhost:11235"
DEFAULT_TIMEOUT_S = 30
DEFAULT_FILTER = "fit"
VALID_FILTERS = ("fit", "raw", "bm25", "llm")


def _get_tool_config(tool_name: str) -> dict | None:
    """Return the tool's config extras (model_extra) dict, or None if unconfigured."""
    config = get_app_config().get_tool_config(tool_name)
    if config is None:
        return None
    extras = config.model_extra
    return extras if extras is not None else {}


def _coerce_timeout(value: object, default: int) -> float:
    """Coerce a config timeout into seconds, falling back to ``default`` on bad input.

    Mirrors ``jina_ai._coerce_timeout``: booleans and non-numeric strings fall
    back to the default so e.g. ``timeout: off`` (YAML ``False``) does not become
    ``0.0`` and time out every request against a healthy server.
    """
    if isinstance(value, bool):
        return float(default)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            logger.warning("Crawl4AI web_fetch: invalid timeout %r in config; using %ss", value, default)
    return float(default)


def _coerce_bool(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default


def _coerce_filter(value: object) -> str:
    """Normalize and validate the markdown filter, falling back to the default.

    Catches typos / stale values (e.g. ``FIt``, ``fit_content``) at config-read
    time instead of letting them reach the server as an opaque HTTP 400.
    """
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in VALID_FILTERS:
            return normalized
        logger.warning("Crawl4AI web_fetch: unknown filter %r in config; using %r (valid: %s)", value, DEFAULT_FILTER, ", ".join(VALID_FILTERS))
    return DEFAULT_FILTER


def _build_client(cfg: dict | None) -> Crawl4AiClient:
    """Build a ``Crawl4AiClient`` from an already-read ``web_fetch`` config dict.

    Takes the config as an argument (rather than reading it again) so a single
    invocation reads ``get_app_config()`` exactly once and cannot split across a
    concurrent hot-reload.
    """
    base_url = DEFAULT_BASE_URL
    token = ""
    timeout_s: float = float(DEFAULT_TIMEOUT_S)
    if cfg is not None:
        base_url = cfg.get("base_url", base_url)
        token = cfg.get("token", token)
        timeout_s = _coerce_timeout(cfg.get("timeout"), DEFAULT_TIMEOUT_S)
    return Crawl4AiClient(base_url=base_url, token=token, timeout_s=timeout_s)


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
        cfg = _get_tool_config("web_fetch")  # read config once; pass the values down
        allow_private_addresses = _coerce_bool(cfg.get("allow_private_addresses") if cfg is not None else None, False)
        url_error = validate_public_http_url(url, allow_private_addresses=allow_private_addresses)
        if url_error:
            return url_error
        filter_mode = _coerce_filter(cfg.get("filter") if cfg is not None else None)
        client = _build_client(cfg)
        markdown = await client.fetch_markdown(url, filter_mode=filter_mode)

        if markdown.startswith("Error:"):
            return markdown

        return markdown[:4096]

    except Exception as e:
        logger.error(f"Error in web_fetch_tool: {e}")
        return f"Error: {str(e)}"
