"""
Web Search Tool - Search the web using DuckDuckGo (no API key required).
"""

import json
import logging
import re
from random import uniform
from threading import Lock
from time import monotonic, sleep

from langchain.tools import tool

from deerflow.community.search_max_results import DEFAULT_MAX_RESULTS, coerce_max_results
from deerflow.community.search_time_range import DDGS_TIMELIMIT_BY_TIME_RANGE, SearchTimeRange
from deerflow.community.url_safety import safe_public_result_url
from deerflow.config import get_app_config

logger = logging.getLogger(__name__)


class DDGSearchError(RuntimeError):
    """Raised when a DuckDuckGo search cannot be executed.

    ``_search_text`` returns an empty list when the search ran and matched
    nothing. Execution failures (client initialization, rate limits,
    timeouts, blocked requests, SDK errors, a missing ddgs dependency) raise
    this error instead, so ``web_search_tool`` can report the failure rather
    than "No results found".
    """


DEFAULT_BACKEND = "auto"
DEFAULT_REGION = "wt-wt"
DEFAULT_SAFESEARCH = "moderate"
DEFAULT_WIKIPEDIA_REGION = "us-en"

WIKIPEDIA_BACKENDS = {"auto", "all", "wikipedia"}
# ddgs 9.14.1: enabled text engines whose implementations honor ``timelimit``.
# Google and Bing also implement it but are disabled upstream in this release.
TIME_RANGE_CAPABLE_BACKENDS = ("brave", "duckduckgo", "yahoo")
DEFAULT_TIME_RANGE_BACKEND = ",".join(TIME_RANGE_CAPABLE_BACKENDS)
WIKIPEDIA_LANGUAGE_ALIASES = {
    "jp": "ja",
    "kr": "ko",
    "tzh": "zh",
    "wt": "en",
}


# This synchronous tool is offloaded by LangChain's ainvoke. Keep lock waits,
# pacing sleeps and the SDK call together in that worker, never on the loop.
_call_lock = Lock()
_last_call: float | None = None
DEFAULT_MIN_INTERVAL_SECONDS = 4.0
DEFAULT_MAX_RETRIES = 2


def _is_challenge(error: Exception) -> bool:
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        text = f"{type(error).__name__}: {error}".lower()
        if re.search(r"ratelimit|rate[ -]?limit|\b202\b|\b429\b|anomaly|captcha|challenge|blocked|vqd", text):
            return True
        error = error.__cause__ or error.__context__
    return False


def _paced_text(ddgs, query: str, search_kwargs: dict, min_interval_seconds: float) -> list[dict]:
    global _last_call
    with _call_lock:
        if _last_call is not None and min_interval_seconds > 0:
            delay = _last_call + min_interval_seconds + uniform(0, 1) - monotonic()
            if delay > 0:
                sleep(delay)
        _last_call = monotonic()
        results = ddgs.text(query, **search_kwargs)
        return list(results) if results else []


def _normalize_backend(backend: str | list[str] | tuple[str, ...] | None) -> str:
    if backend is None:
        return DEFAULT_BACKEND
    if isinstance(backend, (list, tuple)):
        return ",".join(str(part).strip() for part in backend if str(part).strip()) or DEFAULT_BACKEND
    return str(backend).strip() or DEFAULT_BACKEND


def _normalize_setting(value: str | None, default: str) -> str:
    return str(value).strip() if value else default


def _resolve_time_range_backend(backend: str | list[str] | tuple[str, ...] | None) -> str:
    """Exclude DDGS text backends that ignore the native time limit."""
    normalized_backend = _normalize_backend(backend)
    configured_backends = [part.strip().lower() for part in normalized_backend.split(",") if part.strip()]
    if any(part in {"auto", "all"} for part in configured_backends):
        return DEFAULT_TIME_RANGE_BACKEND

    supported_backends = [part for part in configured_backends if part in TIME_RANGE_CAPABLE_BACKENDS]
    excluded_backends = [part for part in configured_backends if part not in TIME_RANGE_CAPABLE_BACKENDS]
    if excluded_backends:
        logger.warning("Ignoring DDGS backends without time-range support: %s", ", ".join(excluded_backends))
    return ",".join(supported_backends) or DEFAULT_TIME_RANGE_BACKEND


