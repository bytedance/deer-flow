"""Offline HTTP boundary tests for the DeepSeek community search provider."""

import asyncio
import importlib
import json
import threading
from types import SimpleNamespace

import httpx
import pytest
from langchain_core.tools import BaseTool
from pydantic import SecretStr

from deerflow.config.app_config import AppConfig
from deerflow.extensions.registry import ExtensionRegistry
from deerflow.reflection import resolve_variable
from deerflow.tools import get_available_tools


def _completion(*, sources=None, **message):
    return {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "content": "带来源的回答",
                    "server_tool_calls": [
                        {
                            "calls": [
                                {
                                    "status": "completed",
                                    "sources": sources
                                    if sources is not None
                                    else [
                                        {"url": "https://example.com/article", "title": "标题", "snippet": "摘要"},
                                    ],
                                }
                            ]
                        }
                    ],
                    **message,
                },
            }
        ],
    }


@pytest.fixture
def provider(monkeypatch):
    module = importlib.import_module("deerflow.community.deepseek.tools")
    state = SimpleNamespace(extras={"api_key": SecretStr(" test-key\n")}, requests=[], clients=[], threads=[], response=_completion())
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    def config():
        state.threads.append(threading.get_ident())
        return SimpleNamespace(get_tool_config=lambda _name: SimpleNamespace(model_extra=state.extras))

    async def respond(request):
        state.requests.append(request)
        if isinstance(state.response, Exception):
            raise state.response
        if callable(state.response):
            return await state.response(request)
        return httpx.Response(200, json=state.response)

    def client(**kwargs):
        state.threads.append(threading.get_ident())
        result = httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
        state.clients.append(result)
        return result

    private_httpx = SimpleNamespace(**vars(httpx))
    private_httpx.AsyncClient = client
    monkeypatch.setattr(module, "httpx", private_httpx)
    monkeypatch.setattr(module, "get_app_config", config)
    state.tool = resolve_variable("deerflow.community.deepseek.tools:web_search_tool", BaseTool)
    return state


def test_provider_entry_preserves_the_web_search_interface(provider):
    assert provider.tool.name == "web_search"
    assert set(provider.tool.args) == {"query", "max_results"}


