"""QQ transport setup, token requests and message routing must stay async."""

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