def _backend_includes_wikipedia(backend: str | list[str] | tuple[str, ...] | None) -> bool:
    backend = _normalize_backend(backend)
    return any(part.strip().lower() in WIKIPEDIA_BACKENDS for part in backend.split(","))


def _contains_codepoint(query: str, ranges: tuple[tuple[int, int], ...]) -> bool:
    return any(start <= ord(char) <= end for char in query for start, end in ranges)


def _infer_wikipedia_region(query: str) -> str:
    """Pick a valid Wikipedia language region when DDGS' worldwide region is used."""
    if _contains_codepoint(query, ((0x3040, 0x30FF), (0x31F0, 0x31FF))):
        return "jp-ja"
    if _contains_codepoint(query, ((0xAC00, 0xD7AF), (0x1100, 0x11FF), (0x3130, 0x318F))):
        return "kr-ko"
    if _contains_codepoint(query, ((0x3400, 0x9FFF),)):
        return "cn-zh"
    if _contains_codepoint(query, ((0x0400, 0x04FF),)):
        return "ru-ru"
    if _contains_codepoint(query, ((0x0370, 0x03FF),)):
        return "gr-el"
    if _contains_codepoint(query, ((0x0590, 0x05FF),)):
        return "il-he"
    if _contains_codepoint(query, ((0x0600, 0x06FF),)):
        return "xa-ar"
    return DEFAULT_WIKIPEDIA_REGION


def _resolve_ddgs_region(query: str, region: str | None, backend: str | list[str] | tuple[str, ...] | None) -> str:
    """
    DDGS' wikipedia engine treats the second part of region as a Wikipedia
    subdomain. Its default worldwide region, wt-wt, becomes wt.wikipedia.org.
    """
    normalized_region = _normalize_setting(region, DEFAULT_REGION).lower()
    if not _backend_includes_wikipedia(backend):
        return normalized_region

    if normalized_region == DEFAULT_REGION:
        return _infer_wikipedia_region(query)

    if "-" not in normalized_region:
        return DEFAULT_WIKIPEDIA_REGION

    country, language = normalized_region.split("-", 1)
    return f"{country}-{WIKIPEDIA_LANGUAGE_ALIASES.get(language, language)}"


