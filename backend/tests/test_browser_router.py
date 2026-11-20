import asyncio
import ipaddress
import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from _router_auth_helpers import make_authed_test_app
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.gateway.auth.models import User
from app.gateway.routers import browser as browser_router
from app.gateway.routers.browser import (
    _negotiate_browser_frame_format,
    _send_browser_frame,
    _should_apply_browser_seed,
    _ws_origin_allowed,
)
from deerflow.config.authorization_config import AuthorizationConfig


@pytest.fixture(autouse=True)
def _isolate_route_authorization(monkeypatch):
    # Existing routing/ownership tests must not inherit local operator policies.
    monkeypatch.setattr("app.gateway.authz._get_route_authorization_config", lambda: AuthorizationConfig(enabled=False))


class _FakeWebSocket:
    """Minimal stand-in exposing only the headers ``_ws_origin_allowed`` reads."""

    def __init__(self, headers: dict[str, str]):
        self.headers = {k.lower(): v for k, v in headers.items()}


def _user(user_id: str = "browser-user") -> SimpleNamespace:
    return SimpleNamespace(id=user_id)


def _browser_ws_app(thread_store=...):
    app = FastAPI()
    app.include_router(browser_router.router)
    if thread_store is not ...:
        app.state.thread_store = thread_store
    return app


def _expect_ws_close(app: FastAPI, code: int, *, headers: dict[str, str] | None = None) -> None:
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect("/api/threads/thread-1/browser/stream", headers=headers or {}):
                pass
    assert exc_info.value.code == code


def test_browser_stream_closes_4401_when_unauthenticated():
    app = _browser_ws_app()
    with patch.object(browser_router, "_authenticate_ws", AsyncMock(return_value=None)):
        _expect_ws_close(app, 4401)


def test_browser_stream_closes_4403_for_cross_origin_upgrade():
    app = _browser_ws_app()
    with patch.object(browser_router, "_authenticate_ws", AsyncMock(return_value=_user())):
        _expect_ws_close(app, 4403, headers={"origin": "https://evil.example.com"})


def test_browser_stream_closes_4404_when_thread_store_missing():
    app = _browser_ws_app()
    with patch.object(browser_router, "_authenticate_ws", AsyncMock(return_value=_user())):
        _expect_ws_close(app, 4404)


@pytest.mark.parametrize("record", [None, {"user_id": None}, {"user_id": "another-user"}])
def test_browser_stream_rejects_missing_or_unowned_thread(record):
    store = MagicMock()
    store.check_access = AsyncMock(return_value=True)
    store.get = AsyncMock(return_value=record)
    app = _browser_ws_app(store)
    with (
        patch.object(browser_router, "_authenticate_ws", AsyncMock(return_value=_user())),
        patch.object(browser_router, "_browser_tools_enabled", return_value=False),
    ):
        _expect_ws_close(app, 4404)
    store.get.assert_awaited_once_with("thread-1", user_id="browser-user")


def test_browser_stream_closes_4404_when_tools_disabled_for_owned_thread():
    store = MagicMock()
    store.check_access = AsyncMock(return_value=True)
    store.get = AsyncMock(return_value={"thread_id": "thread-1", "user_id": "browser-user"})
    app = _browser_ws_app(store)
    with (
        patch.object(browser_router, "_authenticate_ws", AsyncMock(return_value=_user())),
        patch.object(browser_router, "_browser_tools_enabled", return_value=False),
    ):
        _expect_ws_close(app, 4404)


def test_browser_stream_rejects_owned_chat_thread_before_loading_browser():
    store = MagicMock()
    store.get = AsyncMock(return_value={"user_id": "browser-user", "metadata": {"mode": "chat"}})
    app = _browser_ws_app(store)
    with (
        patch.object(browser_router, "_authenticate_ws", AsyncMock(return_value=_user())),
        patch.object(browser_router, "_browser_tools_enabled", return_value=False) as check_tools,
    ):
        _expect_ws_close(app, 4403)
    check_tools.assert_not_called()


