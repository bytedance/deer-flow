"""Web search, web fetch and Actor tools powered by Apify.

``web_search`` and ``web_fetch`` call Apify's Standby Actors ``apify/web-search``
(Google results) and ``apify/web-fetch`` (a page as markdown) over HTTP.
``apify_actor_discover``, ``apify_actor_start`` and ``apify_actor_await`` find,
start and wait for any Actor in Apify Store, so the agent can collect structured
data from sites that have a dedicated scraper. The ``apify-scraper`` skill routes
common platforms to known Actors.

The module uses httpx only, without the Apify SDK. Every tool is async: a run or
a Standby request can take a minute, and a sync tool would hold an executor
thread for that long. An API token is required; see ``APIFY_CREATE_TOKEN_URL``.
"""

import asyncio
import json
import logging
import math
import os
from collections.abc import Callable
from typing import Any
from urllib.parse import quote

import httpx
from langchain.tools import tool
from langgraph.config import get_stream_writer

from deerflow.community.provider_credentials import redact_secret, resolve_api_key
from deerflow.community.search_max_results import DEFAULT_MAX_RESULTS, coerce_max_results
from deerflow.community.url_safety import safe_public_result_url, validate_hosted_fetch_url
from deerflow.config import get_app_config

logger = logging.getLogger(__name__)

# Opens Console's create-token form with the description prefilled. Console shows a
# token only once and new accounts have none, so users must create one, not copy one.
APIFY_CREATE_TOKEN_URL = "https://console.apify.com/settings/integrations?createApiToken=true&for=DeerFlow&utm_source=deerflow&utm_medium=integrations"

_API_BASE_URL = "https://api.apify.com/v2"
_WEB_SEARCH_URL = "https://web-search.apify.actor/"
_WEB_FETCH_URL = "https://web-fetch.apify.actor/"
# Sent with every request so Apify can attribute the traffic to this integration.
_INTEGRATION_HEADERS = {"x-apify-integration-platform": "deerflow"}

# apify/web-search spends up to 60 seconds on a query; the rest covers a Standby cold start,
# which took over 90 seconds in a live run.
_SEARCH_TIMEOUT_SECS = 120.0
_FETCH_TIMEOUT_SECS = 120.0
_API_TIMEOUT_SECS = 30.0
# apify/web-search reads one Google results page, which holds about 10 organic results.
_SEARCH_MAX_RESULTS_CAP = 10
_DISCOVER_DEFAULT_RESULTS = 10
_FETCH_MAX_CHARS = 4096
_STORE_DESCRIPTION_CHARS = 200
_ACTOR_DESCRIPTION_CHARS = 500
_SCHEMA_DESCRIPTION_CHARS = 300
# Input schema keys the model needs to build a valid input. UI-only keys such as
# section captions are dropped to keep the discover result small.
_SCHEMA_PROPERTY_KEYS = ("title", "type", "description", "editor", "default", "prefill", "example", "enum", "items", "properties", "required", "minimum", "maximum")

# Terminal statuses as returned by the Apify API (note the hyphen in "TIMED-OUT").
# "TIMED_OUT" with an underscore is this tool's own result when the local wait
# ends while the run is still going on Apify.
TERMINAL_STATUSES = frozenset({"SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"})

_api_key_warned: set[str] = set()


