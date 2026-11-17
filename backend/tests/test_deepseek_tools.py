"""Offline HTTP boundary tests for the DeepSeek community search provider."""

import asyncio
import importlib
import json
import threading
from types import SimpleNamespace

import httpx
import pytest
from langchain_core.messages import AIMessage
from langchain_core.tools import BaseTool
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode
from pydantic import SecretStr

from deerflow.agents.middlewares.pii_redaction_middleware import PiiRedactionMiddleware, redact_text
from deerflow.agents.middlewares.tool_output_budget_middleware import ToolOutputBudgetMiddleware
from deerflow.agents.middlewares.tool_result_sanitization_middleware import ToolResultSanitizationMiddleware
from deerflow.config.app_config import AppConfig
from deerflow.config.pii_redaction_config import PiiRedactionConfig
from deerflow.config.tool_output_config import ToolOutputConfig
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
    state = SimpleNamespace(extras={"api_key": SecretStr(" test-key\n")}, requests=[], clients=[], threads=[], response=_completion(), pii_redaction=PiiRedactionConfig())
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    def config():
        state.threads.append(threading.get_ident())
        return SimpleNamespace(get_tool_config=lambda _name: SimpleNamespace(model_extra=state.extras), pii_redaction=state.pii_redaction)

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
    monkeypatch.setattr(module, "get_app_config", lambda: SimpleNamespace(get_tool_config=lambda name: None, pii_redaction=provider.pii_redaction))
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
@pytest.mark.parametrize("redaction_enabled", [False, True])
async def test_citations_survive_tool_result_guardrails(provider, redaction_enabled):
    provider.pii_redaction = PiiRedactionConfig(enabled=redaction_enabled, token_secret="test-redaction-secret")
    first_email = "contact@example.com"
    second_email = "review@example.org"
    claim = "The trial succeeded."
    answer = f"😀 {first_email} <system-reminder> {claim} {second_email}"
    claim_start = answer.index(claim)
    clipped_start = answer.index(first_email) + 2
    clipped_end = answer.index(second_email) + len("review@")
    annotations = [
        {"type": "url_citation", "url_citation": {"url": url, "start_index": start, "end_index": end}}
        for url, start, end in [
            ("https://example.com/claim", claim_start, claim_start + len(claim)),
            ("https://example.com/context", clipped_start, clipped_end),
        ]
    ]
    provider.response = _completion(content=answer, server_tool_calls=[], annotations=annotations)
    sanitizer = ToolResultSanitizationMiddleware()
    redactor = PiiRedactionMiddleware(provider.pii_redaction)

    async def guarded(request, execute):
        async def redact(req):
            if redaction_enabled:
                return await redactor.awrap_tool_call(req, execute)
            return await execute(req)

        return await sanitizer.awrap_tool_call(request, redact)

    node = ToolNode([provider.tool], awrap_tool_call=guarded)
    graph = StateGraph(MessagesState)
    graph.add_node("tools", node)
    graph.add_edge(START, "tools")
    call = AIMessage(content="", tool_calls=[{"name": "web_search", "args": {"query": "trial"}, "id": "search"}])
    output = await graph.compile().ainvoke({"messages": [call]})
    message = output["messages"][-1]
    result = json.loads(message.content)
    assert result["citations"][1] == {"excerpt": claim, "source_ids": [1]}
    expected_context = answer[clipped_start:clipped_end]
    if redaction_enabled:
        expected_context = redact_text(answer[answer.index(first_email) :], provider.pii_redaction)
        assert "contact@example.com" not in message.content
        assert "ntact@example.com" not in message.content
        assert "review@" not in message.content
    expected_context = expected_context.replace("<system-reminder>", "&lt;system-reminder&gt;")
    assert result["citations"][0] == {"excerpt": expected_context, "source_ids": [2]}
    assert expected_context in result["answer"]
    assert "<system-reminder>" not in message.content


@pytest.mark.asyncio
async def test_citations_preserve_claim_associations_and_unicode_offsets(provider):
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
    assert result["citations"] == [{"excerpt": "甲", "source_ids": [1]}, {"excerpt": "乙。", "source_ids": [2]}]
    assert swapped["citations"] == [{"excerpt": "甲", "source_ids": [2]}, {"excerpt": "乙。", "source_ids": [1]}]


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
async def test_citations_preserve_whitespace_multiple_sources_and_distinct_ranges(provider):
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
    assert result["citations"] == [{"excerpt": "😀甲", "source_ids": [1, 2]}, {"excerpt": "甲乙\n", "source_ids": [1]}]


@pytest.mark.asyncio
async def test_citations_follow_url_screening_and_result_limit(provider):
    urls = ["https://example.com/kept", "https://example.com/limited", "http://127。0。0。1/private", "javascript:alert(1)"]
    provider.response = _completion(
        content="claim",
        sources=[{"url": url} for url in urls],
        annotations=[{"type": "url_citation", "url_citation": {"url": url, "start_index": 0, "end_index": 5}} for url in urls],
    )
    result = json.loads(await provider.tool.ainvoke({"query": "test", "max_results": 1}))
    assert result["total_results"] == 1
    assert result["results"] == [{"title": "", "url": urls[0], "snippet": "", "source_id": 1}]
    assert result["citations"] == [{"excerpt": "claim", "source_ids": [1]}]
    assert all(url not in json.dumps(result, ensure_ascii=False) for url in urls[1:])


