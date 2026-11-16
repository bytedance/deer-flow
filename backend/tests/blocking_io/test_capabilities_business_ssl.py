"""The bundled business tools must load HTTPX TLS trust off the MCP event loop."""

import ssl
import threading

import httpx
import pytest

from deerflow.capabilities.business import BusinessClient

DINGTALK = {"access_token": "token", "sign_secret": "secret"}
HUBSPOT = {"access_token": "token"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider,credentials,call,expected_path",
    [
        ("dingtalk", DINGTALK, "send_message", "/robot/send"),
        ("hubspot", HUBSPOT, "get_companies", "/crm/v3/objects/companies"),
    ],
)
async def test_business_client_tls_setup_runs_off_loop(provider, credentials, call, expected_path, monkeypatch):
    loop_thread = threading.get_ident()
    original_context = ssl.create_default_context
    contexts = []
    clients = []

    def create_context(*args, **kwargs):
        assert threading.get_ident() != loop_thread, "TLS trust loading blocks the MCP event loop"
        context = original_context(*args, **kwargs)
        contexts.append(context)
        return context

    async def send(self, request, **kwargs):
        assert threading.get_ident() == loop_thread
        clients.append(self)
        assert request.url.path == expected_path
        payload = {"errcode": 0, "errmsg": "ok"} if provider == "dingtalk" else {"results": []}
        return httpx.Response(200, request=request, json=payload)

    monkeypatch.setattr(ssl, "create_default_context", create_context)
    monkeypatch.setattr(httpx.AsyncClient, "send", send)

    client = BusinessClient(provider, credentials)
    if call == "send_message":
        assert await client.send_message("synthetic notification") == {"sent": True}
    else:
        assert (await client.get_companies())["companies"] == []

    assert len(contexts) == 1
    assert len(clients) == 1
    assert clients[0].is_closed