def test_configured_provider_is_assembled_and_invoked_by_the_host(provider):
    config = AppConfig.model_validate(
        {
            "tools": [{"name": "web_search", "group": "web", "use": "deerflow.community.deepseek.tools:web_search_tool"}],
            "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
        }
    )
    tools = get_available_tools(
        app_config=config,
        groups=["web"],
        include_mcp=False,
        subagent_enabled=False,
        include_upload_tool=False,
        extensions=ExtensionRegistry().build(),
    )
    (search,) = [tool for tool in tools if tool.name == "web_search"]
    result = json.loads(search.invoke({"query": "test"}))
    assert result["total_results"] == 1
    assert len(provider.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(("thinking", "wire_value"), [(None, "disabled"), (False, "disabled"), (True, "enabled"), ("false", "disabled"), ("true", "enabled")])
async def test_thinking_payload_and_normalized_results(provider, thinking, wire_value):
    if thinking is not None:
        provider.extras["thinking"] = thinking
    result = json.loads(await provider.tool.ainvoke({"query": "  最新研究  "}))
    (request,) = provider.requests
    assert str(request.url) == "https://api.deepseek.com/chat/completions"
    assert request.headers["Authorization"] == "Bearer test-key"
    assert json.loads(request.content) == {
        "model": "deepseek-flash",
        "thinking": {"type": wire_value},
        "tools": [{"type": "deepseek_web_search"}],
        "messages": [
            {"role": "system", "content": "Search the web for the user's query and answer using retrieved sources. Cite your sources."},
            {"role": "user", "content": "最新研究"},
        ],
        "max_tokens": 8192,
        "stream": False,
    }
    assert result == {
        "query": "最新研究",
        "total_results": 1,
        "results": [{"title": "标题", "url": "https://example.com/article", "snippet": "摘要"}],
        "answer": "带来源的回答",
        "truncated": False,
    }
    assert provider.clients[0].is_closed
    assert all(thread != threading.get_ident() for thread in provider.threads)


@pytest.mark.asyncio
async def test_sources_and_citations_are_screened_deduplicated_and_limited(provider):
    provider.extras.update(max_results=2, model="deployment-model", max_tokens=4096)
    provider.response = _completion(
        sources=[
            "bad-entry",
            {"url": "http://127。0。0。1/private"},
            {"url": "javascript:alert(1)"},
            {"url": "https://example.com/one", "title": None, "snippet": 123},
            {"url": "https://example.com/one", "title": "duplicate"},
        ],
        annotations=[{"type": "url_citation", "url_citation": {"url": "https://example.com/two", "title": "打开的网页"}}],
    )
    provider.response["choices"][0]["finish_reason"] = "length"
    result = json.loads(await provider.tool.ainvoke({"query": "test", "max_results": 1}))
    assert result["results"] == [
        {"url": "https://example.com/two", "title": "打开的网页", "snippet": ""},
        {"url": "https://example.com/one", "title": "duplicate", "snippet": ""},
    ]
    assert result["total_results"] == 2
    assert result["truncated"] is True
    payload = json.loads(provider.requests[0].content)
    assert payload["model"] == "deployment-model"
    assert payload["max_tokens"] == 4096


@pytest.mark.asyncio
async def test_cited_source_beyond_result_limit_keeps_its_search_snippet(provider):
    provider.response = _completion(
        sources=[{"url": f"https://example.com/{index}", "snippet": f"summary-{index}"} for index in range(6)],
        annotations=[{"type": "url_citation", "url_citation": {"url": "https://example.com/5", "title": "引用"}}],
    )
    result = json.loads(await provider.tool.ainvoke({"query": "test", "max_results": 1}))
    assert result["results"] == [{"url": "https://example.com/5", "title": "引用", "snippet": "summary-5"}]


@pytest.mark.asyncio
async def test_multistep_search_preserves_sources_and_citations_from_all_steps(provider):
    provider.response = _completion(
        server_tool_calls=[
            {"reasoning_content": "first step", "calls": [{"status": "completed", "kind": "deep_search", "sources": [{"url": "https://example.com/one", "snippet": "first"}]}]},
            {
                "reasoning_content": "second step",
                "calls": [
                    {"status": "completed", "action": {"type": "open_page"}, "page": {"url": "https://example.com/page", "title": "opened"}},
                    {"status": "completed", "sources": [None, {"url": "https://example.com/two", "title": "second"}]},
                    {"status": "failed", "error": {"code": "unavailable"}},
                ],
            },
        ],
        annotations=[{"type": "url_citation", "url_citation": {"url": "https://example.com/page", "title": "cited page"}}],
    )
    result = json.loads(await provider.tool.ainvoke({"query": "test"}))
    assert result["results"] == [
        {"url": "https://example.com/page", "title": "opened", "snippet": ""},
        {"url": "https://example.com/one", "title": "", "snippet": "first"},
        {"url": "https://example.com/two", "title": "second", "snippet": ""},
    ]
    assert "reasoning_content" not in result
    assert "first step" not in json.dumps(result)


@pytest.mark.asyncio
async def test_opened_page_is_a_source_without_annotations(provider):
    provider.response = _completion(
        server_tool_calls=[
            {
                "calls": [
                    {"status": "completed", "page": {"url": "https://example.com/page", "title": "opened"}},
                    {"status": "completed", "page": {"url": "http://127.0.0.1/private", "title": "private"}},
                ]
            }
        ]
    )
    result = json.loads(await provider.tool.ainvoke({"query": "test"}))
    assert result["results"] == [{"url": "https://example.com/page", "title": "opened", "snippet": ""}]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"choices": "bad"},
        {"choices": ["bad"]},
        {"choices": [{"message": []}]},
        _completion(server_tool_calls="bad"),
        _completion(server_tool_calls=[{"calls": 12}]),
        _completion(server_tool_calls=[{"calls": [{"status": "completed", "page": "bad"}]}]),
        _completion(sources="bad"),
        _completion(sources=["bad"]),
        _completion(annotations=[{"type": "url_citation", "url_citation": []}]),
    ],
)
async def test_malformed_containers_are_errors(provider, payload, caplog):
    provider.response = payload
    result = json.loads(await provider.tool.ainvoke({"query": "private-query"}))
    assert "unexpected response format" in result["error"]
    assert "private-query" not in caplog.text
    assert "test-key" not in caplog.text
    assert provider.clients[0].is_closed


@pytest.mark.asyncio
@pytest.mark.parametrize("rows", [[], None])
async def test_empty_search_is_reported(provider, rows):
    provider.response = _completion(server_tool_calls=[{"calls": [{"status": "completed", "sources": rows}]}])
    assert json.loads(await provider.tool.ainvoke({"query": "test"}))["error"] == "No results found"


