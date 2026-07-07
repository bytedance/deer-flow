"""
Web and image search tools powered by the Brave Search API.

Brave Search provides web and image results from an independent search index
via a REST API. An API key is required. Sign up at
https://brave.com/search/api/ to get one.

Unlike the DuckDuckGo ``backend: brave`` option (which scrapes results via the
DDGS aggregator), this provider calls the official Brave Search API directly,
giving structured results, authenticated quota, and a documented SLA.
"""

import json
import logging
import os
from ipaddress import IPv4Address, IPv6Address, ip_address, ip_network
from urllib.parse import urlparse

import httpx
from langchain.tools import tool

from deerflow.config import get_app_config

logger = logging.getLogger(__name__)

_BRAVE_WEB_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
_BRAVE_IMAGES_ENDPOINT = "https://api.search.brave.com/res/v1/images/search"
_DEFAULT_MAX_RESULTS = 5
# Brave Search API caps the `count` parameter at 20 results per request.
_BRAVE_WEB_MAX_COUNT = 20
# Brave Image Search supports larger batches than web search.
_BRAVE_IMAGE_MAX_COUNT = 200
# NAT64 well-known prefix (RFC 6052): IPv6 literals embedding an IPv4 address.
_NAT64_PREFIX = ip_network("64:ff9b::/96")
_api_key_warned: set[str] = set()


def _get_api_key(tool_name: str = "web_search") -> str | None:
    config = get_app_config().get_tool_config(tool_name)
    if config is not None:
        api_key = (config.model_extra or {}).get("api_key")
        if isinstance(api_key, str) and api_key.strip():
            return api_key.strip()
    env_key = os.getenv("BRAVE_SEARCH_API_KEY")
    if isinstance(env_key, str) and env_key.strip():
        return env_key.strip()
    return None


def _coerce_max_results(
    value: object,
    *,
    default: int = _DEFAULT_MAX_RESULTS,
    max_allowed: int = _BRAVE_WEB_MAX_COUNT,
) -> int:
    try:
        coerced = int(value)
    except (TypeError, ValueError):
        logger.warning(
            "Invalid Brave Search max_results=%r; using default %s",
            value,
            default,
        )
        coerced = default

    return max(1, min(coerced, max_allowed))


def _clean_query(query: str, *, max_length: int = 400) -> str:
    query = query.strip()
    if len(query) > max_length:
        query = query[:max_length]
    return query


def _missing_key_error(query: str, tool_name: str) -> str:
    if tool_name not in _api_key_warned:
        _api_key_warned.add(tool_name)
        logger.warning(
            "Brave Search API key is not set for '%s'. Set BRAVE_SEARCH_API_KEY in your environment or provide api_key in config.yaml. Sign up at https://brave.com/search/api/",
            tool_name,
        )
    return json.dumps(
        {"error": "BRAVE_SEARCH_API_KEY is not configured", "query": query},
        ensure_ascii=False,
    )


def _unexpected_format_error(query: str, *, service_name: str = "Brave Search") -> str:
    return json.dumps(
        {"error": f"{service_name} returned an unexpected response format", "query": query},
        ensure_ascii=False,
    )


def _decode_ipv4(host: str) -> IPv4Address | None:
    """Decode obfuscated IPv4 literals that ``ip_address`` rejects.

    Mirrors the permissive ``inet_aton`` parsing many HTTP clients use, so that
    integer (``2130706433``), hex (``0x7f000001``) and octal (``0177.0.0.1``)
    encodings of an address are recognized.
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
    return IPv4Address(result)


def _is_url_present(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _embedded_ipv4(ip: IPv6Address) -> IPv4Address | None:
    """Extract an IPv4 address embedded in an IPv6 literal, if any.

    Covers IPv4-mapped (``::ffff:a.b.c.d``), 6to4 (``2002::/16``), NAT64
    (``64:ff9b::/96``), and IPv4-compatible (``::a.b.c.d``) forms. These all
    smuggle a v4 destination through the IPv6 path, where ``is_global`` on the
    v6 literal alone would otherwise report a loopback/private target as safe.
    """
    if ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    if ip.sixtofour is not None:
        return ip.sixtofour
    if ip in _NAT64_PREFIX:
        return IPv4Address(int(ip) & 0xFFFFFFFF)
    # IPv4-compatible ``::a.b.c.d`` (high 96 bits zero, excluding ::/:: 1).
    packed = int(ip)
    if packed >> 32 == 0 and packed > 1:
        return IPv4Address(packed & 0xFFFFFFFF)
    return None


def _safe_public_url(value: object) -> str:
    """Return ``value`` only if it is a safe, public http(s) URL, else "".

    This is a best-effort SSRF guard that rejects non-http(s) schemes,
    ``localhost``, and private/non-global IP literals (including obfuscated
    decimal/hex/octal encodings and IPv6 literals embedding a non-global IPv4).
    It only inspects the URL string and cannot catch public hostnames that
    resolve to internal IPs; any consumer that actually downloads these URLs
    must re-validate the resolved IP at fetch time.
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
    if isinstance(ip, IPv6Address):
        embedded = _embedded_ipv4(ip)
        if embedded is not None and not embedded.is_global:
            return ""
    return url if ip.is_global else ""


