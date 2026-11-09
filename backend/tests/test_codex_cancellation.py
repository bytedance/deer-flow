"""Exercise production Codex HTTP ownership with a real loopback SSE peer."""

import asyncio
import json
import threading

import httpx
import pytest
from langchain_core.messages import HumanMessage

from deerflow.models import openai_codex_provider as provider
from deerflow.models.credential_loader import CodexCliCredential


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["headers", "body"])
@pytest.mark.parametrize("api", ["ainvoke", "astream"])
async def test_cancelled_ainvoke_closes_upstream_connection(monkeypatch, phase, api):
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    started = asyncio.Event()
    disconnected = asyncio.Event()
    release = asyncio.Event()
    handlers = set()

    async def handle(reader, writer):
        task = asyncio.current_task()
        handlers.add(task)
        try:
            headers = await reader.readuntil(b"\r\n\r\n")
            size = next(int(line.split(b":", 1)[1]) for line in headers.split(b"\r\n") if line.lower().startswith(b"content-length:"))
            await reader.readexactly(size)
            if phase == "body":
                writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nConnection: close\r\n\r\n")
                writer.write(b'data: {"type":"response.created","response":{"id":"synthetic"}}\n\n')
                await writer.drain()
            started.set()
            # The fixture never completes the model response. Only client EOF
            # can satisfy the assertion, and teardown always releases the peer.
            eof = asyncio.create_task(reader.read())
            done = asyncio.create_task(release.wait())
            try:
                finished, _ = await asyncio.wait({eof, done}, return_when=asyncio.FIRST_COMPLETED)
                if eof in finished and eof.result() == b"":
                    disconnected.set()
            finally:
                eof.cancel()
                done.cancel()
                await asyncio.gather(eof, done, return_exceptions=True)
        finally:
            writer.close()
            await writer.wait_closed()
            handlers.discard(task)

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    monkeypatch.setattr(provider, "CODEX_BASE_URL", f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}")
    monkeypatch.setattr(provider, "load_codex_cli_credential", lambda: CodexCliCredential("synthetic-token", "synthetic-account"))
    model = provider.CodexChatModel(retry_max_attempts=1)

    async def invoke():
        messages = [HumanMessage(content="Synthetic cancellation test")]
        if api == "ainvoke":
            await model.ainvoke(messages)
        else:
            async for _ in model.astream(messages):
                pass

    task = asyncio.create_task(invoke())
    try:
        await asyncio.wait_for(started.wait(), 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.wait_for(disconnected.wait(), 2)
    finally:
        release.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        server.close()
        await server.wait_closed()
        if handlers:
            await asyncio.wait_for(asyncio.gather(*handlers), 5)


@pytest.fixture
def model(monkeypatch):
    monkeypatch.setattr(provider, "load_codex_cli_credential", lambda: CodexCliCredential("synthetic-token", "synthetic-account"))
    return provider.CodexChatModel(retry_max_attempts=3)


@pytest.mark.asyncio
async def test_cancellation_during_retry_closes_response_and_does_not_retry(monkeypatch, model):
    waiting = asyncio.Event()
    calls = []
    responses = []
    clients = []
    client_class = httpx.AsyncClient

    def respond(request):
        calls.append(request)
        response = httpx.Response(429, headers={"Retry-After": "600"}, json={"error": "synthetic"})
        responses.append(response)
        return response

    def create_client(**kwargs):
        client = client_class(transport=httpx.MockTransport(respond), **kwargs)
        clients.append(client)
        return client

    async def sleep(delay):
        assert delay == 600
        assert all(response.is_closed for response in responses)
        assert all(client.is_closed for client in clients)
        waiting.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(provider.httpx, "AsyncClient", create_client)
    monkeypatch.setattr(provider.asyncio, "sleep", sleep)
    task = asyncio.create_task(model.ainvoke("Synthetic retry cancellation"))
    try:
        await asyncio.wait_for(waiting.wait(), 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert len(calls) == 1
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_tls_setup_is_off_loop_and_cancellation_creates_no_client(monkeypatch, model):
    loop = asyncio.get_running_loop()
    started = asyncio.Event()
    finished = asyncio.Event()
    release = threading.Event()
    loop_thread = threading.get_ident()
    real_context = httpx.create_ssl_context

    def context():
        assert threading.get_ident() != loop_thread
        loop.call_soon_threadsafe(started.set)
        try:
            assert release.wait(5)
            return real_context()
        finally:
            loop.call_soon_threadsafe(finished.set)

    def unexpected_client(**kwargs):
        pytest.fail("Cancellation before TLS setup finishes must not create an HTTP client")

    monkeypatch.setattr(provider.httpx, "create_ssl_context", context)
    monkeypatch.setattr(provider.httpx, "AsyncClient", unexpected_client)
    task = asyncio.create_task(model.ainvoke("Synthetic TLS cancellation"))
    try:
        await asyncio.wait_for(started.wait(), 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.wait_for(finished.wait(), 5)


@pytest.mark.asyncio
async def test_repeated_cancellation_drains_client_close(monkeypatch, model):
    closing = asyncio.Event()
    release = asyncio.Event()
    clients = []
    client_class = httpx.AsyncClient

    def respond(request):
        event = {"type": "response.completed", "response": {"output": []}}
        return httpx.Response(200, text=f"data: {json.dumps(event)}\n\n")

    class ClosingClient(client_class):
        async def aclose(self):
            closing.set()
            await release.wait()
            await super().aclose()

    def create_client(**kwargs):
        client = ClosingClient(transport=httpx.MockTransport(respond), **kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr(provider.httpx, "AsyncClient", create_client)
    task = asyncio.create_task(model.ainvoke("Synthetic cleanup cancellation"))
    try:
        await asyncio.wait_for(closing.wait(), 5)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert len(clients) == 1
        assert clients[0].is_closed
    finally:
        release.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