class ApifyError(Exception):
    """An Apify failure whose message is safe to hand to the model."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _tool_settings(tool_name: str) -> tuple[str | None, dict[str, Any]]:
    """Read the API key and the tool's config extras in one config read.

    Config resolution stats and can reparse ``config.yaml``, so the async tools
    run this through ``asyncio.to_thread``.
    """
    config = get_app_config().get_tool_config(tool_name)
    extra = dict(config.model_extra or {}) if config is not None else {}
    api_key = resolve_api_key(extra.get("api_key")) or resolve_api_key(os.getenv("APIFY_API_TOKEN"))
    return api_key, extra


def _missing_key_error(tool_name: str) -> str:
    if tool_name not in _api_key_warned:
        _api_key_warned.add(tool_name)
        logger.warning("Apify API token is not set for '%s'. Set APIFY_API_TOKEN or tools[%s].api_key in config.yaml.", tool_name, tool_name)
    return (
        f"APIFY_API_TOKEN is not configured. Create an API token for DeerFlow in Apify Console ({APIFY_CREATE_TOKEN_URL}) "
        "and copy it right after creating it, because it is shown only once. "
        f"Then set it as the APIFY_API_TOKEN environment variable or as tools[{tool_name}].api_key in config.yaml."
    )


def _positive_number(value: object, *, integer: bool) -> float | None:
    """Return *value* as a positive, finite number, or None when it is not one.

    A ``$VAR`` reference resolves to a string, so ``"300"`` is accepted. A boolean,
    a value that is not positive and finite, or a fraction for an integer setting
    is not a number here.
    """
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number <= 0 or (integer and not number.is_integer()):
        return None
    return int(number) if integer else number


def _config_number(extra: dict[str, Any], key: str, default: float | None, *, integer: bool) -> float | None:
    """Read a positive number from a tool's config extras.

    An invalid value falls back to the default with a warning instead of failing
    the tool call.
    """
    value = extra.get(key)
    if value is None:
        return default
    number = _positive_number(value, integer=integer)
    if number is None:
        logger.warning("Invalid Apify %s=%r; using default %s", key, value, default)
        return default
    return number


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


def _objects(value: object, container: str) -> list[dict[str, Any]] | None:
    """Return the object entries of a response list, or None when it is malformed.

    A missing or null container is empty. A non-list container, or a non-empty
    list that holds no objects, is malformed: the caller reports a format error
    rather than an empty result, which would tell the agent nothing matched.
    """
    if value is None:
        return []
    if not isinstance(value, list):
        logger.error("Apify returned an unexpected '%s' payload type: %s", container, type(value).__name__)
        return None
    usable = [item for item in value if isinstance(item, dict)]
    if value and not usable:
        logger.error("Apify returned '%s' with no usable objects", container)
        return None
    return usable


def _error_detail(response: httpx.Response) -> str | None:
    """Read either error shape Apify returns.

    The API and the Standby gateway send ``{"error": {"message": ...}}``; a Standby
    Actor's own errors are ``{"error": "...", "code": "..."}``.
    """
    try:
        body = response.json()
    except ValueError:
        return None
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, dict) and isinstance(error.get("message"), str):
        return error["message"]
    if isinstance(error, str):
        code = body.get("code")
        return f"{error} (code: {code})" if isinstance(code, str) else error
    return None


def _raise_for_status(response: httpx.Response, action: str) -> None:
    if response.status_code < 400:
        return
    detail = _error_detail(response)
    message = f"{action} failed with HTTP {response.status_code}"
    if detail:
        message = f"{message}: {detail}"
    if response.status_code == 401:
        message = f"{message}. Apify rejected the API token; create a new one for DeerFlow at {APIFY_CREATE_TOKEN_URL}"
    raise ApifyError(message, response.status_code)


def _json_body(response: httpx.Response, action: str) -> object:
    try:
        return response.json()
    except ValueError:
        logger.error("Apify %s returned a body that is not JSON", action)
        raise ApifyError(f"{action} returned an unexpected response format") from None


async def _new_client(timeout: float) -> httpx.AsyncClient:
    # The constructor sets up TLS synchronously, so build the client off the loop.
    return await asyncio.to_thread(httpx.AsyncClient, timeout=timeout, headers=_INTEGRATION_HEADERS)


def _auth(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


async def _api_data(client: httpx.AsyncClient, api_key: str, method: str, path: str, *, action: str, params: dict[str, Any] | None = None, payload: object = None) -> dict[str, Any]:
    """Call the Apify API and return the object in its ``data`` envelope."""
    response = await client.request(method, f"{_API_BASE_URL}{path}", headers=_auth(api_key), params=params, json=payload)
    _raise_for_status(response, action)
    body = _json_body(response, action)
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, dict):
        logger.error("Apify %s returned an unexpected 'data' payload type: %s", action, type(data).__name__)
        raise ApifyError(f"{action} returned an unexpected response format")
    return data


def _actor_path(actor_id: str) -> str:
    """Turn ``owner/name``, ``owner~name`` or a plain Actor ID into a URL path segment."""
    return quote(actor_id.strip().replace("/", "~"), safe="~")


def _error_text(error: Exception, api_key: str | None, action: str) -> str:
    if not isinstance(error, ApifyError):
        logger.error("Apify %s failed: %s", action, type(error).__name__)
    # Some transport errors, such as httpx.ReadTimeout, carry no message.
    return redact_secret(error, api_key) or f"Apify {action} failed: {type(error).__name__}"


@tool("web_search", parse_docstring=True)
async def web_search_tool(query: str, max_results: int | None = None) -> str:
    """Search the web for information. Use this tool to find current information, news, articles, and facts from the internet.

    Args:
        query: Search keywords or a question describing what you want to find. Be specific for better results.
        max_results: Maximum number of results to return, up to 10. If omitted, uses the configured value (default 5).
    """
    api_key, extra = await asyncio.to_thread(_tool_settings, "web_search")
    # Honor the caller-supplied max_results; fall back to config only when omitted.
    if max_results is None:
        max_results = extra.get("max_results")
    count = min(DEFAULT_MAX_RESULTS if max_results is None else coerce_max_results(max_results, provider="Apify", logger=logger), _SEARCH_MAX_RESULTS_CAP)

    if not api_key:
        return json.dumps({"error": _missing_key_error("web_search"), "query": query}, ensure_ascii=False)

    try:
        async with await _new_client(_SEARCH_TIMEOUT_SECS) as client:
            response = await client.post(_WEB_SEARCH_URL, headers=_auth(api_key), json={"query": query, "maxResults": count})
        _raise_for_status(response, "Apify web search")
        body = _json_body(response, "Apify web search")
    except Exception as e:
        return json.dumps({"error": _error_text(e, api_key, "web search"), "query": query}, ensure_ascii=False)

    hits = _objects(body.get("results"), "results") if isinstance(body, dict) else None
    if hits is None:
        if not isinstance(body, dict):
            logger.error("Apify web search returned an unexpected payload type: %s", type(body).__name__)
        return json.dumps({"error": "Apify web search returned an unexpected response format", "query": query}, ensure_ascii=False)
    if not hits:
        return json.dumps({"error": "No results found", "query": query}, ensure_ascii=False)

    results = [
        {
            "title": _text(hit.get("title")),
            "url": safe_public_result_url(hit.get("url")),
            "snippet": _text(hit.get("snippet")),
        }
        for hit in hits[:count]
    ]
    return json.dumps({"query": query, "total_results": len(results), "results": results}, indent=2, ensure_ascii=False)


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
    target_error = validate_hosted_fetch_url(url)
    if target_error:
        return target_error

    api_key, _extra = await asyncio.to_thread(_tool_settings, "web_fetch")
    if not api_key:
        return f"Error: {_missing_key_error('web_fetch')}"

    try:
        async with await _new_client(_FETCH_TIMEOUT_SECS) as client:
            response = await client.post(_WEB_FETCH_URL, headers=_auth(api_key), json={"url": url, "formats": ["markdown"]})
        _raise_for_status(response, "Apify web fetch")
        body = _json_body(response, "Apify web fetch")
    except Exception as e:
        return f"Error: {_error_text(e, api_key, 'web fetch')}"

    if not isinstance(body, dict):
        logger.error("Apify web fetch returned an unexpected payload type: %s", type(body).__name__)
        return "Error: Apify web fetch returned an unexpected response format"
    fetch = body.get("fetch")
    metadata = body.get("metadata")
    if not isinstance(fetch, dict | None) or not isinstance(metadata, dict | None):
        logger.error("Apify web fetch returned unexpected 'fetch'/'metadata' payload types: %s, %s", type(fetch).__name__, type(metadata).__name__)
        return "Error: Apify web fetch returned an unexpected response format"

    # A 200 from the Standby Actor means the Actor ran; the page's own status is here.
    page_status = (fetch or {}).get("httpStatusCode")
    if isinstance(page_status, int) and not isinstance(page_status, bool) and page_status >= 400:
        return f"Error: The page returned HTTP {page_status}"

    content = _text(body.get("markdown"))
    if not content.strip():
        return "Error: No content found"
    title = _text((metadata or {}).get("title")).strip() or "Untitled"
    if len(content) > _FETCH_MAX_CHARS:
        content = f"{content[:_FETCH_MAX_CHARS]}\n\n[Content truncated]"
    return f"# {title}\n\n{content}"


def _compact_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Keep what the model needs to build a valid input: fields, types, defaults, examples."""
    compact: dict[str, Any] = {}
    if isinstance(schema.get("required"), list):
        compact["required"] = schema["required"]
    properties = schema.get("properties")
    if isinstance(properties, dict):
        compact["properties"] = {}
        for name, spec in properties.items():
            if not isinstance(spec, dict):
                continue
            kept = {key: spec[key] for key in _SCHEMA_PROPERTY_KEYS if key in spec}
            description = kept.get("description")
            if isinstance(description, str) and len(description) > _SCHEMA_DESCRIPTION_CHARS:
                kept["description"] = f"{description[:_SCHEMA_DESCRIPTION_CHARS]}..."
            compact["properties"][name] = kept
    return compact


