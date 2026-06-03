# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT
"""
Keenable search and fetch tools for DeerFlow.

Keenable provides low-latency web search and content access APIs built for
AI agents. Obtain an API key at https://keenable.ai/console.

Set the KEENABLE_API_KEY environment variable or configure api_key in config.yaml.
When no key is configured, tools fall back to the public (keyless) free tier.
"""

import asyncio
import importlib.metadata
import json
import os

import requests
from langchain_core.tools import tool

from deerflow.config import get_app_config

_DEFAULT_TIMEOUT = 10
_ALLOWED_SCHEMES = ("http://", "https://")
# Client-side guard for obvious private targets; backend enforces server-side too.
_PRIVATE_HOST_PREFIXES = (
    "127.",
    "localhost",
    "169.254.",
    "10.",
    "192.168.",
    "172.",
)


def _base_url() -> str:
    url = os.environ.get("KEENABLE_API_URL", "https://api.keenable.ai").rstrip("/")
    lower = url.lower()
    if lower.startswith("http://"):
        host = lower[len("http://") :].split("/")[0].split("?")[0].split(":")[0]
        is_loopback = host in ("localhost", "127.0.0.1", "::1") or host.startswith("127.")
        if not is_loopback:
            raise ValueError(
                f"KEENABLE_API_URL must use HTTPS for non-loopback hosts (got {url!r}). "
                "Only http:// loopback addresses are allowed for local development."
            )
    elif not lower.startswith("https://"):
        raise ValueError(f"KEENABLE_API_URL must use HTTPS (got {url!r}).")
    return url


def _get_api_key() -> str:
    config = get_app_config().get_tool_config("web_search")
    api_key = None
    if config is not None and "api_key" in config.model_extra:
        api_key = config.model_extra.get("api_key")
    key = api_key or os.environ.get("KEENABLE_API_KEY", "")
    return key.strip() if key else ""


def _user_agent() -> str:
    try:
        version = importlib.metadata.version("deerflow-harness")
    except importlib.metadata.PackageNotFoundError:
        version = "0.0.0"
    return f"keenable-deerflow/{version}"


def _build_headers(api_key: str) -> dict:
    h = {
        "Content-Type": "application/json",
        "User-Agent": _user_agent(),
    }
    if api_key:
        h["X-API-Key"] = api_key
    return h


def _search_endpoint(api_key: str) -> str:
    base = _base_url()
    return f"{base}/v1/search" if api_key else f"{base}/v1/search/public"


def _fetch_endpoint(api_key: str) -> str:
    base = _base_url()
    return f"{base}/v1/fetch" if api_key else f"{base}/v1/fetch/public"


def _format_http_error(resp: requests.Response) -> str:
    try:
        body = resp.json()
        message = body.get("message") or body.get("error") or resp.text
    except Exception:
        message = resp.text or resp.reason or str(resp.status_code)
    code = resp.status_code
    if code == 401:
        return f"Keenable auth error (401): {message}"
    if code == 402:
        return f"Keenable insufficient credits (402): {message}"
    if code == 429:
        return f"Keenable rate limit exceeded (429): {message}"
    return f"Keenable server error ({code}): {message}"


def _validate_fetch_url(url: str) -> str | None:
    lower = url.lower()
    if not any(lower.startswith(s) for s in _ALLOWED_SCHEMES):
        return "Only http:// and https:// URLs are accepted."
    authority = lower.split("://", 1)[1].split("/")[0].split("?")[0]
    if authority.startswith("["):
        # IPv6 bracket notation — extract address between [ and ]
        ip6 = authority[1:].split("]")[0]
        if ip6 == "::1" or ip6.startswith("::ffff:"):
            return "Fetching private or internal URLs is not allowed."
        host = ip6
    else:
        host = authority.split(":")[0]
    for prefix in _PRIVATE_HOST_PREFIXES:
        if host == prefix.rstrip(".") or host.startswith(prefix):
            return "Fetching private or internal URLs is not allowed."
    return None


