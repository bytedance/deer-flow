"""Serper async calls keep slow HTTP off the default executor."""

import asyncio
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from contextvars import ContextVar
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import httpx
import pytest

from deerflow.community.serper import tools


@contextmanager
def held_response():
    """Keep a real HTTP response pending until the test releases it."""
    entered = threading.Event()
    release = threading.Event()
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            size = int(self.headers["Content-Length"])
            requests.append((self.path, json.loads(self.rfile.read(size))))
            entered.set()
            if not release.wait(5):
                self.send_error(504)
                return
            body = json.dumps(
                {
                    "organic": [{"title": "Example", "link": "https://example.com/a", "snippet": "fixture"}],
                    "images": [{"title": "Example", "imageUrl": "https://example.com/a.png", "link": "https://example.com/a"}],
                }
            ).encode()
            try:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield SimpleNamespace(url=f"http://127.0.0.1:{server.server_port}", entered=entered, release=release, requests=requests)
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        assert not thread.is_alive()


@pytest.mark.parametrize("name", ["web_search", "image_search"])
def test_slow_http_does_not_starve_default_executor(name, monkeypatch):
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    with held_response() as response:
        config = SimpleNamespace(model_extra={"api_key": "fixture-key", "base_url": response.url})
        monkeypatch.setattr(tools, "get_app_config", lambda: SimpleNamespace(get_tool_config=lambda _: config))

        async def run():
            loop = asyncio.get_running_loop()
            loop.set_default_executor(ThreadPoolExecutor(max_workers=1))
            search = asyncio.create_task(getattr(tools, name + "_tool").ainvoke({"query": "probe"}))
            marker = None
            try:
                # Polling only observes the server's explicit request barrier.
                async with asyncio.timeout(3):
                    while not response.entered.is_set():
                        if search.done():
                            pytest.fail(f"Search returned without reaching HTTP: {search.result()}")
                        await asyncio.sleep(0.005)
                marker = loop.run_in_executor(None, lambda: "unrelated-work")
                try:
                    value = await asyncio.wait_for(asyncio.shield(marker), timeout=0.5)
                except TimeoutError:
                    pytest.fail("Serper HTTP occupied the only default-executor worker")
                assert value == "unrelated-work"
                assert not response.release.is_set()
            finally:
                response.release.set()
                result = json.loads(await asyncio.wait_for(search, timeout=3))
                if marker is not None:
                    await asyncio.wait_for(marker, timeout=3)
            assert "error" not in result
            assert len(response.requests) == 1
            assert response.requests[0][0] == ("/search" if name == "web_search" else "/images")

        asyncio.run(run())


def _response(request):
    return httpx.Response(
        200,
        json={
            "organic": [{"link": "https://example.com/a", "snippet": request.headers["X-API-KEY"]}],
            "images": [{"imageUrl": "https://example.com/a.png"}],
        },
    )


