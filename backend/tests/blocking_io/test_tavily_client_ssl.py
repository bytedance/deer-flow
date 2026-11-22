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


@pytest.mark.parametrize(("tool", "args"), [(tools.web_search_tool, {"query": "example"}), (tools.web_fetch_tool, {"url": _URL})], ids=["search", "fetch"])
@pytest.mark.parametrize("cancel_count", [1, 2])
@pytest.mark.parametrize("construction_fails", [False, True], ids=["client-built", "construction-failed"])
async def test_tavily_drains_cancelled_client_construction(tool, args, cancel_count, construction_fails, monkeypatch, caplog):
    loop = asyncio.get_running_loop()
    loop_thread = threading.get_ident()
    started = asyncio.Event()
    release = threading.Event()
    finished = asyncio.Event()
    clients = []
    closed = []
    requests = []
    original_init = AsyncTavilyClient.__init__
    original_close = AsyncTavilyClient.close
    sensitive_detail = "synthetic-sensitive-value"

    def gated_init(self, *args, **kwargs):
        assert threading.get_ident() != loop_thread, "client construction must run off the event loop"
        loop.call_soon_threadsafe(started.set)
        try:
            assert release.wait(10), "the constructor was never released"
            if construction_fails:
                raise RuntimeError(sensitive_detail)
            original_init(self, *args, **kwargs)
            clients.append(self)
        finally:
            loop.call_soon_threadsafe(finished.set)

    async def record_close(self):
        await original_close(self)
        closed.append(self._client.is_closed)

    async def refuse(self, request, **kwargs):
        requests.append(request.url)
        raise AssertionError("cancelled construction must not send a request")

    monkeypatch.setattr(AsyncTavilyClient, "__init__", gated_init)
    monkeypatch.setattr(AsyncTavilyClient, "close", record_close)
    monkeypatch.setattr(httpx.AsyncClient, "send", refuse)

    pending = asyncio.create_task(tool.coroutine(**args))
    start_waiter = asyncio.create_task(started.wait())
    try:
        done, _ = await asyncio.wait({pending, start_waiter}, timeout=10, return_when=asyncio.FIRST_COMPLETED)
        if pending in done:
            await pending
        assert start_waiter in done, "the constructor never started"
        for _ in range(cancel_count):
            pending.cancel()
            await asyncio.sleep(0)  # Let cancellation reach the tool while the constructor is gated.
            assert not pending.done(), "cancellation escaped before the constructor finished"

        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(pending, timeout=10)

        assert requests == []
        if construction_fails:
            assert closed == []
            assert "Tavily client cleanup after cancellation failed (RuntimeError)" in caplog.text
            assert sensitive_detail not in caplog.text
        else:
            assert closed == [True]
    finally:
        release.set()
        pending.cancel()
        start_waiter.cancel()
        await asyncio.gather(pending, start_waiter, return_exceptions=True)
        if started.is_set():
            await asyncio.wait_for(finished.wait(), timeout=10)
        for client in clients:
            if not client._client.is_closed:
                await original_close(client)
