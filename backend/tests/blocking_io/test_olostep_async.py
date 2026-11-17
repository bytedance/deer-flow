"""Olostep community tools must not occupy an executor thread or block the loop.

* The request is awaited on the event loop thread, so no pool thread is held
  for the network round trip.
* The config lookup, which reads the config file, and the client construction,
  which loads the TLS trust store, run off the loop.
* The request goes out through the async client. A ``MockTransport`` runs its
  handler on the calling thread, so a provider that sent the request through a
  sync ``httpx.Client`` would pass the thread assertion; the recorded client
  factory catches that.
* The tool keeps ownership of the client through cancellation: a client built
  after the caller was cancelled is still closed, a repeated cancellation does
  not cut the close short, and a cleanup failure is logged without its message.
"""

import asyncio
import logging
import ssl
import threading
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from deerflow.community.olostep import tools as olostep_tools

pytestmark = pytest.mark.asyncio

_PAYLOADS = {
    "web_search": {"result": {"links": [{"url": "https://example.com", "title": "Synthetic", "description": "Synthetic text"}]}},
    "web_fetch": {"result": {"markdown_content": "Synthetic text", "page_metadata": {"title": "Synthetic"}}},
}


def _invoke(tool_name: str):
    if tool_name == "web_search":
        return olostep_tools.web_search_tool.ainvoke({"query": "synthetic query"})
    return olostep_tools.web_fetch_tool.ainvoke({"url": "https://example.com"})


@pytest.mark.parametrize("tool_name", ["web_search", "web_fetch"])
async def test_olostep_request_on_loop_config_and_client_off_loop(tool_name, monkeypatch) -> None:
    loop_thread = threading.get_ident()
    request_threads: list[int] = []
    config_threads: list[int] = []
    clients: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        request_threads.append(threading.get_ident())
        return httpx.Response(200, json=_PAYLOADS[tool_name])

    transport = httpx.MockTransport(respond)

    def async_client(**kwargs):
        clients.append("AsyncClient")
        return httpx.AsyncClient(transport=transport, **kwargs)

    def sync_client(**kwargs):
        clients.append("Client")
        return httpx.Client(transport=transport, **kwargs)

    def load_config():
        # A real file read, so the strict gate fails if this lands on the loop.
        Path(__file__).read_text(encoding="utf-8")
        config_threads.append(threading.get_ident())
        return SimpleNamespace(get_tool_config=lambda _name: SimpleNamespace(model_extra={"api_key": "synthetic-key"}))

    monkeypatch.setattr(olostep_tools, "httpx", SimpleNamespace(AsyncClient=async_client, Client=sync_client, HTTPStatusError=httpx.HTTPStatusError))
    monkeypatch.setattr(olostep_tools, "get_app_config", load_config)

    result = await _invoke(tool_name)

    assert "Synthetic text" in result
    assert request_threads and all(thread == loop_thread for thread in request_threads)
    assert config_threads and all(thread != loop_thread for thread in config_threads)
    assert clients == ["AsyncClient"], "the request must go out through the async client"


@pytest.mark.parametrize("tool_name", ["web_search", "web_fetch"])
async def test_olostep_tls_setup_runs_off_loop(tool_name, monkeypatch) -> None:
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
        assert request.url.host == "api.olostep.com"
        assert request.headers["Authorization"] == "Bearer synthetic-key"
        clients.append(self)
        return httpx.Response(200, request=request, json=_PAYLOADS[tool_name])

    config = SimpleNamespace(get_tool_config=lambda _name: SimpleNamespace(model_extra={"api_key": "synthetic-key"}))
    monkeypatch.setattr(olostep_tools, "get_app_config", lambda: config)
    monkeypatch.setattr(ssl, "create_default_context", create_context)
    monkeypatch.setattr(httpx.AsyncClient, "send", send)

    result = await _invoke(tool_name)

    assert "Synthetic text" in result
    assert contexts
    assert len(clients) == 1
    assert clients[0].is_closed


def _patch_httpx(monkeypatch, async_client) -> None:
    monkeypatch.setattr(olostep_tools, "httpx", SimpleNamespace(AsyncClient=async_client, HTTPStatusError=httpx.HTTPStatusError))


def _post():
    return olostep_tools._post("synthetic-key", "/v1/searches", {"query": "synthetic query"})


async def test_olostep_closes_client_if_cancelled_during_setup(monkeypatch) -> None:
    loop = asyncio.get_running_loop()
    loop_thread = threading.get_ident()
    started, finished = asyncio.Event(), asyncio.Event()
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

    _patch_httpx(monkeypatch, construct)
    monkeypatch.setattr(real_client, "send", unexpected_send)
    pending = asyncio.create_task(_post())
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


class _GatedCloseTransport(httpx.AsyncBaseTransport):
    """Answers every request, then holds ``aclose`` until the test releases it."""

    def __init__(self) -> None:
        self.closing = asyncio.Event()
        self.release = asyncio.Event()
        self.closed = False

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, request=request, json=_PAYLOADS["web_search"])

    async def aclose(self) -> None:
        self.closing.set()
        await self.release.wait()
        self.closed = True


async def test_olostep_drains_client_close_through_repeated_cancellation(monkeypatch) -> None:
    real_client = httpx.AsyncClient
    transport = _GatedCloseTransport()
    _patch_httpx(monkeypatch, lambda **kwargs: real_client(transport=transport, **kwargs))

    pending = asyncio.create_task(_post())
    try:
        await asyncio.wait_for(transport.closing.wait(), timeout=10)

        pending.cancel()
        await asyncio.sleep(0)
        pending.cancel()  # A second cancellation must not cut the close short.
        await asyncio.sleep(0)
        assert not pending.done(), "the tool returned while the transport was still closing"
        assert not transport.closed

        transport.release.set()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert transport.closed
    finally:
        transport.release.set()
        pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)


@pytest.mark.parametrize("failure_phase", ["construction", "close"])
async def test_olostep_logs_cleanup_failures_during_repeated_cancellation(monkeypatch, caplog, failure_phase) -> None:
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

    _patch_httpx(monkeypatch, construct)
    pending = asyncio.create_task(_post())
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
        assert "RuntimeError" in errors[0].getMessage()
        assert secret not in errors[0].getMessage()
    finally:
        release.set()
        pending.cancel()
        start_waiter.cancel()
        await asyncio.gather(pending, start_waiter, return_exceptions=True)
        if started.is_set():
            await asyncio.wait_for(finished.wait(), timeout=10)