def _run_web_search(
    query: str,
    site: str | None = None,
    published_after: str | None = None,
    published_before: str | None = None,
    acquired_after: str | None = None,
    acquired_before: str | None = None,
    mode: str | None = None,
) -> str:
    config = get_app_config().get_tool_config("web_search")
    timeout = _DEFAULT_TIMEOUT
    if config is not None:
        timeout = config.model_extra.get("timeout", timeout)

    if not query or not query.strip():
        return json.dumps({"error": "query must not be empty", "query": query}, ensure_ascii=False)

    api_key = _get_api_key()

    if mode == "realtime" and not api_key:
        return json.dumps(
            {"error": "mode='realtime' is not available on the free tier; set KEENABLE_API_KEY to use it.", "query": query},
            ensure_ascii=False,
        )

    payload: dict = {"query": query}
    if site is not None:
        payload["site"] = site
    if published_after is not None:
        payload["published_after"] = published_after
    if published_before is not None:
        payload["published_before"] = published_before
    if acquired_after is not None:
        payload["acquired_after"] = acquired_after
    if acquired_before is not None:
        payload["acquired_before"] = acquired_before
    if mode is not None:
        payload["mode"] = mode

    try:
        resp = requests.post(
            _search_endpoint(api_key),
            headers=_build_headers(api_key),
            json=payload,
            timeout=timeout,
        )
        if not resp.ok:
            return json.dumps({"error": _format_http_error(resp), "query": query}, ensure_ascii=False)
        try:
            data = resp.json()
        except Exception:
            return json.dumps({"error": "Keenable returned a non-JSON response", "query": query}, ensure_ascii=False)
        results = data.get("results")
        if not isinstance(results, list):
            return json.dumps({"error": "Unexpected response format from Keenable", "query": query}, ensure_ascii=False)
    except (requests.RequestException, ValueError) as exc:
        return json.dumps({"error": str(exc), "query": query}, ensure_ascii=False)

    if not results:
        return json.dumps({"error": "No results found", "query": query}, ensure_ascii=False)

    normalized = [
        {
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "content": item.get("description", ""),
        }
        for item in results
        if isinstance(item, dict)
    ]

    if not normalized:
        return json.dumps({"error": "Unexpected response format from Keenable", "query": query}, ensure_ascii=False)

    return json.dumps(
        {"query": query, "total_results": len(normalized), "results": normalized},
        indent=2,
        ensure_ascii=False,
    )


@tool("web_search", parse_docstring=True)
def web_search_tool(
    query: str,
    site: str | None = None,
    published_after: str | None = None,
    published_before: str | None = None,
    acquired_after: str | None = None,
    acquired_before: str | None = None,
    mode: str | None = None,
) -> str:
    """Search the web for information. Use this tool to find current information, news, articles, and facts from the internet.

    Args:
        query: Search keywords describing what you want to find. Be specific for better results.
        site: Restrict results to a single domain (e.g. "example.com").
        published_after: Return pages published after this date (YYYY-MM-DD).
        published_before: Return pages published before this date (YYYY-MM-DD).
        acquired_after: Return pages indexed after this date (YYYY-MM-DD).
        acquired_before: Return pages indexed before this date (YYYY-MM-DD).
        mode: Search mode: 'pro' (default) or 'realtime' (requires API key).
    """
    return _run_web_search(query, site, published_after, published_before, acquired_after, acquired_before, mode)


async def async_web_search(
    query: str,
    site: str | None = None,
    published_after: str | None = None,
    published_before: str | None = None,
    acquired_after: str | None = None,
    acquired_before: str | None = None,
    mode: str | None = None,
) -> str:
    return await asyncio.to_thread(_run_web_search, query, site, published_after, published_before, acquired_after, acquired_before, mode)


def _run_web_fetch(url: str) -> str:
    url_error = _validate_fetch_url(url)
    if url_error:
        return f"Error: {url_error}"

    config = get_app_config().get_tool_config("web_fetch")
    timeout = _DEFAULT_TIMEOUT
    if config is not None:
        timeout = config.model_extra.get("timeout", timeout)

    api_key = _get_api_key()

    try:
        resp = requests.get(
            _fetch_endpoint(api_key),
            headers=_build_headers(api_key),
            params={"url": url},
            timeout=timeout,
        )
        if not resp.ok:
            return f"Error: {_format_http_error(resp)}"
        try:
            data = resp.json()
        except Exception:
            return "Error: Keenable returned a non-JSON response."
    except (requests.RequestException, ValueError) as exc:
        return f"Error: {exc}"

    title = data.get("title", "")
    content = data.get("content", "")

    if not content:
        return f"Error: No content returned for {url}."

    header = f"# {title}\n{url}\n\n" if title else f"{url}\n\n"
    return header + content


@tool("web_fetch", parse_docstring=True)
def web_fetch_tool(url: str) -> str:
    """Fetch the contents of a web page at a given URL.
    Only fetch EXACT URLs that have been provided directly by the user or have been returned in results from the web_search tool.
    URLs must include the schema: https://example.com is a valid URL while example.com is an invalid URL.

    Args:
        url: The URL to fetch the contents of.
    """
    return _run_web_fetch(url)


async def async_web_fetch(url: str) -> str:
    return await asyncio.to_thread(_run_web_fetch, url)
