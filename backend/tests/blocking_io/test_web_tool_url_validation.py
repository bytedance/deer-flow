"""Web tools must resolve SSRF-screened hostnames off the agent event loop.

``http://127.1/`` is not an ``ipaddress`` literal, so the URL guard hands it to
the real ``socket.getaddrinfo``, which expands it to 127.0.0.1 without any DNS
traffic. The strict gate's ``socket.getaddrinfo`` rule fails each test if the
tool resolves on the loop instead of in a worker thread.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from deerflow.community.browser_automation import tools as browser_tools
from deerflow.community.browserless import tools as browserless_tools
from deerflow.community.crawl4ai import tools as crawl4ai_tools

pytestmark = pytest.mark.asyncio

_UNRESOLVED_LOOPBACK_URL = "http://127.1/"


async def test_crawl4ai_web_fetch_resolves_off_loop() -> None:
    with (
        patch.object(crawl4ai_tools, "_get_tool_config", return_value={}),
        patch.object(crawl4ai_tools, "_build_client") as build_client,
    ):
        result = await crawl4ai_tools.web_fetch_tool.ainvoke({"url": _UNRESOLVED_LOOPBACK_URL})

    assert result == "Error: Refusing to fetch a private, loopback, or metadata address"
    build_client.assert_not_called()


async def test_browserless_web_fetch_resolves_off_loop() -> None:
    with (
        patch.object(browserless_tools, "_get_tool_config", return_value={}),
        patch.object(browserless_tools, "_get_browserless_client") as get_client,
    ):
        result = await browserless_tools.web_fetch_tool.ainvoke({"url": _UNRESOLVED_LOOPBACK_URL})

    assert result == "Error: Refusing to fetch a private, loopback, or metadata address"
    get_client.assert_not_called()


async def test_browserless_web_capture_resolves_off_loop() -> None:
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
    get_client.assert_not_called()


async def test_browser_navigate_tool_resolves_off_loop() -> None:
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
    manager.acquire_session.assert_not_called()


async def test_browser_navigate_and_capture_resolves_off_loop(tmp_path) -> None:
    manager = MagicMock()
    with (
        patch.object(browser_tools, "_get_tool_config", return_value={}),
        patch.object(browser_tools, "get_browser_session_manager", return_value=manager),
        pytest.raises(ValueError, match="Refusing to browse a private, loopback, or metadata address"),
    ):
        await browser_tools.navigate_and_capture(thread_id="thread-1", url=_UNRESOLVED_LOOPBACK_URL, outputs_path=tmp_path)

    manager.acquire_session.assert_not_called()