async def _input_schema(client: httpx.AsyncClient, api_key: str, path: str) -> dict[str, Any] | None:
    """Read the input schema from the Actor's default build.

    The build carries the schema for every public Actor, while an Actor version
    only shows it to the owner.
    """
    build = await _api_data(client, api_key, "GET", f"/acts/{path}/builds/default", action="Reading the Actor's input schema")
    definition = build.get("actorDefinition")
    schema = definition.get("input") if isinstance(definition, dict) else None
    if not isinstance(schema, dict) and isinstance(build.get("inputSchema"), str):
        try:
            schema = json.loads(build["inputSchema"])
        except ValueError:
            schema = None
    return _compact_schema(schema) if isinstance(schema, dict) else None


async def _search_store(client: httpx.AsyncClient, api_key: str, query: str, limit: int) -> str:
    data = await _api_data(client, api_key, "GET", "/store", action="Apify Store search", params={"search": query, "limit": limit, "sortBy": "relevance"})
    items = _objects(data.get("items"), "items")
    if items is None:
        raise ApifyError("Apify Store search returned an unexpected response format")
    actors = []
    for item in items:
        username, name = _text(item.get("username")), _text(item.get("name"))
        if not username or not name:
            continue
        stats = item.get("stats") if isinstance(item.get("stats"), dict) else {}
        pricing = item.get("currentPricingInfo") if isinstance(item.get("currentPricingInfo"), dict) else {}
        monthly_users = stats.get("totalUsers30Days")
        actors.append(
            {
                "actorId": f"{username}/{name}",
                "title": _text(item.get("title")),
                "description": _text(item.get("description"))[:_STORE_DESCRIPTION_CHARS],
                "monthlyUsers": monthly_users if isinstance(monthly_users, int) and not isinstance(monthly_users, bool) else None,
                "pricingModel": _text(pricing.get("pricingModel")) or None,
                "url": safe_public_result_url(item.get("url")),
            }
        )
    return json.dumps({"action": "store_search", "query": query, "count": len(actors), "actors": actors}, indent=2, ensure_ascii=False)


