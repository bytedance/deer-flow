"""Socket-level SSE delivery through a controlled gzip intermediary.

The proxy compresses eligible responses without a sync flush until EOF, and
honors no-transform. This models a buffering compressor, not every deployment.
"""

from __future__ import annotations

import asyncio
import socket
import zlib
from contextlib import asynccontextmanager, suppress

import httpx
import pytest
import uvicorn
from starlette.types import ASGIApp, Receive, Scope, Send
from test_sse_response_headers import _make_app

from app.gateway.services import SSE_RESPONSE_HEADERS
from deerflow.runtime.stream_bridge.memory import MemoryStreamBridge


@asynccontextmanager
async def _serve(app: ASGIApp):
    ready = asyncio.Event()

    class Server(uvicorn.Server):
        async def startup(self, sockets=None):
            await super().startup(sockets=sockets)
            ready.set()

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        server = Server(uvicorn.Config(app, lifespan="off", log_level="error", timeout_graceful_shutdown=1))
        task = asyncio.create_task(server.serve(sockets=[sock]))
        try:
            await asyncio.wait_for(ready.wait(), timeout=10)
            yield f"http://127.0.0.1:{sock.getsockname()[1]}"
        finally:
            server.should_exit = True
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=5)
            finally:
                if not task.done():
                    task.cancel()
                with suppress(asyncio.CancelledError):
                    await task


class _GzipProxy:
    def __init__(self, upstream: str):
        self.upstream = upstream
        self.saw_body = asyncio.Event()

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        # Only the GET join route is exercised. Connection/transfer headers are
        # deliberately terminated here rather than copied to the next hop.
        async with httpx.AsyncClient(trust_env=False, timeout=10) as client:
            async with client.stream("GET", self.upstream + scope["path"], headers={"Accept-Encoding": "identity"}) as response:
                directives = {value.strip().lower() for value in response.headers.get("cache-control", "").split(",")}
                compressor = None if "no-transform" in directives else zlib.compressobj(wbits=31)
                headers = [(b"content-type", response.headers["content-type"].encode())]
                if compressor is not None:
                    headers.append((b"content-encoding", b"gzip"))
                await send({"type": "http.response.start", "status": response.status_code, "headers": headers})
                async for chunk in response.aiter_raw():
                    body = chunk if compressor is None else compressor.compress(chunk)
                    await send({"type": "http.response.body", "body": body, "more_body": True})
                    self.saw_body.set()
                tail = b"" if compressor is None else compressor.flush()
                await send({"type": "http.response.body", "body": tail, "more_body": False})


async def _next_frame(lines):
    frame = []
    async for line in lines:
        if not line:
            if frame:
                return "\n".join(frame)
        else:
            frame.append(line)
    raise AssertionError("SSE ended before a complete frame arrived")


@pytest.mark.asyncio
@pytest.mark.parametrize("allow_transform", [False, True], ids=["no-transform", "gzip-control"])
async def test_sse_frame_arrives_before_end_through_gzip_proxy(monkeypatch, allow_transform):
    if allow_transform:
        monkeypatch.setitem(SSE_RESPONSE_HEADERS, "Cache-Control", "no-cache")
    app = _make_app(monkeypatch)
    bridge = MemoryStreamBridge()
    app.state.stream_bridge = bridge
    release_tail = asyncio.Event()
    finished = asyncio.Event()

    async def produce():
        await bridge.publish("run-1", "updates", {"text": "first"})
        await release_tail.wait()
        await bridge.publish("run-1", "updates", {"text": "second"})
        await bridge.publish("run-1", "updates", {"text": "third"})
        await bridge.publish_end("run-1")
        finished.set()

    producer = asyncio.create_task(produce())
    first = None
    try:
        async with _serve(app) as origin:
            proxy = _GzipProxy(origin)
            async with _serve(proxy) as endpoint:
                async with httpx.AsyncClient(trust_env=False, timeout=10) as client:
                    async with client.stream("GET", endpoint + "/api/threads/thread-1/runs/run-1/join") as response:
                        assert response.status_code == 200
                        assert response.headers["content-type"].startswith("text/event-stream")
                        lines = response.aiter_lines()
                        first = asyncio.create_task(_next_frame(lines))
                        try:
                            await asyncio.wait_for(proxy.saw_body.wait(), timeout=5)
                            if allow_transform:
                                assert response.headers["content-encoding"] == "gzip"
                                # The origin has sent a frame and the proxy has
                                # consumed it, but gzip has not flushed it.
                                with pytest.raises(TimeoutError):
                                    await asyncio.wait_for(asyncio.shield(first), timeout=0.2)
                                assert not finished.is_set()
                            else:
                                frame = await asyncio.wait_for(asyncio.shield(first), timeout=5)
                                assert '"text": "first"' in frame
                                assert not finished.is_set()
                                assert "content-encoding" not in response.headers
                            release_tail.set()
                            frames = [await asyncio.wait_for(first, timeout=5)]
                            frames.extend([await _next_frame(lines) for _ in range(3)])
                            for value, frame in zip(["first", "second", "third"], frames[:3], strict=True):
                                assert f'"text": "{value}"' in frame
                            assert all("event: updates" in frame for frame in frames[:3])
                            assert "event: end" in frames[3]
                            assert [line async for line in lines] == []
                            assert finished.is_set()
                        finally:
                            release_tail.set()
                            if first is not None and not first.done():
                                first.cancel()
                                with suppress(asyncio.CancelledError):
                                    await first
    finally:
        release_tail.set()
        await producer
