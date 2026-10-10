"""Brave web search must contain malformed HTTP-success payloads at the tool boundary."""

import json
import logging
from types import SimpleNamespace

import httpx
import pytest


@pytest.fixture
def invoke_search(monkeypatch):
    from deerflow.community.brave import tools

    config = SimpleNamespace(get_tool_config=lambda _: SimpleNamespace(model_extra={"api_key": "synthetic-test-key"}))
    monkeypatch.setattr(tools, "get_app_config", lambda: config)
    real_client = httpx.Client

    def invoke(payload, *, status_code=200):
        requests = []

        def respond(request):
            requests.append(request)
            return httpx.Response(status_code, content=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})

        transport = httpx.MockTransport(respond)
        monkeypatch.setattr(
            tools,
            "httpx",
            SimpleNamespace(Client=lambda **kwargs: real_client(transport=transport, **kwargs), HTTPStatusError=httpx.HTTPStatusError),
        )
        result = json.loads(tools.web_search_tool.invoke({"query": "  文档 search  "}))
        assert len(requests) == 1
        assert requests[0].url.path == "/res/v1/web/search"
        assert requests[0].url.params["q"] == "文档 search"
        assert requests[0].url.params["count"] == "5"
        assert result["query"] == "文档 search"
        return result

    return invoke


def _assert_format_error_log(caplog, expected):
    records = [record for record in caplog.records if record.name == "deerflow.community.brave.tools" and record.levelno == logging.ERROR]
    assert [record.getMessage() for record in records] == [expected]
    assert "文档 search" not in caplog.text
    assert "synthetic-test-key" not in caplog.text
    assert "provider-private-payload" not in caplog.text


@pytest.mark.parametrize("web", [False, 0, "", "provider-private-payload", [], ["provider-private-payload"]])
def test_malformed_web_container_returns_format_error(invoke_search, web, caplog):
    assert invoke_search({"web": web}) == {"error": "Brave Search returned an unexpected response format", "query": "文档 search"}
    _assert_format_error_log(caplog, f"Brave Search returned unexpected 'web' payload type: {type(web).__name__}")


@pytest.mark.parametrize("payload", [None, False, 0, "invalid", []])
def test_malformed_top_level_keeps_existing_format_error(invoke_search, payload):
    assert invoke_search(payload) == {"error": "Brave Search returned an unexpected response format", "query": "文档 search"}


@pytest.mark.parametrize("results", [False, 0, "", "provider-private-payload", {}, {"title": "provider-private-payload"}])
def test_malformed_results_container_returns_format_error(invoke_search, results, caplog):
    assert invoke_search({"web": {"results": results}}) == {"error": "Brave Search returned an unexpected response format", "query": "文档 search"}
    _assert_format_error_log(caplog, f"Brave Search returned unexpected 'web.results' payload type: {type(results).__name__}")


@pytest.mark.parametrize("results", [[None], [False, 0, "provider-private-payload", []]])
def test_all_malformed_entries_return_format_error(invoke_search, results, caplog):
    assert invoke_search({"web": {"results": results}}) == {"error": "Brave Search returned an unexpected response format", "query": "文档 search"}
    _assert_format_error_log(caplog, "Brave Search returned 'web.results' with no usable result objects")


def test_mixed_entries_preserve_valid_results_in_order(invoke_search):
    result = invoke_search({"web": {"results": [None, {"title": "文档", "url": "https://example.com/one", "description": "概述"}, "invalid", {}, [], {"title": "Second"}]}})
    assert result == {
        "query": "文档 search",
        "total_results": 3,
        "results": [
            {"title": "文档", "url": "https://example.com/one", "content": "概述"},
            {"title": "", "url": "", "content": ""},
            {"title": "Second", "url": "", "content": ""},
        ],
    }


@pytest.mark.parametrize("payload", [{}, {"web": None}, {"web": {}}, {"web": {"results": None}}, {"web": {"results": []}}])
def test_missing_or_empty_results_keep_no_results_response(invoke_search, payload, caplog):
    assert invoke_search(payload) == {"error": "No results found", "query": "文档 search"}
    assert not [record for record in caplog.records if record.name == "deerflow.community.brave.tools" and record.levelno == logging.ERROR]


def test_valid_results_keep_existing_normalization(invoke_search):
    assert invoke_search({"web": {"results": [{"title": "Title", "url": "https://example.com", "description": "Snippet"}, {}]}}) == {
        "query": "文档 search",
        "total_results": 2,
        "results": [{"title": "Title", "url": "https://example.com", "content": "Snippet"}, {"title": "", "url": "", "content": ""}],
    }


def test_http_transport_patch_does_not_replace_global_client(invoke_search):
    real_client = httpx.Client
    invoke_search({"web": {"results": []}})
    assert httpx.Client is real_client
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(204))) as client:
        assert client.get("https://unrelated.invalid/probe").status_code == 204


@pytest.mark.parametrize("status_code", [403, 503])
def test_http_error_keeps_existing_structured_response(invoke_search, status_code):
    assert invoke_search({"error": "synthetic-denial"}, status_code=status_code) == {
        "error": f"Brave Search API error: HTTP {status_code}",
        "query": "文档 search",
    }