@pytest.mark.asyncio
async def test_missing_key_and_empty_query_do_not_create_clients(provider):
    provider.extras.clear()
    assert "not configured" in json.loads(await provider.tool.ainvoke({"query": "test"}))["error"]
    assert "empty" in json.loads(await provider.tool.ainvoke({"query": " "}))["error"]
    assert provider.clients == []


@pytest.mark.asyncio
async def test_environment_key_fallback(provider, monkeypatch):
    provider.extras["api_key"] = "your-deepseek-api-key"
    monkeypatch.setenv("DEEPSEEK_API_KEY", " env-key\n")
    await provider.tool.ainvoke({"query": "test"})
    assert provider.requests[0].headers["Authorization"] == "Bearer env-key"


@pytest.mark.asyncio
async def test_configured_key_precedes_environment(provider, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "environment-key")
    await provider.tool.ainvoke({"query": "test"})
    assert provider.requests[0].headers["Authorization"] == "Bearer test-key"


@pytest.mark.asyncio
async def test_environment_key_works_without_tool_extras(provider, monkeypatch):
    module = importlib.import_module("deerflow.community.deepseek.tools")
    monkeypatch.setattr(module, "get_app_config", lambda: SimpleNamespace(get_tool_config=lambda name: None))
    monkeypatch.setenv("DEEPSEEK_API_KEY", "environment-key")
    result = json.loads(await provider.tool.ainvoke({"query": "test"}))
    assert result["total_results"] == 1
    assert provider.requests[0].headers["Authorization"] == "Bearer environment-key"


@pytest.mark.asyncio
@pytest.mark.parametrize("options", [{"thinking": "invalid"}, {"timeout_seconds": 0}, {"timeout_seconds": True}, {"timeout_seconds": float("inf")}, {"max_tokens": True}, {"max_tokens": 1.5}, {"max_tokens": 0}, {"model": " "}])
async def test_invalid_options_return_configuration_error_and_close_client(provider, options):
    provider.extras.update(options)
    assert "configuration" in json.loads(await provider.tool.ainvoke({"query": "test"}))["error"]
    assert provider.requests == []
    assert provider.clients[0].is_closed


@pytest.mark.asyncio
async def test_numeric_settings_accept_environment_strings(provider):
    provider.extras.update(max_tokens="4096", timeout_seconds="120")
    result = json.loads(await provider.tool.ainvoke({"query": "test"}))
    assert result["total_results"] == 1
    assert json.loads(provider.requests[0].content)["max_tokens"] == 4096
    assert provider.requests[0].extensions["timeout"]["read"] == 120.0


@pytest.mark.asyncio
async def test_http_and_embedded_errors_do_not_leak_provider_details(provider, caplog):
    async def unauthorized(request):
        return httpx.Response(401, text="secret test-key private-query", request=request)

    provider.response = unauthorized
    result = json.loads(await provider.tool.ainvoke({"query": "private-query"}))
    assert result["error"] == "DeepSeek search API error: HTTP 401"
    provider.response = {"error": {"message": "secret test-key"}, "usage": {}}
    assert "generation failed" in json.loads(await provider.tool.ainvoke({"query": "test"}))["error"]
    assert "secret" not in caplog.text
    assert "test-key" not in caplog.text
    assert "private-query" not in caplog.text


@pytest.mark.asyncio
async def test_transport_timeout_and_invalid_json(provider):
    provider.response = httpx.ReadTimeout("secret test-key")
    assert "timed out" in json.loads(await provider.tool.ainvoke({"query": "test"}))["error"]
    provider.response = httpx.ConnectError("secret test-key")
    assert json.loads(await provider.tool.ainvoke({"query": "test"}))["error"] == "DeepSeek search request failed"

    async def html(request):
        return httpx.Response(200, text="<html>Error</html>")

    provider.response = html
    assert "unexpected response format" in json.loads(await provider.tool.ainvoke({"query": "test"}))["error"]
    assert all(client.is_closed for client in provider.clients)


@pytest.mark.asyncio
async def test_request_deadline_cancels_slow_transport(provider):
    provider.extras["timeout_seconds"] = 0.01

    async def wait(request):
        await asyncio.Event().wait()

    provider.response = wait
    result = json.loads(await provider.tool.ainvoke({"query": "test"}))
    assert result["error"] == "DeepSeek search timed out"
    assert provider.clients[0].is_closed


@pytest.mark.asyncio
async def test_failed_search_is_distinct_from_empty_results(provider):
    provider.response = _completion(server_tool_calls=[{"calls": [{"status": "failed", "error": {"code": "timeout"}}]}])
    assert json.loads(await provider.tool.ainvoke({"query": "test"}))["error"] == "DeepSeek web search failed"


