"""Exercise Jsonify with real HTTPX initialization and no provider requests."""

import asyncio
import ssl
import threading

import httpx
import pytest

from deerflow.community.jsonify import tools


@pytest.fixture
def read_rows(monkeypatch):
    monkeypatch.setattr(tools, "validate_public_http_url", lambda *args, **kwargs: None)
    settings = tools._JsonifySettings(datasets={"demo": "https://jsonify.invalid/serve"})
    args = tools._RowsArgs(dataset="demo")

    async def read():
        return await tools._read_rows(settings, args)

    return read


@pytest.mark.asyncio
async def test_jsonify_loads_tls_trust_off_loop(read_rows, monkeypatch):
    loop_thread = threading.get_ident()
    create_default_context = ssl.create_default_context
    tls_threads = []
    clients = []

    def create_context(*args, **kwargs):
        tls_threads.append(threading.get_ident())
        return create_default_context(*args, **kwargs)

    async def send(self, request, **kwargs):
        assert threading.get_ident() == loop_thread
        assert request.url.host == "jsonify.invalid"
        clients.append(self)
        return httpx.Response(200, request=request, json={"rows": [{"name": "demo"}], "has_more": False})

    monkeypatch.setattr(ssl, "create_default_context", create_context)
    monkeypatch.setattr(httpx.AsyncClient, "send", send)

    result = await read_rows()

    assert result["rows"] == [{"name": "demo"}]
    assert tls_threads and loop_thread not in tls_threads
    assert len(clients) == 1
    assert clients[0].is_closed


@pytest.mark.asyncio
async def test_jsonify_closes_client_if_cancelled_during_setup(read_rows, monkeypatch):
    loop = asyncio.get_running_loop()
    loop_thread = threading.get_ident()
    started = asyncio.Event()
    finished = asyncio.Event()
    release = threading.Event()
    real_client = httpx.AsyncClient
    clients = []

    def construct(**kwargs):
        assert threading.get_ident() != loop_thread, "the constructor must not run on the event loop"
        loop.call_soon_threadsafe(started.set)
        try:
            assert release.wait(10), "the constructor was never released"
            client = real_client(**kwargs)
            clients.append(client)
            return client
        finally:
            loop.call_soon_threadsafe(finished.set)

    async def unexpected_send(self, request, **kwargs):
        pytest.fail("a cancelled construction must not send a request")

    monkeypatch.setattr(httpx, "AsyncClient", construct)
    monkeypatch.setattr(real_client, "send", unexpected_send)
    pending = asyncio.create_task(read_rows())
    start_waiter = asyncio.create_task(started.wait())
    try:
        done, _ = await asyncio.wait({pending, start_waiter}, timeout=10, return_when=asyncio.FIRST_COMPLETED)
        if pending in done:
            await pending
        assert start_waiter in done, "the constructor never started"

        pending.cancel()
        await asyncio.sleep(0)  # Deliver cancellation while construction is still gated.
        release.set()

        with pytest.raises(asyncio.CancelledError):
            await pending
        await asyncio.wait_for(finished.wait(), timeout=10)
        assert len(clients) == 1
        assert clients[0].is_closed
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
