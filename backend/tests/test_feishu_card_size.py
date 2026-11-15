"""Feishu cards stay within the 30 KB card request body.

Feishu rejects a larger card (230025, "The length of the message content
reaches its limit"). Card text was unbounded and ASCII-escaped, 6 bytes per CJK
character in the card and 7 in the request body, so an answer of about 4,400
CJK characters failed its final patch and the reply fallback alike: the answer
was lost and the running card stayed on its last streamed text.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody, PatchMessageRequest, PatchMessageRequestBody, ReplyMessageRequest, ReplyMessageRequestBody
from lark_oapi.core.json import JSON

from app.channels.feishu import FEISHU_CARD_MAX_BYTES, FEISHU_MAX_CARDS_PER_REPLY, FeishuChannel, _card_text_bytes, _split_card_text
from app.channels.message_bus import MessageBus, OutboundMessage
from app.channels.store import JsonChannelStore

pytestmark = pytest.mark.asyncio

_FEISHU_CARD_BODY_LIMIT = 30 * 1024
_REJECTED = SimpleNamespace(success=lambda: False, code=230025, msg="The length of the message content reaches its limit", get_log_id=lambda: "log")


def _body_bytes(request) -> int:
    return len(JSON.marshal(request.request_body).encode("utf-8"))


def _card_text(request) -> str:
    return json.loads(request.request_body.content)["elements"][0]["content"]


class _FeishuApi:
    """Records card requests and rejects any whose body exceeds Feishu's limit."""

    def __init__(self) -> None:
        self.cards: dict[str, str] = {}
        self.replies: list[tuple[str, str]] = []
        self.patches: list[tuple[str, str]] = []
        self.created: list[tuple[str, str]] = []
        self.rejected: list[int] = []
        self.fail_next_reply = 0

    def _admit(self, request) -> bool:
        if _body_bytes(request) > _FEISHU_CARD_BODY_LIMIT:
            self.rejected.append(_body_bytes(request))
            return False
        return True

    def reply(self, request):
        if self.fail_next_reply:
            self.fail_next_reply -= 1
            raise ConnectionError("transient")
        if not self._admit(request):
            return _REJECTED
        card_id = f"card-{len(self.cards) + 1}"
        self.cards[card_id] = _card_text(request)
        self.replies.append((request.message_id, card_id))
        return SimpleNamespace(success=lambda: True, data=SimpleNamespace(message_id=card_id))

    def patch(self, request):
        if not self._admit(request):
            return _REJECTED
        self.cards[request.message_id] = _card_text(request)
        self.patches.append((request.message_id, _card_text(request)))
        return SimpleNamespace(success=lambda: True)

    def create(self, request):
        if not self._admit(request):
            return _REJECTED
        self.created.append((request.request_body.receive_id, _card_text(request)))
        return SimpleNamespace(success=lambda: True)


@pytest.fixture
def feishu(tmp_path, monkeypatch):
    monkeypatch.setattr("app.channels.base.asyncio.sleep", AsyncMock())
    channel = FeishuChannel(MessageBus(), {"app_id": "offline-test", "app_secret": "offline-test"})
    channel.config["channel_store"] = JsonChannelStore(path=tmp_path / "store.json")
    for name, cls in (
        ("_ReplyMessageRequest", ReplyMessageRequest),
        ("_ReplyMessageRequestBody", ReplyMessageRequestBody),
        ("_PatchMessageRequest", PatchMessageRequest),
        ("_PatchMessageRequestBody", PatchMessageRequestBody),
        ("_CreateMessageRequest", CreateMessageRequest),
        ("_CreateMessageRequestBody", CreateMessageRequestBody),
    ):
        setattr(channel, name, cls)
    api = _FeishuApi()
    channel._api_client = MagicMock()
    channel._api_client.im.v1.message.reply.side_effect = api.reply
    channel._api_client.im.v1.message.patch.side_effect = api.patch
    channel._api_client.im.v1.message.create.side_effect = api.create
    return SimpleNamespace(channel=channel, api=api)


def _outbound(text: str, *, final: bool, source: str | None = "source-1") -> OutboundMessage:
    return OutboundMessage(channel_name="feishu", chat_id="oc-chat", thread_id="thread-1", text=text, is_final=final, thread_ts=source, metadata={"user_id": "ou-user"})


def _long_answer(lines: int = 300) -> str:
    # About 18,000 CJK characters: four cards at the budget.
    return "".join(f"第{index}段：这是一段很长的中文回答，用来测试飞书卡片的大小限制。\n" * 3 for index in range(lines))