def test_browser_navigate_rejects_owned_chat_thread_before_loading_browser():
    user = User(email="browser@example.com", password_hash="x", system_role="user")
    app = make_authed_test_app(user_factory=lambda: user)
    app.include_router(browser_router.router)
    app.state.thread_store.get = AsyncMock(return_value={"user_id": str(user.id), "metadata": {"mode": "chat"}})
    with patch.object(browser_router, "_browser_tools_enabled", return_value=False) as check_tools:
        response = TestClient(app).post("/api/threads/thread-1/browser/navigate", json={"url": "https://example.com"})
    assert response.status_code == 422
    assert "Chat mode" in response.json()["detail"]
    check_tools.assert_not_called()


def test_browser_stream_closes_4501_when_browser_runtime_unavailable():
    store = MagicMock()
    store.check_access = AsyncMock(return_value=True)
    store.get = AsyncMock(return_value={"thread_id": "thread-1", "user_id": "browser-user"})
    app = _browser_ws_app(store)
    real_import = __import__

    def fail_browser_runtime_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "deerflow.community.browser_automation" and "get_browser_session_manager" in fromlist:
            raise ImportError("browser runtime unavailable")
        return real_import(name, globals, locals, fromlist, level)

    with (
        patch.object(browser_router, "_authenticate_ws", AsyncMock(return_value=_user())),
        patch.object(browser_router, "_browser_tools_enabled", return_value=True),
        patch("builtins.__import__", side_effect=fail_browser_runtime_import),
    ):
        _expect_ws_close(app, 4501)


def test_browser_navigate_rejects_legacy_null_owner_thread():
    user = User(email="browser@example.com", password_hash="x", system_role="user")
    app = make_authed_test_app(user_factory=lambda: user)
    app.include_router(browser_router.router)
    app.state.thread_store.get = AsyncMock(return_value={"thread_id": "thread-1", "user_id": None})

    with (
        patch.object(browser_router, "_browser_tools_enabled", return_value=True),
        patch("deerflow.community.browser_automation.navigate_and_capture", new=AsyncMock()),
    ):
        response = TestClient(app).post(
            "/api/threads/thread-1/browser/navigate",
            json={"url": "https://example.com"},
        )

    assert response.status_code == 404
    app.state.thread_store.get.assert_awaited_once_with("thread-1", user_id=str(user.id))


def test_browser_tools_disabled_when_cdp_risk_not_explicitly_accepted():
    tool_cfg = SimpleNamespace(name="browser_navigate", model_extra={"cdp_url": "http://127.0.0.1:9222"})
    app_config = SimpleNamespace(tools=[tool_cfg])

    with (
        patch("deerflow.config.get_app_config", return_value=app_config),
        patch("app.gateway.browser_capability.browser_multi_worker_error", return_value=None),
        patch("app.gateway.browser_capability.importlib.util.find_spec", return_value=object()),
    ):
        assert browser_router._browser_tools_enabled() is False


def test_browser_tools_enabled_when_cdp_risk_explicitly_accepted():
    tool_cfg = SimpleNamespace(
        name="browser_navigate",
        model_extra={"cdp_url": "http://127.0.0.1:9222", "allow_unguarded_cdp": True},
    )
    app_config = SimpleNamespace(tools=[tool_cfg])

    with (
        patch("deerflow.config.get_app_config", return_value=app_config),
        patch("app.gateway.browser_capability.browser_multi_worker_error", return_value=None),
        patch("app.gateway.browser_capability.importlib.util.find_spec", return_value=object()),
    ):
        assert browser_router._browser_tools_enabled() is True


