"""Async invocation must not hold an executor worker during WSA network I/O."""

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock


def test_slow_search_leaves_default_executor_available(monkeypatch):
    import deerflow.community.tencent_wsa.tools as wsa

    config = MagicMock()
    config.get_tool_config.return_value.model_extra = {"api_key": "test-key"}
    monkeypatch.setattr(wsa, "get_app_config", lambda: config)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")

    async def scenario():
        loop = asyncio.get_running_loop()
        loop.set_default_executor(ThreadPoolExecutor(max_workers=1))
        received = asyncio.Event()
        release = asyncio.Event()
        handlers = []

        async def handle(reader, writer):
            handlers.append(asyncio.current_task())
            try:
                headers = await reader.readuntil(b"\r\n\r\n")
                length = next(int(line.split(b":", 1)[1]) for line in headers.split(b"\r\n") if line.lower().startswith(b"content-length:"))
                await reader.readexactly(length)
                received.set()
                await release.wait()
                body = json.dumps({"Response": {"Pages": [{"title": "Example", "url": "https://example.com"}]}}).encode()
                writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\nContent-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body)
                await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()

        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        monkeypatch.setattr(wsa, "_SEARCH_ENDPOINT", f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}/search")
        search = asyncio.create_task(wsa.web_search_tool.ainvoke({"query": "example"}))
        fast = None
        try:
            await asyncio.wait_for(received.wait(), timeout=5)
            fast = asyncio.create_task(asyncio.to_thread(lambda: "available"))
            # The response stays parked until cleanup. This is a deadlock guard,
            # not a production latency or performance assertion.
            assert await asyncio.wait_for(asyncio.shield(fast), timeout=5) == "available"
        finally:
            release.set()
            try:
                result = await asyncio.wait_for(search, timeout=5)
            finally:
                server.close()
                await server.wait_closed()
                if fast is not None:
                    await asyncio.wait_for(fast, timeout=5)
                await asyncio.gather(*handlers)
        assert json.loads(result)["total_results"] == 1

    asyncio.run(scenario())


def test_async_config_lookup_preserves_context_off_loop(monkeypatch):
    from contextvars import ContextVar
    from threading import get_ident

    import httpx

    import deerflow.community.tencent_wsa.tools as wsa

    marker = ContextVar("wsa_test_marker")
    marker.set("request-context")
    loop_thread = get_ident()
    observed = []

    def get_config():
        observed.append((get_ident(), marker.get()))
        config = MagicMock()
        config.get_tool_config.return_value.model_extra = {"api_key": "test-key"}
        return config

    client_class = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"Response": {"Pages": []}}))
    monkeypatch.setattr(wsa, "get_app_config", get_config)
    monkeypatch.setattr(wsa.httpx, "AsyncClient", lambda **kwargs: client_class(transport=transport, **kwargs))
    asyncio.run(wsa.web_search_tool.ainvoke({"query": "example"}))
    assert len(observed) == 1
    assert observed[0][0] != loop_thread
    assert observed[0][1] == "request-context"


def test_cancellation_closes_async_client(monkeypatch):
    import httpx
    import pytest

    import deerflow.community.tencent_wsa.tools as wsa

    config = MagicMock()
    config.get_tool_config.return_value.model_extra = {"api_key": "test-key"}
    monkeypatch.setattr(wsa, "get_app_config", lambda: config)
    clients = []
    client_class = httpx.AsyncClient

    async def scenario():
        started = asyncio.Event()

        async def respond(request):
            started.set()
            await asyncio.Future()

        def make_client(**kwargs):
            client = client_class(transport=httpx.MockTransport(respond), **kwargs)
            clients.append(client)
            return client

        monkeypatch.setattr(wsa.httpx, "AsyncClient", make_client)
        search = asyncio.create_task(wsa.web_search_tool.ainvoke({"query": "example"}))
        try:
            await asyncio.wait_for(started.wait(), timeout=5)
        finally:
            search.cancel()
            with pytest.raises(asyncio.CancelledError):
                await search
        assert len(clients) == 1
        assert clients[0].is_closed

    asyncio.run(scenario())


def test_sync_run_remains_available_inside_running_loop(monkeypatch):
    import deerflow.community.tencent_wsa.tools as wsa

    config = MagicMock()
    config.get_tool_config.return_value.model_extra = {}
    monkeypatch.setattr(wsa, "get_app_config", lambda: config)
    monkeypatch.delenv("TENCENTCLOUD_WSA_APIKEY", raising=False)

    async def scenario():
        result = json.loads(wsa.web_search_tool.run({"query": "example"}))
        assert result == {"error": "TENCENTCLOUD_WSA_APIKEY is not configured", "query": "example"}

    asyncio.run(scenario())
