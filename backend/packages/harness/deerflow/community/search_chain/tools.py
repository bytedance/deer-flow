"""Web search that walks an ordered chain of bundled search providers.

The ``web_search`` entry names the providers to try, in order::

    providers: [brave, tavily, exa, searxng, ddg]

Each provider is reached through its own community module (the Brave HTTP
helper, the Tavily/Exa client factories, ``SearxngClient`` and the DDGS search
wrapper); this module only adapts their payloads to one result shape and
decides when to move on:

* a provider without its API key (or, for SearXNG, a ``base_url``) is skipped;
* an exception, HTTP error (including rate limits), ``DDGSearchError`` or a
  malformed payload fails over to the next provider;
* a genuinely empty result set is returned as "No results found" from the
  provider that ran it, unless ``fallback_on_empty: true``;
* when nothing answers, the error lists each provider's failure. It never
  reads "No results found", so the agent does not mistake an outage for a
  query that matched nothing.

Per-provider settings live under a key named after the provider, for example
``brave: {api_key: $BRAVE_SEARCH_API_KEY}`` or
``searxng: {base_url: http://searxng:8080}``. API keys fall back to each
provider's usual environment variable.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from types import SimpleNamespace

from langchain.tools import tool

from deerflow.community.provider_credentials import redact_secret, resolve_api_key
from deerflow.community.search_max_results import DEFAULT_MAX_RESULTS, coerce_max_results
from deerflow.community.search_time_range import BRAVE_FRESHNESS_BY_TIME_RANGE, SearchTimeRange
from deerflow.community.url_safety import safe_public_result_url
from deerflow.config import get_app_config

logger = logging.getLogger(__name__)

DEFAULT_PROVIDERS = ("brave", "tavily", "exa", "searxng", "ddg")
NO_RESULTS = "No results found"
ALL_FAILED = "All web search providers failed"


class ProviderSkipped(Exception):
    """The provider is not configured for this call; try the next one quietly."""


class ProviderFailed(Exception):
    """The provider ran but did not produce a usable answer."""


@dataclass(frozen=True)
class _Call:
    query: str
    max_results: int
    time_range: SearchTimeRange | None
    settings: dict


def _require_key(settings: dict, env_name: str) -> str:
    key = resolve_api_key(settings.get("api_key")) or resolve_api_key(os.getenv(env_name))
    if not key:
        raise ProviderSkipped(f"{env_name} is not configured")
    return key


def _result(title: object, url: object, content: object) -> dict:
    return {
        "title": title if isinstance(title, str) else "",
        "url": safe_public_result_url(url),
        "content": content if isinstance(content, str) else "",
    }


def _objects(value: object, container: str) -> list[dict]:
    """Validate a result container: missing/null is empty, wrong shapes fail over."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise ProviderFailed(f"unexpected '{container}' payload type: {type(value).__name__}")
    objects = [item for item in value if isinstance(item, dict)]
    if value and not objects:
        raise ProviderFailed(f"'{container}' held no usable result objects")
    return objects


async def _brave(call: _Call) -> list[dict]:
    from deerflow.community.brave import tools as brave

    api_key = _require_key(call.settings, "BRAVE_SEARCH_API_KEY")
    params: dict[str, object] = {
        "q": call.query,
        "count": min(call.max_results, brave._BRAVE_WEB_MAX_COUNT),
        "text_decorations": False,
    }
    if call.time_range is not None:
        params["freshness"] = BRAVE_FRESHNESS_BY_TIME_RANGE[call.time_range]
    data, error_json = await asyncio.to_thread(brave._brave_get, brave._BRAVE_WEB_ENDPOINT, api_key, call.query, params, service_name="Brave Search")
    if error_json is not None:
        raise ProviderFailed(json.loads(error_json).get("error", error_json))
    web = data.get("web")
    if web is not None and not isinstance(web, dict):
        raise ProviderFailed(f"unexpected 'web' payload type: {type(web).__name__}")
    rows = _objects((web or {}).get("results"), "web.results")
    return [_result(r.get("title"), r.get("url"), r.get("description")) for r in rows]


async def _tavily(call: _Call) -> list[dict]:
    from deerflow.community.tavily import tools as tavily

    api_key = _require_key(call.settings, "TAVILY_API_KEY")
    search_kwargs: dict[str, object] = {"max_results": call.max_results}
    for key in ("include_domains", "exclude_domains"):
        if call.settings.get(key):
            search_kwargs[key] = call.settings[key]
    if search_kwargs.get("include_domains"):
        search_kwargs["include_domains_mode"] = "filter"
    if call.time_range is not None:
        search_kwargs["time_range"] = call.time_range
    client = tavily._get_tavily_client(config=SimpleNamespace(model_extra={"api_key": api_key}))
    try:
        res = await client.search(call.query, **search_kwargs)
    finally:
        await client.close()
    rows = tavily._response_objects(res, "results")
    if rows is None:
        raise ProviderFailed(tavily._FORMAT_ERROR)
    return [_result(r.get("title"), r.get("url"), r.get("content")) for r in rows]