def _brave_get(
    endpoint: str,
    api_key: str,
    query: str,
    params: dict[str, object],
    *,
    service_name: str,
) -> tuple[dict | None, str | None]:
    headers = {
        "X-Subscription-Token": api_key,
        "Accept": "application/json",
    }
    try:
        with httpx.Client(timeout=30) as client:
            response = client.get(endpoint, headers=headers, params=params)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            logger.error("%s returned an unexpected payload type: %s", service_name, type(data).__name__)
            return None, _unexpected_format_error(query, service_name=service_name)
        return data, None
    except httpx.HTTPStatusError as e:
        logger.error("%s API returned HTTP %s: %s", service_name, e.response.status_code, e.response.text)
        return None, json.dumps(
            {"error": f"{service_name} API error: HTTP {e.response.status_code}", "query": query},
            ensure_ascii=False,
        )
    except Exception as e:
        logger.error("%s request failed: %s: %s", service_name, type(e).__name__, e)
        return None, json.dumps({"error": str(e), "query": query}, ensure_ascii=False)


@tool("web_search", parse_docstring=True)
def web_search_tool(query: str, max_results: int = 5) -> str:
    """Search the web for information using Brave Search.

    Args:
        query: Search keywords describing what you want to find. Be specific for better results.
        max_results: Maximum number of search results to return. Default is 5.
    """
    config = get_app_config().get_tool_config("web_search")
    if config is not None and "max_results" in (config.model_extra or {}):
        max_results = config.model_extra["max_results"]

    count = _coerce_max_results(max_results, max_allowed=_BRAVE_WEB_MAX_COUNT)
    query = _clean_query(query)

    api_key = _get_api_key("web_search")
    if not api_key:
        return _missing_key_error(query, "web_search")

    params = {"q": query, "count": count, "text_decorations": False}

    data, error_json = _brave_get(_BRAVE_WEB_ENDPOINT, api_key, query, params, service_name="Brave Search")
    if error_json is not None:
        return error_json

    web_results = (data.get("web") or {}).get("results", [])
    if not web_results:
        return json.dumps({"error": "No results found", "query": query}, ensure_ascii=False)

    normalized_results = [
        {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "content": r.get("description", ""),
        }
        for r in web_results
    ]

    output = {
        "query": query,
        "total_results": len(normalized_results),
        "results": normalized_results,
    }
    return json.dumps(output, indent=2, ensure_ascii=False)


@tool("image_search", parse_docstring=True)
def image_search_tool(query: str, max_results: int = 5) -> str:
    """Search for images online using Brave Image Search. Use this tool BEFORE image generation to find reference images for characters, portraits, objects, scenes, or any content requiring visual accuracy.

    The returned image URLs can be used as reference images in image generation to significantly improve quality.

    Args:
        query: Search keywords describing the images you want to find. Be specific for better results.
        max_results: Maximum number of images to return. Default is 5, capped at 200.
    """
    config = get_app_config().get_tool_config("image_search")
    extra = (config.model_extra or {}) if config is not None else {}
    if "max_results" in extra:
        max_results = extra["max_results"]
    count = _coerce_max_results(max_results, max_allowed=_BRAVE_IMAGE_MAX_COUNT)
    query = _clean_query(query)

    api_key = _get_api_key("image_search")
    if not api_key:
        return _missing_key_error(query, "image_search")

    params: dict[str, object] = {"q": query, "count": count}
    for key in ("country", "search_lang", "safesearch", "spellcheck"):
        if key in extra:
            params[key] = extra[key]

    data, error_json = _brave_get(
        _BRAVE_IMAGES_ENDPOINT,
        api_key,
        query,
        params,
        service_name="Brave Image Search",
    )
    if error_json is not None:
        return error_json

    images = data.get("results")
    if images is None:
        images = []
    if not isinstance(images, list):
        logger.error("Brave Image Search returned unexpected 'results' payload type: %s", type(images).__name__)
        return _unexpected_format_error(query, service_name="Brave Image Search")
    if not images:
        return json.dumps({"error": "No images found", "query": query}, ensure_ascii=False)

    normalized_results = []
    for item in images:
        if not isinstance(item, dict):
            continue
        thumbnail = item.get("thumbnail") if isinstance(item.get("thumbnail"), dict) else {}
        properties = item.get("properties") if isinstance(item.get("properties"), dict) else {}
        raw_image = properties.get("url")
        raw_thumb = thumbnail.get("src")
        raw_source = item.get("url")

        safe_image = _safe_public_url(raw_image)
        safe_thumb = _safe_public_url(raw_thumb)
        safe_source = _safe_public_url(raw_source)

        # Surface a URL and remember which dict it came from, so the reported
        # width/height describe the URL we actually return rather than a
        # dropped one.
        if safe_image:
            image_url, image_dims = safe_image, properties
        elif not _is_url_present(raw_image):
            image_url, image_dims = safe_thumb, thumbnail
        else:
            image_url, image_dims = "", {}

        if safe_thumb:
            thumbnail_url, thumb_dims = safe_thumb, thumbnail
        elif not _is_url_present(raw_thumb):
            thumbnail_url, thumb_dims = safe_image, properties
        else:
            thumbnail_url, thumb_dims = "", {}

        if not image_url and not thumbnail_url:
            continue

        dims = image_dims if image_url else thumb_dims

        normalized_results.append(
            {
                "title": item.get("title", ""),
                "image_url": image_url,
                "thumbnail_url": thumbnail_url,
                "source_url": safe_source,
                "source": item.get("source", ""),
                "width": dims.get("width"),
                "height": dims.get("height"),
            }
        )
        if len(normalized_results) >= count:
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
