"""
Web and image search tools powered by Serper (Google Search API).

Serper provides real-time Google Search and Google Images results via a JSON
API. An API key is required. Sign up at https://serper.dev to get one.
"""

import json
import logging
import os
from ipaddress import IPv4Address, ip_address
from urllib.parse import urlparse

import httpx
from langchain.tools import tool

from deerflow.config import get_app_config

logger = logging.getLogger(__name__)

_SERPER_SEARCH_ENDPOINT = "https://google.serper.dev/search"
_SERPER_IMAGES_ENDPOINT = "https://google.serper.dev/images"
_SERPER_MAX_RESULTS = 10
_api_key_warned: set[str] = set()


def _get_api_key(tool_name: str) -> str | None:
    config = get_app_config().get_tool_config(tool_name)
    if config is not None:
        api_key = config.model_extra.get("api_key")
        if isinstance(api_key, str) and api_key.strip():
            return api_key.strip()
    env_key = os.getenv("SERPER_API_KEY")
    if isinstance(env_key, str) and env_key.strip():
        return env_key.strip()
    return None


def _coerce_max_results(value: object, default: int = 5, max_allowed: int = _SERPER_MAX_RESULTS) -> int:
    """Coerce config/parameter input into a bounded positive result count."""
    try:
        count = int(value)
    except (TypeError, ValueError):
        return default
    if count <= 0:
        return default
    return min(count, max_allowed)


def _missing_key_error(query: str, tool_name: str) -> str:
    if tool_name not in _api_key_warned:
        _api_key_warned.add(tool_name)
        logger.warning("Serper API key is not set for '%s'. Set SERPER_API_KEY in your environment or provide api_key in config.yaml. Sign up at https://serper.dev", tool_name)
    return json.dumps(
        {"error": "SERPER_API_KEY is not configured", "query": query},
        ensure_ascii=False,
    )


def _unexpected_format_error(query: str) -> str:
    return json.dumps(
        {"error": "Serper returned an unexpected response format", "query": query},
        ensure_ascii=False,
    )


def _response_items(data: dict, field: str, query: str) -> tuple[list[dict] | None, str | None]:
    items = data.get(field)
    # Treat a missing or null field as "no results" (some APIs return
    # ``{"organic": null}`` to signal that) rather than a malformed payload.
    if items is None:
        return [], None
    if not isinstance(items, list):
        logger.error("Serper returned unexpected '%s' payload type: %s", field, type(items).__name__)
        return None, _unexpected_format_error(query)
    return [item for item in items if isinstance(item, dict)], None


def _clean_query(query: str) -> str:
    """Normalize a raw query into the value actually sent to Serper."""
    query = query.strip()
    if len(query) > 500:
        query = query[:500]
    return query


def _decode_ipv4(host: str) -> IPv4Address | None:
    """Decode obfuscated IPv4 literals that ``ip_address`` rejects.

    Mirrors the permissive ``inet_aton`` parsing many HTTP clients use, so that
    integer (``2130706433``), hex (``0x7f000001``) and octal (``0177.0.0.1``)
    encodings of an address are recognized. Returns an ``IPv4Address`` when the
    host decodes to one, otherwise ``None`` (e.g. real domains like
    ``cafe.com`` fail to decode and are left for the caller to treat as a host).
    """
    parts = host.split(".")
    if not 1 <= len(parts) <= 4:
        return None

    values: list[int] = []
    for part in parts:
        if not part:
            return None
        try:
            if part.startswith(("0x", "0X")):
                values.append(int(part, 16))
            elif part.startswith("0") and len(part) > 1:
                values.append(int(part, 8))
            else:
                values.append(int(part, 10))
        except ValueError:
            return None

    *leading, last = values
    for value in leading:
        if not 0 <= value <= 0xFF:
            return None
    max_last = (1 << (8 * (4 - len(leading)))) - 1
    if not 0 <= last <= max_last:
        return None

    result = 0
    for value in leading:
        result = (result << 8) | value
    result = (result << (8 * (4 - len(leading)))) | last
    return ip_address(result)


def _is_url_present(value: object) -> bool:
    """Return ``True`` when *value* is a non-empty URL string.

    Used to distinguish a field that was *absent* (eligible for cross-field
    fallback) from one that was *present but filtered* by the SSRF guard (which
    must stay empty rather than collapse onto its counterpart).
    """
    return isinstance(value, str) and bool(value.strip())


def _safe_public_url(value: object) -> str:
    """Return ``value`` only if it is a safe, public http(s) URL, else "".

    This is a best-effort SSRF guard that rejects non-http(s) schemes,
    ``localhost``, and private/non-global IP literals (including obfuscated
    decimal/hex/octal encodings). It only inspects the URL string and cannot
    catch public hostnames that resolve to internal IPs (e.g. DNS rebinding);
    any consumer that actually downloads these URLs must re-validate the
    resolved IP at fetch time.
    """
    if not isinstance(value, str):
        return ""
    url = value.strip()
    try:
        parsed = urlparse(url)
    except ValueError:
        return ""
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or not parsed.hostname:
        return ""

    # Strip a single trailing dot (FQDN root label). ``localhost.`` and
    # ``127.0.0.1.`` resolve to loopback on common resolvers but would
    # otherwise slip past the localhost/IP checks below.
    host = parsed.hostname.lower().rstrip(".")
    if not host:
        return ""
    if host == "localhost" or host.endswith(".localhost"):
        return ""

    try:
        ip = ip_address(host)
    except ValueError:
        ip = _decode_ipv4(host)
        if ip is None:
            return url
    return url if ip.is_global else ""


