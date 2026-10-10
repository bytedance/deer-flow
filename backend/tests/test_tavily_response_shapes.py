"""Tavily web_search/web_fetch must contain malformed HTTP-success payloads.

These cases drive the real tools and the real AsyncTavilyClient through an offline
HTTPX MockTransport, so each one exercises the response-decoding path rather than a
mocked normalizer.
"""

import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from tavily import AsyncTavilyClient

_LOGGER_NAME = "deerflow.community.tavily.tools"
_FORMAT_ERROR = "Tavily returned an unexpected response format"
_SEARCH_QUERY = "docs search"
_FETCH_URL = "https://example.com/docs"


@pytest.fixture(autouse=True)
def app_config(monkeypatch):
    from deerflow.community.tavily import tools

    config = SimpleNamespace(get_tool_config=lambda _: None)
    monkeypatch.setattr(tools, "get_app_config", lambda: config)


def _transport(payload, status_code=200):
    requests = []

    def respond(request):
        requests.append(request)
        content = payload if isinstance(payload, str) else json.dumps(payload)
        return httpx.Response(status_code, content=content.encode("utf-8"), headers={"Content-Type": "application/json"})

    return httpx.MockTransport(respond), requests


async def _invoke(monkeypatch, tool, arguments, payload, status_code=200):
    from deerflow.community.tavily import tools

    transport, requests = _transport(payload, status_code)
    http_client = httpx.AsyncClient(transport=transport, base_url="https://api.tavily.test")
    client = AsyncTavilyClient(api_key="synthetic-test-key", client=http_client)
    monkeypatch.setattr(tools, "_get_tavily_client", lambda *args, **kwargs: client)
    try:
        result = await tool.ainvoke(arguments)
    finally:
        await http_client.aclose()
    return result, requests


async def _invoke_search(monkeypatch, payload, status_code=200):
    from deerflow.community.tavily.tools import web_search_tool

    return await _invoke(monkeypatch, web_search_tool, {"query": _SEARCH_QUERY}, payload, status_code)


async def _invoke_fetch(monkeypatch, payload, status_code=200):
    from deerflow.community.tavily.tools import web_fetch_tool

    return await _invoke(monkeypatch, web_fetch_tool, {"url": _FETCH_URL}, payload, status_code)


async def _invoke_with_stubbed_client(monkeypatch, tool_name, method, payload, arguments):
    """Exercise a top-level shape the real SDK cannot return (it indexes the parsed body)."""
    from deerflow.community.tavily import tools

    client = MagicMock(spec=AsyncTavilyClient)
    setattr(client, method, AsyncMock(return_value=payload))
    monkeypatch.setattr(tools, "_get_tavily_client", lambda *args, **kwargs: client)
    tool = tools.web_search_tool if tool_name == "web_search" else tools.web_fetch_tool
    return await tool.ainvoke(arguments)


def _error_logs(caplog):
    return [record.getMessage() for record in caplog.records if record.name == _LOGGER_NAME and record.levelno == logging.ERROR]


def _assert_no_payload_values_leaked(caplog):
    assert "provider-private-payload" not in caplog.text
    assert "synthetic-test-key" not in caplog.text
    assert "example.com" not in caplog.text


@pytest.mark.anyio
@pytest.mark.parametrize("payload", [None, ["provider-private-payload"], "provider-private-payload"])
async def test_search_non_object_payload_returns_format_error(monkeypatch, payload, caplog):
    result = await _invoke_with_stubbed_client(monkeypatch, "web_search", "search", payload, {"query": _SEARCH_QUERY})

    assert json.loads(result) == {"error": _FORMAT_ERROR, "query": _SEARCH_QUERY}
    assert _error_logs(caplog) == [f"Tavily returned unexpected payload type: {type(payload).__name__}"]
    _assert_no_payload_values_leaked(caplog)


@pytest.mark.anyio
@pytest.mark.parametrize("results", [False, 0, "", "provider-private-payload", {}, {"0": "provider-private-payload"}])
async def test_search_malformed_results_container_returns_format_error(monkeypatch, results, caplog):
    result, _ = await _invoke_search(monkeypatch, {"results": results})

    assert json.loads(result) == {"error": _FORMAT_ERROR, "query": _SEARCH_QUERY}
    assert _error_logs(caplog) == [f"Tavily returned unexpected 'results' payload type: {type(results).__name__}"]
    _assert_no_payload_values_leaked(caplog)


@pytest.mark.anyio
@pytest.mark.parametrize("results", [[None], [False, 0, "provider-private-payload", []]])
async def test_search_all_malformed_entries_return_format_error(monkeypatch, results, caplog):
    result, _ = await _invoke_search(monkeypatch, {"results": results})

    assert json.loads(result) == {"error": _FORMAT_ERROR, "query": _SEARCH_QUERY}
    assert _error_logs(caplog) == ["Tavily returned 'results' with no usable result objects"]
    _assert_no_payload_values_leaked(caplog)


