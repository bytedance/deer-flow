import asyncio
from concurrent.futures import Future
from unittest.mock import AsyncMock

import pytest

from deerflow.community.browser_automation import session as native


def test_scope_is_owner_incarnation_bound_and_rejects_other_thread():
    scope = native.BrowserSessionScope("owner", "thread", "inc")
    with native.browser_session_scope(scope):
        assert native.browser_session_key("thread") == scope.key
        with pytest.raises(ValueError, match="thread"):
            native.browser_session_key("other")
    assert native.browser_session_key("thread") == "thread"
    assert native.BrowserSessionScope("other", "thread", "inc").key != scope.key
    assert native.BrowserSessionScope("owner", "thread", "next").key != scope.key


@pytest.mark.asyncio
async def test_scope_survives_task_and_thread_hops():
    scope = native.BrowserSessionScope("owner", "thread", "inc")

    async def read():
        return await asyncio.to_thread(native.browser_session_key, "thread")

    with native.browser_session_scope(scope):
        task = asyncio.create_task(read())
    assert await task == scope.key


class PrivateLoop:
    def __init__(self):
        self.closes = []

    def submit(self, coro):
        coro.close()
        future = Future()
        self.closes.append(future)
        return future


@pytest.mark.asyncio
async def test_strict_capacity_counts_closing_and_unknown_sessions():
    manager = native.BrowserSessionManager(max_sessions=1, strict_physical_capacity=True)
    manager._loop = loop = PrivateLoop()
    manager.get_session("first", pin=True)
    with pytest.raises(native.BrowserSessionCapacityError):
        manager.get_session("second")
    close = asyncio.create_task(manager.close_session("first"))
    await asyncio.sleep(0)
    with pytest.raises(native.BrowserSessionCapacityError):
        manager.get_session("second")
    loop.closes[0].set_exception(RuntimeError("close unknown"))
    with pytest.raises(RuntimeError, match="unknown"):
        await close
    with pytest.raises(native.BrowserSessionCapacityError):
        manager.get_session("second")


@pytest.mark.asyncio
async def test_strict_capacity_releases_only_after_close_completion():
    manager = native.BrowserSessionManager(max_sessions=1, strict_physical_capacity=True)
    manager._loop = loop = PrivateLoop()
    manager.get_session("first")
    close = asyncio.create_task(manager.close_session("first"))
    await asyncio.sleep(0)
    loop.closes[0].set_result(None)
    assert await close
    manager.get_session("second")


@pytest.mark.asyncio
async def test_strict_native_close_requires_disconnected_browser():
    session = native.BrowserSession(PrivateLoop(), headless=True, timeout_ms=1000, viewport={}, strict_physical_capacity=True)

    class Browser:
        close = AsyncMock()

        def is_connected(self):
            return True

    session._browser = Browser()
    with pytest.raises(RuntimeError, match="disconnect"):
        await session._close()
    assert session._browser is not None


def test_strict_mode_rejects_cdp_even_operator_optout():
    manager = native.BrowserSessionManager(max_sessions=1, strict_physical_capacity=True)
    with pytest.raises(ValueError, match="CDP"):
        manager.get_session("thread", cdp_url="http://127.0.0.1:9222", allow_unguarded_cdp=True)


def test_public_manager_config_must_precede_initialization():
    native.reset_browser_session_manager()
    try:
        native.configure_browser_session_manager(max_sessions=1, strict_physical_capacity=True)
        assert native.get_browser_session_manager()._max_sessions == 1
        with pytest.raises(RuntimeError, match="initialized"):
            native.configure_browser_session_manager(max_sessions=2)
    finally:
        native.reset_browser_session_manager()


@pytest.mark.asyncio
async def test_strict_lru_retires_old_session_before_retry_can_admit():
    manager = native.BrowserSessionManager(max_sessions=1, strict_physical_capacity=True)
    manager._loop = loop = PrivateLoop()
    manager.get_session("first")
    with pytest.raises(native.BrowserSessionCapacityError):
        manager.get_session("second")
    assert len(loop.closes) == 1
    loop.closes[0].set_result(None)
    manager.get_session("second")


