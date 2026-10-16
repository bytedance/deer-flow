"""Pinned browser egress: a loopback SOCKS5 proxy that connects only to vetted addresses.

The context request guard screens a URL by resolving its hostname, but
Chromium resolves the name again when it opens the connection. A rebinding DNS
server can pass the screen with a public answer and then hand Chromium a
private or cloud-metadata address. Launching Chromium through this proxy moves
name resolution out of the browser: over SOCKS5, Chromium sends the hostname
itself, the proxy resolves it exactly once through the session's egress
resolver, and it opens the TCP connection only to the addresses that resolver
vetted.

Only the SOCKS5 ``CONNECT`` command without authentication is supported, which
is everything Chromium sends for HTTP, HTTPS, and WebSocket traffic. The proxy
never parses the tunnelled bytes.
"""

from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import logging
from collections.abc import Callable

logger = logging.getLogger(__name__)

# Resolves a destination host (DNS name or IP literal) to the addresses the
# browser may connect to. Raises ``ValueError`` when the host must be refused;
# any other exception is logged as a resolver fault and the connection fails.
EgressResolver = Callable[[str], list[str]]

_SOCKS_VERSION = 5
_NO_AUTHENTICATION = 0x00
_NO_ACCEPTABLE_METHODS = 0xFF
_CONNECT = 0x01
_ADDRESS_IPV4 = 0x01
_ADDRESS_DOMAIN = 0x03
_ADDRESS_IPV6 = 0x04
_REPLY_SUCCEEDED = 0x00
_REPLY_GENERAL_FAILURE = 0x01
_REPLY_NOT_ALLOWED = 0x02
_REPLY_HOST_UNREACHABLE = 0x04
_REPLY_COMMAND_NOT_SUPPORTED = 0x07
_REPLY_ADDRESS_TYPE_NOT_SUPPORTED = 0x08

_HANDSHAKE_TIMEOUT_S = 15
_RESOLVE_TIMEOUT_S = 15
_CONNECT_TIMEOUT_S = 15
_CLOSE_TIMEOUT_S = 2


class _RefusedRequest(Exception):
    def __init__(self, reply: int) -> None:
        super().__init__(reply)
        self.reply = reply


class BrowserEgressProxy:
    """A per-session SOCKS5 proxy bound to 127.0.0.1 on an ephemeral port."""

    def __init__(self, resolve: EgressResolver) -> None:
        self._resolve = resolve
        self._server: asyncio.Server | None = None
        self._client_writers: set[asyncio.StreamWriter] = set()

    async def start(self) -> str:
        """Start listening and return the ``socks5://`` server URL for Chromium."""
        if self._server is None:
            self._server = await asyncio.start_server(self._handle, host="127.0.0.1", port=0)
        port = self._server.sockets[0].getsockname()[1]
        return f"socks5://127.0.0.1:{port}"

    async def close(self) -> None:
        server, self._server = self._server, None
        if server is None:
            return
        server.close()
        # Server.wait_closed() waits for every open connection, so close the
        # tunnels the browser left behind instead of waiting on them.
        for writer in list(self._client_writers):
            writer.close()
        # A handler still resolving, or accepted just before close, can outlive
        # the sweep; it must not hold up session close or eviction.
        with contextlib.suppress(Exception):
            await asyncio.wait_for(server.wait_closed(), timeout=_CLOSE_TIMEOUT_S)

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        if self._server is None:
            # Accepted just before close(); never open a tunnel after it.
            writer.close()
            return
        self._client_writers.add(writer)
        try:
            try:
                host, port = await asyncio.wait_for(_read_connect_request(reader, writer), timeout=_HANDSHAKE_TIMEOUT_S)
            except _RefusedRequest as exc:
                await _reply(writer, exc.reply)
                return
            try:
                addresses = await asyncio.wait_for(asyncio.to_thread(self._resolve, host), timeout=_RESOLVE_TIMEOUT_S)
            except ValueError as exc:
                logger.warning("browser egress refused for %s:%d: %s", host, port, exc)
                await _reply(writer, _REPLY_NOT_ALLOWED)
                return
            except TimeoutError:
                logger.warning("browser egress resolution timed out for %s:%d", host, port)
                await _reply(writer, _REPLY_HOST_UNREACHABLE)
                return
            except Exception:
                # A resolver fault is not a policy refusal; keep the two
                # distinguishable in the log and in the browser's error.
                logger.exception("browser egress resolver failed for %s:%d", host, port)
                await _reply(writer, _REPLY_GENERAL_FAILURE)
                return
            upstream = await _open_first(addresses, port)
            if upstream is None:
                await _reply(writer, _REPLY_HOST_UNREACHABLE)
                return
            upstream_reader, upstream_writer = upstream
            try:
                await _reply(writer, _REPLY_SUCCEEDED)
                await asyncio.gather(_relay(reader, upstream_writer), _relay(upstream_reader, writer))
            finally:
                with contextlib.suppress(Exception):
                    upstream_writer.close()
                    await upstream_writer.wait_closed()
        except (asyncio.IncompleteReadError, ConnectionError, TimeoutError):
            pass
        finally:
            self._client_writers.discard(writer)
            with contextlib.suppress(Exception):
                writer.close()
                await writer.wait_closed()