@pytest.mark.asyncio
async def test_exhausted_generation_budget_is_distinct_from_empty_results(provider):
    provider.response = _completion(server_tool_calls=[])
    provider.response["choices"][0]["finish_reason"] = "length"
    assert "max_tokens" in json.loads(await provider.tool.ainvoke({"query": "test"}))["error"]


@pytest.mark.asyncio
async def test_content_filter_does_not_return_a_fabricated_answer(provider):
    provider.response = _completion()
    provider.response["choices"][0]["finish_reason"] = "content_filter"
    result = json.loads(await provider.tool.ainvoke({"query": "test"}))
    assert result["error"] == "DeepSeek search did not complete"
    assert "answer" not in result


@pytest.mark.asyncio
async def test_client_initialization_failure_contains_sensitive_exception(provider, monkeypatch, caplog):
    module = importlib.import_module("deerflow.community.deepseek.tools")

    def fail(**kwargs):
        raise OSError("test-key private-query")

    monkeypatch.setattr(module.httpx, "AsyncClient", fail)
    result = json.loads(await provider.tool.ainvoke({"query": "private-query"}))
    assert result["error"] == "DeepSeek search initialization failed"
    assert "test-key" not in caplog.text
    assert "private-query" not in caplog.text
    assert provider.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("value, count", [(1000, 50), ("3", 3), (False, 5), (0, 5)])
async def test_configured_result_count_is_bounded(provider, value, count):
    provider.extras["max_results"] = value
    provider.response = _completion(sources=[{"url": f"https://example.com/{index}"} for index in range(60)])
    result = json.loads(await provider.tool.ainvoke({"query": "test"}))
    assert result["total_results"] == count


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_count", [1, 2])
async def test_cancellation_during_client_creation_closes_late_client(provider, monkeypatch, cancel_count):
    module = importlib.import_module("deerflow.community.deepseek.tools")
    original = module.httpx.AsyncClient
    started = asyncio.Event()
    created = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()

    def delayed_client(**kwargs):
        loop.call_soon_threadsafe(started.set)
        release.wait()
        client = original(**kwargs)
        loop.call_soon_threadsafe(created.set)
        return client

    monkeypatch.setattr(module.httpx, "AsyncClient", delayed_client)
    task = asyncio.create_task(provider.tool.ainvoke({"query": "test"}))
    try:
        await asyncio.wait_for(started.wait(), 5)
        task.cancel()
        if cancel_count == 2:
            checkpoint = asyncio.Event()
            loop.call_soon(checkpoint.set)
            await checkpoint.wait()
            task.cancel()
    finally:
        release.set()
        if not task.cancelling():
            task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.wait_for(created.wait(), 5)
    assert provider.clients[0].is_closed
    assert provider.requests == []


@pytest.mark.asyncio
async def test_cancellation_propagates_and_closes_client(provider):
    started = asyncio.Event()

    async def wait(request):
        started.set()
        await asyncio.Event().wait()

    provider.response = wait
    task = asyncio.create_task(provider.tool.ainvoke({"query": "test"}))
    try:
        await asyncio.wait_for(started.wait(), 5)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert provider.clients[0].is_closed


@pytest.mark.asyncio
@pytest.mark.parametrize("trigger", ["request_cancel", "request_timeout", "response_complete"])
async def test_repeated_cancellation_drains_transport_teardown(provider, monkeypatch, trigger):
    request_started = asyncio.Event()
    close_started = asyncio.Event()
    release_close = asyncio.Event()
    close_completed = asyncio.Event()

    async def respond(request):
        request_started.set()
        if trigger != "response_complete":
            await asyncio.Event().wait()
        return httpx.Response(200, json=_completion())

    class GatedTransport(httpx.MockTransport):
        async def aclose(self):
            close_started.set()
            await release_close.wait()
            await super().aclose()
            close_completed.set()

    transport = GatedTransport(respond)
    module = importlib.import_module("deerflow.community.deepseek.tools")

    def client(**kwargs):
        result = httpx.AsyncClient(transport=transport, **kwargs)
        provider.clients.append(result)
        return result

    monkeypatch.setattr(module.httpx, "AsyncClient", client)
    if trigger == "request_timeout":
        provider.extras["timeout_seconds"] = 0.01
    task = asyncio.create_task(provider.tool.ainvoke({"query": "test"}))
    finished_before_release = False
    try:
        await asyncio.wait_for(request_started.wait(), 5)
        if trigger == "request_cancel":
            task.cancel()
        await asyncio.wait_for(close_started.wait(), 5)
        for _ in range(2):
            task.cancel()
            checkpoint = asyncio.Event()
            asyncio.get_running_loop().call_soon(checkpoint.set)
            await checkpoint.wait()
        finished_before_release = task.done()
    finally:
        release_close.set()
        if not task.done():
            task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        completed_by_tool = close_completed.is_set()
        if not completed_by_tool:
            await transport.aclose()
    assert not finished_before_release
    assert completed_by_tool
    assert provider.clients[0].is_closed


