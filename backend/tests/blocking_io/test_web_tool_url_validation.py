"""Web tools must resolve SSRF-screened hostnames off the agent event loop.

A synthetic hostname resolves to loopback through a native resolver fixture,
without depending on platform-specific numeric-host parsing or external DNS.
The real ``socket.getaddrinfo`` wrapper and the strict gate's rule remain active,
so resolution on the loop still fails instead of reaching the fixture.
"""

import _socket
import asyncio
import socket
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from blockbuster import BlockingError

from deerflow.community.browser_automation import tools as browser_tools
from deerflow.community.browser_automation.egress import BrowserEgressProxy
from deerflow.community.browserless import tools as browserless_tools
from deerflow.community.crawl4ai import tools as crawl4ai_tools
from deerflow.community.url_safety import resolve_host_addresses

pytestmark = pytest.mark.asyncio

_LOOPBACK_HOST = "loopback.test.invalid"
_UNRESOLVED_LOOPBACK_URL = f"http://{_LOOPBACK_HOST}/"


@pytest.fixture
def loopback_dns(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []
    native_getaddrinfo = _socket.getaddrinfo

    def getaddrinfo(host, port, *args, **kwargs):
        if host == _LOOPBACK_HOST:
            calls.append(host)
            return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("127.0.0.1", port or 0))]
        return native_getaddrinfo(host, port, *args, **kwargs)

    # Patch below socket.getaddrinfo, not over Blockbuster's instrumented wrapper.
    monkeypatch.setattr(_socket, "getaddrinfo", getaddrinfo)
    return calls


async def test_loopback_dns_keeps_on_loop_resolution_blocked(loopback_dns: list[str]) -> None:
    with pytest.raises(BlockingError, match="socket.getaddrinfo"):
        resolve_host_addresses(_LOOPBACK_HOST)

    assert loopback_dns == []


async def test_crawl4ai_web_fetch_resolves_off_loop(loopback_dns: list[str]) -> None:
    with (
        patch.object(crawl4ai_tools, "_get_tool_config", return_value={}),
        patch.object(crawl4ai_tools, "_build_client") as build_client,
    ):
        result = await crawl4ai_tools.web_fetch_tool.ainvoke({"url": _UNRESOLVED_LOOPBACK_URL})

    assert result == "Error: Refusing to fetch a private, loopback, or metadata address"
    assert loopback_dns == [_LOOPBACK_HOST]
    build_client.assert_not_called()


async def test_browserless_web_fetch_resolves_off_loop(loopback_dns: list[str]) -> None:
    with (
        patch.object(browserless_tools, "_get_tool_config", return_value={}),
        patch.object(browserless_tools, "_get_browserless_client") as get_client,
    ):
        result = await browserless_tools.web_fetch_tool.ainvoke({"url": _UNRESOLVED_LOOPBACK_URL})

    assert result == "Error: Refusing to fetch a private, loopback, or metadata address"
    assert loopback_dns == [_LOOPBACK_HOST]
    get_client.assert_not_called()


async def test_browserless_web_capture_resolves_off_loop(loopback_dns: list[str]) -> None:
    with (
        patch.object(browserless_tools, "_get_tool_config", return_value={}),
        patch.object(browserless_tools, "_get_browserless_client") as get_client,
    ):
        result = await browserless_tools.web_capture_tool.coroutine(
            runtime=SimpleNamespace(context={}, state={}),
            url=_UNRESOLVED_LOOPBACK_URL,
            tool_call_id="call-1",
        )

    assert result.update["messages"][0].content == "Error: Refusing to capture a private, loopback, or metadata address"
    assert loopback_dns == [_LOOPBACK_HOST]
    get_client.assert_not_called()


async def test_browser_navigate_tool_resolves_off_loop(loopback_dns: list[str]) -> None:
    manager = MagicMock()
    with (
        patch.object(browser_tools, "_get_tool_config", return_value={}),
        patch.object(browser_tools, "get_browser_session_manager", return_value=manager),
    ):
        result = await browser_tools.browser_navigate_tool.coroutine(
            runtime=SimpleNamespace(context={"thread_id": "thread-1"}, state={}),
            url=_UNRESOLVED_LOOPBACK_URL,
            tool_call_id="call-1",
        )

    assert result.update["messages"][0].content == "Error: Refusing to browse a private, loopback, or metadata address"
    assert loopback_dns == [_LOOPBACK_HOST]
    manager.acquire_session.assert_not_called()


async def test_browser_navigate_and_capture_resolves_off_loop(tmp_path, loopback_dns: list[str]) -> None:
    manager = MagicMock()
    with (
        patch.object(browser_tools, "_get_tool_config", return_value={}),
        patch.object(browser_tools, "get_browser_session_manager", return_value=manager),
        pytest.raises(ValueError, match="Refusing to browse a private, loopback, or metadata address"),
    ):
        await browser_tools.navigate_and_capture(thread_id="thread-1", url=_UNRESOLVED_LOOPBACK_URL, outputs_path=tmp_path)

    manager.acquire_session.assert_not_called()
    assert loopback_dns == [_LOOPBACK_HOST]


async def test_browser_request_guard_resolves_off_loop(loopback_dns: list[str]) -> None:
    # The context route guard screens every redirect hop and subresource on the
    # shared Playwright loop, which also pumps Live frames for every session.
    from deerflow.community.browser_automation.session import BrowserSession

    captured = {}

    class _FakeContext:
        async def route(self, _pattern, handler):
            captured["handler"] = handler

    class _FakeRoute:
        request = SimpleNamespace(url=_UNRESOLVED_LOOPBACK_URL)
        aborted_with = None

        async def abort(self, error_code):
            self.aborted_with = error_code

        async def continue_(self):
            raise AssertionError("a loopback request must not continue")

    session = BrowserSession(MagicMock(), headless=True, timeout_ms=1000, viewport={"width": 1000, "height": 500}, url_guard=browser_tools.validate_browser_url)
    session._context = _FakeContext()
    route = _FakeRoute()
    with patch.object(browser_tools, "_get_tool_config", return_value={}):
        await session._install_request_guard()
        await captured["handler"](route)

    assert route.aborted_with == "blockedbyclient"
    assert loopback_dns == [_LOOPBACK_HOST]


async def test_browser_egress_proxy_resolves_off_loop(loopback_dns: list[str]) -> None:
    # Chromium hands every hostname to the session's egress proxy, which runs on
    # the same shared Playwright loop as the request guard.
    proxy = BrowserEgressProxy(browser_tools.resolve_browser_egress)
    with patch.object(browser_tools, "_get_tool_config", return_value={}):
        proxy_url = await proxy.start()
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", int(proxy_url.rsplit(":", 1)[1]))
            writer.write(b"\x05\x01\x00")
            await writer.drain()
            assert await reader.readexactly(2) == b"\x05\x00"
            hostname = _LOOPBACK_HOST.encode("ascii")
            writer.write(b"\x05\x01\x00\x03" + bytes([len(hostname)]) + hostname + b"\x00\x50")
            await writer.drain()
            reply = await reader.readexactly(10)
            writer.close()
        finally:
            await proxy.close()

    assert reply[1] == 0x02  # refused: the hostname resolves to loopback
    assert loopback_dns == [_LOOPBACK_HOST]
