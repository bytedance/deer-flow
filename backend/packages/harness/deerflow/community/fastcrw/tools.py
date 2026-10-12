import json
import logging
import os

from firecrawl import FirecrawlApp
from langchain.tools import tool

from deerflow.community.search_max_results import DEFAULT_MAX_RESULTS, coerce_max_results
from deerflow.community.url_safety import validate_delegated_backend_url, validate_public_http_url
from deerflow.config import get_app_config

logger = logging.getLogger(__name__)

# fastCRW is a Firecrawl-compatible web data engine (single Rust binary; self-host
# or cloud). Because the REST API is Firecrawl-compatible, this provider reuses the
# Firecrawl client and only swaps the base URL. Cloud default points at the managed
# service; override `base_url` in the tool config (or set CRW_API_URL) for self-host.
DEFAULT_BASE_URL = "https://fastcrw.com/api"


def _get_fastcrw_client(
    tool_name: str = "web_search",
    *,
    cfg: dict | None = None,
    base_url: str | None = None,
) -> FirecrawlApp:
    """Build a fastCRW client from one configuration snapshot.

    ``cfg`` is the tool config extras already read by the caller. Resolving the
    API key and endpoint from that same snapshot keeps a backend change made
    between the URL screen and client construction from pairing one revision's
    endpoint with another revision's key.
    """
    if cfg is None:
        cfg = _get_tool_config_extra(tool_name)
    api_key = cfg.get("api_key")
    if base_url is None:
        base_url = cfg.get("base_url")
    if api_key is None:
        api_key = os.getenv("CRW_API_KEY")
    if base_url is None:
        base_url = os.getenv("CRW_API_URL", DEFAULT_BASE_URL)
    return FirecrawlApp(api_key=api_key, api_url=base_url)  # type: ignore[arg-type]


def _resolve_fastcrw_base_url(cfg: dict | None) -> str:
    """Resolve the fastCRW base URL from config, then the ``CRW_API_URL`` env var.

    The backend screen must run on this resolved value (config key first, then the
    env fallback), not on the raw config key, or the ``CRW_API_URL`` path would
    bypass the gate.
    """
    base_url = cfg.get("base_url") if cfg is not None else None
    if base_url is None:
        base_url = os.getenv("CRW_API_URL", DEFAULT_BASE_URL)
    return base_url


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
    """Refuse delegation to a self-hosted fastCRW backend unless its egress is isolated.

    fastCRW resolves the target URL, follows redirects, and loads subresources in
    the fastCRW service's own network namespace, so the target-URL screen cannot be
    enforced end-to-end. Delegation is only safe when the backend's outbound network
    is isolated from private and metadata networks, which the operator confirms via
    ``network_isolation_confirmed``. Blocking; fastCRW's ``web_fetch_tool`` is sync.
    """
    network_isolation_confirmed = _coerce_bool(cfg.get("network_isolation_confirmed"), False)
    return validate_delegated_backend_url(base_url, network_isolation_confirmed=network_isolation_confirmed)


@tool("web_search", parse_docstring=True)
def web_search_tool(query: str) -> str:
    """Search the web.

    Args:
        query: The query to search for.
    """
    try:
        config = get_app_config().get_tool_config("web_search")
        max_results = DEFAULT_MAX_RESULTS
        if config is not None:
            max_results = coerce_max_results(config.model_extra.get("max_results", max_results), provider="fastCRW", logger=logger)

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
        cfg = _get_tool_config_extra("web_fetch")
        allow_private_addresses = _coerce_bool(cfg.get("allow_private_addresses"), False)
        url_error = validate_public_http_url(url, allow_private_addresses=allow_private_addresses)
        if url_error:
            return url_error
        base_url = _resolve_fastcrw_base_url(cfg)
        backend_error = _validate_backend_base_url(cfg, base_url)
        if backend_error:
            return backend_error
        client = _get_fastcrw_client("web_fetch", cfg=cfg, base_url=base_url)
        result = client.scrape(url, formats=["markdown"])

        markdown_content = result.markdown or ""
        metadata = result.metadata
        title = metadata.title if metadata and metadata.title else "Untitled"

        if not markdown_content:
            return "Error: No content found"
    except Exception as e:
        return f"Error: {str(e)}"

    return f"# {title}\n\n{markdown_content[:4096]}"
