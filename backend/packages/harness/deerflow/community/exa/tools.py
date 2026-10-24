import json
import logging
import os
from urllib.parse import urlparse

from exa_py import Exa
from langchain.tools import tool

from deerflow.community.url_safety import safe_public_result_url, validate_delegated_backend_url
from deerflow.config import get_app_config

logger = logging.getLogger(__name__)

DEFAULT_MAX_RESULTS = 5
DEFAULT_CONTENTS_MAX_CHARACTERS = 1000


def _coerce_positive_int(value: object, default: int, option: str) -> int:
    """Normalize a config value before handing it to the Exa SDK.

    ``$VAR`` references in config.yaml resolve to strings, and exa-py rejects a
    string ``num_results`` outright, so every search would fail. Only an integer
    or an integer-form string is accepted: ``int()`` would silently truncate a
    float such as an unquoted ``3.5`` and turn ``true`` into 1. Anything else
    (blank, non-numeric, fractional, boolean, zero or negative) warns and keeps
    the default instead.
    """
    if isinstance(value, int) and not isinstance(value, bool):
        count = value
    elif isinstance(value, str) and value.strip().isdecimal():
        count = int(value.strip())
    else:
        count = 0
    if count <= 0:
        logger.warning("Invalid Exa %s=%r; using default %s", option, value, default)
        return default
    return count


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


def _resolve_base_url(extra: dict) -> str | None:
    """Return the configured Exa-compatible base URL, or ``None`` for the SDK default.

    A non-blank string ``base_url`` in the tool entry takes precedence over
    ``EXA_BASE_URL``. Overrides must be absolute HTTP(S) URLs with a host, a
    valid port, and no query or fragment; an invalid one raises without echoing
    the configured value and never falls back to another host.
    """
    base_url = extra.get("base_url")
    if not isinstance(base_url, str) or not base_url.strip():
        base_url = os.getenv("EXA_BASE_URL") or ""
    base_url = base_url.strip()
    if not base_url:
        return None
    try:
        parsed = urlparse(base_url)
        valid = parsed.scheme in {"http", "https"} and bool(parsed.netloc and parsed.hostname) and "?" not in base_url and "#" not in base_url
        # Accessing port also rejects invalid and out-of-range ports.
        parsed.port
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("Invalid Exa base_url/EXA_BASE_URL: use an absolute HTTP(S) URL with a host, a valid port, and no query or fragment")
    return base_url.rstrip("/")


def _get_exa_client(tool_name: str = "web_search") -> Exa:
    config = get_app_config().get_tool_config(tool_name)
    extra = config.model_extra if config is not None else {}
    return _build_exa_client(extra, _resolve_base_url(extra))


def _build_exa_client(extra: dict, base_url: str | None) -> Exa:
    kwargs = {"api_key": extra.get("api_key")}
    if base_url:
        kwargs["base_url"] = base_url
    return Exa(**kwargs)


@tool("web_search", parse_docstring=True)
def web_search_tool(query: str) -> str:
    """Search the web.

    Args:
        query: The query to search for.
    """
    try:
        config = get_app_config().get_tool_config("web_search")
        max_results = DEFAULT_MAX_RESULTS
        search_type = "auto"
        contents_max_characters = DEFAULT_CONTENTS_MAX_CHARACTERS
        if config is not None:
            max_results = _coerce_positive_int(config.model_extra.get("max_results", max_results), DEFAULT_MAX_RESULTS, "max_results")
            search_type = config.model_extra.get("search_type", search_type)
            contents_max_characters = _coerce_positive_int(
                config.model_extra.get("contents_max_characters", contents_max_characters),
                DEFAULT_CONTENTS_MAX_CHARACTERS,
                "contents_max_characters",
            )

        client = _get_exa_client()
        res = client.search(
            query,
            type=search_type,
            num_results=max_results,
            contents={"highlights": {"max_characters": contents_max_characters}},
        )

        normalized_results = [
            {
                "title": result.title or "",
                "url": safe_public_result_url(result.url),
                "snippet": "\n".join(result.highlights) if result.highlights else "",
            }
            for result in res.results
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
        extra = config.model_extra if config is not None else {}
        base_url = _resolve_base_url(extra)
        if base_url:
            # A custom backend fetches the URL in its own network, like other delegated fetch services.
            backend_error = validate_delegated_backend_url(
                base_url,
                network_isolation_confirmed=_coerce_bool(extra.get("network_isolation_confirmed"), False),
            )
            if backend_error:
                return backend_error
        client = _build_exa_client(extra, base_url)
        res = client.get_contents([url], text={"max_characters": 4096})

        if res.results:
            result = res.results[0]
            title = result.title or "Untitled"
            text = result.text or ""
            return f"# {title}\n\n{text[:4096]}"
        else:
            return "Error: No results found"
    except Exception as e:
        return f"Error: {str(e)}"