def test_browser_navigate_redacts_failure_url_from_logs_and_response(caplog):
    user = User(email="browser@example.com", password_hash="x", system_role="user")
    app = make_authed_test_app(user_factory=lambda: user)
    app.include_router(browser_router.router)
    app.state.thread_store.get = AsyncMock(return_value={"thread_id": "thread-1", "user_id": str(user.id)})
    failing_url = "https://example.com/callback?code=secret#fragment"

    caplog.set_level(logging.ERROR, logger="app.gateway.routers.browser")
    with (
        patch.object(browser_router, "_browser_tools_enabled", return_value=True),
        patch(
            "deerflow.community.browser_automation.navigate_and_capture",
            new=AsyncMock(side_effect=RuntimeError(f"timed out opening {failing_url}")),
        ),
    ):
        response = TestClient(app).post(
            "/api/threads/thread-1/browser/navigate",
            json={"url": failing_url},
        )

    assert response.status_code == 502
    assert response.json() == {"detail": "Browser navigation failed"}
    assert "https://example.com/callback" in caplog.text
    assert "code=secret" not in caplog.text
    assert "fragment" not in caplog.text
    assert "secret" not in response.text


def test_browser_stream_seed_applies_to_blank_page():
    assert _should_apply_browser_seed("about:blank", "https://github.com/bytedance/deer-flow")


def test_browser_stream_seed_applies_when_current_url_differs():
    assert _should_apply_browser_seed(
        "https://docs.byteplus.com/en/docs/InfoQuest/What_is_Info_Quest",
        "https://github.com/bytedance/deer-flow",
    )


def test_browser_stream_seed_ignores_hash_and_trailing_slash_for_same_page():
    assert not _should_apply_browser_seed(
        "https://github.com/bytedance/deer-flow/#readme",
        "https://github.com/bytedance/deer-flow/",
    )


def test_ws_origin_allowed_without_origin_header():
    # Native ws clients / tests do not send Origin — allow them.
    assert _ws_origin_allowed(_FakeWebSocket({"host": "app.example.com"})) is True


def test_ws_origin_allowed_same_origin_host():
    # Browser page scheme (https) differs from the ws scheme, so same-origin
    # compares host[:port] against the upgrade target Host.
    ws = _FakeWebSocket({"origin": "https://app.example.com", "host": "app.example.com"})
    assert _ws_origin_allowed(ws) is True


@pytest.mark.asyncio
async def test_send_browser_frame_uses_binary_websocket_message_when_requested():
    websocket = MagicMock()
    websocket.send_bytes = AsyncMock()
    websocket.send_text = AsyncMock()

    await _send_browser_frame(websocket, b"\xff\xd8jpeg", binary=True)

    websocket.send_bytes.assert_awaited_once_with(b"\xff\xd8jpeg")
    websocket.send_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_browser_frame_keeps_legacy_base64_json_protocol():
    websocket = MagicMock()
    websocket.send_bytes = AsyncMock()
    websocket.send_text = AsyncMock()

    await _send_browser_frame(websocket, b"\xff\xd8jpeg", binary=False)

    websocket.send_bytes.assert_not_awaited()
    payload = json.loads(websocket.send_text.await_args.args[0])
    assert payload == {"type": "frame", "data": "/9hq cGVn".replace(" ", "")}


@pytest.mark.asyncio
async def test_browser_frame_format_rejects_unknown_capability():
    websocket = MagicMock()
    websocket.query_params = {"frame_format": "avif"}
    websocket.accept = AsyncMock()
    websocket.send_text = AsyncMock()
    websocket.close = AsyncMock()

    result = await _negotiate_browser_frame_format(websocket)

    assert result is None
    websocket.accept.assert_awaited_once()
    payload = json.loads(websocket.send_text.await_args.args[0])
    assert payload["type"] == "error"
    assert "frame_format" in payload["message"]
    websocket.close.assert_awaited_once_with(code=1008)


@pytest.mark.asyncio
@pytest.mark.parametrize(("value", "expected"), [(None, False), ("binary", True)])
async def test_browser_frame_format_accepts_legacy_and_binary(value, expected):
    websocket = MagicMock()
    websocket.query_params = {} if value is None else {"frame_format": value}
    websocket.accept = AsyncMock()
    websocket.send_text = AsyncMock()
    websocket.close = AsyncMock()

    assert await _negotiate_browser_frame_format(websocket) is expected
    websocket.accept.assert_awaited_once()
    websocket.send_text.assert_not_awaited()
    websocket.close.assert_not_awaited()