@pytest.mark.asyncio
async def test_strict_shutdown_waits_for_closing_and_refuses_unknown():
    manager = native.BrowserSessionManager(max_sessions=1, strict_physical_capacity=True)
    manager._loop = loop = PrivateLoop()
    manager.get_session("first")
    close = asyncio.create_task(manager.close_session("first"))
    await asyncio.sleep(0)
    shutdown = asyncio.create_task(manager.close_all_sessions())
    await asyncio.sleep(0)
    assert not shutdown.done()
    loop.closes[0].set_exception(RuntimeError("physical close unknown"))
    with pytest.raises(RuntimeError, match="unknown"):
        await close
    with pytest.raises(RuntimeError, match="unknown"):
        await shutdown


@pytest.mark.asyncio
async def test_real_scoped_native_browser_guard_egress_and_physical_close(monkeypatch):
    pytest.importorskip("playwright.async_api")
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from deerflow.community.browser_automation import tools

    class Page(BaseHTTPRequestHandler):
        def do_GET(self):
            content = b"<button onclick=\"document.title='clicked'\">Go</button><p>native scoped probe</p>"
            self.send_response(200)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Page)
    serving = threading.Thread(target=server.serve_forever, daemon=True)
    serving.start()
    # Explicit fixture-only private-address exception; retain native guard/proxy.
    monkeypatch.setattr(tools, "_get_tool_config", lambda name: {"allow_private_addresses": True})
    manager = native.BrowserSessionManager(max_sessions=1, strict_physical_capacity=True)
    scope = native.BrowserSessionScope("probe-owner", "probe-thread", "probe-inc")
    try:
        with native.browser_session_scope(scope):
            with manager.acquire_session(scope.thread_id, url_guard=tools.validate_browser_url, egress_resolver=tools.resolve_browser_egress) as session:
                snapshot = await session.navigate(f"http://127.0.0.1:{server.server_port}/native-probe")
                await session.click(snapshot.elements[0].ref)
                assert "native scoped probe" in await session.get_text()
                assert (await session.screenshot_bytes()).startswith(b"\x89PNG")
                assert session._request_guard_bound and session._egress_proxy is not None
            assert await manager.close_session(scope.thread_id)
        assert not manager._sessions and not manager._closing
        assert session._browser is None and session._egress_proxy is None
    finally:
        await manager.close_all_sessions()
        server.shutdown()
        server.server_close()
        serving.join(timeout=5)


@pytest.mark.asyncio
async def test_strict_retired_session_held_by_live_cannot_reinitialize():
    from types import SimpleNamespace

    session = native.BrowserSession(PrivateLoop(), headless=True, timeout_ms=1000, viewport={}, strict_physical_capacity=True)
    await session._close()
    launch = AsyncMock(side_effect=AssertionError("retired Live attempted Chromium launch"))
    session._playwright = SimpleNamespace(chromium=SimpleNamespace(launch=launch))
    with pytest.raises(RuntimeError, match="retired"):
        await session._ensure_page()
    launch.assert_not_awaited()


@pytest.mark.asyncio
async def test_strict_close_waits_for_cancelled_caller_launch_to_settle():
    from types import SimpleNamespace

    session = native.BrowserSession(PrivateLoop(), headless=True, timeout_ms=1000, viewport={}, strict_physical_capacity=True)
    entered, settle = asyncio.Event(), asyncio.Event()
    connected = True

    async def close_browser():
        nonlocal connected
        connected = False

    page = SimpleNamespace(is_closed=lambda: False)
    context = SimpleNamespace(new_page=AsyncMock(return_value=page), set_default_timeout=lambda value: None, close=AsyncMock())
    browser = SimpleNamespace(new_context=AsyncMock(return_value=context), close=AsyncMock(side_effect=close_browser), is_connected=lambda: connected)

    async def launch(**kwargs):
        entered.set()
        await settle.wait()
        return browser

    session._playwright = SimpleNamespace(chromium=SimpleNamespace(launch=launch), stop=AsyncMock())
    session._bind_new_page_listener = lambda: None
    initialize = asyncio.create_task(session._ensure_page())
    await entered.wait()
    initialize.cancel()
    await asyncio.gather(initialize, return_exceptions=True)
    close = asyncio.create_task(session._close())
    await asyncio.sleep(0)
    try:
        assert not close.done(), "Physical close was published before in-flight launch settled"
    finally:
        settle.set()
        await close
    assert not connected and session._browser is None
    with pytest.raises(RuntimeError, match="retired"):
        await session._ensure_page()
