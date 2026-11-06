"""Exercise Jsonify with real HTTPX initialization and no provider requests."""

import asyncio
import logging
import ssl
import threading
from types import SimpleNamespace

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


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_phase", ["construction", "close"])
async def test_jsonify_logs_failures_during_repeated_cancellation(read_rows, monkeypatch, caplog, failure_phase):
    loop = asyncio.get_running_loop()
    loop_thread = threading.get_ident()
    started, finished = asyncio.Event(), asyncio.Event()
    release = threading.Event()
    close_threads = []
    secret = "synthetic-sensitive-value"
    caplog.set_level(logging.ERROR)

    async def close():
        close_threads.append(threading.get_ident())
        raise RuntimeError(secret)

    def construct(**kwargs):
        assert threading.get_ident() != loop_thread
        loop.call_soon_threadsafe(started.set)
        try:
            assert release.wait(10), "the constructor was never released"
            if failure_phase == "construction":
                raise RuntimeError(secret)
            return SimpleNamespace(aclose=close)
        finally:
            loop.call_soon_threadsafe(finished.set)

    monkeypatch.setattr(httpx, "AsyncClient", construct)
    pending = asyncio.create_task(read_rows())
    start_waiter = asyncio.create_task(started.wait())
    try:
        done, _ = await asyncio.wait({pending, start_waiter}, timeout=10, return_when=asyncio.FIRST_COMPLETED)
        if pending in done:
            await pending
        assert start_waiter in done, "the constructor never started"

        pending.cancel()
        await asyncio.sleep(0)  # Enter cleanup while construction is still gated.
        pending.cancel()
        await asyncio.sleep(0)  # Cancel the drain before its worker fails.
        release.set()

        with pytest.raises(asyncio.CancelledError):
            await pending
        await asyncio.wait_for(finished.wait(), timeout=10)

        assert close_threads == ([loop_thread] if failure_phase == "close" else [])
        errors = [record for record in caplog.records if record.levelno == logging.ERROR]
        assert len(errors) == 1
        assert errors[0].levelno == logging.ERROR
        assert "RuntimeError" in errors[0].getMessage()
        assert secret not in errors[0].getMessage()
    finally:
        release.set()
        pending.cancel()
        start_waiter.cancel()
        await asyncio.gather(pending, start_waiter, return_exceptions=True)
        if started.is_set():
            await asyncio.wait_for(finished.wait(), timeout=10)
