import asyncio
import inspect
import json
import logging

from firecrawl import AsyncFirecrawlApp
from langchain.tools import tool

from deerflow.community.url_safety import validate_delegated_backend_url, validate_public_http_url
from deerflow.config import get_app_config

logger = logging.getLogger(__name__)


async def _aclose_firecrawl_client(client: AsyncFirecrawlApp) -> None:
    """Best-effort close of the pooled async HTTP client a per-call app constructed.

    ``AsyncFirecrawlApp`` eagerly builds an ``httpx.AsyncClient``-backed pool in
    its constructor and exposes no public teardown, so reach it through the
    delegating v2 client. The declared dependency range (``firecrawl-py>=1.15.0``)
    includes versions without that attribute, and teardown runs from a
    ``finally`` — absence or failure here must never mask the tool's own result.
    """
    pooled = getattr(getattr(client, "_v2_client", None), "async_http_client", None)
    if pooled is None:
        return
    try:
        close = getattr(pooled, "close", None)
        if not callable(close):
            logger.warning("Firecrawl async HTTP pool has no close method")
            return
        result = close()
        if inspect.isawaitable(result):
            await result
    except Exception:
        logger.warning("Failed to close the Firecrawl async HTTP pool", exc_info=True)


DEFAULT_MAX_RESULTS = 5


def _coerce_max_results(value: object) -> int:
    """Normalize the configured ``max_results`` before handing it to Firecrawl."""
    if isinstance(value, bool) or (isinstance(value, float) and not value.is_integer()):
        # int() accepts booleans and silently truncates a YAML value such as 3.5.
        count = 0
    else:
        try:
            count = int(value)  # type: ignore[call-overload]
        except (TypeError, ValueError, OverflowError):
            count = 0
    if count <= 0:
        logger.warning("Invalid Firecrawl max_results=%r; using default %s", value, DEFAULT_MAX_RESULTS)
        return DEFAULT_MAX_RESULTS
    return count


def _get_tool_config_extra(tool_name: str) -> dict:
    config = get_app_config().get_tool_config(tool_name)
    return dict(config.model_extra or {}) if config is not None else {}


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


def _validate_backend_base_url(cfg: dict, base_url: str) -> str | None:
    """Refuse delegation to a self-hosted Firecrawl backend unless its egress is isolated.

    Firecrawl resolves the target URL, follows redirects, and loads subresources
    in the Firecrawl service's own network namespace, so the target-URL screen
    cannot be enforced end-to-end. Delegation is only safe when the backend's
    outbound network is isolated from private and metadata networks, which the
    operator confirms via ``network_isolation_confirmed``. Blocking; call via
    ``asyncio.to_thread``.
    """
    network_isolation_confirmed = _coerce_bool(cfg.get("network_isolation_confirmed"), False)
    return validate_delegated_backend_url(base_url, network_isolation_confirmed=network_isolation_confirmed)


def _get_firecrawl_client(tool_name: str = "web_search", api_url: str | None = None) -> AsyncFirecrawlApp:
    config = get_app_config().get_tool_config(tool_name)
    api_key = None
    if config is not None:
        if "api_key" in config.model_extra:
            api_key = config.model_extra.get("api_key")
        if api_url is None and "base_url" in config.model_extra:
            api_url = config.model_extra.get("base_url")
    kwargs = {"api_key": api_key}
    if api_url:
        kwargs["api_url"] = api_url
    return AsyncFirecrawlApp(**kwargs)  # type: ignore[arg-type]


@tool("web_search", parse_docstring=True)
async def web_search_tool(query: str) -> str:
    """Search the web.

    Args:
        query: The query to search for.
    """
    client: AsyncFirecrawlApp | None = None
    try:
        config = get_app_config().get_tool_config("web_search")
        max_results = DEFAULT_MAX_RESULTS
        if config is not None:
            max_results = _coerce_max_results(config.model_extra.get("max_results", max_results))

        client = _get_firecrawl_client("web_search")
        result = await client.search(query, limit=max_results)

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
    finally:
        if client is not None:
            await _aclose_firecrawl_client(client)


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
    client: AsyncFirecrawlApp | None = None
    try:
        cfg = _get_tool_config_extra("web_fetch")
        allow_private_addresses = _coerce_bool(cfg.get("allow_private_addresses"), False)
        url_error = await asyncio.to_thread(validate_public_http_url, url, allow_private_addresses=allow_private_addresses)
        if url_error:
            return url_error
        api_url = cfg.get("base_url")
        if api_url is not None:
            backend_error = await asyncio.to_thread(_validate_backend_base_url, cfg, api_url)
            if backend_error:
                return backend_error
        client = _get_firecrawl_client("web_fetch", api_url=api_url)
        result = await client.scrape(url, formats=["markdown"])

        markdown_content = result.markdown or ""
        metadata = result.metadata
        title = metadata.title if metadata and metadata.title else "Untitled"

        if not markdown_content:
            return "Error: No content found"
    except Exception as e:
        return f"Error: {str(e)}"
    finally:
        if client is not None:
            await _aclose_firecrawl_client(client)

    return f"# {title}\n\n{markdown_content[:4096]}"
