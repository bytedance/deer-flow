import asyncio
import json
import os

from apify_client import ApifyClient
from langchain.tools import tool
from langgraph.config import get_stream_writer

from deerflow.config import get_app_config

# Terminal statuses as returned by the Apify API (note: hyphen in "TIMED-OUT").
# "TIMED_OUT" (underscore) is a separate local-poll sentinel used by this integration
# when the actor is still running but our local timeout_secs deadline is exceeded.
TERMINAL_STATUSES = {"SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"}


def _get_apify_client(tool_name: str) -> ApifyClient:
    config = get_app_config().get_tool_config(tool_name)
    api_key = None
    if config is not None and "api_key" in config.model_extra:
        api_key = config.model_extra.get("api_key")
    if not api_key:
        api_key = os.environ.get("APIFY_API_TOKEN")
    if not api_key:
        raise ValueError(f"APIFY_API_TOKEN is not configured. Set it as tools[{tool_name}].api_key in config.yaml or as the APIFY_API_TOKEN environment variable.")
    return ApifyClient(api_key)


@tool("web_search", parse_docstring=True)
def web_search_tool(query: str) -> str:
    """Search the web.

    Args:
        query: The query to search for.
    """
    try:
        config = get_app_config().get_tool_config("web_search")
        max_results = 5
        if config is not None:
            max_results = config.model_extra.get("max_results", max_results)

        client = _get_apify_client("web_search")
        run = client.actor("apify/google-search-scraper").call(
            run_input={
                "queries": [query],
                "maxPagesPerQuery": 1,
                "resultsPerPage": max_results,
            }
        )

        items = list(client.dataset(run["defaultDatasetId"]).iterate_items(limit=1))
        organic = items[0].get("organicResults", []) if items else []

        normalized = [
            {
                "title": r.get("title", "") or "",
                "url": r.get("url", "") or "",
                "snippet": r.get("description", "") or "",
            }
            for r in organic[:max_results]
        ]
        return json.dumps(normalized, indent=2, ensure_ascii=False)
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
        crawler_type = "cheerio"
        if config is not None:
            crawler_type = config.model_extra.get("crawler_type", crawler_type)

        client = _get_apify_client("web_fetch")
        run = client.actor("apify/website-content-crawler").call(
            run_input={
                "startUrls": [{"url": url}],
                "maxCrawlPages": 1,
                "crawlerType": crawler_type,
            }
        )

        items = list(client.dataset(run["defaultDatasetId"]).iterate_items(limit=1))
        if not items:
            return "Error: No content found"

        item = items[0]
        title = item.get("title", "Untitled") or "Untitled"
        content = item.get("markdown", "") or item.get("text", "")

        if not content:
            return "Error: No content found"

        # Truncate on UTF-8 byte boundary to keep payload size predictable
        encoded = content.encode("utf-8")
        if len(encoded) > 4096:
            truncated = encoded[:4096].decode("utf-8", errors="ignore")
            suffix = "\n\n[Content truncated]"
        else:
            truncated = content
            suffix = ""
        return f"# {title}\n\n{truncated}{suffix}"
    except Exception as e:
        return f"Error: {str(e)}"


@tool("apify_actor_discover", parse_docstring=True)
def apify_actor_discover_tool(query: str = "", actor_id: str = "") -> str:
    """Search the Apify Store for actors, or fetch an actor's input schema.
    Use before apify_actor_start on an unfamiliar actor to learn what input it expects.
    Provide query to search the store, or actor_id to fetch a specific actor's schema. Not both.

    Args:
        query: Search term to find actors in the Apify Store. E.g. 'instagram scraper'.
        actor_id: Actor ID to fetch its input schema. Accepts 'username/actor-name' (e.g. 'apify/instagram-scraper') or a plain ID (e.g. 'h7sDV53CddomktSi5').
    """
    if not query and not actor_id:
        return "Error: provide either query or actor_id, not neither"
    if query and actor_id:
        return "Error: provide either query or actor_id, not both"

    try:
        config = get_app_config().get_tool_config("apify_actor_discover")
        limit = 10
        if config is not None:
            limit = config.model_extra.get("max_results", limit)

        client = _get_apify_client("apify_actor_discover")

        if query:
            result = client.store().list(search=query, limit=limit)
            actors = []
            for a in result.items:
                username = a.get("username") or ""
                name = a.get("name") or ""
                if not username or not name:
                    continue
                actors.append(
                    {
                        "actorId": f"{username}/{name}",
                        "title": a.get("title") or "",
                        "description": (a.get("description") or "")[:200],
                    }
                )
            return json.dumps(
                {"action": "store_search", "query": query, "count": len(actors), "actors": actors},
                indent=2,
                ensure_ascii=False,
            )

        actor = client.actor(actor_id).get()
        if not actor:
            return f"Error: actor '{actor_id}' not found"

        input_schema = None
        try:
            versions = client.actor(actor_id).versions().list()
            if versions.items:
                latest_version_number = versions.items[-1].get("versionNumber")
                if latest_version_number:
                    version_detail = client.actor(actor_id).version(latest_version_number).get()
                    raw_schema = version_detail.get("inputSchema") if version_detail else None
                else:
                    raw_schema = versions.items[-1].get("inputSchema")
                # inputSchema may be stored as a JSON string; parse it to avoid double-encoding
                if isinstance(raw_schema, str):
                    try:
                        input_schema = json.loads(raw_schema)
                    except json.JSONDecodeError:
                        input_schema = raw_schema
                else:
                    input_schema = raw_schema
        except Exception:
            pass  # input schema is best-effort

        return json.dumps(
            {
                "action": "actor_schema",
                "actorId": actor_id,
                "title": actor.get("title") or "",
                "description": (actor.get("description") or "")[:500],
                "inputSchema": input_schema,
            },
            indent=2,
            ensure_ascii=False,
        )
    except Exception as e:
        return f"Error: {str(e)}"