async def _describe_actor(client: httpx.AsyncClient, api_key: str, actor_id: str) -> str:
    path = _actor_path(actor_id)
    try:
        actor = await _api_data(client, api_key, "GET", f"/acts/{path}", action="Reading the Actor")
    except ApifyError as e:
        if e.status_code == 404:
            return f"Error: Actor '{actor_id}' not found. Use an ID like 'username/actor-name' from a Store search."
        raise
    username, name = _text(actor.get("username")), _text(actor.get("name"))
    canonical_id = f"{username}/{name}" if username and name else actor_id
    try:
        input_schema = await _input_schema(client, api_key, path)
    except ApifyError as e:
        logger.warning("Apify input schema lookup failed with HTTP %s", e.status_code)
        input_schema = None
    result: dict[str, Any] = {
        "action": "actor_schema",
        "actorId": canonical_id,
        "title": _text(actor.get("title")),
        "description": _text(actor.get("description"))[:_ACTOR_DESCRIPTION_CHARS],
        "inputSchema": input_schema,
    }
    if username and name:
        result["url"] = safe_public_result_url(f"https://apify.com/{username}/{name}")
    if input_schema is None:
        result["note"] = "This Actor publishes no input schema. Read its README on Apify Store before starting it."
    return json.dumps(result, indent=2, ensure_ascii=False)


@tool("apify_actor_discover", parse_docstring=True)
async def apify_actor_discover_tool(query: str = "", actor_id: str = "") -> str:
    """Search the Apify Store for actors, or fetch an actor's input schema.
    Use before apify_actor_start on an unfamiliar actor to learn what input it expects.
    Provide query to search the store, or actor_id to fetch a specific actor's schema. Not both.

    Args:
        query: Search term to find actors in the Apify Store. E.g. 'instagram scraper'.
        actor_id: Actor ID to fetch its input schema. Accepts 'username/actor-name' (e.g. 'apify/instagram-scraper') or a plain ID (e.g. 'h7sDV53CddomktSi5').
    """
    query, actor_id = query.strip(), actor_id.strip()
    if not query and not actor_id:
        return "Error: provide either query or actor_id"
    if query and actor_id:
        return "Error: provide either query or actor_id, not both"

    api_key, extra = await asyncio.to_thread(_tool_settings, "apify_actor_discover")
    if not api_key:
        return f"Error: {_missing_key_error('apify_actor_discover')}"
    configured = extra.get("max_results")
    limit = _DISCOVER_DEFAULT_RESULTS if configured is None else coerce_max_results(configured, provider="Apify", logger=logger, default=_DISCOVER_DEFAULT_RESULTS)

    try:
        async with await _new_client(_API_TIMEOUT_SECS) as client:
            if query:
                return await _search_store(client, api_key, query, limit)
            return await _describe_actor(client, api_key, actor_id)
    except Exception as e:
        return f"Error: {_error_text(e, api_key, 'Actor discovery')}"


