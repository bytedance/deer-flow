"""Olostep community tools must not occupy an executor thread or block the loop.

* The request is awaited on the event loop thread, so no pool thread is held
  for the network round trip.
* The config lookup, which reads the config file, and the client construction,
  which loads the TLS trust store, run off the loop.
* The request goes out through the async client. A ``MockTransport`` runs its
  handler on the calling thread, so a provider that sent the request through a
  sync ``httpx.Client`` would pass the thread assertion; the recorded client
  factory catches that.
"""

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
