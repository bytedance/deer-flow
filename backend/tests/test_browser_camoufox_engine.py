"""Opt-in Camoufox launch engine for managed browser sessions (offline).

The ``camoufox`` package is optional, so every test here fakes it (or its
absence) through ``sys.modules``; no browser binary is launched.
"""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from deerflow.community.browser_automation import session as session_mod
from deerflow.community.browser_automation import tools as browser_tools
from deerflow.community.browser_automation.session import BrowserSession, BrowserSessionManager


def _fake_browser():
    page = MagicMock()
    page.is_closed.return_value = False
    context = MagicMock()
    context.new_page = AsyncMock(return_value=page)
    context.set_default_timeout = MagicMock()
    context.route = AsyncMock()
    context.on = MagicMock()
    browser = MagicMock()
    browser.is_connected.return_value = True
    browser.new_context = AsyncMock(return_value=context)
    return browser, context, page


@pytest.fixture
def fake_playwright(monkeypatch):
    async_api = ModuleType("playwright.async_api")
    async_api.async_playwright = MagicMock()
    playwright = ModuleType("playwright")
    playwright.async_api = async_api
    monkeypatch.setitem(sys.modules, "playwright", playwright)
    monkeypatch.setitem(sys.modules, "playwright.async_api", async_api)


def _fake_camoufox(monkeypatch, launcher):
    async_api = ModuleType("camoufox.async_api")
    async_api.AsyncNewBrowser = launcher
    package = ModuleType("camoufox")
    package.async_api = async_api
    monkeypatch.setitem(sys.modules, "camoufox", package)
    monkeypatch.setitem(sys.modules, "camoufox.async_api", async_api)


def _session(engine=None, **kwargs):
    if engine is not None:
        kwargs["engine"] = engine
    session = BrowserSession(MagicMock(), headless=True, timeout_ms=1000, viewport={"width": 1000, "height": 500}, **kwargs)
    chromium = MagicMock()
    session._playwright = SimpleNamespace(chromium=chromium)
    return session, chromium


@pytest.mark.asyncio
async def test_camoufox_engine_launches_through_camoufox_with_egress_options(monkeypatch, fake_playwright):
    browser, context, page = _fake_browser()
    launcher = AsyncMock(return_value=browser)
    _fake_camoufox(monkeypatch, launcher)
    session, chromium = _session("camoufox", url_guard=lambda _url: None)
    proxy = {"server": "socks5://127.0.0.1:4242", "bypass": "<-loopback>"}

    with patch.object(session, "_egress_proxy_settings", AsyncMock(return_value=proxy)):
        assert await session._ensure_page() is page

    chromium.launch.assert_not_called()
    launcher.assert_awaited_once_with(
        session._playwright,
        headless=True,
        block_webrtc=True,
        firefox_user_prefs={"network.proxy.socks_remote_dns": True, "network.proxy.allow_hijacking_localhost": True},
        proxy=proxy,
    )
    # The managed-context invariants hold on Firefox too.
    browser.new_context.assert_awaited_once_with(viewport={"width": 1000, "height": 500}, device_scale_factor=2)
    context.route.assert_awaited_once()
    assert session._request_guard_bound is True


@pytest.mark.asyncio
async def test_camoufox_engine_without_egress_resolver_omits_proxy(monkeypatch, fake_playwright):
    browser, _context, _page = _fake_browser()
    launcher = AsyncMock(return_value=browser)
    _fake_camoufox(monkeypatch, launcher)
    session, _chromium = _session("camoufox")

    await session._ensure_page()

    assert "proxy" not in launcher.await_args.kwargs


@pytest.mark.asyncio
async def test_camoufox_engine_missing_package_raises_actionable_error(monkeypatch, fake_playwright):
    # ``None`` in sys.modules makes ``import camoufox`` raise ImportError.
    monkeypatch.setitem(sys.modules, "camoufox", None)
    monkeypatch.setitem(sys.modules, "camoufox.async_api", None)
    session, chromium = _session("camoufox")  # construction never imports camoufox

    with pytest.raises(RuntimeError, match=r"uv sync --extra browser --extra camoufox.*camoufox fetch"):
        await session._ensure_page()
    chromium.launch.assert_not_called()


@pytest.mark.asyncio
async def test_default_engine_keeps_the_chromium_launch_unchanged(monkeypatch, fake_playwright):
    monkeypatch.setitem(sys.modules, "camoufox", None)  # importing it would fail loudly
    browser, _context, page = _fake_browser()
    session, chromium = _session()
    chromium.launch = AsyncMock(return_value=browser)

    assert await session._ensure_page() is page
    chromium.launch.assert_awaited_once_with(headless=True, proxy=None)


def test_unknown_engine_is_rejected():
    with pytest.raises(ValueError, match="Unknown browser engine 'webkit'"):
        BrowserSession(MagicMock(), headless=True, timeout_ms=1000, viewport={}, engine="webkit")


def test_manager_rejects_camoufox_with_cdp_url_and_passes_engine():
    manager = BrowserSessionManager()
    with patch.object(session_mod, "ensure_browser_worker_compatibility"), patch.object(manager, "_ensure_loop", return_value=MagicMock()):
        with pytest.raises(ValueError, match="Chromium-only"):
            manager.get_session("t", engine="camoufox", cdp_url="http://127.0.0.1:9222", allow_unguarded_cdp=True)
        assert manager.get_session("t", engine="camoufox")._engine == "camoufox"
        assert manager.get_session("u")._engine == "chromium"


@pytest.mark.parametrize(("cfg", "expected"), [({}, "chromium"), ({"engine": " Camoufox "}, "camoufox"), ({"engine": ""}, "chromium")])
@pytest.mark.asyncio
async def test_browser_tools_pass_the_configured_engine(tmp_path, cfg, expected):
    manager = MagicMock()
    session = MagicMock()
    session.navigate = AsyncMock(return_value=MagicMock(url="https://example.com/", title="Example"))
    session.screenshot_bytes = AsyncMock(side_effect=RuntimeError("no screenshot"))
    manager.acquire_session.return_value.__enter__.return_value = session
    manager.get_session.return_value = session
    with (
        patch.object(browser_tools, "_get_tool_config", return_value=cfg),
        patch.object(browser_tools, "_validate_url", return_value=None),
        patch.object(browser_tools, "get_browser_session_manager", return_value=manager),
    ):
        await browser_tools.navigate_and_capture(thread_id="thread-1", url="https://example.com/", outputs_path=tmp_path)
        browser_tools._resolve_session(SimpleNamespace(context={"thread_id": "thread-1"}, state={}), cfg)

    assert manager.acquire_session.call_args.kwargs["engine"] == expected
    assert manager.get_session.call_args.kwargs["engine"] == expected