@tool("apify_actor_start", parse_docstring=True)
async def apify_actor_start_tool(actor_id: str, run_input: str, description: str = "") -> str:
    """Start an Apify actor run asynchronously and return a run reference immediately.
    The actor runs in the background — use apify_actor_await with the returned run_id and dataset_id to wait for results.
    To run multiple actors in parallel, call this tool once per actor, then call apify_actor_await for each run.
    You MUST call this tool directly when asked to start an actor — do not ask for clarification.

    Args:
        actor_id: The Apify actor ID. Accepts 'username/actor-name' (e.g. 'apify/instagram-scraper') or a plain ID (e.g. 'h7sDV53CddomktSi5'). Must not be empty.
        run_input: The actor input as a JSON object encoded as a string. Use "{}" for no input. E.g. '{"query": "test"}'.
        description: Optional human-readable label for this run, e.g. 'Scraping TikTok profile @apify'.
    """
    actor_id = actor_id.strip()
    if not actor_id:
        return "Error: actor_id must not be empty"
    try:
        parsed_input = json.loads(run_input) if run_input.strip() else {}
    except json.JSONDecodeError as e:
        return f"Error: run_input is not valid JSON — {e}"
    if not isinstance(parsed_input, dict):
        return 'Error: run_input must be a JSON object, for example \'{"query": "test"}\''

    api_key, extra = await asyncio.to_thread(_tool_settings, "apify_actor_start")
    if not api_key:
        return f"Error: {_missing_key_error('apify_actor_start')}"

    params: dict[str, Any] = {}
    for key, param in (("timeout_secs", "timeout"), ("memory_mbytes", "memory")):
        value = _config_number(extra, key, None, integer=True)
        if value is not None:
            params[param] = value
    # A cost cap that cannot be read must not start the run without one. Apify reads
    # a cap of 0 as no cap at all, so 0 is refused like any other invalid value.
    configured_cap = extra.get("max_total_charge_usd")
    if configured_cap is not None:
        cap = _positive_number(configured_cap, integer=False)
        if cap is None:
            logger.error("Invalid Apify max_total_charge_usd=%r; refusing to start the run without a cost cap", configured_cap)
            return "Error: tools[apify_actor_start].max_total_charge_usd in config.yaml must be a positive number of US dollars. The run was not started. Ask the operator to fix the setting."
        params["maxTotalChargeUsd"] = cap

    try:
        async with await _new_client(_API_TIMEOUT_SECS) as client:
            run = await _api_data(client, api_key, "POST", f"/acts/{_actor_path(actor_id)}/runs", action="Starting the Actor", params=params, payload=parsed_input)
    except Exception as e:
        return f"Error: {_error_text(e, api_key, 'Actor start')}"

    run_id, dataset_id, status = run.get("id"), run.get("defaultDatasetId"), run.get("status")
    if not (isinstance(run_id, str) and isinstance(dataset_id, str) and isinstance(status, str)):
        logger.error("Apify Actor start returned a run without string id, defaultDatasetId and status")
        return "Error: Starting the Actor returned an unexpected response format"
    ref: dict[str, Any] = {"runId": run_id, "actorId": actor_id, "datasetId": dataset_id, "status": status}
    if description:
        ref["description"] = description
    return json.dumps({"action": "start", "runs": [ref]}, indent=2, ensure_ascii=False)


def _stream_writer() -> Callable[[dict[str, Any]], None]:
    try:
        return get_stream_writer()
    except RuntimeError:
        # Called outside a graph run, for example from a script: drop progress events.
        return lambda _event: None