@pytest.mark.anyio
async def test_search_mixed_entries_preserve_valid_results_in_order(monkeypatch, caplog):
    payload = {"results": [None, {"title": "First", "url": "https://ok.example/one", "content": "snippet"}, "invalid", [], {"title": "Second"}]}

    result, _ = await _invoke_search(monkeypatch, payload)

    assert json.loads(result) == [
        {"title": "First", "url": "https://ok.example/one", "snippet": "snippet"},
        {"title": "Second", "url": "", "snippet": ""},
    ]
    assert _error_logs(caplog) == []


@pytest.mark.anyio
@pytest.mark.parametrize("payload", [{}, {"results": None}, {"results": []}])
async def test_search_missing_or_empty_results_keep_empty_list(monkeypatch, payload, caplog):
    result, _ = await _invoke_search(monkeypatch, payload)

    assert json.loads(result) == []
    assert _error_logs(caplog) == []


@pytest.mark.anyio
async def test_search_valid_payload_keeps_existing_normalization(monkeypatch, caplog):
    payload = {
        "query": _SEARCH_QUERY,
        "results": [{"title": "Release notes", "url": "https://example.com/releases", "content": "A recent release."}],
    }

    result, requests = await _invoke_search(monkeypatch, payload)

    assert json.loads(result) == [{"title": "Release notes", "url": "https://example.com/releases", "snippet": "A recent release."}]
    assert len(requests) == 1
    assert _error_logs(caplog) == []


@pytest.mark.anyio
@pytest.mark.parametrize("payload", [None, ["provider-private-payload"], "provider-private-payload"])
async def test_fetch_non_object_payload_returns_format_error(monkeypatch, payload, caplog):
    result = await _invoke_with_stubbed_client(monkeypatch, "web_fetch", "extract", payload, {"url": _FETCH_URL})

    assert result == "Error: Tavily returned an unexpected response format"
    assert _error_logs(caplog) == [f"Tavily returned unexpected payload type: {type(payload).__name__}"]
    _assert_no_payload_values_leaked(caplog)


@pytest.mark.anyio
@pytest.mark.parametrize("failed", [False, 0, "", "provider-private-payload", {"0": "provider-private-payload"}])
async def test_fetch_malformed_failed_results_container_returns_format_error(monkeypatch, failed, caplog):
    result, _ = await _invoke_fetch(monkeypatch, {"failed_results": failed})

    assert result == "Error: Tavily returned an unexpected response format"
    assert _error_logs(caplog) == [f"Tavily returned unexpected 'failed_results' payload type: {type(failed).__name__}"]
    _assert_no_payload_values_leaked(caplog)


@pytest.mark.anyio
@pytest.mark.parametrize("failed", [[None], [False, "provider-private-payload"]])
async def test_fetch_failed_results_without_objects_returns_format_error(monkeypatch, failed, caplog):
    result, _ = await _invoke_fetch(monkeypatch, {"failed_results": failed})

    assert result == "Error: Tavily returned an unexpected response format"
    assert _error_logs(caplog) == ["Tavily returned 'failed_results' with no usable result objects"]
    _assert_no_payload_values_leaked(caplog)


@pytest.mark.anyio
async def test_fetch_failed_result_without_error_returns_generic_error(monkeypatch, caplog):
    result, _ = await _invoke_fetch(monkeypatch, {"failed_results": [{"url": _FETCH_URL}]})

    assert result == "Error: Extraction failed"
    assert _error_logs(caplog) == []


@pytest.mark.anyio
@pytest.mark.parametrize("results", [False, {}, "provider-private-payload", [None], [False, 0]])
async def test_fetch_malformed_results_returns_format_error(monkeypatch, results, caplog):
    result, _ = await _invoke_fetch(monkeypatch, {"failed_results": [], "results": results})

    assert result == "Error: Tavily returned an unexpected response format"
    assert len(_error_logs(caplog)) == 1
    _assert_no_payload_values_leaked(caplog)


@pytest.mark.anyio
async def test_fetch_result_without_raw_content_returns_title_only(monkeypatch, caplog):
    result, _ = await _invoke_fetch(monkeypatch, {"results": [{"url": "https://example.com/report"}]})

    assert result == "# https://example.com/report\n\n"
    assert _error_logs(caplog) == []


@pytest.mark.anyio
@pytest.mark.parametrize("raw_content", [123, {"text": "provider-private-payload"}])
async def test_fetch_coerces_non_string_raw_content(monkeypatch, raw_content, caplog):
    result, _ = await _invoke_fetch(monkeypatch, {"results": [{"title": "Report", "raw_content": raw_content}]})

    assert result == f"# Report\n\n{raw_content if isinstance(raw_content, str) else str(raw_content)}"
    assert _error_logs(caplog) == []


@pytest.mark.anyio
async def test_fetch_valid_payload_keeps_existing_normalization(monkeypatch, caplog):
    payload = {"failed_results": [], "results": [{"title": "Report title", "url": "https://example.com/report", "raw_content": "Important findings."}]}

    result, requests = await _invoke_fetch(monkeypatch, payload)

    assert result == "# Report title\n\nImportant findings."
    assert len(requests) == 1
    assert _error_logs(caplog) == []
