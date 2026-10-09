"""Brave web search must contain malformed HTTP-success payloads at the tool boundary."""

import json
from types import SimpleNamespace

import httpx
import pytest


@pytest.fixture
def invoke_search(monkeypatch):
    from deerflow.community.brave import tools

    config = SimpleNamespace(get_tool_config=lambda _: SimpleNamespace(model_extra={"api_key": "synthetic-test-key"}))
    monkeypatch.setattr(tools, "get_app_config", lambda: config)
    real_client = httpx.Client

    def invoke(payload):
        requests = []

        def respond(request):
            requests.append(request)
            return httpx.Response(200, content=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})

        transport = httpx.MockTransport(respond)
        monkeypatch.setattr(tools.httpx, "Client", lambda **kwargs: real_client(transport=transport, **kwargs))
        result = json.loads(tools.web_search_tool.invoke({"query": "  文档 search  "}))
        assert len(requests) == 1
        assert requests[0].url.path == "/res/v1/web/search"
        assert requests[0].url.params["q"] == "文档 search"
        assert requests[0].url.params["count"] == "5"
        assert result["query"] == "文档 search"
        return result

    return invoke


@pytest.mark.parametrize("web", [False, 0, "", "invalid", [], ["invalid"]])
def test_malformed_web_container_returns_format_error(invoke_search, web):
    assert invoke_search({"web": web}) == {"error": "Brave Search returned an unexpected response format", "query": "文档 search"}


@pytest.mark.parametrize("payload", [None, False, 0, "invalid", []])
def test_malformed_top_level_keeps_existing_format_error(invoke_search, payload):
    assert invoke_search(payload) == {"error": "Brave Search returned an unexpected response format", "query": "文档 search"}


@pytest.mark.parametrize("results", [False, 0, "", "invalid", {}, {"title": "not a list"}])
def test_malformed_results_container_returns_format_error(invoke_search, results):
    assert invoke_search({"web": {"results": results}}) == {"error": "Brave Search returned an unexpected response format", "query": "文档 search"}


@pytest.mark.parametrize("results", [[None], [False, 0, "invalid", []]])
def test_all_malformed_entries_return_format_error(invoke_search, results):
    assert invoke_search({"web": {"results": results}}) == {"error": "Brave Search returned an unexpected response format", "query": "文档 search"}


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
def test_missing_or_empty_results_keep_no_results_response(invoke_search, payload):
    assert invoke_search(payload) == {"error": "No results found", "query": "文档 search"}


def test_valid_results_keep_existing_normalization(invoke_search):
    assert invoke_search({"web": {"results": [{"title": "Title", "url": "https://example.com", "description": "Snippet"}, {}]}}) == {
        "query": "文档 search",
        "total_results": 2,
        "results": [{"title": "Title", "url": "https://example.com", "content": "Snippet"}, {"title": "", "url": "", "content": ""}],
    }
