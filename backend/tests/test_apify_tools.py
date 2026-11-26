"""Tests for the Apify community tools.

Every test drives the real tool through an offline HTTPX transport: a fake Apify
answers the requests the tool actually builds, so the request shape, the response
validation and the normalization are all under test. The provider's own ``httpx``
reference is replaced; the shared ``httpx.AsyncClient`` stays untouched.
"""

import json
import logging
import re
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from deerflow.community.apify import tools as apify_tools

pytestmark = pytest.mark.asyncio

TOKEN = "test-apify-token"

Handler = Callable[[httpx.Request], httpx.Response]


class FakeApify:
    """Routes requests by (method, host, path) and records every request it saw."""

    def __init__(self) -> None:
        self.routes: dict[tuple[str, str, str], Handler | list[Handler]] = {}
        self.requests: list[httpx.Request] = []

    def on(self, method: str, url: str, *responses: httpx.Response | Handler) -> None:
        parsed = urlparse(url if "://" in url else f"https://api.apify.com{url}")
        # A fresh copy per request: a scripted response can be served more than once.
        handlers = [r if callable(r) else (lambda _req, r=r: httpx.Response(r.status_code, headers=r.headers, content=r.content)) for r in responses]
        self.routes[(method, parsed.hostname or "", parsed.path)] = handlers

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        handlers = self.routes.get((request.method, request.url.host, request.url.path))
        if not handlers:
            return httpx.Response(404, json={"error": {"type": "record-not-found", "message": "Not found"}})
        # Repeat the last response once the scripted sequence is used up.
        handler = handlers.pop(0) if len(handlers) > 1 else handlers[0]
        return handler(request)

    def only(self, method: str, path: str) -> list[httpx.Request]:
        return [r for r in self.requests if r.method == method and r.url.path == path]


@pytest.fixture
def apify(monkeypatch: pytest.MonkeyPatch) -> FakeApify:
    fake = FakeApify()
    transport = httpx.MockTransport(fake)
    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(apify_tools, "httpx", SimpleNamespace(AsyncClient=lambda **kwargs: real_async_client(transport=transport, **kwargs)))
    return fake


@pytest.fixture
def config(monkeypatch: pytest.MonkeyPatch) -> Callable[..., None]:
    def configure(tool_config: dict[str, Any] | None = None, **extra: Any) -> None:
        values = {"api_key": TOKEN, **extra} if tool_config is None else tool_config
        monkeypatch.setattr(apify_tools, "get_app_config", lambda: SimpleNamespace(get_tool_config=lambda _name: SimpleNamespace(model_extra=dict(values))))

    configure()
    return configure


