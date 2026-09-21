"""Offline A1 regression: fake identity/store/browser, real route authorization.

No real account, database, browser, network listener, or model is used.
"""

import asyncio
import base64
import json
import threading
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.gateway.auth_disabled import get_auth_disabled_user
from app.gateway.auth_middleware import AuthMiddleware
from app.gateway.routers import browser
from deerflow.authz.provider import AuthzDecision
from deerflow.authz.rbac import RbacAuthorizationProvider
from deerflow.config.authorization_config import AuthorizationConfig


@pytest.mark.parametrize("role", ["admin", "user"])
@pytest.mark.parametrize("writable", [False, True])
@pytest.mark.parametrize("binary", [False, True])
def test_browser_stream_enforces_write_permission(monkeypatch, role, writable, binary):
    permissions = ["threads:read", "runs:read", "projects:read"]
    if writable:
        permissions.append("threads:write")
    policy = {
        "routes": {"allow": permissions},
        "tools": {"allow": False},
        "sandbox": {"allow": False},
        "mcp_servers": {"allow": False},
        "models": {"allow": "*"},
        "skills": {"allow": "*"},
    }
    provider = RbacAuthorizationProvider(roles={"admin": policy, "user": policy})
    config = AuthorizationConfig(enabled=True, fail_closed=True, default_role="user")
    monkeypatch.setattr("app.gateway.authz._get_route_authorization_config", lambda: config)
    monkeypatch.setattr("app.gateway.authz._get_cached_route_provider", lambda _: provider)
    user = SimpleNamespace(id="readonly-demo-owner", system_role=role, oauth_provider=None, oauth_id=None)
    monkeypatch.setattr("app.gateway.deps.get_current_user_from_request", AsyncMock(return_value=user))
    monkeypatch.setattr(browser, "_authenticate_ws", AsyncMock(return_value=user))
    monkeypatch.setattr(browser, "_browser_tools_enabled", lambda: True)
    monkeypatch.setattr("deerflow.config.get_app_config", lambda: SimpleNamespace(get_tool_config=lambda _: None))

    received = threading.Event()
    frame_sent = threading.Event()
    send_browser_frame = browser._send_browser_frame

    async def send_frame(websocket, data, *, binary):
        await send_browser_frame(websocket, data, binary=binary)
        frame_sent.set()

    monkeypatch.setattr(browser, "_send_browser_frame", send_frame)
    events = []
    acquisitions = []
    frame = b"\xff\xd8\xffsynthetic-frame\xff\xd9"

    async def start_screencast(on_frame):
        on_frame(frame)

    session = SimpleNamespace(
        start_screencast=AsyncMock(side_effect=start_screencast),
        stop_screencast=AsyncMock(),
        current_url=AsyncMock(return_value="about:blank"),
        tabs=AsyncMock(return_value=[]),
    )

    async def dispatch_input(event):
        events.append(event)
        received.set()

    session.dispatch_input = dispatch_input

    @contextmanager
    def acquire_session(thread_id, **kwargs):
        acquisitions.append(thread_id)
        yield session

    monkeypatch.setattr(
        "deerflow.community.browser_automation.get_browser_session_manager",
        lambda: SimpleNamespace(acquire_session=acquire_session),
    )
    app = FastAPI()
    app.include_router(browser.router)
    app.add_middleware(AuthMiddleware)
    app.state.thread_store = SimpleNamespace(get=AsyncMock(return_value={"user_id": user.id}))
    click = {"type": "click", "nx": 0.25, "ny": 0.5}
    close_code = None
    accepted = False
    with TestClient(app) as client:
        client.cookies.set("access_token", "synthetic-cookie-not-a-real-token")
        if not writable:
            response = client.post("/api/threads/test-thread/browser/navigate", json={"url": "https://example.invalid"})
            assert response.status_code == 403, response.text
            assert acquisitions == []
            print(f"{role}: HTTP navigation=403")
        try:
            path = "/api/threads/test-thread/browser/stream" + ("?frame_format=binary" if binary else "")
            with client.websocket_connect(path, headers={"origin": "http://testserver"}) as ws:
                accepted = True
                ws.send_json(click)
                assert received.wait(3), "Accepted connection, but no click reached the fake browser within 3 seconds"
                assert frame_sent.wait(3), "No frame was sent within 3 seconds"
                while True:
                    message = ws.receive()
                    if "bytes" in message:
                        assert binary and message["bytes"] == frame
                        break
                    payload = json.loads(message["text"])
                    if payload.get("type") == "frame":
                        assert not binary and payload["data"] == base64.b64encode(frame).decode("ascii")
                        break
        except WebSocketDisconnect as exc:
            close_code = exc.code

    print(f"{role}: writable={writable}, WS accepted={accepted}, close={close_code}, fake browser events={events}")
    if writable:
        assert accepted and events == [click]
        session.stop_screencast.assert_awaited_once()
    else:
        assert (accepted, close_code, acquisitions, events) == (False, 4403, [], []), "Read-only identity reached browser control"
        session.start_screencast.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["none", "resolve", "missing", "decision", "invalid_decision", "unknown_role"])
