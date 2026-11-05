"""Browserless must load HTTPX TLS trust off the agent event loop."""

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
