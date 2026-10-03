"""Offline coverage for Anthropic async transports across native event loops."""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Iterator
from contextvars import copy_context
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import anthropic
import pytest
from langchain_anthropic import ChatAnthropic
from langchain_core.callbacks import AsyncCallbackHandler

from deerflow.config.app_config import AppConfig
from deerflow.config.model_config import ModelConfig
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.models import factory as factory_module
from deerflow.models.factory import create_chat_model


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.ports: list[int] = []
        self.closed = 0
        self.condition = threading.Condition()
        self.stream_started = threading.Event()
        self.finish_stream = threading.Event()

    def wait_closed(self, count: int) -> bool:
        with self.condition:
            return self.condition.wait_for(lambda: self.closed >= count, timeout=5)


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def handle(self) -> None:
        try:
            super().handle()
        finally:
            with self.server.condition:  # type: ignore[attr-defined]
                self.server.closed += 1  # type: ignore[attr-defined]
                self.server.condition.notify_all()  # type: ignore[attr-defined]

    def do_POST(self) -> None:
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        assert self.path == "/v1/messages"
        assert self.headers["x-api-key"] == "loopback-test-key"
        assert self.headers["x-loop-fixture"] == "present"
        self.server.ports.append(self.client_address[1])  # type: ignore[attr-defined]
        if request.get("stream"):
            self._stream()
        elif request["messages"][0]["content"] == "trigger-error":
            self._json(400, {"type": "error", "error": {"type": "invalid_request_error", "message": "fixture"}})
        else:
            self._json(200, _MESSAGE)

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _stream(self) -> None:
        events = [
            ("message_start", {"type": "message_start", "message": _MESSAGE | {"content": [], "stop_reason": None, "usage": {"input_tokens": 1, "output_tokens": 0}}}),
            ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}),
            ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "ok"}}),
            ("content_block_stop", {"type": "content_block_stop", "index": 0}),
            ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None}, "usage": {"output_tokens": 1}}),
            ("message_stop", {"type": "message_stop"}),
        ]
        body = b"".join(f"event: {name}\ndata: {json.dumps(event)}\n\n".encode() for name, event in events)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        try:
            self.wfile.write(f"{len(body):X}\r\n".encode() + body + b"\r\n")
            self.wfile.flush()
            self.server.stream_started.set()  # type: ignore[attr-defined]
            self.server.finish_stream.wait(timeout=10)  # type: ignore[attr-defined]
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
        except OSError:
            pass

    def log_message(self, _format: str, *args: object) -> None:
        return


_MESSAGE = {
    "id": "msg_loop_fixture",
    "type": "message",
    "role": "assistant",
    "content": [{"type": "text", "text": "ok"}],
    "model": "claude-loop-fixture",
    "stop_reason": "end_turn",
    "stop_sequence": None,
    "usage": {"input_tokens": 1, "output_tokens": 1},
}


@pytest.fixture
def local_server() -> Iterator[tuple[_Server, str]]:
    server = _Server()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, f"http://127.0.0.1:{server.server_port}"
    finally:
        server.finish_stream.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)


def _model(url: str | None, use: str = "langchain_anthropic:ChatAnthropic", timeout: float | None = 5, proxy: str | None = None):
    config = AppConfig(
        models=[
            ModelConfig(
                name="fixture",
                use=use,
                model="claude-loop-fixture",
                anthropic_api_key="loopback-test-key",
                anthropic_api_url=url,
                default_request_timeout=timeout,
                anthropic_proxy=proxy,
                default_headers={"x-loop-fixture": "present"},
                max_retries=0,
            )
        ],
        sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"),
    )
    return create_chat_model("fixture", app_config=config, attach_tracing=False)


@pytest.mark.parametrize("use", ["langchain_anthropic:ChatAnthropic", "langchain_anthropic.chat_models:ChatAnthropic"])
def test_official_anthropic_imports_are_safe_across_native_event_loops(local_server, use: str) -> None:
    server, url = local_server
    first_done, release_first = threading.Event(), threading.Event()
    results: list[tuple[str, int] | Exception] = []

    def invoke() -> tuple[str, int]:
        async def run() -> str:
            return str((await _model(url, use=use).ainvoke("ping")).content)

        return asyncio.run(run()), threading.get_ident()

    def first_thread() -> None:
        try:
            results.append(invoke())
        except Exception as exc:
            results.append(exc)
        first_done.set()
        release_first.wait(timeout=10)

    thread = threading.Thread(target=first_thread)
    thread.start()
    assert first_done.wait(timeout=10), "first loop did not finish"
    try:
        assert isinstance(results[0], tuple), f"first loop failed: {results[0]!r}"
        second = invoke()
        first = results[0]
        assert first[0] == second[0] == "ok"
        assert first[1] != second[1]
        assert len(server.ports) == 2 and len(set(server.ports)) == 2
        assert server.wait_closed(2), "completed invocations should close both sockets"
    finally:
        release_first.set()
        thread.join(timeout=10)


def test_sync_invocation_is_unchanged(local_server) -> None:
    server, url = local_server
    assert _model(url).invoke("ping").content == "ok"
    assert len(server.ports) == 1


def test_async_client_closes_after_error(local_server) -> None:
    server, url = local_server

    async def run() -> None:
        with pytest.raises(anthropic.BadRequestError):
            await _model(url).ainvoke("trigger-error")

    asyncio.run(run())
    assert len(server.ports) == 1 and server.wait_closed(1)