@pytest.fixture
def events(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    seen: list[dict[str, Any]] = []
    monkeypatch.setattr(apify_tools, "get_stream_writer", lambda: seen.append)
    return seen


def _data(payload: dict[str, Any], status: int = 200) -> httpx.Response:
    return httpx.Response(status, json={"data": payload})


def _error(status: int, message: str, error_type: str = "invalid-input") -> httpx.Response:
    return httpx.Response(status, json={"error": {"type": error_type, "message": message}})


class TestCredentials:
    async def test_configured_key_is_stripped(self, config):
        config({"api_key": "  configured-key\n"})
        assert apify_tools._tool_settings("web_search")[0] == "configured-key"

    async def test_blank_configured_key_falls_back_to_stripped_environment_key(self, config, monkeypatch):
        config({"api_key": "   "})
        monkeypatch.setenv("APIFY_API_TOKEN", "  env-apify-key\n")
        assert apify_tools._tool_settings("web_search")[0] == "env-apify-key"

    async def test_unconfigured_tool_reads_the_environment(self, monkeypatch):
        monkeypatch.setattr(apify_tools, "get_app_config", lambda: SimpleNamespace(get_tool_config=lambda _name: None))
        monkeypatch.setenv("APIFY_API_TOKEN", "env-only")
        assert apify_tools._tool_settings("apify_actor_start") == ("env-only", {})

    async def test_missing_key_points_to_the_create_token_form(self, config, apify, monkeypatch):
        config({})
        monkeypatch.delenv("APIFY_API_TOKEN", raising=False)

        payload = json.loads(await apify_tools.web_search_tool.ainvoke({"query": "q"}))

        message = payload["error"]
        assert "tools[web_search].api_key" in message and "APIFY_API_TOKEN" in message and "shown only once" in message
        link = urlparse(re.search(r"https://console\.apify\.com\S+?(?=\))", message).group(0))
        assert link.path == "/settings/integrations"
        assert parse_qs(link.query) == {"createApiToken": ["true"], "for": ["DeerFlow"], "utm_source": ["deerflow"], "utm_medium": ["integrations"]}
        assert apify.requests == []

    async def test_rejected_token_points_to_the_create_token_form_without_echoing_it(self, config, apify):
        apify.on("POST", "https://web-search.apify.actor/", _error(401, f"Token {TOKEN} is not valid", "user-or-token-not-found"))

        message = json.loads(await apify_tools.web_search_tool.ainvoke({"query": "q"}))["error"]

        assert "HTTP 401" in message and apify_tools.APIFY_CREATE_TOKEN_URL in message
        assert TOKEN not in message and "[REDACTED]" in message

    async def test_requests_carry_the_token_and_the_integration_header(self, config, apify):
        apify.on("POST", "https://web-search.apify.actor/", httpx.Response(200, json={"results": []}))

        await apify_tools.web_search_tool.ainvoke({"query": "q"})

        (request,) = apify.requests
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
        assert request.headers["x-apify-integration-platform"] == "deerflow"


class TestWebSearch:
    async def test_sends_the_query_and_normalizes_results(self, config, apify):
        hits = [
            {"position": 1, "url": "https://example.com/a", "title": "A", "snippet": "first"},
            "not an object",
            {"position": 2, "url": "http://169.254.169.254/latest/meta-data", "title": "Metadata", "snippet": "blocked"},
        ]
        apify.on("POST", "https://web-search.apify.actor/", httpx.Response(200, json={"query": "q", "results": hits}))

        payload = json.loads(await apify_tools.web_search_tool.ainvoke({"query": "langgraph news"}))

        assert json.loads(apify.requests[0].content) == {"query": "langgraph news", "maxResults": 5}
        assert payload["total_results"] == 2
        assert payload["results"] == [
            {"title": "A", "url": "https://example.com/a", "snippet": "first"},
            {"title": "Metadata", "url": "", "snippet": "blocked"},
        ]

    @pytest.mark.parametrize(("configured", "requested", "sent"), [("3", None, 3), (5, 7, 7), (5, 50, 10), (True, None, 5)])
    async def test_result_count_comes_from_the_call_then_config_and_is_capped(self, config, apify, configured, requested, sent):
        config(max_results=configured)
        apify.on("POST", "https://web-search.apify.actor/", httpx.Response(200, json={"results": [{"url": f"https://e.com/{i}"} for i in range(12)]}))
        args = {"query": "q"} if requested is None else {"query": "q", "max_results": requested}

        payload = json.loads(await apify_tools.web_search_tool.ainvoke(args))

        assert json.loads(apify.requests[0].content)["maxResults"] == sent
        assert payload["total_results"] == sent

    async def test_empty_results_are_reported_as_no_results(self, config, apify):
        apify.on("POST", "https://web-search.apify.actor/", httpx.Response(200, json={"results": []}))
        assert json.loads(await apify_tools.web_search_tool.ainvoke({"query": "q"}))["error"] == "No results found"

    @pytest.mark.parametrize("body", [{"results": {"url": "x"}}, {"results": ["a", "b"]}, ["not", "an", "object"]])
    async def test_malformed_containers_are_format_errors(self, config, apify, body, caplog):
        apify.on("POST", "https://web-search.apify.actor/", httpx.Response(200, json=body))
        with caplog.at_level(logging.ERROR, logger=apify_tools.__name__):
            payload = json.loads(await apify_tools.web_search_tool.ainvoke({"query": "secret query"}))
        assert payload["error"] == "Apify web search returned an unexpected response format"
        assert "secret query" not in caplog.text

    async def test_actor_input_errors_reach_the_model(self, config, apify):
        apify.on("POST", "https://web-search.apify.actor/", httpx.Response(400, json={"code": "INVALID_QUERY", "error": "Query is too long"}))
        message = json.loads(await apify_tools.web_search_tool.ainvoke({"query": "q"}))["error"]
        assert message == "Apify web search failed with HTTP 400: Query is too long (code: INVALID_QUERY)"

    async def test_transport_failure_is_an_error_result(self, config, apify):
        def fail(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        apify.on("POST", "https://web-search.apify.actor/", fail)
        assert "connection refused" in json.loads(await apify_tools.web_search_tool.ainvoke({"query": "q"}))["error"]

    async def test_a_timeout_without_a_message_is_still_named(self, config, apify):
        def time_out(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("", request=request)

        apify.on("POST", "https://web-search.apify.actor/", time_out)
        error = json.loads(await apify_tools.web_search_tool.ainvoke({"query": "q"}))["error"]
        assert error == "Apify web search failed: ReadTimeout"


class TestWebFetch:
    async def test_returns_the_title_from_metadata_and_the_markdown(self, config, apify):
        body = {"fetch": {"loadedUrl": "https://apify.com/", "httpStatusCode": 200}, "metadata": {"title": "Apify: Marketplace"}, "markdown": "Body text"}
        apify.on("POST", "https://web-fetch.apify.actor/", httpx.Response(200, json=body))

        result = await apify_tools.web_fetch_tool.ainvoke({"url": "https://apify.com"})

        assert result == "# Apify: Marketplace\n\nBody text"
        assert json.loads(apify.requests[0].content) == {"url": "https://apify.com", "formats": ["markdown"]}

    async def test_long_content_is_truncated(self, config, apify):
        apify.on("POST", "https://web-fetch.apify.actor/", httpx.Response(200, json={"metadata": {}, "markdown": "x" * 5000}))
        result = await apify_tools.web_fetch_tool.ainvoke({"url": "https://example.com"})
        assert result == f"# Untitled\n\n{'x' * 4096}\n\n[Content truncated]"

    async def test_the_page_status_is_checked_not_only_the_actor_status(self, config, apify):
        apify.on("POST", "https://web-fetch.apify.actor/", httpx.Response(200, json={"fetch": {"httpStatusCode": 404}, "markdown": "Not found page"}))
        assert await apify_tools.web_fetch_tool.ainvoke({"url": "https://example.com/missing"}) == "Error: The page returned HTTP 404"

    async def test_empty_content_is_reported(self, config, apify):
        apify.on("POST", "https://web-fetch.apify.actor/", httpx.Response(200, json={"metadata": {"title": "T"}, "markdown": "  "}))
        assert await apify_tools.web_fetch_tool.ainvoke({"url": "https://example.com"}) == "Error: No content found"

    @pytest.mark.parametrize("body", [["list"], {"fetch": "ok", "markdown": "x"}, {"metadata": ["t"], "markdown": "x"}])
    async def test_malformed_containers_are_format_errors(self, config, apify, body):
        apify.on("POST", "https://web-fetch.apify.actor/", httpx.Response(200, json=body))
        assert await apify_tools.web_fetch_tool.ainvoke({"url": "https://example.com"}) == "Error: Apify web fetch returned an unexpected response format"

    @pytest.mark.parametrize("url", ["http://169.254.169.254/latest/meta-data", "http://localhost:8001/api", "ftp://example.com/file", "example.com"])
    async def test_non_public_urls_are_refused_before_calling_apify(self, config, apify, url):
        result = await apify_tools.web_fetch_tool.ainvoke({"url": url})
        assert result.startswith("Error: ")
        assert apify.requests == []


class TestDiscover:
    async def test_store_search_normalizes_and_screens_entries(self, config, apify):
        items = [
            {
                "username": "trudax",
                "name": "reddit-scraper",
                "title": "Reddit Scraper",
                "description": "d" * 300,
                "stats": {"totalUsers30Days": 1200},
                "currentPricingInfo": {"pricingModel": "PAY_PER_EVENT"},
                "url": "https://apify.com/trudax/reddit-scraper",
            },
            {"name": "no-owner"},
            "not an object",
        ]
        apify.on("GET", "/v2/store", _data({"items": items, "total": 3}))

        payload = json.loads(await apify_tools.apify_actor_discover_tool.ainvoke({"query": "reddit"}))

        params = apify.requests[0].url.params
        assert (params["search"], params["limit"], params["sortBy"]) == ("reddit", "10", "relevance")
        assert payload["count"] == 1
        assert payload["actors"] == [
            {
                "actorId": "trudax/reddit-scraper",
                "title": "Reddit Scraper",
                "description": "d" * 200,
                "monthlyUsers": 1200,
                "pricingModel": "PAY_PER_EVENT",
                "url": "https://apify.com/trudax/reddit-scraper",
            }
        ]

    async def test_store_search_honors_configured_max_results(self, config, apify):
        config(max_results="3")
        apify.on("GET", "/v2/store", _data({"items": []}))
        await apify_tools.apify_actor_discover_tool.ainvoke({"query": "maps"})
        assert apify.requests[0].url.params["limit"] == "3"

    async def test_actor_id_returns_the_input_schema_from_the_default_build(self, config, apify):
        schema = {
            "title": "Input",
            "type": "object",
            "required": ["username"],
            "properties": {
                "username": {"title": "Usernames", "type": "array", "editor": "stringList", "prefill": ["apify"], "description": "u" * 400, "sectionCaption": "Basics"},
                "resultsLimit": {"type": "integer", "default": 10, "minimum": 1},
            },
        }
        apify.on("GET", "/v2/acts/apify~instagram-profile-scraper", _data({"username": "apify", "name": "instagram-profile-scraper", "title": "Instagram Profile Scraper", "description": "Profiles"}))
        apify.on("GET", "/v2/acts/apify~instagram-profile-scraper/builds/default", _data({"actorDefinition": {"input": schema}}))

        payload = json.loads(await apify_tools.apify_actor_discover_tool.ainvoke({"actor_id": "apify/instagram-profile-scraper"}))

        assert payload["actorId"] == "apify/instagram-profile-scraper"
        assert payload["url"] == "https://apify.com/apify/instagram-profile-scraper"
        assert payload["inputSchema"] == {
            "required": ["username"],
            "properties": {
                "username": {"title": "Usernames", "type": "array", "editor": "stringList", "prefill": ["apify"], "description": f"{'u' * 300}..."},
                "resultsLimit": {"type": "integer", "default": 10, "minimum": 1},
            },
        }
        assert "note" not in payload

    async def test_actor_id_falls_back_to_the_build_input_schema_string(self, config, apify):
        apify.on("GET", "/v2/acts/h7sDV53CddomktSi5", _data({"username": "o", "name": "a"}))
        apify.on("GET", "/v2/acts/h7sDV53CddomktSi5/builds/default", _data({"inputSchema": json.dumps({"properties": {"q": {"type": "string"}}})}))
        payload = json.loads(await apify_tools.apify_actor_discover_tool.ainvoke({"actor_id": "h7sDV53CddomktSi5"}))
        assert payload["inputSchema"] == {"properties": {"q": {"type": "string"}}}

    async def test_missing_schema_says_so(self, config, apify):
        apify.on("GET", "/v2/acts/o~a", _data({"username": "o", "name": "a"}))
        apify.on("GET", "/v2/acts/o~a/builds/default", _error(404, "Build not found", "record-not-found"))
        payload = json.loads(await apify_tools.apify_actor_discover_tool.ainvoke({"actor_id": "o/a"}))
        assert payload["inputSchema"] is None and "README" in payload["note"]

    async def test_unknown_actor_is_not_found(self, config, apify):
        apify.on("GET", "/v2/acts/o~missing", _error(404, "Actor was not found", "record-not-found"))
        result = await apify_tools.apify_actor_discover_tool.ainvoke({"actor_id": "o/missing"})
        assert result.startswith("Error: Actor 'o/missing' not found")

    @pytest.mark.parametrize("args", [{}, {"query": " ", "actor_id": ""}, {"query": "q", "actor_id": "o/a"}])
    async def test_exactly_one_of_query_and_actor_id(self, config, apify, args):
        assert (await apify_tools.apify_actor_discover_tool.ainvoke(args)).startswith("Error: provide either query or actor_id")
        assert apify.requests == []


class TestStart:
    async def test_starts_the_run_with_the_input_and_configured_limits(self, config, apify):
        config(timeout_secs="120", memory_mbytes=1024, max_total_charge_usd="0.5")
        apify.on("POST", "/v2/acts/apify~instagram-scraper/runs", _data({"id": "run-1", "defaultDatasetId": "ds-1", "status": "READY"}, 201))

        payload = json.loads(await apify_tools.apify_actor_start_tool.ainvoke({"actor_id": "apify/instagram-scraper", "run_input": '{"username": ["nasa"]}', "description": "NASA"}))

        (request,) = apify.requests
        assert json.loads(request.content) == {"username": ["nasa"]}
        assert dict(request.url.params) == {"timeout": "120", "memory": "1024", "maxTotalChargeUsd": "0.5"}
        assert payload == {"action": "start", "runs": [{"runId": "run-1", "actorId": "apify/instagram-scraper", "datasetId": "ds-1", "status": "READY", "description": "NASA"}]}

    async def test_invalid_run_limits_are_dropped_with_a_warning(self, config, apify, caplog):
        config(timeout_secs=True, memory_mbytes="lots")
        apify.on("POST", "/v2/acts/o~a/runs", _data({"id": "r", "defaultDatasetId": "d", "status": "READY"}))
        with caplog.at_level(logging.WARNING, logger=apify_tools.__name__):
            await apify_tools.apify_actor_start_tool.ainvoke({"actor_id": "o/a", "run_input": "{}"})
        assert dict(apify.requests[0].url.params) == {}
        assert caplog.text.count("Invalid Apify") == 2

    # Apify reads a cap of 0 as no cap, so 0 must not reach it either.
    @pytest.mark.parametrize("cap", [0, "0", -1, "lots", "", True, "inf", "nan"])
    async def test_an_invalid_cost_cap_refuses_to_start_the_run(self, config, apify, cap):
        config(max_total_charge_usd=cap)
        apify.on("POST", "/v2/acts/o~a/runs", _data({"id": "r", "defaultDatasetId": "d", "status": "READY"}))
        result = await apify_tools.apify_actor_start_tool.ainvoke({"actor_id": "o/a", "run_input": "{}"})
        assert result.startswith("Error: tools[apify_actor_start].max_total_charge_usd")
        assert "The run was not started" in result
        assert apify.requests == []

    @pytest.mark.parametrize(("run_input", "error"), [("not json", "not valid JSON"), ('["a"]', "must be a JSON object"), ('"text"', "must be a JSON object")])
    async def test_run_input_must_be_a_json_object(self, config, apify, run_input, error):
        assert error in await apify_tools.apify_actor_start_tool.ainvoke({"actor_id": "o/a", "run_input": run_input})
        assert apify.requests == []

    async def test_input_validation_errors_reach_the_model(self, config, apify):
        apify.on("POST", "/v2/acts/o~a/runs", _error(400, "Input is not valid: Field input.queries must be string"))
        result = await apify_tools.apify_actor_start_tool.ainvoke({"actor_id": "o/a", "run_input": '{"queries": ["x"]}'})
        assert result == "Error: Starting the Actor failed with HTTP 400: Input is not valid: Field input.queries must be string"

    async def test_a_run_without_ids_is_a_format_error(self, config, apify):
        apify.on("POST", "/v2/acts/o~a/runs", _data({"status": "READY"}))
        assert await apify_tools.apify_actor_start_tool.ainvoke({"actor_id": "o/a", "run_input": "{}"}) == "Error: Starting the Actor returned an unexpected response format"


class TestAwait:
    async def test_polls_until_succeeded_and_returns_the_items(self, config, apify, events):
        config(poll_interval_secs="0.01", max_items="2")
        apify.on("GET", "/v2/actor-runs/run-1", _data({"status": "RUNNING"}), _data({"status": "SUCCEEDED", "defaultDatasetId": "ds-run"}))
        apify.on("GET", "/v2/datasets/ds-run/items", httpx.Response(200, json=[{"username": "nasa"}, {"username": "apify"}]))

        payload = json.loads(await apify_tools.apify_actor_await_tool.ainvoke({"run_id": "run-1", "dataset_id": "ds-passed", "description": "Profiles"}))

        assert payload == {"runId": "run-1", "status": "SUCCEEDED", "resultCount": 2, "results": [{"username": "nasa"}, {"username": "apify"}], "description": "Profiles"}
        (items_request,) = apify.only("GET", "/v2/datasets/ds-run/items")
        assert (items_request.url.params["limit"], items_request.url.params["clean"]) == ("2", "true")
        assert [(e["type"], e["status"]) for e in events] == [("apify_run_polling", "WAITING"), ("apify_run_polling", "RUNNING"), ("apify_run_completed", "SUCCEEDED")]
        assert events[-1]["resultCount"] == 2

    async def test_a_failed_run_reports_its_status_message(self, config, apify, events):
        apify.on("GET", "/v2/actor-runs/run-1", _data({"status": "FAILED", "statusMessage": "Input is not valid"}))
        payload = json.loads(await apify_tools.apify_actor_await_tool.ainvoke({"run_id": "run-1", "dataset_id": "d"}))
        assert payload == {"runId": "run-1", "status": "FAILED", "error": "Run failed", "statusMessage": "Input is not valid"}
        assert events[-1]["type"] == "apify_run_failed"
        assert apify.only("GET", "/v2/datasets/d/items") == []

    async def test_an_unknown_run_is_not_found(self, config, apify, events):
        apify.on("GET", "/v2/actor-runs/nope", _error(404, "Actor run was not found", "record-not-found"))
        payload = json.loads(await apify_tools.apify_actor_await_tool.ainvoke({"run_id": "nope", "dataset_id": "d"}))
        assert payload["status"] == "NOT_FOUND"

    async def test_the_local_timeout_tells_the_agent_to_wait_again(self, config, apify, events):
        config(poll_interval_secs=0.01, timeout_secs="0.05")
        apify.on("GET", "/v2/actor-runs/run-1", _data({"status": "RUNNING"}))
        payload = json.loads(await apify_tools.apify_actor_await_tool.ainvoke({"run_id": "run-1", "dataset_id": "d"}))
        assert payload["status"] == "TIMED_OUT"
        assert "call apify_actor_await again" in payload["error"]

    async def test_invalid_config_numbers_fall_back_to_defaults(self, config, apify, events):
        # `$VAR` references resolve to strings; a bad one must not raise outside the error boundary.
        config(poll_interval_secs="soon", timeout_secs=False, max_items=2.5)
        apify.on("GET", "/v2/actor-runs/run-1", _data({"status": "SUCCEEDED", "defaultDatasetId": "d"}))
        apify.on("GET", "/v2/datasets/d/items", httpx.Response(200, json=[]))
        payload = json.loads(await apify_tools.apify_actor_await_tool.ainvoke({"run_id": "run-1", "dataset_id": "d"}))
        assert payload["status"] == "SUCCEEDED"
        assert apify.only("GET", "/v2/datasets/d/items")[0].url.params["limit"] == "50"

    async def test_malformed_dataset_items_are_an_error_result(self, config, apify, events):
        apify.on("GET", "/v2/actor-runs/run-1", _data({"status": "SUCCEEDED", "defaultDatasetId": "d"}))
        apify.on("GET", "/v2/datasets/d/items", httpx.Response(200, json={"items": []}))
        payload = json.loads(await apify_tools.apify_actor_await_tool.ainvoke({"run_id": "run-1", "dataset_id": "d"}))
        assert payload["status"] == "ERROR" and "unexpected response format" in payload["error"]
        assert events[-1]["type"] == "apify_run_failed"

    async def test_works_outside_a_graph_run_without_a_stream_writer(self, config, apify):
        apify.on("GET", "/v2/actor-runs/run-1", _data({"status": "ABORTED"}))
        payload = json.loads(await apify_tools.apify_actor_await_tool.coroutine(run_id="run-1", dataset_id="d"))
        assert payload["status"] == "ABORTED"

    async def test_empty_run_id_is_rejected(self, config, apify):
        assert await apify_tools.apify_actor_await_tool.ainvoke({"run_id": " ", "dataset_id": "d"}) == "Error: run_id must not be empty"
