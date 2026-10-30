"""Keep real HTTPX TLS setup; replace only the network response."""

import asyncio
import ssl

import httpx
import pytest

from deerflow.community.lightrag.client import LightRAGClient
from deerflow.community.ragflow.client import RAGFlowClient


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["ragflow", "lightrag"])
async def test_retrieval_client_loads_tls_trust_off_loop(provider, monkeypatch):
    original = ssl.create_default_context
    contexts = []
    clients = []

    def ssl_context(*args, **kwargs):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            context = original(*args, **kwargs)
            contexts.append(context)
            return context
        raise AssertionError("TLS trust loading must run off the event loop")

    async def send(self, request, **kwargs):
        clients.append(self)
        if provider == "ragflow":
            assert request.url.path == "/api/v1/datasets"
            assert request.url.params["ids"] == "synthetic-dataset"
            assert request.headers["Authorization"] == "Bearer synthetic-key"
            payload = {"code": 0, "data": [{"id": "synthetic-dataset"}]}
        else:
            assert request.url.path == "/query/data"
            assert request.headers["X-API-Key"] == "synthetic-key"
            payload = {"status": "success", "data": {"chunks": []}}
        return httpx.Response(200, request=request, json=payload)

    monkeypatch.setattr(ssl, "create_default_context", ssl_context)
    monkeypatch.setattr(httpx.AsyncClient, "send", send)
    if provider == "ragflow":
        client = RAGFlowClient(base_url="https://ragflow.invalid", api_key="synthetic-key")
        assert await client.list_datasets(dataset_id="synthetic-dataset") == [{"id": "synthetic-dataset"}]
    else:
        client = LightRAGClient(base_url="https://lightrag.invalid", api_key="synthetic-key")
        assert await client.query_data("synthetic query") == {"chunks": []}
    assert contexts
    assert len(clients) == 1
    assert clients[0].is_closed
