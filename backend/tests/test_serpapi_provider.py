"""Offline contracts for SerpApi's Google and single-page Extract engines."""

import asyncio
import json
from types import SimpleNamespace

import httpcore
import httpx
import pytest

from deerflow.community.serpapi import tools

pytestmark = pytest.mark.asyncio
KEY = "synthetic-secret&+/value"
URL = "https://example.org/article?tag[]=coffee&lang=en"


def _clear_proxy_env(monkeypatch):
    for name in ("http_proxy", "https_proxy", "all_proxy", "no_proxy"):
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(name.upper(), raising=False)


@pytest.fixture
def api(monkeypatch):
    state = SimpleNamespace(requests=[], response=httpx.Response(200, json={}), extras={"web_search": {}, "web_fetch": {}})

    def respond(request):
        state.requests.append(request)
        if isinstance(state.response, Exception):
            raise state.response
        return state.response

    monkeypatch.setenv("SERPAPI_API_KEY", KEY)
    monkeypatch.setattr(tools, "get_app_config", lambda: SimpleNamespace(get_tool_config=lambda name: SimpleNamespace(model_extra=state.extras[name])))
    state.transport = httpx.MockTransport(respond)
    client = tools._SerpApiClient
    monkeypatch.setattr(tools, "_SerpApiClient", lambda params: client(params, transport=state.transport))
    return state


async def test_google_organic_results_key_precedence_and_local_limit(api, caplog, monkeypatch):
    caplog.set_level("DEBUG")
    monkeypatch.setenv("SERPAPI_API_KEY", "other-synthetic-key")
    api.extras["web_search"] = {"api_key": f"  {KEY}\n", "max_results": 1}
    valid = {"title": "Coffee", "link": "https://example.org/", "snippet": "Caf\u00e9"}
    rows = [None, valid, {"link": "http://localhost/", "title": 23}, valid]
    api.response = httpx.Response(200, json={"organic_results": rows, "serpapi_pagination": {"next": "https://example.org/next"}})
    query = " private terms & coffee "
    result = json.loads(await tools.web_search_tool.ainvoke({"query": query, "max_results": 2}))
    assert result == [{"title": "Coffee", "url": "https://example.org/", "snippet": "Caf\u00e9"}, {"title": "", "url": "", "snippet": ""}]
    assert len(api.requests) == 1
    sent = api.requests[0]
    assert (sent.method, str(sent.url.copy_with(query=None))) == ("GET", "https://serpapi.com/search.json")
    assert dict(sent.url.params) == {"engine": "google", "q": query, "api_key": KEY}
    assert "synthetic-secret" not in caplog.text and "private" not in caplog.text


@pytest.mark.parametrize("query", ["", " \n\t "])
async def test_google_rejects_blank_query_before_request(api, query):
    result = await tools.web_search_tool.ainvoke({"query": query})
    assert not api.requests
    assert json.loads(result) == {"error": "Search query must not be empty"}


@pytest.mark.parametrize("configured,expected", [(2, 2), (0, 5)])
async def test_google_configured_limit(api, configured, expected):
    api.extras["web_search"] = {"max_results": configured}
    api.response = httpx.Response(200, json={"organic_results": [{"title": "coffee"}] * 7})
    assert len(json.loads(await tools.web_search_tool.ainvoke({"query": "coffee"}))) == expected


@pytest.mark.parametrize("rows,empty", [(None, True), ([], True), ({}, False), (["malformed"], False)])
async def test_google_distinguishes_empty_from_malformed(api, rows, empty):
    api.response = httpx.Response(200, json={"organic_results": rows})
    error = json.loads(await tools.web_search_tool.ainvoke({"query": "coffee"}))["error"]
    assert ("No results found" if empty else "unexpected response format") in error


@pytest.mark.parametrize(
    ("status", "state", "expected"),
    [("Success", "Fully empty", "No results found"), ("Error", "Fully empty", "SerpApi reported an error"), ("Success", "Unknown", "SerpApi reported an error")],
)
async def test_google_empty_success_with_provider_error_field(api, status, state, expected):
    api.response = httpx.Response(200, json={"search_metadata": {"status": status}, "search_information": {"organic_results_state": state}, "error": KEY})
    assert json.loads(await tools.web_search_tool.ainvoke({"query": "coffee"})) == {"error": expected}


