"""Personal MCP clients must load TLS trust off the Gateway event loop."""

import asyncio
import ssl
import threading

import httpx
import pytest

from deerflow.mcp.personal_network import personal_httpx_client_factory


@pytest.mark.asyncio
@pytest.mark.parametrize("concurrent", [False, True])
async def test_personal_mcp_tls_setup_runs_off_loop(monkeypatch, concurrent):
    loop_thread = threading.get_ident()
    original_context = ssl.create_default_context
    contexts = []
    requests = []

    def create_context(*args, **kwargs):
        assert threading.get_ident() != loop_thread, "TLS trust loading blocks the event loop"
        context = original_context(*args, **kwargs)
        contexts.append(context)
        return context

    async def send(self, request):
        assert threading.get_ident() == loop_thread
        requests.append((self, request))
        return httpx.Response(200, request=request, content=b"ok")

    monkeypatch.setattr(ssl, "create_default_context", create_context)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", send)
    monkeypatch.setenv("SSL_CERT_FILE", "/missing-personal-mcp-test.pem")
    async with personal_httpx_client_factory(headers={"Authorization": "Bearer synthetic"}) as client:
        urls = ["https://8.8.8.8/first", "https://1.1.1.1/second", "https://8.8.8.8/third"]
        responses = await asyncio.gather(*(client.get(url) for url in urls)) if concurrent else [await client.get(url) for url in urls]
        assert all(response.text == "ok" for response in responses)
    assert client.is_closed
    assert len(contexts) == 1
    assert contexts[0].check_hostname
    assert contexts[0].verify_mode == ssl.CERT_REQUIRED
    by_path = {request.url.path: transport for transport, request in requests}
    assert by_path["/first"] is by_path["/third"]
    assert by_path["/first"] is not by_path["/second"]
    assert all(request.headers["Authorization"] == "Bearer synthetic" for _, request in requests)


@pytest.mark.asyncio
async def test_personal_mcp_tls_setup_failure_can_be_retried(monkeypatch):
    original_context = ssl.create_default_context
    attempts = []
    requests = []

    def create_context(*args, **kwargs):
        attempts.append(True)
        if len(attempts) == 1:
            raise OSError("TLS trust unavailable")
        return original_context(*args, **kwargs)

    async def send(self, request):
        requests.append(request)
        return httpx.Response(200, request=request, content=b"ok")

    monkeypatch.setattr(ssl, "create_default_context", create_context)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", send)
    async with personal_httpx_client_factory() as client:
        with pytest.raises(OSError, match="TLS trust unavailable"):
            await client.get("https://8.8.8.8/mcp")
        assert not requests
        for _ in range(2):
            assert (await client.get("https://8.8.8.8/mcp")).text == "ok"
    assert len(attempts) == 2
    assert len(requests) == 2
    assert client.is_closed