def _search_text(
    query: str,
    max_results: int = DEFAULT_MAX_RESULTS,
    region: str | None = DEFAULT_REGION,
    safesearch: str | None = DEFAULT_SAFESEARCH,
    backend: str | list[str] | tuple[str, ...] | None = DEFAULT_BACKEND,
    time_range: SearchTimeRange | None = None,
    min_interval_seconds: float = DEFAULT_MIN_INTERVAL_SECONDS,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> list[dict]:
    """
    Execute text search using DuckDuckGo.

    Args:
        query: Search keywords
        max_results: Maximum number of results
        region: Search region
        safesearch: Safe search level
        backend: DDGS backend(s), e.g. "auto", "duckduckgo", or "duckduckgo,brave"
        time_range: Optional relative publication/update window
        min_interval_seconds: Minimum process-wide text-call interval, plus jitter
        max_retries: Number of extra attempts for upstream challenges (0-5)

    Returns:
        List of search results

    Raises:
        DDGSearchError: If the search could not be executed, including a
            ``DDGS`` client that fails to initialize. A genuinely empty
            result set is not an error and still returns an empty list.
    """
    try:
        from ddgs import DDGS
    except ImportError as e:
        raise DDGSearchError("ddgs library not installed. Run: pip install ddgs") from e

    try:
        # Constructing the client can already fail (proxy or client setup), so
        # it stays inside the boundary that maps failures to DDGSearchError.
        ddgs = DDGS(timeout=30)

        backend = _resolve_time_range_backend(backend) if time_range is not None else _normalize_backend(backend)
        safesearch = _normalize_setting(safesearch, DEFAULT_SAFESEARCH)
        effective_region = _resolve_ddgs_region(query, region, backend)
        search_kwargs: dict[str, object] = {
            "region": effective_region,
            "safesearch": safesearch,
            "max_results": max_results,
            "backend": backend,
        }
        if time_range is not None:
            search_kwargs["timelimit"] = DDGS_TIMELIMIT_BY_TIME_RANGE[time_range]
        min_interval_seconds = float(min_interval_seconds)
        if not 0 <= min_interval_seconds <= 300:
            raise ValueError("min_interval_seconds must be between 0 and 300")
        if isinstance(max_retries, bool) or not isinstance(max_retries, int) or not 0 <= max_retries <= 5:
            raise ValueError("max_retries must be an integer between 0 and 5")
        for attempt in range(max_retries + 1):
            try:
                return _paced_text(ddgs, query, search_kwargs, min_interval_seconds)
            except Exception as exc:
                if not _is_challenge(exc):
                    raise
                if attempt == max_retries:
                    raise DDGSearchError(f"DuckDuckGo blocked/challenged this request: {type(exc).__name__}: {exc}") from exc
                sleep(min(2**attempt, 16))

    except DDGSearchError:
        raise
    except Exception as e:
        # ddgs signals a genuinely empty result set with the exact message
        # "No results found."; every other failure (rate limit, timeout,
        # blocked HTML, SDK error) must surface as an error instead, or the
        # agent reads an outage as "no matches" and rewrites the query.
        if not _is_challenge(e) and str(e).strip().rstrip(".!").lower() == "no results found":
            return []
        raise DDGSearchError(f"{type(e).__name__}: {e}") from e


@tool("web_search", parse_docstring=True)
def web_search_tool(
    query: str,
    max_results: int = DEFAULT_MAX_RESULTS,
    time_range: SearchTimeRange | None = None,
) -> str:
    """Search the web for information. Use this tool to find current information, news, articles, and facts from the internet.

    Args:
        query: Search keywords describing what you want to find. Be specific for better results.
        max_results: Maximum number of results to return. Default is 5.
        time_range: Optional relative publication/update window. Use only when the request requires recent results.
    """
    config = get_app_config().get_tool_config("web_search")
    region = DEFAULT_REGION
    safesearch = DEFAULT_SAFESEARCH
    backend = DEFAULT_BACKEND
    pacing_options = {}

    if config is not None:
        # Override tool call defaults from config if set.
        max_results = config.model_extra.get("max_results", max_results)
        region = config.model_extra.get("region", region)
        safesearch = config.model_extra.get("safesearch", safesearch)
        backend = config.model_extra.get("backend", backend)
        pacing_options = {key: config.model_extra[key] for key in ("min_interval_seconds", "max_retries") if key in config.model_extra}

    try:
        results = _search_text(
            query=query,
            max_results=coerce_max_results(max_results, provider="DDG Search", logger=logger),
            region=region,
            safesearch=safesearch,
            backend=backend,
            time_range=time_range,
            **pacing_options,
        )
    except DDGSearchError as e:
        logger.error("DuckDuckGo search failed: %s", e)
        return json.dumps({"error": f"DuckDuckGo search failed: {e}", "query": query}, ensure_ascii=False)

    if not results:
        return json.dumps({"error": "No results found", "query": query}, ensure_ascii=False)

    normalized_results = [
        {
            "title": r.get("title", ""),
            "url": safe_public_result_url(r.get("href", r.get("link"))),
            "content": r.get("body", r.get("snippet", "")),
        }
        for r in results
    ]

    output = {
        "query": query,
        "total_results": len(normalized_results),
        "results": normalized_results,
    }

    return json.dumps(output, indent=2, ensure_ascii=False)