def test_ws_origin_allowed_rejects_cross_origin():
    ws = _FakeWebSocket({"origin": "https://evil.example.com", "host": "app.example.com"})
    assert _ws_origin_allowed(ws) is False


def test_ws_origin_allowed_rejects_malformed_origin():
    ws = _FakeWebSocket({"origin": "not-a-url", "host": "app.example.com"})
    assert _ws_origin_allowed(ws) is False


def test_ws_origin_allowed_honors_configured_cors_origin(monkeypatch):
    monkeypatch.setenv("GATEWAY_CORS_ORIGINS", "https://console.example.com")
    ws = _FakeWebSocket({"origin": "https://console.example.com", "host": "gateway.internal"})
    assert _ws_origin_allowed(ws) is True


def test_ws_origin_allowed_honors_forwarded_host():
    # Behind a proxy the real upgrade target is X-Forwarded-Host, not Host.
    ws = _FakeWebSocket(
        {
            "origin": "https://app.example.com",
            "host": "gateway.internal",
            "x-forwarded-host": "app.example.com",
        },
    )
    assert _ws_origin_allowed(ws) is True


def test_browser_frames_dirname_shared_between_tools_and_scanner():
    """The screenshots dir name must stay identical in the writer and the scanner.

    Both sides import the single ``BROWSER_FRAMES_DIRNAME`` constant; this locks
    that they resolve to the same value so the workspace-changes ignore cannot
    silently drift away from where the browser tools write frames.
    """
    from deerflow.community.browser_automation import tools as browser_tools
    from deerflow.constants import BROWSER_FRAMES_DIRNAME
    from deerflow.workspace_changes.scanner import EXCLUDED_DIR_NAMES

    assert browser_tools._BROWSER_FRAMES_DIRNAME == BROWSER_FRAMES_DIRNAME
    assert BROWSER_FRAMES_DIRNAME in EXCLUDED_DIR_NAMES


def test_validate_browser_url_rejects_private_and_non_http(monkeypatch):
    """WS seed / navigate events reuse the same SSRF policy as the agent tools.

    With no ``allow_private_addresses`` override the shared validator must reject
    loopback / metadata / non-http targets, so the live stream cannot be steered
    at internal infrastructure.
    """
    from deerflow.community.browser_automation import tools as browser_tools
    from deerflow.community.browser_automation import validate_browser_url

    # Isolate from any local config.yaml that may set allow_private_addresses.
    monkeypatch.setattr(browser_tools, "_get_tool_config", lambda _tool_name: {})

    assert validate_browser_url("http://169.254.169.254/latest/meta-data/") is not None
    assert validate_browser_url("http://127.0.0.1:8001/") is not None
    assert validate_browser_url("file:///etc/passwd") is not None
    assert validate_browser_url("ftp://example.com") is not None
    # A normal public URL passes (returns None = allowed).
    monkeypatch.setattr(browser_tools, "_resolve_host_addresses", lambda _host: [ipaddress.ip_address("93.184.215.14")])
    assert validate_browser_url("https://github.com/bytedance/deer-flow") is None


