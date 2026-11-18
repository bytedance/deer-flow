"""Browserless must load HTTPX TLS trust off the agent event loop."""

import asyncio
import ssl
import threading

import httpx
import pytest

from deerflow.community.browserless.browserless_client import BrowserlessClient


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["fetch_html_with_status", "capture_screenshot"])
async def test_browserless_client_tls_setup_runs_off_loop(operation, monkeypatch):
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
        clients.append(self)
        assert request.url.host == "browserless.example"
        if operation == "capture_screenshot":
            assert request.url.path == "/screenshot"
            return httpx.Response(
                200,
                request=request,
                content=b"\x89PNG synthetic",
                headers={"Content-Type": "image/png", "X-Response-Code": "200"},
            )
        assert request.url.path == "/content"
        return httpx.Response(
            200,
            request=request,
            text="<html>synthetic page</html>",
            headers={"X-Response-Code": "200", "X-Response-Status": "OK"},
        )

    monkeypatch.setattr(ssl, "create_default_context", create_context)
    monkeypatch.setattr(httpx.AsyncClient, "send", send)

    client = BrowserlessClient("https://browserless.example", token="token")

    if operation == "capture_screenshot":
        result = await client.capture_screenshot("https://example.com")
        assert result.content == b"\x89PNG synthetic"
    else:
        result = await client.fetch_html_with_status("https://example.com")
        assert result.html == "<html>synthetic page</html>"

    assert contexts
    assert len(clients) == 1
    assert clients[0].is_closed


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["fetch_html_with_status", "capture_screenshot"])
async def test_browserless_client_closes_client_built_after_cancellation(operation, monkeypatch):
    """Cancelling during construction must not leak the client it eventually builds.

    ``httpx.AsyncClient`` cannot be interrupted inside its constructor, so the
    worker keeps running after the await is cancelled and then hands back a live
    client. Nothing can enter the ``async with`` for it, so whoever owns the
    construction task has to close it, and the operation must still end cancelled.
    """
    real_client = httpx.AsyncClient
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    built = []
    sent = []

    def gated_client(*args, **kwargs):
        started.set()
        assert release.wait(10), "the constructor was never released"
        client = real_client(*args, **kwargs)
        built.append(client)
        finished.set()
        return client

    async def send(self, request, **kwargs):
        sent.append(request.url)
        return httpx.Response(200, request=request, text="unreachable")

    monkeypatch.setattr(httpx, "AsyncClient", gated_client)
    monkeypatch.setattr(real_client, "send", send)

    client = BrowserlessClient("https://browserless.example", token="token")
    if operation == "capture_screenshot":
        pending = asyncio.ensure_future(client.capture_screenshot("https://example.com"))
    else:
        pending = asyncio.ensure_future(client.fetch_html_with_status("https://example.com"))

    assert await asyncio.to_thread(started.wait, 10), "the constructor never started"
    # The operation is suspended on the constructor now, so the cancellation lands
    # there and never reaches the request: release the worker only afterwards.
    pending.cancel()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    release.set()

    with pytest.raises(asyncio.CancelledError):
        await pending

    # The worker thread cannot be stopped, so wait for it before judging what it
    # built; a leaked client is only visible once the constructor has returned.
    assert await asyncio.to_thread(finished.wait, 10), "the constructor never finished"

    assert sent == [], "a cancelled construction must not send a request"
    assert len(built) == 1
    assert built[0].is_closed, "the client built after the cancellation was leaked"
