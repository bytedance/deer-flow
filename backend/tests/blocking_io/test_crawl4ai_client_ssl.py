"""Crawl4AI's HTTPX client must load TLS trust off the agent event loop."""

import ssl
import threading

import httpx
import pytest

from deerflow.community.crawl4ai.crawl4ai_client import Crawl4AiClient


@pytest.mark.asyncio
async def test_crawl4ai_client_tls_setup_runs_off_loop(monkeypatch):
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
        assert request.url.host == "crawl4ai.example"
        assert request.url.path == "/md"
        return httpx.Response(200, request=request, json={"success": True, "markdown": "synthetic page"})

    monkeypatch.setattr(ssl, "create_default_context", create_context)
    monkeypatch.setattr(httpx.AsyncClient, "send", send)

    client = Crawl4AiClient("https://crawl4ai.example")
    result = await client.fetch_markdown("https://example.com")

    assert result == "synthetic page"
    assert contexts
    assert len(clients) == 1
    assert clients[0].is_closed