@pytest.mark.parametrize(
    ("tool", "args", "http_proxy", "https_proxy", "no_proxy", "destination"),
    [
        (tools.web_search_tool, {"query": "coffee"}, None, "http://https-proxy.example:8080", "other.example", ("https-proxy.example", 8080)),
        (tools.web_fetch_tool, {"url": URL}, None, None, "", ("fallback.example", 8081)),
        (tools.web_fetch_tool, {"url": URL}, None, "http://https-proxy.example:8080", "serpapi.com", ("serpapi.com", 443)),
        (tools.web_search_tool, {"query": "coffee"}, None, "invalid://operator:synthetic-password@proxy.example", "", None),
        (tools.web_search_tool, {"query": "coffee"}, "invalid://operator:synthetic-password@proxy.example", None, "", None),
    ],
    ids=["https-before-all", "all-fallback", "no-proxy", "invalid-proxy", "native-client-validates-all-routes"],
)
async def test_environment_proxy_routes_without_connecting(monkeypatch, caplog, tool, args, http_proxy, https_proxy, no_proxy, destination):
    connections = []

    async def connect_tcp(self, host, port, **kwargs):
        connections.append((host, port))
        raise httpcore.ConnectError("offline")

    _clear_proxy_env(monkeypatch)
    monkeypatch.setenv("ALL_PROXY", "http://fallback.example:8081")
    if http_proxy:
        monkeypatch.setenv("HTTP_PROXY", http_proxy)
    if https_proxy:
        monkeypatch.setenv("HTTPS_PROXY", https_proxy)
    monkeypatch.setenv("NO_PROXY", no_proxy)
    monkeypatch.setenv("SERPAPI_API_KEY", KEY)
    monkeypatch.setattr(tools, "get_app_config", lambda: SimpleNamespace(get_tool_config=lambda _: None))
    monkeypatch.setattr(httpcore.AnyIOBackend, "connect_tcp", connect_tcp)

    result = await tool.ainvoke(args)
    if destination is None:
        assert not connections
        assert "SerpApi HTTP transport could not be configured" in result
        assert "synthetic-password" not in result + caplog.text
    else:
        assert "SerpApi request failed" in result
        assert connections == [destination]


@pytest.mark.parametrize("length", [24, 4096, 4500])
async def test_extract_returns_only_bounded_markdown_from_one_url(api, length):
    markdown = "    " + "x" * (length - 5) + "\n"
    api.response = httpx.Response(200, json={"markdown": markdown, "inline_links": [{"link": "https://example.org/next"}]})
    result = await tools.web_fetch_tool.ainvoke({"url": URL})
    if length <= 4096:
        assert result == markdown
    else:
        assert len(result) == 4096 and result.startswith(markdown[:4000]) and "truncated" in result
    assert len(api.requests) == 1
    assert dict(api.requests[0].url.params) == {"engine": "extract", "mode": "scrape", "url": URL, "api_key": KEY}


@pytest.mark.parametrize("url", ["file:///page", "https://user:pass@example.org/", "http://127.0.0.1/", "http://metadata.google.internal/"])
async def test_extract_refuses_unsafe_url_before_request(api, url):
    assert (await tools.web_fetch_tool.ainvoke({"url": url})).startswith("Error:")
    assert not api.requests


@pytest.mark.parametrize("markdown,expected", [(None, "No Markdown content found"), ("", "No Markdown content found"), ("\n \t", "No Markdown content found"), ({"text": KEY}, "unexpected response format")])
async def test_extract_refuses_missing_or_malformed_markdown(api, markdown, expected):
    api.response = httpx.Response(200, json={"markdown": markdown, "other_fields": KEY})
    result = await tools.web_fetch_tool.ainvoke({"url": URL})
    assert result.startswith("Error:") and expected in result and KEY not in result