def _install_async_client(monkeypatch, handler, *, transport=None):
    clients = []
    real_client = httpx.AsyncClient

    def create(**kwargs):
        client = real_client(transport=transport or httpx.MockTransport(handler), trust_env=False, **kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr(tools.httpx, "AsyncClient", create)
    monkeypatch.setattr(tools.httpx, "Client", lambda **_: pytest.fail("Async invocation used synchronous HTTP"))
    config = SimpleNamespace(model_extra={"api_key": "fixture-key"})
    monkeypatch.setattr(tools, "get_app_config", lambda: SimpleNamespace(get_tool_config=lambda _: config))
    return clients


@pytest.mark.parametrize("name", ["web_search", "image_search"])
@pytest.mark.parametrize("stage", ["request", "backoff"])
def test_cancellation_closes_client_without_retry(name, stage, monkeypatch):
    async def run():
        entered = asyncio.Event()
        requests = []

        async def handle(request):
            requests.append(request)
            if stage == "backoff":
                return httpx.Response(503)
            entered.set()
            await asyncio.Future()

        async def sleep(_):
            entered.set()
            await asyncio.Future()

        clients = _install_async_client(monkeypatch, handle)
        config = SimpleNamespace(model_extra={"api_key": "fixture-key", "max_retries": 3})
        monkeypatch.setattr(tools, "get_app_config", lambda: SimpleNamespace(get_tool_config=lambda _: config))
        monkeypatch.setattr(tools, "asyncio", SimpleNamespace(**{**vars(asyncio), "sleep": sleep}))
        search = asyncio.create_task(getattr(tools, name + "_tool").ainvoke({"query": "probe"}))
        try:
            await asyncio.wait_for(entered.wait(), timeout=3)
            search.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(search, timeout=3)
            assert len(requests) == 1
            assert len(clients) == 1 and clients[0].is_closed
        finally:
            if not search.done():
                search.cancel()
                await asyncio.gather(search, return_exceptions=True)

    asyncio.run(run())


@pytest.mark.parametrize("creation_fails", [False, True])
def test_repeated_cancellation_during_client_construction_drains_handoff(creation_fails, monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    clients = []
    real_client = httpx.AsyncClient

    def create(**kwargs):
        entered.set()
        assert release.wait(5)
        if creation_fails:
            raise RuntimeError("constructor failed")
        client = real_client(transport=httpx.MockTransport(_response), **kwargs)
        clients.append(client)
        return client

    _install_async_client(monkeypatch, _response)
    monkeypatch.setattr(tools.httpx, "AsyncClient", create)

    async def run():
        search = asyncio.create_task(tools.web_search_tool.ainvoke({"query": "probe"}))
        try:
            async with asyncio.timeout(3):
                while not entered.is_set():
                    await asyncio.sleep(0.005)
            search.cancel()
            await asyncio.sleep(0)
            search.cancel()
            await asyncio.sleep(0)
            assert not search.done(), "Client ownership must be reconciled before cancellation returns"
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(search, timeout=3)
            assert len(clients) == (0 if creation_fails else 1)
            assert all(client.is_closed for client in clients)
        finally:
            release.set()
            await asyncio.gather(search, return_exceptions=True)

    asyncio.run(run())


def test_repeated_cancellation_during_close_drains_transport(monkeypatch):
    async def run():
        closing = asyncio.Event()
        release = asyncio.Event()
        closed = asyncio.Event()

        class Transport(httpx.MockTransport):
            async def aclose(self):
                closing.set()
                await release.wait()
                await super().aclose()
                closed.set()

        clients = _install_async_client(monkeypatch, _response, transport=Transport(_response))
        search = asyncio.create_task(tools.web_search_tool.ainvoke({"query": "probe"}))
        try:
            await asyncio.wait_for(closing.wait(), timeout=3)
            search.cancel()
            await asyncio.sleep(0)
            search.cancel()
            await asyncio.sleep(0)
            assert not search.done()
            assert not closed.is_set()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(search, timeout=3)
            assert closed.is_set()
            assert len(clients) == 1 and clients[0].is_closed
        finally:
            release.set()
            await asyncio.gather(search, return_exceptions=True)

    asyncio.run(run())


def test_previously_handled_cancellation_does_not_cancel_success(monkeypatch):
    clients = _install_async_client(monkeypatch, _response)

    async def run():
        task = asyncio.current_task()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.sleep(0)
        assert task.cancelling()
        data, error = await tools._aserper_post("https://google.serper.dev/search", "fixture-key", "probe", 5)
        assert error is None and data["organic"]
        assert len(clients) == 1 and clients[0].is_closed

    asyncio.run(run())


def test_async_calls_capture_scoped_configuration_off_loop(monkeypatch):
    scoped = ContextVar("serper_test_config")
    reads = []
    requests = []
    main_thread = threading.get_ident()

    def get_config():
        value = scoped.get()
        reads.append((value["api_key"], threading.get_ident()))
        return SimpleNamespace(get_tool_config=lambda _: SimpleNamespace(model_extra=value))

    async def handle(request):
        requests.append(request)
        await asyncio.sleep(0)
        return _response(request)

    clients = _install_async_client(monkeypatch, handle)
    monkeypatch.setattr(tools, "get_app_config", get_config)

    async def call(key):
        token = scoped.set({"api_key": key, "base_url": f"https://{key}.example/api"})
        try:
            return json.loads(await tools.web_search_tool.ainvoke({"query": key}))
        finally:
            scoped.reset(token)

    async def run():
        results = await asyncio.gather(call("first"), call("second"))
        assert {r["query"] for r in results} == {"first", "second"}

    asyncio.run(run())
    assert len(reads) == 2
    assert all(thread_id != main_thread for _, thread_id in reads)
    assert len(requests) == 2
    for request in requests:
        key = request.headers["X-API-KEY"]
        assert str(request.url) == f"https://{key}.example/api/search"
        assert json.loads(request.content)["q"] == key
    assert all(client.is_closed for client in clients)