async def _dataset_items(client: httpx.AsyncClient, api_key: str, dataset_id: str, limit: int) -> list[dict[str, Any]]:
    response = await client.get(f"{_API_BASE_URL}/datasets/{quote(dataset_id, safe='')}/items", headers=_auth(api_key), params={"limit": limit, "clean": "true", "format": "json"})
    _raise_for_status(response, "Reading the run's results")
    items = _objects(_json_body(response, "Reading the run's results"), "items")
    if items is None:
        raise ApifyError("Reading the run's results returned an unexpected response format")
    return items


@tool("apify_actor_await", parse_docstring=True)
async def apify_actor_await_tool(run_id: str, dataset_id: str, description: str = "") -> str:
    """Wait for a previously started Apify actor run to complete and return its results.
    Polls the run status internally until it reaches a terminal state, streaming progress
    events. A single call handles all polling — loop detection never fires.

    Args:
        run_id: The run ID from apify_actor_start (runs[0].runId).
        dataset_id: The dataset ID from apify_actor_start (runs[0].datasetId).
        description: Optional human-readable label for this run, e.g. 'Waiting for TikTok scraper'.
    """
    run_id = run_id.strip()
    if not run_id:
        return "Error: run_id must not be empty"

    def result(entry: dict[str, Any]) -> str:
        if description:
            entry["description"] = description
        return json.dumps(entry, indent=2, ensure_ascii=False)

    # Config resolution reads files; keep it off the event loop.
    api_key, extra = await asyncio.to_thread(_tool_settings, "apify_actor_await")
    poll_interval_secs = _config_number(extra, "poll_interval_secs", 5, integer=False)
    timeout_secs = _config_number(extra, "timeout_secs", 300, integer=False)
    max_items = _config_number(extra, "max_items", 50, integer=True)
    if not api_key:
        return result({"runId": run_id, "status": "ERROR", "error": _missing_key_error("apify_actor_await")})

    writer = _stream_writer()
    loop = asyncio.get_running_loop()
    start_time = loop.time()
    deadline = start_time + timeout_secs

    def elapsed() -> int:
        return int(loop.time() - start_time)

    writer({"type": "apify_run_polling", "runId": run_id, "status": "WAITING", "elapsed_secs": 0})
    try:
        async with await _new_client(_API_TIMEOUT_SECS) as client:
            while True:
                try:
                    run = await _api_data(client, api_key, "GET", f"/actor-runs/{quote(run_id, safe='')}", action="Reading the run")
                except ApifyError as e:
                    if e.status_code != 404:
                        raise
                    writer({"type": "apify_run_failed", "runId": run_id, "status": "NOT_FOUND", "elapsed_secs": elapsed()})
                    return result({"runId": run_id, "status": "NOT_FOUND", "error": "Run not found"})

                status = _text(run.get("status"))
                if status in TERMINAL_STATUSES:
                    if status != "SUCCEEDED":
                        writer({"type": "apify_run_failed", "runId": run_id, "status": status, "elapsed_secs": elapsed()})
                        entry: dict[str, Any] = {"runId": run_id, "status": status, "error": f"Run {status.lower()}"}
                        if _text(run.get("statusMessage")):
                            entry["statusMessage"] = run["statusMessage"]
                        return result(entry)
                    # Prefer the run's own dataset in case it differs from the one passed in.
                    resolved_dataset_id = _text(run.get("defaultDatasetId")) or dataset_id.strip()
                    if not resolved_dataset_id:
                        raise ApifyError("The run has no dataset to read results from")
                    items = await _dataset_items(client, api_key, resolved_dataset_id, max_items)
                    writer({"type": "apify_run_completed", "runId": run_id, "status": "SUCCEEDED", "elapsed_secs": elapsed(), "resultCount": len(items)})
                    return result({"runId": run_id, "status": "SUCCEEDED", "resultCount": len(items), "results": items})

                remaining = deadline - loop.time()
                if remaining <= 0:
                    break
                writer({"type": "apify_run_polling", "runId": run_id, "status": status, "elapsed_secs": elapsed()})
                await asyncio.sleep(min(poll_interval_secs, remaining))
    except asyncio.CancelledError:
        writer({"type": "apify_run_cancelled", "runId": run_id})
        raise
    except Exception as e:
        writer({"type": "apify_run_failed", "runId": run_id, "status": "ERROR", "elapsed_secs": elapsed()})
        return result({"runId": run_id, "status": "ERROR", "error": _error_text(e, api_key, "run await")})

    return result(
        {
            "runId": run_id,
            "status": "TIMED_OUT",
            "error": f"Run did not finish within {timeout_secs:g}s. It is still running on Apify; call apify_actor_await again with the same run_id to keep waiting.",
        }
    )
