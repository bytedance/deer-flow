"""Exercise real HTTPX/SSL construction with only the network response replaced."""

import asyncio
import ssl
from pathlib import Path

import httpx
import pytest


@pytest.fixture
def weknora_provider(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / "examples/deerflow-extension-weknora"))
    from deerflow_extension_weknora import WeKnoraProvider

    monkeypatch.setenv("WEKNORA_BLOCKING_TEST_KEY", "synthetic")
    return WeKnoraProvider({"spaces": [{"base_url": "https://weknora.invalid", "tenant_id": "1", "api_key_env": "WEKNORA_BLOCKING_TEST_KEY", "user_ids": ["alice"]}]})


@pytest.mark.asyncio
async def test_weknora_ssl_setup_is_off_loop(weknora_provider, monkeypatch):
    from deerflow.knowledge import KnowledgeRequestContext

    async def send(self, request, **kwargs):
        assert request.headers["X-Tenant-ID"] == "1"
        return httpx.Response(200, request=request, json={"success": True, "data": [{"id": "kb", "name": "Synthetic"}]})

    original = ssl.create_default_context

    def ssl_context(*args, **kwargs):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return original(*args, **kwargs)
        raise AssertionError("SSL trust loading must run off the event loop")

    monkeypatch.setattr(ssl, "create_default_context", ssl_context)
    monkeypatch.setattr(httpx.AsyncClient, "send", send)
    catalog = await weknora_provider.catalog(context=KnowledgeRequestContext("alice", "lead_agent"), page=1, page_size=20, search="")
    assert catalog.items[0].name == "Synthetic"
