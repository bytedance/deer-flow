"""Exercise the built-in provider through the real MCP and HTTPX clients."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from deerflow.community.parallel_search import tools as parallel_tools
from deerflow.config.app_config import AppConfig, pop_current_app_config, push_current_app_config
from deerflow.tools.tools import get_available_tools


@pytest.fixture
def configured_search(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    config_path.write_bytes((Path(__file__).resolve().parents[2] / "config.example.yaml").read_bytes())
    extensions_path = tmp_path / "extensions_config.json"
    extensions_path.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("DEER_FLOW_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions_path))
    config = AppConfig.from_file(str(config_path))
    tools = get_available_tools(groups=["web"], include_mcp=False, app_config=config)
    (search,) = [tool for tool in tools if tool.name == "web_search"]
    assert search is parallel_tools.web_search_tool
    push_current_app_config(config)
    try:
        yield search
    finally:
        pop_current_app_config()


@pytest.fixture
def fake_parallel(monkeypatch):
    def install(*, payload=None, status=200, is_error=False, deadline=None):
        calls = []
        clients = []

        async def reply(request: httpx.Request) -> httpx.Response:
            rpc = json.loads(request.content)
            method = rpc["method"]
            calls.append((request, rpc))
            if method == "initialize":
                result = {"protocolVersion": rpc["params"]["protocolVersion"], "capabilities": {"tools": {}}, "serverInfo": {"name": "search", "version": "1"}}
            elif method == "notifications/initialized":
                return httpx.Response(202)
            elif method == "tools/list":
                result = {"tools": [{"name": "web_search", "inputSchema": {"type": "object"}}]}
            else:
                assert method == "tools/call"
                if deadline is not None:
                    deadline.reschedule(asyncio.get_running_loop().time())
                    await asyncio.Event().wait()
                if status != 200:
                    return httpx.Response(status)
                result = {"content": [], "structuredContent": payload, "isError": is_error}
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": rpc["id"], "result": result})

        def make_client(**kwargs):
            client = httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
            clients.append(client)
            return client

        monkeypatch.setattr(parallel_tools, "httpx", SimpleNamespace(AsyncClient=make_client))
        return calls, clients

    return install


@pytest.mark.asyncio
async def test_installed_search_sends_only_query_and_normalizes_results(configured_search, fake_parallel):
    source = {"title": "Apollo", "url": "https://www.nasa.gov/apollo", "excerpts": ["Excerpt", 1, "More"]}
    hidden = {"title": None, "url": "http://127.0.0.1/internal", "excerpts": "invalid"}
    calls, clients = fake_parallel(payload={"results": [None, source, hidden, *[source] * 4], "session_id": "server-session"})

    output = json.loads(await configured_search.ainvoke({"query": "NASA Apollo 11", "max_results": 1}))

    assert [rpc["method"] for _, rpc in calls] == ["initialize", "notifications/initialized", "tools/call", "tools/list"]
    for request, _ in calls:
        assert str(request.url) == "https://mcp.parallel.ai/mcp?tools=web_search"
        assert request.headers["User-Agent"] == "deer-flow"
        assert "Authorization" not in request.headers
    assert calls[2][1]["params"] == {"name": "web_search", "arguments": {"objective": "NASA Apollo 11", "search_queries": ["NASA Apollo 11"]}}
    normalized_source = {"title": "Apollo", "url": "https://www.nasa.gov/apollo", "content": "Excerpt\n\nMore"}
    assert output == {
        "query": "NASA Apollo 11",
        "total_results": 5,
        "results": [
            normalized_source,
            {"title": "", "url": "", "content": ""},
            *[normalized_source] * 3,
        ],
    }
    assert clients[0].is_closed


@pytest.mark.asyncio
async def test_recency_is_passed_as_an_objective_preference(configured_search, fake_parallel):
    calls, _ = fake_parallel(payload={"results": []})
    await configured_search.ainvoke({"query": "test", "time_range": "week"})
    assert calls[2][1]["params"]["arguments"] == {"objective": "test. Prioritize results from the past week.", "search_queries": ["test"]}


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"results": None}, {"results": []}])
async def test_empty_search_is_success(configured_search, fake_parallel, payload):
    fake_parallel(payload=payload)
    assert json.loads(await configured_search.ainvoke({"query": "nothing"})) == {"query": "nothing", "total_results": 0, "results": []}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "error"),
    [
        ({"payload": {"results": "invalid"}}, "Invalid Parallel Search response."),
        ({"payload": {"results": [1]}}, "Invalid Parallel Search response."),
        ({"is_error": True}, "Parallel Search reported a search error."),
        ({"status": 429}, "Parallel Search rate limit reached. Try again later or choose another web search provider."),
        ({"status": 503}, "Parallel Search request failed."),
    ],
)
async def test_provider_failures_are_distinct_from_empty_search(configured_search, fake_parallel, response, error):
    calls, clients = fake_parallel(**response)
    assert json.loads(await configured_search.ainvoke({"query": "test"})) == {"query": "test", "error": error}
    assert calls[2][1]["method"] == "tools/call"
    assert clients[0].is_closed


@pytest.mark.asyncio
async def test_search_timeout_closes_client(configured_search, fake_parallel, monkeypatch):
    deadline = asyncio.timeout(None)
    calls, clients = fake_parallel(deadline=deadline)
    monkeypatch.setattr(parallel_tools, "asyncio", SimpleNamespace(timeout=lambda _: deadline, to_thread=asyncio.to_thread))
    assert json.loads(await configured_search.ainvoke({"query": "test"})) == {"query": "test", "error": "Parallel Search request timed out."}
    assert deadline.expired()
    assert calls[-1][1]["method"] == "tools/call"
    assert clients[0].is_closed