def test_browser_stream_resolves_seed_and_navigate_urls_off_the_loop():
    store = MagicMock()
    store.check_access = AsyncMock(return_value=True)
    store.get = AsyncMock(return_value={"thread_id": "thread-1", "user_id": "browser-user"})
    app = _browser_ws_app(store)
    session = MagicMock()
    for method in ("current_url", "navigate", "start_screencast", "stop_screencast", "tabs", "dispatch_input"):
        setattr(session, method, AsyncMock())
    session.current_url.return_value = "about:blank"
    session.tabs.return_value = []
    manager = MagicMock()
    manager.acquire_session.return_value.__enter__.return_value = session
    resolved_on_loop: dict[str, bool] = {}

    def resolve(host: str) -> list[ipaddress._BaseAddress]:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            resolved_on_loop[host] = False
        else:
            resolved_on_loop[host] = True
        return [ipaddress.ip_address("127.0.0.1" if host == "internal.example" else "93.184.215.14")]

    from deerflow.community.browser_automation import tools as browser_tools

    with (
        patch.object(browser_router, "_authenticate_ws", AsyncMock(return_value=_user())),
        patch.object(browser_router, "_browser_tools_enabled", return_value=True),
        patch("deerflow.config.get_app_config", return_value=SimpleNamespace(get_tool_config=lambda _name: None)),
        patch("deerflow.community.browser_automation.get_browser_session_manager", return_value=manager),
        patch.object(browser_tools, "_get_tool_config", return_value={}),
        patch.object(browser_tools, "_resolve_host_addresses", side_effect=resolve),
        TestClient(app) as client,
        client.websocket_connect("/api/threads/thread-1/browser/stream?seed=https://seed.example/") as ws,
    ):
        ws.send_text(json.dumps({"type": "navigate", "url": "https://internal.example/"}))
        while (payload := ws.receive_json())["type"] != "nav_rejected":
            pass

    assert payload["url"] == "https://internal.example/"
    session.navigate.assert_awaited_once_with("https://seed.example/")
    session.dispatch_input.assert_not_awaited()
    assert resolved_on_loop == {"seed.example": False, "internal.example": False}


def test_browser_stream_acquires_the_session_with_pinned_egress():
    # The first caller's launch options stick to a thread's session, so a Live
    # viewer that opens it first must not launch Chromium without the egress proxy.
    store = MagicMock()
    store.check_access = AsyncMock(return_value=True)
    store.get = AsyncMock(return_value={"thread_id": "thread-1", "user_id": "browser-user"})
    app = _browser_ws_app(store)
    session = MagicMock()
    for method in ("current_url", "start_screencast", "stop_screencast", "tabs"):
        setattr(session, method, AsyncMock())
    session.current_url.return_value = None
    session.tabs.return_value = []
    manager = MagicMock()
    manager.acquire_session.return_value.__enter__.return_value = session

    from deerflow.community.browser_automation import resolve_browser_egress

    with (
        patch.object(browser_router, "_authenticate_ws", AsyncMock(return_value=_user())),
        patch.object(browser_router, "_browser_tools_enabled", return_value=True),
        patch("deerflow.config.get_app_config", return_value=SimpleNamespace(get_tool_config=lambda _name: None)),
        patch("deerflow.community.browser_automation.get_browser_session_manager", return_value=manager),
        TestClient(app) as client,
        client.websocket_connect("/api/threads/thread-1/browser/stream") as ws,
    ):
        # The upgrade is accepted before the route reads config and acquires the session.
        assert ws.receive_json() == {"type": "tabs", "tabs": []}

    manager.acquire_session.assert_called_once()
    assert manager.acquire_session.call_args.kwargs["egress_resolver"] is resolve_browser_egress


