import json
import logging
import time
import urllib.error
import urllib.request

from langchain.tools import tool

from deerflow.community.url_safety import validate_public_http_url
from deerflow.config import get_app_config

logger = logging.getLogger(__name__)

DEFAULT_PLAYWRIGHT_ENDPOINT = "http://localhost:3000/scrape"
DEFAULT_WAIT_FOR_MS = 3_000
DEFAULT_TIMEOUT_S = 120.0
DEFAULT_MAX_CHARS = 20_000
DEFAULT_RETRIES = 3
DEFAULT_RETRY_DELAY_S = 2.0
RETRYABLE_HTTP_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}


def _get_tool_config(tool_name: str) -> dict:
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


def _coerce_int(value: object, default: int, *, minimum: int = 0, maximum: int | None = None) -> int:
    if isinstance(value, bool):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    if parsed < minimum:
        return default
    if maximum is not None and parsed > maximum:
        return maximum
    return parsed


def _coerce_float(value: object, default: float, *, minimum: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > minimum else default


def _truncate(value: str, max_chars: int) -> str:
    if max_chars <= 0 or len(value) <= max_chars:
        return value
    return f"{value[:max_chars]}\n\n[truncated to {max_chars} characters]"


def _extract_response_content(raw: str, fallback_status: int) -> tuple[str, int]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return raw, fallback_status

    if not isinstance(parsed, dict):
        return raw, fallback_status

    status = parsed.get("pageStatusCode") or parsed.get("statusCode") or parsed.get("status") or fallback_status
    content = parsed.get("markdown") or parsed.get("content") or parsed.get("html") or ""
    return str(content), _coerce_int(status, fallback_status)


def _fetch_with_playwright(
    url: str,
    *,
    endpoint: str,
    wait_for_ms: int,
    timeout_s: float,
    retries: int,
    retry_delay_s: float,
) -> tuple[str, int]:
    payload = json.dumps({"url": url, "waitFor": wait_for_ms}).encode("utf-8")
    last_error: Exception | None = None

    total_attempts = retries + 1
    attempts_made = 0
    for attempt in range(total_attempts):
        attempts_made = attempt + 1
        try:
            request = urllib.request.Request(
                endpoint,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=timeout_s) as response:
                raw = response.read().decode("utf-8", "replace")
                return _extract_response_content(raw, response.status)
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code not in RETRYABLE_HTTP_STATUS_CODES or attempt >= total_attempts - 1:
                break
            time.sleep(retry_delay_s)
        except (TimeoutError, urllib.error.URLError) as exc:
            last_error = exc
            if attempt >= total_attempts - 1:
                break
            time.sleep(retry_delay_s)

    return f"Error: Playwright fetch failed after {attempts_made} attempt(s): {last_error}", 0


def _fetch_with_config(tool_name: str, url: str, wait_for: int | None) -> tuple[str, int, int]:
    cfg = _get_tool_config(tool_name)
    allow_private_addresses = _coerce_bool(cfg.get("allow_private_addresses"), False)
    url_error = validate_public_http_url(url, allow_private_addresses=allow_private_addresses, action="fetch")
    if url_error:
        return url_error, 0, _coerce_int(cfg.get("max_chars"), DEFAULT_MAX_CHARS, minimum=0)

    wait_for_ms = wait_for if wait_for is not None else _coerce_int(cfg.get("wait_for_ms", cfg.get("waitFor")), DEFAULT_WAIT_FOR_MS)
    wait_for_ms = _coerce_int(wait_for_ms, DEFAULT_WAIT_FOR_MS, minimum=0, maximum=60_000)
    timeout_s = _coerce_float(cfg.get("timeout_s"), DEFAULT_TIMEOUT_S)
    retries = _coerce_int(cfg.get("retries"), DEFAULT_RETRIES, minimum=0, maximum=10)
    retry_delay_s = _coerce_float(cfg.get("retry_delay_s"), DEFAULT_RETRY_DELAY_S)
    max_chars = _coerce_int(cfg.get("max_chars"), DEFAULT_MAX_CHARS, minimum=0)
    endpoint = str(cfg.get("base_url") or DEFAULT_PLAYWRIGHT_ENDPOINT)

    content, status = _fetch_with_playwright(
        url,
        endpoint=endpoint,
        wait_for_ms=wait_for_ms,
        timeout_s=timeout_s,
        retries=retries,
        retry_delay_s=retry_delay_s,
    )
    return content, status, max_chars


@tool("web_fetch", parse_docstring=True)
def web_fetch_tool(url: str, wait_for: int | None = None) -> str:
    """Fetch rendered content from a public page through a self-hosted Playwright HTTP service.

    Use this provider for JavaScript-heavy pages where a plain HTTP fetch cannot obtain rendered content.

    Args:
        url: The full http(s) URL to fetch.
        wait_for: Optional milliseconds to wait after page load before capture.
    """
    try:
        content, status, max_chars = _fetch_with_config("web_fetch", url, wait_for)
        if status == 0:
            return content
        if not 200 <= status < 300 or not content:
            return f"Error: no content (status={status})"
        return _truncate(content, max_chars)
    except Exception as exc:
        logger.exception("Error in web_fetch_tool")
        return f"Error: {exc}"
