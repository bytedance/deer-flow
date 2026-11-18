"""Loopback peers for exercising SDK transports at the socket boundary.

Both run on the calling test's event loop and only ever bind ``127.0.0.1:0``.

- ``StalledWebSocketServer`` completes the WebSocket opening handshake, then
  reads and discards every frame without answering, so a client's close
  handshake never gets its ACK. ``closed`` is set once the peer observes EOF,
  i.e. once the client actually released the TCP connection.
- ``LocalHttpServer`` answers every request with a fixed status and JSON body,
  or (``stall=True``) accepts the connection and never responds. Each request
  body is recorded so tests can assert on what the SDK sent, and ``calls``
  keeps each request's method, path and headers (names lowercased).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from collections.abc import Callable
from typing import Any

_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


async def wait_until(predicate: Callable[[], Any], *, timeout: float = 5.0, interval: float = 0.01) -> Any:
    """Poll ``predicate`` (which may read another thread's state) until it is truthy."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        value = predicate()
        if value:
            return value
        if loop.time() >= deadline:
            raise TimeoutError("condition not met in time")
        await asyncio.sleep(interval)


def transport_socket(connection: Any) -> Any:
    """The socket object under a ``websockets`` connection, for release checks after stop."""
    return connection.transport.get_extra_info("socket")


def _header(request: bytes, name: str) -> str:
    prefix = name.lower() + ":"
    for line in request.decode("latin-1").split("\r\n"):
        if line.lower().startswith(prefix):
            return line.split(":", 1)[1].strip()
    return ""


class StalledWebSocketServer:
    def __init__(self) -> None:
        self.accepted = asyncio.Event()
        self.closed = asyncio.Event()
        self.port = 0
        self._server: asyncio.base_events.Server | None = None

    async def __aenter__(self) -> StalledWebSocketServer:
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        assert self._server is not None
        self._server.close()
        try:
            await asyncio.wait_for(self._server.wait_closed(), timeout=5)
        except TimeoutError:
            pass

    @property
    def url(self) -> str:
        return f"ws://127.0.0.1:{self.port}/"

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            request = await reader.readuntil(b"\r\n\r\n")
            key = _header(request, "Sec-WebSocket-Key")
            accept = base64.b64encode(hashlib.sha1((key + _WS_GUID).encode("ascii")).digest()).decode("ascii")
            writer.write(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n" + f"Sec-WebSocket-Accept: {accept}\r\n\r\n").encode("ascii"))
            await writer.drain()
            self.accepted.set()
            while await reader.read(65536):
                pass  # swallow pings, data and the close frame; never answer
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            self.closed.set()
            writer.close()


class LocalHttpServer:
    def __init__(self, *, status: int = 200, body: Any = None, stall: bool = False) -> None:
        self.status = status
        self.body = body if body is not None else {}
        self.stall = stall
        self.requests: list[dict[str, Any]] = []
        self.calls: list[tuple[str, str, dict[str, str]]] = []
        self.accepted = asyncio.Event()
        self.closed = asyncio.Event()
        self.port = 0
        self._server: asyncio.base_events.Server | None = None

    async def __aenter__(self) -> LocalHttpServer:
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        assert self._server is not None
        self._server.close()
        try:
            await asyncio.wait_for(self._server.wait_closed(), timeout=5)
        except TimeoutError:
            pass

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/open"

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            head = await reader.readuntil(b"\r\n\r\n")
            length = int(_header(head, "Content-Length") or 0)
            raw = await reader.readexactly(length) if length else b""
            request_line, *header_lines = head.decode("latin-1").split("\r\n")
            method, path, _ = request_line.split(" ", 2)
            headers = {name.strip().lower(): value.strip() for name, sep, value in (line.partition(":") for line in header_lines) if sep}
            self.calls.append((method, path, headers))
            try:
                self.requests.append(json.loads(raw) if raw else {})
            except ValueError:
                self.requests.append({"raw": raw.decode("latin-1")})
            self.accepted.set()
            if self.stall:
                while await reader.read(65536):
                    pass  # hold the request open until the client gives up
                return
            payload = json.dumps(self.body).encode("utf-8")
            writer.write((f"HTTP/1.1 {self.status} X\r\nContent-Type: application/json\r\nContent-Length: {len(payload)}\r\nConnection: close\r\n\r\n").encode("ascii") + payload)
            await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            self.closed.set()
            writer.close()
