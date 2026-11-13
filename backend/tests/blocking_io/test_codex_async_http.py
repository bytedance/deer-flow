"""Codex async requests load TLS trust outside the event loop."""

import json

import httpx
import pytest

from deerflow.models import openai_codex_provider as provider
from deerflow.models.credential_loader import CodexCliCredential


@pytest.mark.asyncio
async def test_codex_async_http_with_real_tls_setup(monkeypatch):
    monkeypatch.setattr(provider, "load_codex_cli_credential", lambda: CodexCliCredential("synthetic-token", "synthetic-account"))
    model = provider.CodexChatModel(retry_max_attempts=1)
    client_class = httpx.AsyncClient
    clients = []

    def respond(request):
        event = {"type": "response.completed", "response": {"output": [{"type": "message", "content": [{"type": "output_text", "text": "OK"}]}]}}
        return httpx.Response(200, text=f"data: {json.dumps(event)}\n\n")

    def client(**kwargs):
        instance = client_class(transport=httpx.MockTransport(respond), **kwargs)
        clients.append(instance)
        return instance

    monkeypatch.setattr(provider.httpx, "AsyncClient", client)
    result = await model.ainvoke("Synthetic nonblocking request")
    assert result.content == "OK"
    assert len(clients) == 1
    assert clients[0].is_closed