@pytest.mark.parametrize("fail_closed", [True, False])
async def test_browser_stream_uses_shared_authorization_failure_policy(monkeypatch, failure, fail_closed):
    config = AuthorizationConfig(enabled=True, fail_closed=fail_closed)
    monkeypatch.setattr("app.gateway.authz._get_route_authorization_config", lambda: config)
    decision = AsyncMock(return_value=AuthzDecision(allow=True, reasons=[]))
    if failure == "decision":
        decision.side_effect = RuntimeError("synthetic policy outage")
    elif failure == "invalid_decision":
        decision.return_value = None
    provider = SimpleNamespace(aauthorize=decision)
    if failure == "unknown_role":
        provider = RbacAuthorizationProvider(roles={"user": {"routes": {"allow": "*"}}})
    factory = MagicMock(return_value=None if failure == "missing" else provider)
    if failure == "resolve":
        factory.side_effect = ValueError("synthetic invalid provider")
    monkeypatch.setattr("app.gateway.authz._get_cached_route_provider", factory)
    user = get_auth_disabled_user()  # Synthetic admin must NOT bypass configured authorization.
    monkeypatch.setattr(browser, "_authenticate_ws", AsyncMock(return_value=user))
    websocket = MagicMock()
    websocket.headers = {}
    websocket.close = AsyncMock()
    websocket.app.state.thread_store.get = AsyncMock(return_value={"user_id": user.id})
    monkeypatch.setattr(browser, "_browser_tools_enabled", lambda: True)
    negotiate = AsyncMock(return_value=None)  # Stop before browser acquisition for allowed cases.
    monkeypatch.setattr(browser, "_negotiate_browser_frame_format", negotiate)

    await browser.browser_stream(websocket, "test-thread")

    if failure != "none" and fail_closed:
        websocket.close.assert_awaited_once_with(code=4403)
        websocket.app.state.thread_store.get.assert_not_awaited()
        negotiate.assert_not_awaited()
    else:
        negotiate.assert_awaited_once()
        websocket.close.assert_not_awaited()
    if failure == "none":
        assert all(not call.args[0].principal.is_internal for call in decision.await_args_list)


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [ValueError("synthetic config error"), asyncio.CancelledError()])
async def test_browser_stream_authorization_setup_error_or_cancellation_never_accepts(monkeypatch, caplog, error):
    monkeypatch.setattr(browser, "_authenticate_ws", AsyncMock(return_value=get_auth_disabled_user()))
    monkeypatch.setattr("app.gateway.authz._get_route_authorization_config", MagicMock(side_effect=error))
    websocket = MagicMock()
    websocket.headers = {}
    websocket.close = AsyncMock()
    negotiate = AsyncMock()
    monkeypatch.setattr(browser, "_negotiate_browser_frame_format", negotiate)

    if isinstance(error, asyncio.CancelledError):
        with pytest.raises(asyncio.CancelledError):
            await browser.browser_stream(websocket, "test-thread")
        websocket.close.assert_not_awaited()
    else:
        await browser.browser_stream(websocket, "test-thread")
        websocket.close.assert_awaited_once_with(code=4501)
    records = [record for record in caplog.records if record.name == browser.logger.name and record.getMessage() == "Failed to resolve browser stream permissions"]
    if isinstance(error, asyncio.CancelledError):
        assert records == []
    else:
        assert len(records) == 1
        assert records[0].exc_info is not None
        assert records[0].exc_info[1] is error
        assert records[0].exc_info[2] is not None
    negotiate.assert_not_awaited()
    websocket.app.state.thread_store.get.assert_not_called()


@pytest.mark.asyncio
async def test_browser_stream_rechecks_policy_on_new_connection(monkeypatch):
    config = AuthorizationConfig(enabled=False)
    monkeypatch.setattr("app.gateway.authz._get_route_authorization_config", lambda: config)
    provider = RbacAuthorizationProvider(roles={"admin": {"routes": {"allow": []}}})
    factory = MagicMock(return_value=provider)
    monkeypatch.setattr("app.gateway.authz._get_cached_route_provider", factory)
    monkeypatch.setattr(browser, "_authenticate_ws", AsyncMock(return_value=get_auth_disabled_user()))
    monkeypatch.setattr(browser, "_browser_tools_enabled", lambda: True)
    websocket = MagicMock()
    websocket.headers = {}
    websocket.close = AsyncMock()
    websocket.app.state.thread_store.get = AsyncMock(return_value={"user_id": get_auth_disabled_user().id})
    negotiate = AsyncMock(return_value=None)
    monkeypatch.setattr(browser, "_negotiate_browser_frame_format", negotiate)

    await browser.browser_stream(websocket, "test-thread")
    factory.assert_not_called()  # Disabled mode keeps legacy behavior.
    negotiate.assert_awaited_once()
    config.enabled = True
    await browser.browser_stream(websocket, "test-thread")
    websocket.close.assert_awaited_once_with(code=4403)
    negotiate.assert_awaited_once()  # Second connection never gets this far.