def test_public_stream_closes_when_finalized_in_another_task(local_server) -> None:
    server, url = local_server

    async def run() -> None:
        stream = _model(url).astream("ping")
        first_chunk = await asyncio.create_task(anext(stream))
        while first_chunk.content != "ok":
            first_chunk = await asyncio.create_task(anext(stream))
        await asyncio.create_task(stream.aclose())

    asyncio.run(run())
    server.finish_stream.set()
    assert server.stream_started.is_set()
    assert len(server.ports) == 1 and server.wait_closed(1)


def test_ainvoke_stream_callback_path_closes_owned_transport_on_cancel(local_server) -> None:
    server, url = local_server

    async def run() -> None:
        request = asyncio.create_task(_model(url).ainvoke("ping", stream=True))
        assert await asyncio.to_thread(server.stream_started.wait, 5)
        request.cancel()
        with pytest.raises(asyncio.CancelledError):
            await request
        server.finish_stream.set()
        assert await asyncio.to_thread(server.wait_closed, 1)

    asyncio.run(run())
    assert len(server.ports) == 1


def test_ainvoke_stream_callback_path_closes_owned_transport_on_success(local_server) -> None:
    server, url = local_server
    server.finish_stream.set()

    response = asyncio.run(_model(url).ainvoke("ping", stream=True))

    assert response.content == "ok"
    assert len(server.ports) == 1 and server.wait_closed(1)


class _BlockingStreamingCallback(AsyncCallbackHandler):
    def __init__(self) -> None:
        self.started = threading.Event()

    async def on_llm_new_token(self, token: str, **kwargs: Any) -> None:
        self.started.set()
        await asyncio.Future()


def test_ainvoke_stream_callback_cancellation_closes_abandoned_internal_stream(local_server) -> None:
    server, url = local_server
    callback = _BlockingStreamingCallback()

    async def run() -> None:
        request = asyncio.create_task(_model(url).ainvoke("ping", config={"callbacks": [callback]}, stream=True))
        assert await asyncio.to_thread(callback.started.wait, 5)
        request.cancel()
        with pytest.raises(asyncio.CancelledError):
            await request
        server.finish_stream.set()
        assert await asyncio.to_thread(server.wait_closed, 1)

    asyncio.run(run())
    assert len(server.ports) == 1


class _CustomAnthropicModel(ChatAnthropic):
    pass


def test_factory_does_not_wrap_custom_anthropic_subclasses(local_server, monkeypatch) -> None:
    _, url = local_server
    monkeypatch.setattr(factory_module, "resolve_class", lambda *_: _CustomAnthropicModel)
    assert type(_model(url, use="custom_provider:CustomAnthropicModel")) is _CustomAnthropicModel


def test_copied_context_gets_a_transport_owned_by_its_async_task(local_server) -> None:
    server, url = local_server
    child_result: list[object] = []

    async def parent() -> None:
        model = _model(url)
        async with model._async_client_scope():
            assert (await model.ainvoke("parent loop")).content == "ok"
            parent_client = model._async_client
            context = copy_context()

            def child_thread() -> None:
                try:
                    child_result.append(context.run(lambda: asyncio.run(model.ainvoke("copied context")).content))
                except Exception as exc:
                    child_result.append(exc)

            thread = threading.Thread(target=child_thread)
            thread.start()
            await asyncio.to_thread(thread.join, 10)
            assert not thread.is_alive()
            assert child_result == ["ok"]
            assert model._async_client is parent_client
        assert server.wait_closed(2)
        assert len(server.ports) == 2 and len(set(server.ports)) == 2

    asyncio.run(parent())


def test_async_client_keeps_default_url_and_none_timeout(monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    model = _model(None, timeout=None)
    params = dict(model._client_params)
    params["base_url"] = None
    model.__dict__["_client_params"] = params

    async def inspect_client() -> None:
        async with model._async_client_scope():
            client = model._async_client
            assert str(client.base_url).rstrip("/") == "https://api.anthropic.com"
            assert all(getattr(client._client.timeout, field) is None for field in ("connect", "read", "write", "pool"))
            assert client.max_retries == 0

    asyncio.run(inspect_client())


def test_anthropic_proxy_and_provider_options_reach_sdk_client(local_server, monkeypatch) -> None:
    _, url = local_server
    proxy = "http://127.0.0.1:9"
    model = _model(url, timeout=3, proxy=proxy)
    captured: dict[str, Any] = {}

    class FakeSDKClient:
        def __init__(self, **kwargs: Any) -> None:
            captured["client"] = kwargs
            self.closed = False

        async def close(self) -> None:
            self.closed = True

    def make_http_client(**kwargs: Any) -> object:
        captured["transport"] = kwargs
        return object()

    from deerflow.models import anthropic_provider

    monkeypatch.setattr(anthropic_provider.anthropic, "DefaultAsyncHttpxClient", make_http_client)
    monkeypatch.setattr(anthropic_provider.anthropic, "AsyncClient", FakeSDKClient)

    async def run() -> FakeSDKClient:
        async with model._async_client_scope():
            return model._async_client

    sdk_client = asyncio.run(run())
    assert captured["transport"] == {"base_url": url, "timeout": 3, "proxy": proxy}
    params = captured["client"]
    assert params["api_key"] == "loopback-test-key"
    assert params["base_url"] == url and params["timeout"] == 3 and params["max_retries"] == 0
    assert params["default_headers"]["x-loop-fixture"] == "present"
    assert sdk_client.closed