@pytest.fixture
def live_browser():
    store = MagicMock()
    store.get = AsyncMock(return_value={"user_id": "browser-user"})
    ws = MagicMock()
    ws.headers = {}
    ws.query_params = {}
    ws.app.state.thread_store = store
    ws.accept = AsyncMock()
    ws.close = AsyncMock()
    ws.send_text = AsyncMock()
    ws.receive_text = asyncio.Event().wait  # The client remains connected and idle.
    session = MagicMock()
    session.current_url = AsyncMock(return_value=None)
    session.tabs = AsyncMock(return_value=[])
    session.start_screencast = AsyncMock()
    session.stop_screencast = AsyncMock()
    manager = MagicMock()
    lease = manager.acquire_session.return_value
    lease.__enter__.return_value = session
    with (
        patch.object(browser_router, "_authenticate_ws", AsyncMock(return_value=_user())),
        patch.object(browser_router, "_browser_tools_enabled", return_value=True),
        patch("deerflow.config.get_app_config", return_value=SimpleNamespace(get_tool_config=lambda _: None)),
        patch("deerflow.community.browser_automation.get_browser_session_manager", return_value=manager),
    ):
        yield ws, session, lease, store


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("next_record", "close_code", "blocked_start"),
    [
        ({"user_id": "browser-user", "metadata": {"mode": "chat"}}, 4403, False),
        ({"user_id": "other-user"}, 4404, False),
        (OSError("store unavailable"), 4501, False),
        pytest.param({"user_id": "browser-user", "metadata": {"mode": "chat"}}, 4403, True, id="chat-during-startup"),
    ],
)
async def test_live_browser_closes_and_releases_idle_socket_after_access_changes(live_browser, next_record, close_code, blocked_start):
    ws, session, lease, store = live_browser
    store.get = AsyncMock(side_effect=[{"user_id": "browser-user"}, next_record])
    startup_cancelled = asyncio.Event()

    async def start_screencast(_callback):
        if blocked_start:
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                startup_cancelled.set()
                raise

    session.start_screencast = AsyncMock(side_effect=start_screencast)
    with patch.object(browser_router, "_BROWSER_ACCESS_CHECK_SECONDS", 0):
        await asyncio.wait_for(browser_router.browser_stream(ws, "thread-1"), timeout=2)
    ws.accept.assert_awaited_once()
    ws.close.assert_awaited_once_with(code=close_code)
    if blocked_start:
        assert startup_cancelled.is_set()
    session.stop_screencast.assert_awaited_once()
    lease.__exit__.assert_called_once()


@pytest.mark.asyncio
async def test_location_update_reaches_slow_live_browser_while_access_is_checked(live_browser):
    ws, session, _, store = live_browser
    session.current_url = AsyncMock(side_effect=[None, "https://visited.example/"])
    delivered = asyncio.Event()

    async def send_text(raw):
        if json.loads(raw)["type"] == "url":
            before = store.get.await_count
            await asyncio.sleep(0.1)
            assert store.get.await_count > before
            delivered.set()

    async def receive_text():
        await delivered.wait()
        raise WebSocketDisconnect()

    ws.send_text = send_text
    ws.receive_text = receive_text
    with patch.object(browser_router, "_BROWSER_ACCESS_CHECK_SECONDS", 0.02):
        await asyncio.wait_for(browser_router.browser_stream(ws, "thread-1"), timeout=2)
    assert delivered.is_set()


def test_browser_navigate_reports_thread_read_timeout_as_unavailable():
    user = User(email="browser@example.com", password_hash="x", system_role="user")
    app = make_authed_test_app(user_factory=lambda: user)
    app.include_router(browser_router.router)
    app.state.thread_store.get = AsyncMock(side_effect=TimeoutError())
    with patch.object(browser_router, "_browser_tools_enabled") as check_tools:
        response = TestClient(app, raise_server_exceptions=False).post("/api/threads/thread-1/browser/navigate", json={"url": "https://example.com"})
    assert response.status_code == 503
    check_tools.assert_not_called()


@pytest.mark.asyncio
async def test_peer_disconnect_during_live_frame_does_not_log_stream_failure(live_browser, caplog):
    ws, session, lease, _ = live_browser

    async def start_screencast(on_frame):
        on_frame(b"jpeg")

    session.start_screencast.side_effect = start_screencast
    ws.query_params = {"frame_format": "binary"}
    ws.send_bytes = AsyncMock(side_effect=WebSocketDisconnect(code=1000))
    with caplog.at_level(logging.ERROR, logger=browser_router.__name__):
        await asyncio.wait_for(browser_router.browser_stream(ws, "thread-1"), timeout=2)
    ws.send_bytes.assert_awaited_once_with(b"jpeg")
    lease.__exit__.assert_called_once()
    assert "browser stream error" not in caplog.text