def _serper_post(endpoint: str, api_key: str, query: str, max_results: int) -> tuple[dict | None, str | None]:
    """Send a POST request to a Serper endpoint.

    ``query`` is expected to already be normalized via :func:`_clean_query`.

    Returns a ``(data, error_json)`` tuple: on success ``data`` is the parsed
    JSON response and ``error_json`` is ``None``; on failure ``data`` is ``None``
    and ``error_json`` is a serialized structured error ready to return.
    """
    headers = {
        "X-API-KEY": api_key,
        "Content-Type": "application/json",
    }
    payload = {"q": query, "num": max_results}

    try:
        with httpx.Client(timeout=30) as client:
            response = client.post(endpoint, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            logger.error("Serper returned an unexpected payload type: %s", type(data).__name__)
            return None, _unexpected_format_error(query)
        return data, None
    except httpx.HTTPStatusError as e:
        resp_text = (e.response.text or "")[:500]
        logger.error("Serper API returned HTTP %s: %s", e.response.status_code, resp_text)
        return None, json.dumps(
            {"error": f"Serper API error: HTTP {e.response.status_code}", "query": query},
            ensure_ascii=False,
        )
    except Exception as e:
        logger.error("Serper request failed: %s: %s", type(e).__name__, str(e)[:500])
        return None, json.dumps({"error": str(e)[:500], "query": query}, ensure_ascii=False)


@tool("web_search", parse_docstring=True)
def web_search_tool(query: str, max_results: int = 5) -> str:
    """Search the web for information using Google Search via Serper.

    Args:
        query: Search keywords describing what you want to find. Be specific for better results.
        max_results: Maximum number of search results to return. Default is 5, capped at 10.
    """
    config = get_app_config().get_tool_config("web_search")
    if config is not None and "max_results" in config.model_extra:
        max_results = config.model_extra.get("max_results", max_results)
    max_results = _coerce_max_results(max_results)
    query = _clean_query(query)

    api_key = _get_api_key("web_search")
    if not api_key:
        return _missing_key_error(query, "web_search")

    data, error_json = _serper_post(_SERPER_SEARCH_ENDPOINT, api_key, query, max_results)
    if error_json is not None:
        return error_json

    organic, error_json = _response_items(data, "organic", query)
    if error_json is not None:
        return error_json
    if not organic:
        return json.dumps({"error": "No results found", "query": query}, ensure_ascii=False)

    # Search result links are returned verbatim (not passed through
    # _safe_public_url): they are surfaced as citations for the model to read,
    # not fetched/downloaded by this tool, unlike image_search image URLs.
    normalized_results = [
        {
            "title": r.get("title", ""),
            "url": r.get("link", ""),
            "content": r.get("snippet", ""),
        }
        for r in organic[:max_results]
    ]

    output = {
        "query": query,
        "total_results": len(normalized_results),
        "results": normalized_results,
    }
    return json.dumps(output, indent=2, ensure_ascii=False)


@tool("image_search", parse_docstring=True)
def image_search_tool(query: str, max_results: int = 5) -> str:
    """Search for images online using Google Images via Serper. Use this tool BEFORE image generation to find reference images for characters, portraits, objects, scenes, or any content requiring visual accuracy.

    The returned image URLs can be used as reference images in image generation to significantly improve quality.

    Args:
        query: Search keywords describing the images you want to find. Be specific for better results (e.g., "Japanese woman street photography 1990s" instead of just "woman").
        max_results: Maximum number of images to return. Default is 5, capped at 10.
    """
    config = get_app_config().get_tool_config("image_search")
    if config is not None and "max_results" in config.model_extra:
        max_results = config.model_extra.get("max_results", max_results)
    max_results = _coerce_max_results(max_results)
    query = _clean_query(query)

    api_key = _get_api_key("image_search")
    if not api_key:
        return _missing_key_error(query, "image_search")

    data, error_json = _serper_post(_SERPER_IMAGES_ENDPOINT, api_key, query, max_results)
    if error_json is not None:
        return error_json

    images, error_json = _response_items(data, "images", query)
    if error_json is not None:
        return error_json
    if not images:
        return json.dumps({"error": "No images found", "query": query}, ensure_ascii=False)

    normalized_results = []
    for r in images:
        raw_image = r.get("imageUrl")
        raw_thumb = r.get("thumbnailUrl")
        # Evaluate the (non-trivial) SSRF guard once per field instead of twice.
        safe_image = _safe_public_url(raw_image)
        safe_thumb = _safe_public_url(raw_thumb)
        # Cross-fall back only when the other field was *absent*. A field that
        # was present but failed the SSRF filter is left empty rather than
        # collapsed onto its counterpart, so a dropped high-res URL never
        # silently masquerades as the preview (and vice versa), preserving the
        # high-res/preview contract callers rely on.
        image_url = safe_image or (safe_thumb if not _is_url_present(raw_image) else "")
        thumbnail_url = safe_thumb or (safe_image if not _is_url_present(raw_thumb) else "")
        if not image_url and not thumbnail_url:
            continue
        normalized_results.append(
            {
                "title": r.get("title", ""),
                "image_url": image_url,
                "thumbnail_url": thumbnail_url,
            }
        )
        if len(normalized_results) >= max_results:
            break

    if not normalized_results:
        return json.dumps({"error": "No safe image URLs found", "query": query}, ensure_ascii=False)

    output = {
        "query": query,
        "total_results": len(normalized_results),
        "results": normalized_results,
        "usage_hint": "Use the 'image_url' values as reference images in image generation. Download them first if needed.",
    }
    return json.dumps(output, indent=2, ensure_ascii=False)