async def _read_connect_request(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> tuple[str, int]:
    """Negotiate no-auth SOCKS5 and return the ``CONNECT`` destination."""
    version, method_count = await reader.readexactly(2)
    methods = await reader.readexactly(method_count)
    if version != _SOCKS_VERSION:
        raise ConnectionError("not a SOCKS5 client")
    if _NO_AUTHENTICATION not in methods:
        writer.write(bytes([_SOCKS_VERSION, _NO_ACCEPTABLE_METHODS]))
        await writer.drain()
        raise ConnectionError("SOCKS5 client requires authentication")
    writer.write(bytes([_SOCKS_VERSION, _NO_AUTHENTICATION]))
    await writer.drain()

    version, command, _reserved, address_type = await reader.readexactly(4)
    if version != _SOCKS_VERSION:
        raise ConnectionError("not a SOCKS5 request")
    if address_type == _ADDRESS_IPV4:
        host = str(ipaddress.IPv4Address(await reader.readexactly(4)))
    elif address_type == _ADDRESS_IPV6:
        host = str(ipaddress.IPv6Address(await reader.readexactly(16)))
    elif address_type == _ADDRESS_DOMAIN:
        (length,) = await reader.readexactly(1)
        raw_host = await reader.readexactly(length)
        try:
            host = raw_host.decode("ascii")
        except UnicodeDecodeError:
            raise _RefusedRequest(_REPLY_ADDRESS_TYPE_NOT_SUPPORTED) from None
        if not host:
            raise _RefusedRequest(_REPLY_ADDRESS_TYPE_NOT_SUPPORTED)
    else:
        raise _RefusedRequest(_REPLY_ADDRESS_TYPE_NOT_SUPPORTED)
    port = int.from_bytes(await reader.readexactly(2), "big")
    if command != _CONNECT:
        raise _RefusedRequest(_REPLY_COMMAND_NOT_SUPPORTED)
    return host, port


async def _reply(writer: asyncio.StreamWriter, reply: int) -> None:
    # The bound address is unused by Chromium, so always report 0.0.0.0:0.
    writer.write(bytes([_SOCKS_VERSION, reply, 0x00, _ADDRESS_IPV4, 0, 0, 0, 0, 0, 0]))
    await writer.drain()


async def _open_first(addresses: list[str], port: int) -> tuple[asyncio.StreamReader, asyncio.StreamWriter] | None:
    """Connect to the first reachable vetted address within one shared deadline."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + _CONNECT_TIMEOUT_S
    for index, address in enumerate(addresses):
        remaining = deadline - loop.time()
        if remaining <= 0:
            break
        # Leave every later address an equal share of the remaining budget so a
        # black-holed first answer cannot strand reachable candidates.
        try:
            return await asyncio.wait_for(asyncio.open_connection(address, port), timeout=remaining / (len(addresses) - index))
        except (OSError, TimeoutError):
            continue
    return None


async def _relay(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while chunk := await reader.read(65_536):
            writer.write(chunk)
            await writer.drain()
    except ConnectionError:
        pass
    finally:
        with contextlib.suppress(Exception):
            writer.close()
            await writer.wait_closed()
