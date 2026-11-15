"""Keep Tavily's synchronous TLS setup off the tool event loop."""

import asyncio
import ssl
import threading
from types import SimpleNamespace

import httpx
import pytest
from tavily import AsyncTavilyClient

from deerflow.community.tavily import tools

pytestmark = pytest.mark.asyncio

_URL = "https://example.com/article"


@pytest.fixture(autouse=True)
def tavily_config(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "synthetic-test-key")
    monkeypatch.setattr(tools, "get_app_config", lambda: SimpleNamespace(get_tool_config=lambda name: None))


@pytest.mark.parametrize(
    ("tool", "args", "route", "result"),
    [
        (tools.web_search_tool, {"query": "example"}, "/search", {"title": "Example", "url": _URL, "content": "search snippet"}),
        (tools.web_fetch_tool, {"url": _URL}, "/extract", {"url": _URL, "raw_content": "page body"}),
    ],
    ids=["search", "fetch"],
)
async def test_tavily_builds_tls_off_loop(tool, args, route, result, monkeypatch):
    loop_thread = threading.get_ident()
    create_context = ssl.create_default_context
    context_threads = []
    requests = []

    def record_context(*args, **kwargs):
        context_threads.append(threading.get_ident())
        return create_context(*args, **kwargs)

    async def respond(request):
        assert threading.get_ident() == loop_thread
        requests.append(request.url.path)
        return httpx.Response(200, json={"results": [result]})

    monkeypatch.setattr(ssl, "create_default_context", record_context)
    transport = httpx.MockTransport(respond)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", lambda self, request: transport.handle_async_request(request))

    assert _URL in await tool.ainvoke(args)
    assert requests == [route]
    assert context_threads
    assert loop_thread not in context_threads


async def test_tavily_closes_client_when_fetch_is_cancelled_during_construction(monkeypatch):
    loop = asyncio.get_running_loop()
    started = asyncio.Event()
    release = threading.Event()
    constructed = asyncio.Event()
    closed = []
    requests = []
    original_init = AsyncTavilyClient.__init__
    original_close = AsyncTavilyClient.close

    def gated_init(self, *args, **kwargs):
        loop.call_soon_threadsafe(started.set)
        assert release.wait(10), "the constructor was never released"
        try:
            original_init(self, *args, **kwargs)
        finally:
            loop.call_soon_threadsafe(constructed.set)

    async def record_close(self):
        await original_close(self)
        closed.append(self._client.is_closed)

    async def refuse(self, request, **kwargs):
        requests.append(request.url)
        raise AssertionError("cancelled construction must not send a request")

    monkeypatch.setattr(AsyncTavilyClient, "__init__", gated_init)
    monkeypatch.setattr(AsyncTavilyClient, "close", record_close)
    monkeypatch.setattr(httpx.AsyncClient, "send", refuse)

    pending = asyncio.create_task(tools.web_fetch_tool.coroutine(url=_URL))
    try:
        await asyncio.wait_for(started.wait(), timeout=10)
    finally:
        pending.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await pending
        await asyncio.wait_for(constructed.wait(), timeout=10)

    assert requests == []
    assert closed == [True]
