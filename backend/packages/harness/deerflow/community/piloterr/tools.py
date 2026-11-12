"""
Web fetch tool powered by the Piloterr website API.

Piloterr fetches a page from its own infrastructure and returns the HTML. Three
engines share one key: ``crawler`` (plain HTTP, the default), ``rendering``
(a headless browser for JavaScript pages) and ``webunlocker`` (for pages behind
anti-bot protection). The HTML goes through the same readability extraction as
the Jina reader before it reaches the model. An API key is required. Sign up at
https://www.piloterr.com and see https://docs.piloterr.com for the reference.
"""

import logging
import os

import httpx
from langchain.tools import tool

from deerflow.community.provider_credentials import redact_secret, resolve_api_key
from deerflow.community.url_safety import validate_public_http_url
from deerflow.config import get_app_config
from deerflow.utils.readability import ReadabilityExtractor

logger = logging.getLogger(__name__)

_PILOTERR_BASE_URL = "https://api.piloterr.com/v2/website"
_DEFAULT_ENGINE = "crawler"
_ENGINES = ("crawler", "rendering", "webunlocker")
_DEFAULT_TIMEOUT = 60
_MAX_TIMEOUT = 300
_FETCH_MAX_CHARS = 4096
# The rendering engine can wait after the page loads; Piloterr accepts 0-30 seconds.
_MAX_WAIT_IN_SECONDS = 30

# Tool names whose missing-key warning was already logged in this process.
_api_key_warned: set[str] = set()

readability_extractor = ReadabilityExtractor()


def _tool_extra(tool_name: str = "web_fetch") -> dict:
    config = get_app_config().get_tool_config(tool_name)
    return dict(config.model_extra or {}) if config is not None else {}


def _get_api_key(extra: dict) -> str | None:
    return resolve_api_key(extra.get("api_key")) or resolve_api_key(os.getenv("PILOTERR_API_KEY"))


def _missing_key_message(tool_name: str) -> str:
    """Log the missing-key warning once per process; return the model-facing message."""
    if tool_name not in _api_key_warned:
        _api_key_warned.add(tool_name)
        logger.warning("Piloterr API key is not set for '%s'. Set PILOTERR_API_KEY in your environment or provide api_key in config.yaml. Sign up at https://www.piloterr.com", tool_name)
    return "PILOTERR_API_KEY is not configured"


def _coerce_engine(value: object) -> str:
    if value is None:
        return _DEFAULT_ENGINE
    if isinstance(value, str) and value.strip().lower() in _ENGINES:
        return value.strip().lower()
    logger.warning("Invalid Piloterr engine=%r; using %r (one of %s)", value, _DEFAULT_ENGINE, list(_ENGINES))
    return _DEFAULT_ENGINE


def _coerce_int(value: object, *, default: int | None, minimum: int, maximum: int) -> int | None:
    if value is None or isinstance(value, bool):
        return default
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return default
    if isinstance(value, float) and not value.is_integer():
        return default
    return min(max(number, minimum), maximum)


# Piloterr is credit-metered: name the fix so the model does not retry these
# as if they were transient.
_STATUS_HINTS = {
    402: "Piloterr credits exhausted, check the plan or top up at https://www.piloterr.com",
    429: "Piloterr rate limit reached, retry later or lower the request rate",
}


def _error_detail(response: httpx.Response) -> str:
    """Piloterr errors arrive as {"error": "..."} or {"error": {"message": "..."}}."""
    try:
        error = response.json().get("error")
    except (ValueError, AttributeError):
        return ""
    if isinstance(error, dict):
        error = error.get("message")
    return error[:300] if isinstance(error, str) else ""


def _piloterr_get(engine: str, api_key: str, params: dict[str, object], timeout: int) -> tuple[str | None, str | None]:
    """Fetch a page through one Piloterr engine.

    Returns ``(html, None)`` on success or ``(None, "Error: ...")`` on failure.
    The API answers with the page HTML as a JSON string; a raw HTML body is
    accepted too.
    """
    headers = {"x-api-key": api_key, "Accept": "application/json", "User-Agent": "deerflow"}
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.get(f"{_PILOTERR_BASE_URL}/{engine}", headers=headers, params=params)
        if response.status_code >= 400:
            detail = redact_secret(_error_detail(response), api_key)
            logger.error("Piloterr API returned HTTP %s: %s", response.status_code, detail)
            hint = _STATUS_HINTS.get(response.status_code)
            parts = [part for part in (detail, hint) if part]
            suffix = f": {'; '.join(parts)}" if parts else ""
            return None, f"Error: Piloterr API error: HTTP {response.status_code}{suffix}"
        try:
            body = response.json()
        except ValueError:
            body = response.text
        if not isinstance(body, str):
            logger.error("Piloterr returned an unexpected payload type: %s", type(body).__name__)
            return None, "Error: Piloterr returned an unexpected response format"
        return body, None
    except Exception as e:
        message = redact_secret(str(e)[:500], api_key)
        logger.error("Piloterr request failed: %s: %s", type(e).__name__, message)
        return None, f"Error: {message}"


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
    extra = _tool_extra("web_fetch")
    url_error = validate_public_http_url(url)
    if url_error:
        return url_error

    api_key = _get_api_key(extra)
    if not api_key:
        return f"Error: {_missing_key_message('web_fetch')}"

    engine = _coerce_engine(extra.get("engine"))
    timeout = _coerce_int(extra.get("timeout"), default=_DEFAULT_TIMEOUT, minimum=1, maximum=_MAX_TIMEOUT)
    params: dict[str, object] = {"query": url}
    if engine == "rendering":
        wait = _coerce_int(extra.get("wait_in_seconds"), default=None, minimum=0, maximum=_MAX_WAIT_IN_SECONDS)
        if wait is not None:
            params["wait_in_seconds"] = wait

    html_content, error = _piloterr_get(engine, api_key, params, timeout)
    if error is not None:
        return error
    if not html_content or not html_content.strip():
        return "Error: No content found"

    article = readability_extractor.extract_article(html_content, url=url)
    return article.to_markdown()[:_FETCH_MAX_CHARS]
