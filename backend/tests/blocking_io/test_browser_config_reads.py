"""Regression anchors: the browser config gates read the live config off the loop.

``_browser_tools_enabled`` calls ``get_app_config()``, which stats and re-hashes
``config.yaml`` and ``extensions_config.json`` on every call and reparses them
after an edit (see ``config/AGENTS.md`` "Config Caching"). The live-view
WebSocket runs that gate on every connect, and the navigate route on every
request, so the read must run in a worker — the same seam #7557 fixed for route
authorization.

The live socket also reads ``get_tool_config("browser_navigate")`` for the
session settings, which pays the same per-call cost.

The strict Blockbuster gate from ``tests/blocking_io/conftest.py`` fails a test
whose body blocks the loop, so an anchor cannot pass by accident.
"""

from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.gateway.routers import browser as browser_router
from deerflow.config.app_config import get_app_config, reset_app_config
from deerflow.config.extensions_config import reset_extensions_config

pytestmark = pytest.mark.asyncio

_CONFIG_YAML = """sandbox:
  use: deerflow.sandbox.local:LocalSandboxProvider
tools:
  - name: browser_navigate
    group: browser
    use: deerflow.community.browser_automation.tools:browser_navigate_tool
"""


@pytest.fixture(autouse=True)
def _config_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(_CONFIG_YAML, encoding="utf-8")
    extensions_path = tmp_path / "extensions_config.json"
    extensions_path.write_text('{"mcpServers": {}, "skills": {}}', encoding="utf-8")
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions_path))
    reset_app_config()
    reset_extensions_config()


class _Recorder:
    """Counts config reads and records which threads performed them."""

    def __init__(self) -> None:
        self.calls = 0
        self.threads: list[int] = []

    def __call__(self):
        self.calls += 1
        self.threads.append(threading.get_ident())
        return get_app_config()


def _loop_thread() -> int:
    return threading.main_thread().ident or threading.get_ident()


async def test_capability_gate_reads_config_off_the_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = _Recorder()
    # _browser_tools_enabled rebinds get_app_config from deerflow.config at call
    # time (``from deerflow.config import get_app_config`` inside the function),
    # so the patch has to land on that module; a browser_router attribute would
    # be read by nothing.
    import deerflow.config as config_module

    monkeypatch.setattr(config_module, "get_app_config", recorder)

    await browser_router._browser_tools_enabled_async()

    assert recorder.calls >= 1, "the gate must read the live config"
    assert recorder.threads[0] != _loop_thread(), "the config read must run in a worker, not on the loop"


async def test_the_gate_swallows_config_failures_without_leaving_the_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    """The gate suppresses config errors; that must not mask an on-loop read.

    ``_browser_tools_enabled`` wraps its read in ``contextlib.suppress(Exception)``
    so a broken config disables the surface instead of failing the request. A
    Blockbuster error raised on the loop would be swallowed too, which is why
    this module asserts the reading thread rather than relying on the gate
    raising: here the read still happens, in a worker, even when it fails.
    """
    recorder = _Recorder()
    import deerflow.config as config_module

    def _broken():
        recorder.calls += 1
        recorder.threads.append(threading.get_ident())
        raise ValueError("config unreadable")

    monkeypatch.setattr(config_module, "get_app_config", _broken)

    assert await browser_router._browser_tools_enabled_async() is False

    assert recorder.calls == 1
    assert recorder.threads[0] != _loop_thread(), "even a failing read must run in a worker"


class _StopAfterToolConfig(Exception):
    """Raised by the manager stub the socket calls right after the tool-config read."""


async def test_browser_stream_reads_tool_config_off_the_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    """The live socket's second config read is the one this module documents.

    ``browser_stream`` resolves ``get_tool_config("browser_navigate")`` after the
    capability gate, for the session's headless/viewport/cdp_url settings. It
    pays the same per-call stat + hash, so it must run in a worker too — and
    unlike the gate it is not covered by any other anchor.
    """
    recorder = _Recorder()
    import deerflow.config as config_module

    monkeypatch.setattr(config_module, "get_app_config", recorder)
    # Fake the gate's verdict: playwright is absent in CI venvs, so the real
    # capability check would short-circuit before the read under test.
    monkeypatch.setattr(browser_router, "_browser_tools_enabled_async", AsyncMock(return_value=True))
    monkeypatch.setattr(browser_router, "_browser_thread_owned_by", AsyncMock(return_value=True))
    monkeypatch.setattr(browser_router, "_negotiate_browser_frame_format", AsyncMock(return_value=False))
    monkeypatch.setattr(browser_router, "_authenticate_ws", AsyncMock(return_value=MagicMock(id="u1")))
    # Every guard between the handshake and the read under test.
    monkeypatch.setattr(browser_router, "_ws_origin_allowed", lambda websocket: True)
    monkeypatch.setattr(browser_router, "resolve_route_permissions", AsyncMock(return_value={browser_router.Permissions.THREADS_WRITE}))

    websocket = MagicMock()
    websocket.app.state.thread_store = MagicMock()
    # The socket's failure path awaits close(); a bare MagicMock is not awaitable.
    websocket.close = AsyncMock()
    websocket.send_text = AsyncMock()

    # The manager lookup follows the read under test; stop there. browser_stream
    # binds get_browser_session_manager with a function-local import, so the
    # patch has to land on deerflow.community.browser_automation — a
    # browser_router attribute would be read by nothing.
    import deerflow.community.browser_automation as browser_automation

    fake_manager = MagicMock()
    fake_manager.acquire_session = MagicMock(side_effect=_StopAfterToolConfig())
    monkeypatch.setattr(browser_automation, "get_browser_session_manager", lambda: fake_manager)

    await browser_router.browser_stream(websocket, "thread-1")

    # The stub has to fire: otherwise the test runs past the seam it names, hits
    # the real manager, and would still pass on a broad escape. The socket's own
    # `except Exception` turns the stub's error into close(4501), so the visible
    # evidence is the call plus that close.
    assert fake_manager.acquire_session.call_count == 1
    websocket.close.assert_awaited_once_with(code=4501)
    # The real factory caches a process-global singleton and builds Playwright
    # state; the stub must keep it from ever running.
    from deerflow.community.browser_automation import session as browser_session

    assert browser_session._manager is None
    assert recorder.calls >= 1, "the socket must read the tool config"
    assert recorder.threads[0] != _loop_thread(), "the tool-config read must run in a worker, not on the loop"
