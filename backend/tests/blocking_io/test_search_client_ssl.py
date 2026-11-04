"""Exercise real search-tool TLS setup while replacing only network responses."""

import json
import ssl
import threading
from types import SimpleNamespace

import httpx
import pytest

from deerflow.community.groundroute import tools as groundroute
from deerflow.community.webz import tools as webz
from deerflow.community.youcom import tools as youcom


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["youcom-keyed", "youcom-keyless", "groundroute-search", "groundroute-fetch", "webz"])
async def test_search_tool_tls_setup_runs_off_loop(provider, monkeypatch):
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
        if provider.startswith("youcom"):
            assert request.url.host == "api.you.com"
            assert request.url.params["count"] == "5"
            if provider == "youcom-keyed":
                assert request.headers["X-API-Key"] == "synthetic-key"
                assert request.url.path == "/v1/search"
            else:
                assert "X-API-Key" not in request.headers
                assert request.url.path == "/v1/agents/search"
            payload = {"results": {"web": [{"url": "https://example.com", "title": "Synthetic", "snippets": ["Synthetic text"]}]}}
        elif provider.startswith("groundroute"):
            assert request.url.host == "api.groundroute.ai"
            assert request.headers["Authorization"] == "Bearer synthetic-key"
            body = json.loads(request.content)
            assert body["max_results"] == (1 if provider.endswith("fetch") else 5)
            payload = {"results": [{"url": "https://example.com", "title": "Synthetic", "snippet": "Synthetic text", "content": "Synthetic text"}]}
        else:
            assert request.url.host == "api.webz.io"
            assert request.headers["Authorization"] == "Bearer synthetic-key"
            assert json.loads(request.content) == {"query": "synthetic query", "k": 5}
            payload = {"results": [{"article": {"url": "https://example.com", "title": "Synthetic", "summary": "Synthetic text"}}]}
        return httpx.Response(200, request=request, json=payload)

    def config():
        key = "" if provider == "youcom-keyless" else "synthetic-key"
        return SimpleNamespace(get_tool_config=lambda _: SimpleNamespace(model_extra={"api_key": key, "max_results": 5}))

    for module in (youcom, groundroute, webz):
        monkeypatch.setattr(module, "get_app_config", config)
    monkeypatch.delenv("YDC_API_KEY", raising=False)
    monkeypatch.setattr(ssl, "create_default_context", create_context)
    monkeypatch.setattr(httpx.AsyncClient, "send", send)
    module = youcom if provider.startswith("youcom") else groundroute if provider.startswith("groundroute") else webz
    tool = module.web_fetch_tool if provider.endswith("fetch") else module.web_search_tool
    result = await tool.ainvoke({"url": "https://example.com"} if provider.endswith("fetch") else {"query": "synthetic query"})
    assert "Synthetic text" in result
    assert contexts
    assert len(clients) == 1
    assert clients[0].is_closed
