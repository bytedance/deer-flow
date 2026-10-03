"""Pinned browser egress: the SOCKS5 proxy, its policy, and the session wiring.

The proxy tests drive the real asyncio server with a minimal SOCKS5 client, so
the protocol bytes Chromium exchanges with it are exercised end to end. The last
test repeats the rebinding scenario against a real headless Chromium and is
skipped when Playwright is not installed.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from deerflow.community import url_safety
from deerflow.community.browser_automation import egress
from deerflow.community.browser_automation import session as session_mod
from deerflow.community.browser_automation import tools as browser_tools
from deerflow.community.browser_automation.egress import BrowserEgressProxy
from deerflow.community.browser_automation.session import BrowserSession


async def _start_echo_server() -> tuple[asyncio.Server, int]:
    async def echo(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.write(await reader.read(1024))
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(echo, host="127.0.0.1", port=0)
    return server, server.sockets[0].getsockname()[1]


async def _socks_connect(proxy_url: str, address_type: int, address: bytes, port: int, *, command: int = 0x01, methods: bytes = b"\x00"):
    """Run the client half of a SOCKS5 CONNECT; return (method reply, reply code, reader, writer)."""
    proxy_port = int(proxy_url.rsplit(":", 1)[1])
    reader, writer = await asyncio.open_connection("127.0.0.1", proxy_port)
    writer.write(bytes([5, len(methods)]) + methods)
    await writer.drain()
    _version, method = await reader.readexactly(2)
    if method == 0xFF:
        return method, None, reader, writer
    writer.write(bytes([5, command, 0, address_type]) + address + port.to_bytes(2, "big"))
    await writer.drain()
    reply = await reader.readexactly(10)
    return method, reply[1], reader, writer


def _domain(host: str) -> bytes:
    return bytes([len(host)]) + host.encode("ascii")


@pytest.mark.asyncio
async def test_proxy_connects_to_the_vetted_address_not_the_requested_name():
    echo, echo_port = await _start_echo_server()
    asked: list[str] = []

    def resolve(host: str) -> list[str]:
        asked.append(host)
        return ["127.0.0.1"]

    proxy = BrowserEgressProxy(resolve)
    try:
        _method, reply, reader, writer = await _socks_connect(await proxy.start(), 0x03, _domain("rebind.example"), echo_port)
        assert reply == 0x00
        writer.write(b"ping")
        await writer.drain()
        assert await reader.read(1024) == b"ping"
        writer.close()
    finally:
        await proxy.close()
        echo.close()
    assert asked == ["rebind.example"]


@pytest.mark.asyncio
async def test_proxy_refuses_a_host_the_resolver_rejects_without_connecting():
    connections: list[str] = []

    async def record(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        connections.append("upstream")
        writer.close()

    upstream = await asyncio.start_server(record, host="127.0.0.1", port=0)
    upstream_port = upstream.sockets[0].getsockname()[1]

    def resolve(host: str) -> list[str]:
        raise ValueError("Error: Refusing to browse a private, loopback, or metadata address")

    proxy = BrowserEgressProxy(resolve)
    try:
        _method, reply, _reader, writer = await _socks_connect(await proxy.start(), 0x03, _domain("metadata.example"), upstream_port)
        writer.close()
    finally:
        await proxy.close()
        upstream.close()
    assert reply == 0x02  # connection not allowed by ruleset
    assert connections == []


@pytest.mark.asyncio
async def test_proxy_hands_ip_literals_to_the_resolver():
    echo, echo_port = await _start_echo_server()
    asked: list[str] = []

    def resolve(host: str) -> list[str]:
        asked.append(host)
        return [host]

    proxy = BrowserEgressProxy(resolve)
    try:
        _method, reply, _reader, writer = await _socks_connect(await proxy.start(), 0x01, socket.inet_aton("127.0.0.1"), echo_port)
        writer.close()
    finally:
        await proxy.close()
        echo.close()
    assert reply == 0x00
    assert asked == ["127.0.0.1"]


@pytest.mark.asyncio
async def test_proxy_falls_through_to_the_next_vetted_address():
    echo, echo_port = await _start_echo_server()
    # The echo server listens on IPv4 loopback only, so the IPv6 loopback answer
    # is refused (or unavailable) and only the second vetted address connects.
    proxy = BrowserEgressProxy(lambda _host: ["::1", "127.0.0.1"])
    try:
        _method, reply, _reader, writer = await _socks_connect(await proxy.start(), 0x03, _domain("multi.example"), echo_port)
        writer.close()
    finally:
        await proxy.close()
        echo.close()
    assert reply == 0x00


@pytest.mark.asyncio
async def test_proxy_reports_unreachable_when_no_vetted_address_answers():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        closed_port = probe.getsockname()[1]

    proxy = BrowserEgressProxy(lambda _host: ["127.0.0.1"])
    try:
        _method, reply, _reader, writer = await _socks_connect(await proxy.start(), 0x03, _domain("down.example"), closed_port)
        writer.close()
    finally:
        await proxy.close()
    assert reply == 0x04


@pytest.mark.asyncio
async def test_proxy_rejects_commands_other_than_connect():
    resolve = MagicMock()
    proxy = BrowserEgressProxy(resolve)
    try:
        _method, reply, _reader, writer = await _socks_connect(await proxy.start(), 0x03, _domain("bind.example"), 80, command=0x02)
        writer.close()
    finally:
        await proxy.close()
    assert reply == 0x07
    resolve.assert_not_called()


@pytest.mark.asyncio
async def test_proxy_rejects_clients_that_require_authentication():
    resolve = MagicMock()
    proxy = BrowserEgressProxy(resolve)
    try:
        method, _reply, _reader, writer = await _socks_connect(await proxy.start(), 0x03, _domain("auth.example"), 80, methods=b"\x02")
        writer.close()
    finally:
        await proxy.close()
    assert method == 0xFF
    resolve.assert_not_called()


def _blocking_resolver():
    """A resolver that hangs until released, like a wedged getaddrinfo."""
    release = threading.Event()

    def resolve(_host: str) -> list[str]:
        release.wait(timeout=10)
        return ["127.0.0.1"]

    return resolve, release


@pytest.mark.asyncio
async def test_proxy_reports_a_resolver_fault_as_general_failure(caplog):
    def resolve(_host: str) -> list[str]:
        raise RuntimeError("config store unavailable")

    proxy = BrowserEgressProxy(resolve)
    try:
        _method, reply, _reader, writer = await _socks_connect(await proxy.start(), 0x03, _domain("fault.example"), 80)
        writer.close()
    finally:
        await proxy.close()
    # 0x01 (general failure), distinct from the 0x02 a policy refusal returns.
    assert reply == 0x01
    assert "browser egress resolver failed for fault.example:80" in caplog.text
    assert "config store unavailable" in caplog.text


@pytest.mark.asyncio
async def test_proxy_bounds_a_stuck_resolution(monkeypatch):
    monkeypatch.setattr(egress, "_RESOLVE_TIMEOUT_S", 0.2)
    resolve, release = _blocking_resolver()
    proxy = BrowserEgressProxy(resolve)
    try:
        _method, reply, _reader, writer = await asyncio.wait_for(_socks_connect(await proxy.start(), 0x03, _domain("wedged.example"), 80), timeout=2.0)
        writer.close()
    finally:
        release.set()
        await proxy.close()
    assert reply == 0x04


@pytest.mark.asyncio
async def test_proxy_close_is_bounded_by_a_tunnel_it_could_not_sweep(monkeypatch):
    monkeypatch.setattr(egress, "_CLOSE_TIMEOUT_S", 0.2)
    proxy = BrowserEgressProxy(MagicMock())
    proxy_port = int((await proxy.start()).rsplit(":", 1)[1])
    reader, writer = await asyncio.open_connection("127.0.0.1", proxy_port)
    try:
        while not proxy._client_writers:
            await asyncio.sleep(0.01)
        # Simulate a connection whose handler registered after the sweep: its
        # transport stays open in the 15 s handshake read, which would otherwise
        # hold Server.wait_closed() and with it session close.
        proxy._client_writers.clear()
        await asyncio.wait_for(proxy.close(), timeout=1.0)
    finally:
        writer.close()


@pytest.mark.asyncio
async def test_proxy_drops_a_connection_accepted_after_close():
    resolve = MagicMock(side_effect=ValueError("refused"))
    proxy = BrowserEgressProxy(resolve)
    await proxy.start()
    await proxy.close()
    reader = asyncio.StreamReader()
    reader.feed_data(b"\x05\x01\x00\x05\x01\x00\x03" + _domain("late.example") + (80).to_bytes(2, "big"))
    reader.feed_eof()
    writer = MagicMock()
    writer.drain = AsyncMock()
    writer.wait_closed = AsyncMock()

    # A handler scheduled for a connection accepted just before close() runs now.
    await asyncio.wait_for(proxy._handle(reader, writer), timeout=1.0)

    writer.close.assert_called_once()
    resolve.assert_not_called()


@pytest.mark.asyncio
async def test_proxy_close_ends_open_tunnels():
    held = asyncio.Event()

    async def hold(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        held.set()
        await reader.read()
        writer.close()

    upstream = await asyncio.start_server(hold, host="127.0.0.1", port=0)
    upstream_port = upstream.sockets[0].getsockname()[1]
    proxy = BrowserEgressProxy(lambda _host: ["127.0.0.1"])
    try:
        _method, reply, reader, writer = await _socks_connect(await proxy.start(), 0x03, _domain("idle.example"), upstream_port)
        assert reply == 0x00
        await asyncio.wait_for(held.wait(), timeout=1.0)
        await asyncio.wait_for(proxy.close(), timeout=2.0)
        assert await asyncio.wait_for(reader.read(), timeout=1.0) == b""
        writer.close()
    finally:
        upstream.close()


def test_resolve_public_addresses_returns_the_vetted_answer():
    public = [ipaddress.ip_address("93.184.215.14"), ipaddress.ip_address("2606:2800:21f:cb07:6820:80da:af6b:8b2c")]

    assert url_safety.resolve_public_addresses("example.com", resolver=lambda _host: public) == public


@pytest.mark.parametrize(
    ("hostname", "answer", "message"),
    [
        ("localhost", None, "Error: Refusing to connect to a private or loopback address"),
        ("169.254.169.254", None, "Error: Refusing to connect to a private, loopback, or metadata address"),
        ("unresolvable.example", [], "Error: URL host could not be resolved"),
        ("mixed.example", ["93.184.215.14", "10.0.0.5"], "Error: Refusing to connect to a private, loopback, or metadata address"),
    ],
)
def test_resolve_public_addresses_refuses_with_the_validator_message(hostname, answer, message):
    def resolver(_host):
        assert answer is not None, "literal and blocked hosts must not be resolved"
        return [ipaddress.ip_address(address) for address in answer]

    with pytest.raises(ValueError) as exc_info:
        url_safety.resolve_public_addresses(hostname, resolver=resolver)
    assert str(exc_info.value) == message


def test_resolve_browser_egress_applies_the_browse_policy():
    answers = {"public.example": ["93.184.215.14", "93.184.215.14"], "internal.example": ["10.0.0.5"]}

    def resolver(host):
        return [ipaddress.ip_address(address) for address in answers[host]]

    with patch.object(browser_tools, "_get_tool_config", return_value={}), patch.object(browser_tools, "_resolve_host_addresses", side_effect=resolver):
        assert browser_tools.resolve_browser_egress("public.example") == ["93.184.215.14"]
        with pytest.raises(ValueError, match="Refusing to browse a private, loopback, or metadata address"):
            browser_tools.resolve_browser_egress("internal.example")

    with patch.object(browser_tools, "_get_tool_config", return_value={"allow_private_addresses": True}), patch.object(browser_tools, "_resolve_host_addresses", side_effect=resolver):
        assert browser_tools.resolve_browser_egress("internal.example") == ["10.0.0.5"]


def _fake_playwright_modules():
    fake_async_api = ModuleType("playwright.async_api")
    fake_async_api.async_playwright = MagicMock()
    fake_playwright = ModuleType("playwright")
    fake_playwright.async_api = fake_async_api
    return patch.dict(sys.modules, {"playwright": fake_playwright, "playwright.async_api": fake_async_api})


def _fake_browser():
    page = MagicMock()
    page.is_closed.return_value = False
    context = MagicMock()
    context.new_page = AsyncMock(return_value=page)
    context.route = AsyncMock()
    browser = MagicMock()
    browser.is_connected.return_value = True
    browser.new_context = AsyncMock(return_value=context)
    browser.close = AsyncMock()
    context.close = AsyncMock()
    chromium = MagicMock()
    chromium.launch = AsyncMock(return_value=browser)
    return chromium


@pytest.mark.asyncio
async def test_session_launches_chromium_through_its_egress_proxy_and_closes_it():
    session = BrowserSession(MagicMock(), headless=True, timeout_ms=1000, viewport={"width": 1000, "height": 500}, egress_resolver=lambda _host: [])
    chromium = _fake_browser()
    session._playwright = SimpleNamespace(chromium=chromium, stop=AsyncMock())

    with _fake_playwright_modules():
        await session._ensure_page()

    proxy = chromium.launch.await_args.kwargs["proxy"]
    assert proxy["server"].startswith("socks5://127.0.0.1:")
    assert proxy["bypass"] == "<-loopback>"
    proxy_port = int(proxy["server"].rsplit(":", 1)[1])
    _reader, writer = await asyncio.open_connection("127.0.0.1", proxy_port)
    writer.close()

    await session._close()
    with pytest.raises(OSError):
        await asyncio.open_connection("127.0.0.1", proxy_port)


@pytest.mark.asyncio
async def test_session_without_egress_resolver_launches_directly():
    session = BrowserSession(MagicMock(), headless=True, timeout_ms=1000, viewport={"width": 1000, "height": 500})
    chromium = _fake_browser()
    session._playwright = SimpleNamespace(chromium=chromium)

    with _fake_playwright_modules():
        await session._ensure_page()

    chromium.launch.assert_awaited_once_with(headless=True, proxy=None)


@pytest.mark.asyncio
async def test_manager_passes_the_egress_resolver_to_new_sessions():
    manager = session_mod.BrowserSessionManager()
    with patch.object(session_mod, "ensure_browser_worker_compatibility"), patch.object(manager, "_ensure_loop", return_value=MagicMock()):
        session = manager.get_session("egress-thread", egress_resolver=browser_tools.resolve_browser_egress)
    assert session._egress_resolver is browser_tools.resolve_browser_egress


@pytest.mark.asyncio
async def test_browser_tools_acquire_sessions_with_pinned_egress(tmp_path):
    manager = MagicMock()
    page_snapshot = MagicMock(url="https://example.com/", title="Example")
    session = MagicMock()
    session.navigate = AsyncMock(return_value=page_snapshot)
    session.screenshot_bytes = AsyncMock(side_effect=RuntimeError("no screenshot"))
    manager.acquire_session.return_value.__enter__.return_value = session
    manager.get_session.return_value = session
    with (
        patch.object(browser_tools, "_get_tool_config", return_value={}),
        patch.object(browser_tools, "get_browser_session_manager", return_value=manager),
        patch.object(browser_tools, "_resolve_host_addresses", return_value=[ipaddress.ip_address("93.184.215.14")]),
    ):
        await browser_tools.navigate_and_capture(thread_id="thread-1", url="https://example.com/", outputs_path=tmp_path)
        browser_tools._resolve_session(SimpleNamespace(context={"thread_id": "thread-1"}, state={}), "browser_navigate")

    assert manager.acquire_session.call_args.kwargs["egress_resolver"] is browser_tools.resolve_browser_egress
    assert manager.get_session.call_args.kwargs["egress_resolver"] is browser_tools.resolve_browser_egress


@pytest.mark.asyncio
async def test_real_chromium_cannot_follow_a_rebinding_answer():
    """A name that passes both URL screens but answers loopback to the connect is refused."""
    pytest.importorskip("playwright.async_api")

    class _Internal(BaseHTTPRequestHandler):
        def do_GET(self):
            body = b"<title>metadata</title>iam-credentials"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    internal = ThreadingHTTPServer(("127.0.0.1", 0), _Internal)
    threading.Thread(target=internal.serve_forever, daemon=True).start()
    # Chromium resolves *.localhost to loopback by itself, so without the pinned
    # egress proxy this navigation would reach the internal server directly.
    url = f"http://rebind.localhost:{internal.server_address[1]}/"
    lookups = 0

    def rebinding_resolver(_host):
        nonlocal lookups
        lookups += 1
        # The navigate screen and the request guard see a public answer; the
        # lookup the connection actually uses sees loopback.
        return [ipaddress.ip_address("93.184.215.14" if lookups <= 2 else "127.0.0.1")]

    session_mod.reset_browser_session_manager()
    manager = session_mod.get_browser_session_manager()
    runtime = SimpleNamespace(context={"thread_id": "rebind-thread"}, state={"thread_data": {}})
    try:
        with (
            patch.object(browser_tools, "_get_tool_config", return_value={"timeout_ms": 15000}),
            patch.object(browser_tools, "_resolve_host_addresses", side_effect=rebinding_resolver),
            patch.object(browser_tools, "_capture_step_screenshot", AsyncMock(return_value=None)),
        ):
            result = await browser_tools.browser_navigate_tool.coroutine(runtime=runtime, url=url, tool_call_id="call-1")
    finally:
        await manager.close_session("rebind-thread")
        session_mod.reset_browser_session_manager()
        internal.shutdown()

    content = result.update["messages"][0].content
    assert "ERR_SOCKS_CONNECTION_FAILED" in content
    assert "iam-credentials" not in content
    # navigate screen, request guard, then the proxy's own lookup for the connect
    assert lookups >= 3