@pytest.mark.parametrize(("name", "args"), [("web_search", {"query": "coffee"}), ("web_fetch", {"url": URL})])
@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (httpx.Response(302, headers={"Location": "https://example.org/elsewhere"}), "HTTP 302"),
        (httpx.Response(401, json={"error": KEY}), "HTTP 401"),
        (httpx.Response(200, json={"error": KEY}), "SerpApi reported"),
        (httpx.Response(200, content=KEY.encode()), "invalid JSON"),
        (httpx.ConnectError(KEY), "request failed"),
        (httpx.ReadTimeout(KEY), "timed out"),
    ],
)
async def test_provider_failures_do_not_disclose_credentials_or_retry(api, caplog, name, args, response, expected):
    caplog.set_level("DEBUG")
    api.response = response
    result = await getattr(tools, f"{name}_tool").ainvoke(args)
    error = json.loads(result)["error"] if name == "web_search" else result.removeprefix("Error: ")
    assert expected in error
    assert "synthetic-secret" not in result + caplog.text
    assert len(api.requests) == 1


@pytest.mark.parametrize(("name", "args"), [("web_search", {"query": "coffee"}), ("web_fetch", {"url": URL})])
async def test_missing_key_stops_before_network(api, monkeypatch, name, args):
    monkeypatch.delenv("SERPAPI_API_KEY")
    api.extras[name] = {"api_key": "your-serper-api-key"}
    result = await getattr(tools, f"{name}_tool").ainvoke(args)
    assert "SERPAPI_API_KEY is not configured" in result
    assert not api.requests


async def test_config_error_does_not_disclose_secret(api, monkeypatch, caplog):
    def invalid_config():
        raise ValueError(KEY)

    monkeypatch.setattr(tools, "get_app_config", invalid_config)
    result = await tools.web_search_tool.ainvoke({"query": "coffee"})
    assert "configuration could not be loaded" in json.loads(result)["error"]
    assert not api.requests and KEY not in result + caplog.text


async def test_cancellation_closes_the_inflight_transport(api):
    started, closed = asyncio.Event(), asyncio.Event()

    class Transport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            started.set()
            await asyncio.Event().wait()

        async def aclose(self):
            closed.set()

    api.transport = Transport()
    task = asyncio.create_task(tools.web_fetch_tool.ainvoke({"url": URL}))
    try:
        await asyncio.wait_for(started.wait(), timeout=5)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert closed.is_set()


@pytest.mark.parametrize("case", ["response-headers", "read-error", "proxy-tunnel"])
async def test_echoed_credentials_stay_out_of_http_debug_logs(monkeypatch, caplog, case):
    # Run the HTTP/1.1 parser and both libraries' real logging paths, with no socket.
    _clear_proxy_env(monkeypatch)
    monkeypatch.setenv("no_proxy", "" if case == "proxy-tunnel" else "*")
    responses = [f"HTTP/1.1 403 {KEY}\r\nX-Error: {KEY}\r\nContent-Length: 0\r\n\r\n".encode()]
    request_lines = []
    if case == "proxy-tunnel":
        monkeypatch.setenv("https_proxy", "http://proxy.example:8080")
        responses.insert(0, b"HTTP/1.1 200 Connection established\r\n\r\n")

        async def capture_write(self, buffer, timeout=None):
            if buffer:
                request_lines.append(buffer.split(b"\r\n", 1)[0])

        monkeypatch.setattr(httpcore.AsyncMockStream, "write", capture_write)
    elif case == "read-error":

        async def fail_read(self, max_bytes, timeout=None):
            raise httpcore.ReadError(KEY)

        monkeypatch.setattr(httpcore.AsyncMockStream, "read", fail_read)
    monkeypatch.setattr(httpcore.AnyIOBackend, "connect_tcp", httpcore.AsyncMockBackend(responses).connect_tcp)
    monkeypatch.setenv("SERPAPI_API_KEY", KEY)
    monkeypatch.setattr(tools, "get_app_config", lambda: SimpleNamespace(get_tool_config=lambda _: None))
    caplog.set_level("DEBUG")
    result = await tools.web_search_tool.ainvoke({"query": "coffee"})
    if case == "read-error":
        assert "SerpApi request failed" in result
        assert "receive_response_headers.failed" in caplog.text
    else:
        assert "HTTP 403" in result
    assert "synthetic-secret" not in result + caplog.text
    if case == "proxy-tunnel":
        connect, get = request_lines
        assert connect == b"CONNECT serpapi.com:443 HTTP/1.1"
        assert get.startswith(b"GET /search.json?") and b"api_key=synthetic-secret" in get