async def _exa(call: _Call) -> list[dict]:
    from deerflow.community.exa import tools as exa

    api_key = _require_key(call.settings, "EXA_API_KEY")
    if call.time_range is not None:
        raise ProviderSkipped("time_range is not supported by the Exa provider")
    extra = {**call.settings, "api_key": api_key}
    search_type = call.settings.get("search_type", "auto")

    def _search():
        client = exa._build_exa_client(extra, exa._resolve_base_url(extra))
        return client.search(
            call.query,
            type=search_type,
            num_results=call.max_results,
            contents={"highlights": {"max_characters": exa.DEFAULT_CONTENTS_MAX_CHARACTERS}},
        )

    res = await asyncio.to_thread(_search)
    return [_result(r.title, r.url, "\n".join(r.highlights) if r.highlights else "") for r in (res.results or [])]


async def _searxng(call: _Call) -> list[dict]:
    from deerflow.community.searxng.searxng_client import SearxngClient

    base_url = call.settings.get("base_url")
    if not isinstance(base_url, str) or not base_url.strip():
        raise ProviderSkipped("searxng.base_url is not configured")
    search_kwargs: dict[str, object] = {"max_results": call.max_results}
    if call.time_range is not None:
        search_kwargs["time_range"] = call.time_range
    rows = _objects(await SearxngClient(base_url=base_url.strip()).search(call.query, **search_kwargs), "results")
    return [_result(r.get("title"), r.get("url"), r.get("content")) for r in rows]


async def _ddg(call: _Call) -> list[dict]:
    from deerflow.community.ddg_search import tools as ddg

    rows = await asyncio.to_thread(
        ddg._search_text,
        query=call.query,
        max_results=call.max_results,
        region=call.settings.get("region", ddg.DEFAULT_REGION),
        safesearch=call.settings.get("safesearch", ddg.DEFAULT_SAFESEARCH),
        backend=call.settings.get("backend", ddg.DEFAULT_BACKEND),
        time_range=call.time_range,
        # Forward the DDG tool's pacing knobs only when set, so its defaults apply otherwise.
        **{key: call.settings[key] for key in ("min_interval_seconds", "max_retries") if key in call.settings},
    )
    rows = _objects(rows, "results")
    return [_result(r.get("title"), r.get("href", r.get("link")), r.get("body", r.get("snippet"))) for r in rows]


PROVIDERS: dict[str, Callable[[_Call], Awaitable[list[dict]]]] = {
    "brave": _brave,
    "tavily": _tavily,
    "exa": _exa,
    "searxng": _searxng,
    "ddg": _ddg,
}


def _provider_names(extra: dict) -> list[str]:
    raw = extra.get("providers")
    if raw is None:
        return list(DEFAULT_PROVIDERS)
    if isinstance(raw, str):
        raw = raw.split(",")
    if not isinstance(raw, (list, tuple)):
        logger.warning("Invalid search_chain providers=%r; using the default order", raw)
        return list(DEFAULT_PROVIDERS)
    names = [str(name).strip().lower() for name in raw if str(name).strip()]
    return names or list(DEFAULT_PROVIDERS)


def _flag(value: object) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return value is True


@tool("web_search", parse_docstring=True)
async def web_search_tool(query: str, max_results: int = DEFAULT_MAX_RESULTS, time_range: SearchTimeRange | None = None) -> str:
    """Search the web for information. Use this tool to find current information, news, articles, and facts from the internet.

    Args:
        query: Search keywords describing what you want to find. Be specific for better results.
        max_results: Maximum number of results to return. Default is 5.
        time_range: Optional relative publication/update window. Use only when the request requires recent results.
    """
    # Config resolution stats and hashes the config files; keep it off the event loop.
    config = (await asyncio.to_thread(get_app_config)).get_tool_config("web_search")
    extra = (config.model_extra or {}) if config is not None else {}
    if "max_results" in extra:
        max_results = extra["max_results"]
    count = coerce_max_results(max_results, provider="Search chain", logger=logger)
    fallback_on_empty = _flag(extra.get("fallback_on_empty", False))

    attempts: list[dict] = []
    answered_empty = False
    for name in _provider_names(extra):
        adapter = PROVIDERS.get(name)
        if adapter is None:
            attempts.append({"provider": name, "status": "skipped", "reason": "unknown provider"})
            continue
        settings = extra.get(name)
        settings = settings if isinstance(settings, dict) else {}
        try:
            results = await adapter(_Call(query, count, time_range, settings))
        except ProviderSkipped as e:
            attempts.append({"provider": name, "status": "skipped", "reason": str(e)})
            continue
        except Exception as e:
            secret = resolve_api_key(settings.get("api_key"))
            error = redact_secret(f"{type(e).__name__}: {e}" if not isinstance(e, ProviderFailed) else e, secret)
            logger.warning("search_chain provider %s failed: %s", name, error)
            attempts.append({"provider": name, "status": "failed", "error": error})
            continue

        if not results:
            if fallback_on_empty:
                answered_empty = True
                attempts.append({"provider": name, "status": "empty"})
                continue
            return json.dumps({"error": NO_RESULTS, "query": query, "provider": name, "attempts": attempts}, ensure_ascii=False)

        results = results[:count]
        output = {"query": query, "provider": name, "total_results": len(results), "results": results}
        if attempts:
            output["attempts"] = attempts
        return json.dumps(output, indent=2, ensure_ascii=False)

    if answered_empty:
        return json.dumps({"error": NO_RESULTS, "query": query, "attempts": attempts}, ensure_ascii=False)
    summary = "; ".join(f"{a['provider']}: {a.get('error') or a.get('reason')}" for a in attempts) or "no providers configured"
    return json.dumps({"error": f"{ALL_FAILED} ({summary})", "query": query, "attempts": attempts}, ensure_ascii=False)
