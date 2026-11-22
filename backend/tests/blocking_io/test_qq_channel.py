"""QQ transport setup, token requests and message routing must stay async."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.channels.message_bus import MessageBus, OutboundMessage
from app.channels.qq import QQChannel


@pytest.mark.asyncio
async def test_qq_transport_and_message_path_do_not_block(monkeypatch):
    channel = QQChannel(MessageBus(), {"app_id": "fixture-app", "client_secret": "fixture-secret"})
    try:
        # Real SSL trust loading and httpx initialization; only network replies
        # are replaced. This fails if initialization moves onto the event loop.
        await channel._setup_transport()
        monkeypatch.setattr(
            channel._http,
            "post",
            AsyncMock(
                return_value=httpx.Response(
                    200,
                    json={"access_token": "fixture-token", "expires_in": 7200},
                    request=httpx.Request("POST", "https://bots.qq.com/app/getAppAccessToken"),
                )
            ),
        )
        request = AsyncMock(return_value=httpx.Response(200, json={"id": "reply"}))
        monkeypatch.setattr(channel._http, "request", request)
        await channel._handle_inbound(
            {
                "t": "C2C_MESSAGE_CREATE",
                "d": {
                    "id": "source",
                    "content": "hello",
                    "author": {"user_openid": "alice"},
                },
            }
        )
        assert channel.bus.get_inbound_nowait().user_id == "alice"
        await channel.send(
            OutboundMessage(
                channel_name="qq",
                chat_id="c2c:alice",
                thread_id="thread",
                thread_ts="source",
                text="reply",
            )
        )
        request.assert_awaited_once()
    finally:
        await channel.stop()


@pytest.mark.asyncio
async def test_qq_notification_serialized_http_path_does_not_block():
    requests = []

    def respond(request):
        requests.append(request)
        if request.url.host == "bots.qq.com":
            return httpx.Response(200, json={"access_token": "fixture-token", "expires_in": 7200})
        return httpx.Response(200, json={"id": "notification"})

    repo = SimpleNamespace(
        list_connections=AsyncMock(
            return_value=[
                {
                    "owner_user_id": "owner",
                    "provider": "qq",
                    "status": "connected",
                    "external_account_id": "user-openid",
                    "workspace_id": "app1:c2c",
                    "metadata": {"chat_type": "c2c"},
                }
            ]
        )
    )
    channel = QQChannel(MessageBus(), {"app_id": "app1", "client_secret": "fixture-secret", "connection_repo": repo})
    try:
        await channel._setup_transport()
        await channel._http.aclose()
        channel._http = await asyncio.to_thread(httpx.AsyncClient, transport=httpx.MockTransport(respond), timeout=15, trust_env=False)
        channel._running = True
        channel._ready.set()
        channel._listener = asyncio.create_task(asyncio.Event().wait())
        await channel.send_notification_for_owner(owner_user_id="owner", target="user-openid", text_markdown="任务完成")
        assert len(requests) == 2
        assert requests[1].url.path == "/v2/users/user-openid/messages"
        assert json.loads(requests[1].content) == {"msg_type": 0, "content": "任务完成"}
    finally:
        await channel.stop()
