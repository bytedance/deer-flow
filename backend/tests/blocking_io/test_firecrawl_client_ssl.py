"""Exercise Firecrawl SDK construction with offline HTTP responses."""

import asyncio
import json
import ssl
import threading
from types import SimpleNamespace

import httpx
import pytest
from firecrawl.v2.utils import http_client_async

from deerflow.community.firecrawl import tools


@pytest.fixture
def sdk_client(monkeypatch):
    class OfflineClient(httpx.AsyncClient):
        pass

    monkeypatch.setattr(http_client_async, "httpx", SimpleNamespace(**(vars(httpx) | {"AsyncClient": OfflineClient})))
    return OfflineClient


@pytest.fixture(params=["search", "fetch"])
def invoke(request, monkeypatch, sdk_client):
    config = SimpleNamespace(get_tool_config=lambda _: SimpleNamespace(model_extra={"api_key": "synthetic-key"}))
    monkeypatch.setattr(tools, "get_app_config", lambda: config)
    monkeypatch.setattr(tools, "validate_public_http_url", lambda *args, **kwargs: None)
    tool = tools.web_search_tool if request.param == "search" else tools.web_fetch_tool
    arguments = {"query": "synthetic query"} if request.param == "search" else {"url": "https://example.com"}
    return lambda: tool.ainvoke(arguments)


@pytest.mark.asyncio
async def test_firecrawl_loads_tls_trust_off_loop(invoke, monkeypatch, sdk_client):
    loop_thread = threading.get_ident()
    original_context = ssl.create_default_context
    contexts = []
    clients = []

    def create_context(*args, **kwargs):
        assert threading.get_ident() != loop_thread, "TLS trust loading blocks the event loop"
        context = original_context(*args, **kwargs)
        contexts.append(context)
        return context

    async def send(self, request, **kwargs):
        assert threading.get_ident() == loop_thread
        assert request.url.host == "api.firecrawl.dev"
        assert request.headers["Authorization"] == "Bearer synthetic-key"
        clients.append(self)
        body = json.loads(request.content)
        if request.url.path == "/v2/search":
            assert body["query"] == "synthetic query"
            assert body["limit"] == 5
            data = {"web": [{"title": "Synthetic", "url": "https://example.com", "description": "Synthetic text"}]}
        else:
            assert request.url.path == "/v2/scrape"
            assert body["url"] == "https://example.com"
            assert body["formats"] == ["markdown"]
            data = {"markdown": "Synthetic text", "metadata": {"title": "Synthetic"}}
        return httpx.Response(200, request=request, json={"success": True, "data": data})

    monkeypatch.setattr(ssl, "create_default_context", create_context)
    monkeypatch.setattr(sdk_client, "send", send)
    result = await invoke()
    assert "Synthetic text" in result
    assert contexts
    assert len(clients) == 1
    assert clients[0].is_closed


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_count", [1, 2])
@pytest.mark.parametrize("construction_fails", [False, True])
async def test_firecrawl_closes_client_cancelled_during_setup(invoke, monkeypatch, cancel_count, construction_fails, caplog, sdk_client):
    loop = asyncio.get_running_loop()
    loop_thread = threading.get_ident()
    started, finished = asyncio.Event(), asyncio.Event()
    release = threading.Event()
    real_app = tools.AsyncFirecrawlApp
    clients = []

    def construct(**kwargs):
        assert threading.get_ident() != loop_thread, "SDK construction must run off the event loop"
        loop.call_soon_threadsafe(started.set)
        try:
            assert release.wait(10), "SDK construction was never released"
            if construction_fails:
                raise RuntimeError("synthetic-sensitive-value")
            app = real_app(**kwargs)
            clients.append(app._v2_client.async_http_client._client)
            return app
        finally:
            loop.call_soon_threadsafe(finished.set)

    async def unexpected_send(self, request, **kwargs):
        pytest.fail("cancelled setup must not send a request")

    monkeypatch.setattr(tools, "AsyncFirecrawlApp", construct)
    monkeypatch.setattr(sdk_client, "send", unexpected_send)
    pending = asyncio.create_task(invoke())
    start_waiter = asyncio.create_task(started.wait())
    try:
        done, _ = await asyncio.wait({pending, start_waiter}, timeout=10, return_when=asyncio.FIRST_COMPLETED)
        if pending in done:
            await pending
        assert start_waiter in done, "SDK construction never started"
        for _ in range(cancel_count):
            pending.cancel()
            await asyncio.sleep(0)  # Deliver cancellation while construction is gated.
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await pending
        await asyncio.wait_for(finished.wait(), timeout=10)
        assert len(clients) == (0 if construction_fails else 1)
        assert all(client.is_closed for client in clients)
        if construction_fails:
            assert "RuntimeError" in caplog.text
            assert "synthetic-sensitive-value" not in caplog.text
    finally:
        release.set()
        pending.cancel()
        start_waiter.cancel()
        await asyncio.gather(pending, start_waiter, return_exceptions=True)
        if started.is_set():
            await asyncio.wait_for(finished.wait(), timeout=10)
        for client in clients:
            if not client.is_closed:
                await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_phase", ["construction", "request"])
async def test_firecrawl_preserves_errors_and_closes_clients(invoke, monkeypatch, failure_phase, sdk_client):
    real_app = tools.AsyncFirecrawlApp
    clients = []

    def construct(**kwargs):
        if failure_phase == "construction":
            raise RuntimeError("synthetic construction failure")
        app = real_app(**kwargs)
        clients.append(app._v2_client.async_http_client._client)
        return app

    async def send(self, request, **kwargs):
        raise RuntimeError("synthetic request failure")

    monkeypatch.setattr(tools, "AsyncFirecrawlApp", construct)
    monkeypatch.setattr(sdk_client, "send", send)
    result = await invoke()
    assert f"synthetic {failure_phase} failure" in result
    assert len(clients) == (0 if failure_phase == "construction" else 1)
    assert all(client.is_closed for client in clients)