@pytest.mark.parametrize("text", ["plain", "中文回答", 'quote " and \\ backslash', "line\nbreak\ttab\r\b\f", "emoji 😀 and 한국어 é", "\x01control\x7f", "lone \ud83d surrogate", "\u2028 separators \u2029"])
async def test_card_text_bytes_match_the_sdk_request_body(text):
    def body(content_text: str) -> int:
        request_body = PatchMessageRequestBody.builder().content(FeishuChannel._build_card_content(content_text)).build()
        return len(JSON.marshal(request_body).encode("utf-8"))

    assert body(text) - body("") == _card_text_bytes(text)


async def test_cjk_card_content_is_not_ascii_escaped():
    content = FeishuChannel._build_card_content("中文")

    assert "中文" in content
    assert json.loads(content)["elements"][0]["content"] == "中文"


async def test_long_text_splits_on_lines_into_cards_that_fit():
    answer = _long_answer()

    cards = _split_card_text(answer)

    assert len(cards) > 1
    assert "".join(cards) == answer
    assert all(card.endswith("\n") for card in cards[:-1])
    for card in cards:
        request = PatchMessageRequest.builder().message_id("card").request_body(PatchMessageRequestBody.builder().content(FeishuChannel._build_card_content(card)).build()).build()
        assert _body_bytes(request) <= FEISHU_CARD_MAX_BYTES


async def test_text_without_line_breaks_still_splits_within_budget():
    answer = "中" * 30_000

    cards = _split_card_text(answer)

    assert "".join(cards) == answer
    assert all(_card_text_bytes(card) <= FEISHU_CARD_MAX_BYTES for card in cards)


async def test_split_is_capped_and_the_last_card_is_clipped():
    cards = _split_card_text("中" * 200_000)

    assert len(cards) == FEISHU_MAX_CARDS_PER_REPLY
    assert cards[-1].endswith("... (truncated)")
    assert all(_card_text_bytes(card) <= FEISHU_CARD_MAX_BYTES for card in cards)


async def test_long_final_answer_continues_in_further_cards(feishu):
    channel, api = feishu.channel, feishu.api
    channel._running_card_ids["source-1"] = "running-card"
    api.cards["running-card"] = "thinking..."
    answer = _long_answer()

    for cut in (len(answer) // 3, 2 * len(answer) // 3):
        await channel.send(_outbound(answer[:cut] + " ▉", final=False))
    await channel.send(_outbound(answer, final=True))

    assert api.rejected == []
    continuation_ids = [card_id for source, card_id in api.replies if source == "source-1"]
    shown = api.cards["running-card"] + "".join(api.cards[card_id] for card_id in continuation_ids)
    assert shown == answer
    assert len(continuation_ids) == len(_split_card_text(answer)) - 1
    assert "source-1" not in channel._running_card_ids


async def test_streamed_update_over_budget_shows_what_fits(feishu):
    channel, api = feishu.channel, feishu.api
    channel._running_card_ids["source-1"] = "running-card"
    answer = _long_answer()

    await channel.send(_outbound(answer + " ▉", final=False))

    assert api.rejected == []
    assert api.replies == []
    shown = api.cards["running-card"]
    assert shown.endswith("\n\n…")
    assert answer.startswith(shown.removesuffix("\n\n…"))


async def test_running_card_created_from_an_oversized_update_fits(feishu):
    channel, api = feishu.channel, feishu.api

    await channel.send(_outbound(_long_answer() + " ▉", final=False))

    assert api.rejected == []
    assert len(api.replies) == 1
    assert channel._running_card_ids["source-1"] == api.replies[0][1]


async def test_retry_does_not_repeat_delivered_cards(feishu):
    channel, api = feishu.channel, feishu.api
    channel._running_card_ids["source-1"] = "running-card"
    answer = _long_answer()
    # The first continuation fails once; the retry resumes from it.
    api.fail_next_reply = 1

    await channel.send(_outbound(answer, final=True))

    continuation_ids = [card_id for _, card_id in api.replies]
    assert len(api.patches) == 1
    assert api.cards["running-card"] + "".join(api.cards[card_id] for card_id in continuation_ids) == answer
    store = channel.config["channel_store"]
    for card_id in continuation_ids:
        assert await store.get_thread_id("feishu", "oc-chat", topic_id=card_id) == "thread-1"


async def test_reply_without_running_card_and_push_without_source_split_too(feishu):
    channel, api = feishu.channel, feishu.api
    answer = _long_answer()

    await channel.send(_outbound(answer, final=True))
    await channel.send(_outbound(answer, final=True, source=None))

    assert api.rejected == []
    assert "".join(api.cards[card_id] for _, card_id in api.replies) == answer
    assert "".join(text for _, text in api.created) == answer