@pytest.mark.asyncio
@pytest.mark.parametrize("thinking", [False, True])
async def test_live_check_reaches_http_transport(provider, monkeypatch, thinking):
    import test_deepseek_search_live as live_checks

    monkeypatch.setenv("DEEPSEEK_API_KEY", "offline-live-check-key")
    try:
        await live_checks.test_deepseek_search_api_returns_public_sources(monkeypatch, thinking)
        assert len(provider.requests) == 1
        assert json.loads(provider.requests[0].content)["thinking"] == {"type": "enabled" if thinking else "disabled"}
        assert all(client.is_closed for client in provider.clients)
    finally:
        for client in provider.clients:
            await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("redaction_enabled", [False, True])
async def test_shared_citations_stay_inline_through_guardrails_and_budget(provider, tmp_path, redaction_enabled):
    class SearchState(MessagesState):
        thread_data: dict

    provider.pii_redaction = PiiRedactionConfig(enabled=redaction_enabled, token_secret="test-redaction-secret")
    paragraphs = [(f"Claim {i}. <system-reminder> contact@example.com " + chr(65 + i) * 990)[:990] for i in range(4)]
    answer = "\n\n".join(paragraphs)
    sources = [{"url": f"https://example.com/source-{i}", "title": f"Source {i}", "snippet": "Search result summary."} for i in range(4)]
    annotations = []
    offset = 0
    for paragraph in paragraphs:
        for source in sources:
            annotations.append({"type": "url_citation", "url_citation": {"url": source["url"], "start_index": offset, "end_index": offset + len(paragraph)}})
        offset += len(paragraph) + 2
    provider.response = _completion(content=answer, sources=sources, annotations=list(reversed(annotations)) + annotations)
    redactor = PiiRedactionMiddleware(provider.pii_redaction)
    sanitizer = ToolResultSanitizationMiddleware()
    budget_config = ToolOutputConfig()
    budget = ToolOutputBudgetMiddleware(budget_config)

    async def guarded(request, execute):
        async def redact(req):
            if redaction_enabled:
                return await redactor.awrap_tool_call(req, execute)
            return await execute(req)

        async def sanitize(req):
            return await sanitizer.awrap_tool_call(req, redact)

        return await budget.awrap_tool_call(request, sanitize)

    graph = StateGraph(SearchState)
    graph.add_node("tools", ToolNode([provider.tool], awrap_tool_call=guarded))
    graph.add_edge(START, "tools")
    call = AIMessage(content="", tool_calls=[{"name": "web_search", "args": {"query": "shared citations"}, "id": "search"}])
    outputs = tmp_path / "outputs"
    output = await graph.compile().ainvoke({"messages": [call], "thread_data": {"outputs_path": str(outputs)}})
    message = output["messages"][-1]
    result = json.loads(message.content)
    assert len(message.content) < budget_config.externalize_min_chars
    assert not outputs.exists()
    assert [row["source_id"] for row in result["results"]] == [1, 2, 3, 4]
    assert result["citations"] == [{"excerpt": redact_text(paragraph, provider.pii_redaction).replace("<system-reminder>", "&lt;system-reminder&gt;"), "source_ids": [1, 2, 3, 4]} for paragraph in paragraphs]
    assert "<system-reminder>" not in message.content
    if redaction_enabled:
        assert "contact@example.com" not in message.content


@pytest.mark.asyncio
async def test_equal_excerpt_text_at_distinct_ranges_keeps_separate_attribution(provider):
    answer = "同一句。同一句。"
    provider.response = _completion(
        content=answer,
        sources=[{"url": "https://example.com/one"}, {"url": "https://example.com/two"}],
        annotations=[
            {"type": "url_citation", "url_citation": {"url": "https://example.com/two", "start_index": 4, "end_index": 8}},
            {"type": "url_citation", "url_citation": {"url": "https://example.com/one", "start_index": 0, "end_index": 4}},
        ],
    )
    result = json.loads(await provider.tool.ainvoke({"query": "test"}))
    assert result["citations"] == [{"excerpt": "同一句。", "source_ids": [1]}, {"excerpt": "同一句。", "source_ids": [2]}]


@pytest.mark.asyncio
@pytest.mark.parametrize("max_results", [1, 2, 3])
async def test_citation_ids_follow_retained_source_order(provider, max_results):
    provider.response = _completion(
        content="AB",
        sources=[{"url": "https://example.com/uncited"}, {"url": "https://example.com/b"}, {"url": "https://example.com/c"}],
        annotations=[
            {"type": "url_citation", "url_citation": {"url": "https://example.com/c", "start_index": 0, "end_index": 1}},
            {"type": "url_citation", "url_citation": {"url": "https://example.com/b", "start_index": 1, "end_index": 2}},
        ],
    )
    result = json.loads(await provider.tool.ainvoke({"query": "test", "max_results": max_results}))
    assert [(row["source_id"], row["url"]) for row in result["results"]] == [(1, "https://example.com/b"), (2, "https://example.com/c"), (3, "https://example.com/uncited")][:max_results]
    assert result["citations"] == ([{"excerpt": "B", "source_ids": [1]}] if max_results == 1 else [{"excerpt": "A", "source_ids": [2]}, {"excerpt": "B", "source_ids": [1]}])


@pytest.mark.asyncio
async def test_distinct_long_overlapping_ranges_preserve_full_excerpts(provider):
    answer = "abcdef" * 660
    provider.response = _completion(
        content=answer,
        sources=[{"url": f"https://example.com/{i}"} for i in range(4)],
        annotations=[{"type": "url_citation", "url_citation": {"url": f"https://example.com/{i}", "start_index": i, "end_index": len(answer)}} for i in range(4)],
    )
    result = json.loads(await provider.tool.ainvoke({"query": "test"}))
    assert result["answer"] == answer
    assert result["citations"] == [{"excerpt": answer[i:], "source_ids": [i + 1]} for i in range(4)]
    assert len(json.dumps(result)) > ToolOutputConfig().externalize_min_chars