@tool("apify_actor_start", parse_docstring=True)
def apify_actor_start_tool(actor_id: str, run_input: str, description: str = "") -> str:
    """Start an Apify actor run asynchronously and return a run reference immediately.
    The actor runs in the background — use apify_actor_await with the returned run_id and dataset_id to wait for results.
    To run multiple actors in parallel, call this tool once per actor, then call apify_actor_await for each run.
    You MUST call this tool directly when asked to start an actor — do not ask for clarification.

    Args:
        actor_id: The Apify actor ID. Accepts 'username/actor-name' (e.g. 'apify/instagram-scraper') or a plain ID (e.g. 'h7sDV53CddomktSi5'). Must not be empty.
        run_input: The actor input as a JSON-encoded string. Use "{}" for no input. E.g. '{"query": "test"}'.
        description: Optional human-readable label for this run, e.g. 'Scraping TikTok profile @apify'.
    """
    if not actor_id:
        return "Error: actor_id must not be empty"

    try:
        parsed_input = json.loads(run_input)
    except json.JSONDecodeError as e:
        return f"Error: run_input is not valid JSON — {str(e)}"

    try:
        config = get_app_config().get_tool_config("apify_actor_start")
        timeout_secs = None
        memory_mbytes = None
        if config is not None:
            timeout_secs = config.model_extra.get("timeout_secs")
            memory_mbytes = config.model_extra.get("memory_mbytes")

        client = _get_apify_client("apify_actor_start")

        start_kwargs: dict = {"run_input": parsed_input}
        if timeout_secs is not None:
            start_kwargs["timeout_secs"] = timeout_secs
        if memory_mbytes is not None:
            start_kwargs["memory_mbytes"] = memory_mbytes

        run = client.actor(actor_id).start(**start_kwargs)
        ref: dict = {
            "runId": run["id"],
            "actorId": actor_id,
            "datasetId": run["defaultDatasetId"],
            "status": run["status"],
        }
        if description:
            ref["description"] = description
        return json.dumps({"action": "start", "runs": [ref]}, indent=2, ensure_ascii=False)
    except Exception as e:
        return f"Error: {str(e)}"


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
    if not run_id:
        return "Error: run_id must not be empty"

    config = get_app_config().get_tool_config("apify_actor_await")
    poll_interval_secs = 5
    timeout_secs = 300
    max_items = 50
    if config is not None:
        poll_interval_secs = config.model_extra.get("poll_interval_secs", poll_interval_secs)
        timeout_secs = config.model_extra.get("timeout_secs", timeout_secs)
        max_items = config.model_extra.get("max_items", max_items)

    client = _get_apify_client("apify_actor_await")
    writer = get_stream_writer()

    loop = asyncio.get_running_loop()
    start_time = loop.time()
    deadline = start_time + timeout_secs

    writer({"type": "apify_run_polling", "runId": run_id, "status": "WAITING", "elapsed_secs": 0})

    try:
        while loop.time() < deadline:
            run = await asyncio.to_thread(client.run(run_id).get)
            elapsed = int(loop.time() - start_time)

            if not run:
                writer({"type": "apify_run_failed", "runId": run_id, "status": "NOT_FOUND", "elapsed_secs": elapsed})
                entry: dict = {"runId": run_id, "status": "NOT_FOUND", "error": "Run not found"}
                if description:
                    entry["description"] = description
                return json.dumps(entry, ensure_ascii=False)

            status = run.get("status", "")

            if status in TERMINAL_STATUSES:
                if status != "SUCCEEDED":
                    writer({"type": "apify_run_failed", "runId": run_id, "status": status, "elapsed_secs": elapsed})
                    entry = {"runId": run_id, "status": status, "error": f"Run {status.lower()}"}
                    if description:
                        entry["description"] = description
                    return json.dumps(entry, indent=2, ensure_ascii=False)

                # Use the fresh run's dataset ID in case it differs from the one passed in
                resolved_dataset_id = run.get("defaultDatasetId") or dataset_id
                items = await asyncio.to_thread(lambda: list(client.dataset(resolved_dataset_id).iterate_items(limit=max_items)))
                writer({"type": "apify_run_completed", "runId": run_id, "status": "SUCCEEDED", "elapsed_secs": elapsed, "resultCount": len(items)})
                entry = {"runId": run_id, "status": "SUCCEEDED", "resultCount": len(items), "results": items}
                if description:
                    entry["description"] = description
                return json.dumps(entry, indent=2, ensure_ascii=False)

            writer({"type": "apify_run_polling", "runId": run_id, "status": status, "elapsed_secs": elapsed})
            await asyncio.sleep(poll_interval_secs)

    except asyncio.CancelledError:
        writer({"type": "apify_run_cancelled", "runId": run_id})
        raise
    except Exception as e:
        elapsed = int(loop.time() - start_time)
        writer({"type": "apify_run_failed", "runId": run_id, "status": "ERROR", "elapsed_secs": elapsed})
        entry = {"runId": run_id, "status": "ERROR", "error": str(e)}
        if description:
            entry["description"] = description
        return json.dumps(entry, indent=2, ensure_ascii=False)

    elapsed = int(loop.time() - start_time)
    entry = {"runId": run_id, "error": f"Run did not complete within {timeout_secs}s", "status": "TIMED_OUT"}
    if description:
        entry["description"] = description
    return json.dumps(entry, indent=2, ensure_ascii=False)
