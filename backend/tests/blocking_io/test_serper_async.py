"""Serper setup and retry waits must stay off the agent event loop."""

import json
from types import SimpleNamespace

import httpx
import pytest

from deerflow.community.serper import tools


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["web_search", "image_search"])
async def test_async_serper_setup_and_backoff_are_nonblocking(name, tmp_path, monkeypatch):
    # Fixture file creation is explicitly off-loop; the real read below remains
    # under the strict detector so bypassing the setup offload is caught.
    import asyncio

    fixture = tmp_path / "setup.txt"
    await asyncio.to_thread(fixture.write_text, "fixture", encoding="utf8")
    reads = []
    clients = []
    requests = []
    real_client = httpx.AsyncClient

    def config():
        assert fixture.read_text(encoding="utf8") == "fixture"
        reads.append("config")
        return SimpleNamespace(get_tool_config=lambda _: SimpleNamespace(model_extra={"api_key": "fixture-key", "max_retries": 1}))

    async def handle(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"organic": [{"link": "https://example.com/a"}], "images": [{"imageUrl": "https://example.com/a.png"}]})

    def create(**kwargs):
        assert fixture.read_text(encoding="utf8") == "fixture"
        reads.append("client")
        client = real_client(transport=httpx.MockTransport(handle), trust_env=False, **kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr(tools, "get_app_config", config)
    monkeypatch.setattr(tools.httpx, "AsyncClient", create)
    monkeypatch.setattr(tools.httpx, "Client", lambda **_: pytest.fail("Async call used sync HTTP"))
    monkeypatch.setattr(tools.random, "uniform", lambda low, high: low)
    result = json.loads(await getattr(tools, name + "_tool").ainvoke({"query": "probe"}))
    assert "error" not in result
    assert reads == ["config", "client"]
    assert len(requests) == 2
    assert len(clients) == 1 and clients[0].is_closed