@pytest.mark.asyncio
async def test_citation_spans_preserve_claim_associations_and_unicode_offsets(provider):
    answer = "😀甲。乙。"
    first = {"url": "https://example.com/one", "title": "first", "start_index": 1, "end_index": 2}
    second = {"url": "https://example.com/two", "title": "second", "start_index": 3, "end_index": len(answer)}
    provider.response = _completion(
        content=answer,
        sources=[first, second],
        annotations=[{"type": "url_citation", "url_citation": first}, {"type": "url_citation", "url_citation": second}],
    )
    result = json.loads(await provider.tool.ainvoke({"query": "test"}))
    first["start_index"], second["start_index"] = second["start_index"], first["start_index"]
    first["end_index"], second["end_index"] = second["end_index"], first["end_index"]
    swapped = json.loads(await provider.tool.ainvoke({"query": "test"}))
    assert result != swapped
    assert result["answer"] == swapped["answer"] == answer
    assert result["results"][0]["citation_spans"] == [{"start_index": 1, "end_index": 2}]
    assert result["results"][1]["citation_spans"] == [{"start_index": 3, "end_index": len(answer)}]
    assert answer[1:2] == "甲"
    assert swapped["results"][0]["citation_spans"] == [{"start_index": 3, "end_index": len(answer)}]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("start", "end"),
    [(None, None), (None, 1), (0, None), ("0", 1), (0, "1"), (False, 1), (0, True), (0.0, 1), (0, 1.0), (-1, 1), (0, 0), (2, 1), (0, 4)],
)
async def test_invalid_citation_spans_preserve_legacy_source_shape(provider, start, end):
    citation = {"url": "https://example.com/cited", "title": "source", "start_index": start, "end_index": end}
    provider.response = _completion(content="甲😀乙", server_tool_calls=[], annotations=[{"type": "url_citation", "url_citation": citation}])
    result = json.loads(await provider.tool.ainvoke({"query": "test"}))
    assert result == {
        "query": "test",
        "total_results": 1,
        "results": [{"title": "source", "url": citation["url"], "snippet": ""}],
        "answer": "甲😀乙",
        "truncated": False,
    }


@pytest.mark.asyncio
async def test_citation_spans_preserve_whitespace_multiple_sources_and_distinct_ranges(provider):
    answer = "  😀甲乙\n"
    annotations = [
        {"type": "url_citation", "url_citation": {"url": url, "start_index": start, "end_index": end}}
        for url, start, end in [
            ("https://example.com/one", 2, 4),
            ("https://example.com/one", 2, 4),
            ("https://example.com/one", 3, len(answer)),
            ("https://example.com/two", 2, 4),
        ]
    ]
    provider.response = _completion(content=answer, server_tool_calls=[], annotations=annotations)
    result = json.loads(await provider.tool.ainvoke({"query": "test"}))
    assert result["answer"] == answer
    assert result["results"][0]["citation_spans"] == [{"start_index": 2, "end_index": 4}, {"start_index": 3, "end_index": len(answer)}]
    assert result["results"][1]["citation_spans"] == [{"start_index": 2, "end_index": 4}]
    assert answer[2:4] == "😀甲"


@pytest.mark.asyncio
async def test_citation_spans_follow_url_screening_and_result_limit(provider):
    urls = ["https://example.com/kept", "https://example.com/limited", "http://127。0。0。1/private", "javascript:alert(1)"]
    provider.response = _completion(
        content="claim",
        sources=[{"url": url} for url in urls],
        annotations=[{"type": "url_citation", "url_citation": {"url": url, "start_index": 0, "end_index": 5}} for url in urls],
    )
    result = json.loads(await provider.tool.ainvoke({"query": "test", "max_results": 1}))
    assert result["total_results"] == 1
    assert result["results"] == [{"title": "", "url": urls[0], "snippet": "", "citation_spans": [{"start_index": 0, "end_index": 5}]}]
    assert all(url not in json.dumps(result, ensure_ascii=False) for url in urls[1:])
