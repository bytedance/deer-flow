"""Regression anchor: DingTalk AI card calls must not fetch a token on the loop.

dingtalk-stream's ``get_access_token()`` refreshes through ``requests.post``
with no timeout. Card creation (``_send_running_reply``) and card streaming
(``send``) both run on the Gateway loop, so a card call through the SDK's
``AICardReplier`` blocked the loop for the whole refresh, about every two
hours. The channel now sends card requests through its own httpx client with
its own token.

This anchor drives the real channel methods with a real
``DingTalkStreamClient`` whose token cache is empty, under the strict gate, and
asserts the card requests reached the local OpenAPI peer with the channel's
token. The SDK's endpoints point away from the real API (its token endpoint at
the discard port), so a call that slipped back to the SDK fails fast instead of
leaving the machine or hanging the loop.
"""

from __future__ import annotations

import pytest
from dingtalk_stream import card_replier, stream
from dingtalk_stream.chatbot import ChatbotMessage
from dingtalk_stream.credential import Credential
from dingtalk_stream.stream import DingTalkStreamClient
from support.local_sockets import LocalHttpServer

from app.channels import dingtalk as dingtalk_module
from app.channels.dingtalk import _CONVERSATION_TYPE_P2P, DingTalkChannel
from app.channels.message_bus import MessageBus

pytestmark = pytest.mark.asyncio

_UNREACHABLE_SDK_ENDPOINT = "http://127.0.0.1:9"


def _channel() -> DingTalkChannel:
    channel = DingTalkChannel(MessageBus(), config={"card_template_id": "tpl_123"})
    channel._client_id, channel._client_secret = "id", "secret"
    channel._dingtalk_client = DingTalkStreamClient(Credential("id", "secret"))
    return channel


def _incoming() -> ChatbotMessage:
    incoming = ChatbotMessage()
    incoming.conversation_type = _CONVERSATION_TYPE_P2P
    incoming.sender_staff_id = "user_001"
    return incoming


async def test_card_create_and_stream_never_fetch_the_sdk_token_on_the_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(stream, "DINGTALK_OPENAPI_ENDPOINT", _UNREACHABLE_SDK_ENDPOINT)
    async with LocalHttpServer(body={"accessToken": "tok", "expireIn": 7200}) as api:
        base = api.url.removesuffix("/open")
        monkeypatch.setattr(dingtalk_module, "DINGTALK_API_BASE", base)
        monkeypatch.setattr(card_replier, "DINGTALK_OPENAPI_ENDPOINT", base)
        channel = _channel()

        track = await channel._create_and_deliver_card("Working on it...", chatbot_message=_incoming())
        assert track
        await channel._stream_update_card(track, "done", is_finalize=True)

    assert [(method, path, headers.get("x-acs-dingtalk-access-token")) for method, path, headers in api.calls] == [
        ("POST", "/v1.0/oauth2/accessToken", None),
        ("POST", "/v1.0/card/instances/createAndDeliver", "tok"),
        ("PUT", "/v1.0/card/streaming", "tok"),
    ]
