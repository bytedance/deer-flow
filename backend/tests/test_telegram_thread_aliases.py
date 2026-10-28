"""Telegram group replies to the bot's answer must continue that answer's thread.

The inbound side keys a group message by its reply-to message id, but nothing
bound the *bot's own* delivered message ids to the DeerFlow thread that
produced them, so replying to an answer created a brand-new conversation
(#7653). These tests drive the production ``send``/``send_file`` delivery paths
and assert every delivered bot message id is bound as a reply topic of the
producing thread — in the shared store, and in the connection repository for
user-owned connections — while private chats stay untouched.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from app.channels.connection_identity import lookup_thread_id
from app.channels.message_bus import InboundMessage, InboundMessageType, MessageBus, OutboundMessage
from app.channels.telegram import TelegramChannel

GROUP_CHAT = "-1004242"
PRIVATE_CHAT = "4242100"


class RecordingStore:
    """ChannelStore double recording topic bindings."""

    def __init__(self) -> None:
        self.bindings: dict[tuple[str, str, str], str] = {}
        self.calls: list[tuple[str, str, str]] = []

    async def set_thread_id(self, channel_name: str, chat_id: str, thread_id: str, *, topic_id: str | None = None, user_id: str = "") -> None:
        assert topic_id is not None
        self.bindings[(channel_name, chat_id, topic_id)] = thread_id
        self.calls.append((channel_name, chat_id, topic_id))

    async def get_thread_id(self, channel_name: str, chat_id: str, topic_id: str | None = None) -> str | None:
        if topic_id is None:
            return None
        return self.bindings.get((channel_name, chat_id, topic_id))


class RecordingRepo:
    """ConnectionRepository double for user-owned connections."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def set_thread_id(self, *, connection_id: str, owner_user_id: str, provider: str, external_conversation_id: str, external_topic_id: str | None, thread_id: str) -> None:
        self.calls.append(
            {
                "connection_id": connection_id,
                "owner_user_id": owner_user_id,
                "provider": provider,
                "chat_id": external_conversation_id,
                "topic_id": external_topic_id,
                "thread_id": thread_id,
            }
        )


class FakeBot:
    """Just enough Bot API for the send paths: ids increment per message."""

    def __init__(self) -> None:
        self._next_id = 600

    def _sent(self) -> SimpleNamespace:
        self._next_id += 1
        return SimpleNamespace(message_id=self._next_id)

    async def send_message(self, **kwargs: Any) -> SimpleNamespace:
        return self._sent()

    async def edit_message_text(self, **kwargs: Any) -> bool:
        return True

    async def send_photo(self, **kwargs: Any) -> SimpleNamespace:
        return self._sent()

    async def send_document(self, **kwargs: Any) -> SimpleNamespace:
        return self._sent()


def _channel(store: RecordingStore | None = None, repo: RecordingRepo | None = None) -> TelegramChannel:
    config: dict[str, Any] = {"bot_token": "test-token"}
    if store is not None:
        config["channel_store"] = store
    if repo is not None:
        config["connection_repo"] = repo
    channel = TelegramChannel(bus=MessageBus(), config=config)
    channel._application = SimpleNamespace(bot=FakeBot())
    return channel


def _outbound(chat_id: str, *, thread_id: str = "thread-1", is_final: bool = True, text: str = "answer", **extra: Any) -> OutboundMessage:
    return OutboundMessage(
        channel_name="telegram",
        chat_id=chat_id,
        thread_id=thread_id,
        text=text,
        is_final=is_final,
        thread_ts="500",
        metadata={},
        **extra,
    )


def _group_reply(chat_id: str, topic_id: str) -> InboundMessage:
    msg = InboundMessage(
        channel_name="telegram",
        chat_id=chat_id,
        user_id="7",
        text="follow-up",
        msg_type=InboundMessageType.CHAT,
        thread_ts="700",
        metadata={},
    )
    msg.topic_id = topic_id
    return msg


def test_streamed_group_answer_ids_resolve_back_to_the_thread():
    store = RecordingStore()
    channel = _channel(store=store)
    bot = channel._application.bot

    asyncio.run(channel.send(_outbound(GROUP_CHAT, is_final=False, text="partial")))
    asyncio.run(channel.send(_outbound(GROUP_CHAT, text="final answer")))

    # The streamed placeholder is the message users reply to; its id must
    # resolve back through the real lookup path.
    placeholder_id = bot._next_id  # the first sent message (601)
    resolved = asyncio.run(lookup_thread_id(_group_reply(GROUP_CHAT, str(placeholder_id)), repo=None, store=store))
    assert resolved == "thread-1"


def test_overflow_chunk_ids_resolve_back_to_the_thread():
    store = RecordingStore()
    channel = _channel(store=store)

    # Longer than Telegram's 4096-unit cap, forcing an overflow chunk message.
    asyncio.run(channel.send(_outbound(GROUP_CHAT, text="字" * 5000)))

    bound_topics = {topic for (_channel_name, _chat, topic) in store.calls}
    assert len(bound_topics) >= 2, "both the edited first chunk and the overflow chunk must be bound"
    for topic in bound_topics:
        assert asyncio.run(store.get_thread_id("telegram", GROUP_CHAT, topic)) == "thread-1"


def test_private_chat_answers_bind_no_aliases():
    store = RecordingStore()
    channel = _channel(store=store)

    asyncio.run(channel.send(_outbound(PRIVATE_CHAT, is_final=False, text="partial")))
    asyncio.run(channel.send(_outbound(PRIVATE_CHAT, text="final answer")))

    assert store.calls == []


def test_connection_owned_answers_bind_in_the_connection_repo():
    store = RecordingStore()
    repo = RecordingRepo()
    channel = _channel(store=store, repo=repo)

    asyncio.run(channel.send(_outbound(GROUP_CHAT, connection_id="conn-1", owner_user_id="user-1", text="owned answer")))

    assert store.calls == [], "connection-owned routing must not touch the global store"
    assert repo.calls, "the connection repo must receive the bot-message alias"
    call = repo.calls[0]
    assert call["provider"] == "telegram"
    assert call["chat_id"] == GROUP_CHAT
    assert call["thread_id"] == "thread-1"
    assert call["topic_id"] is not None and call["topic_id"].isdigit()


def test_attachment_ids_resolve_back_to_the_thread(monkeypatch):
    store = RecordingStore()
    channel = _channel(store=store)

    def fake_load(_path: str, _filename: str) -> object:
        # Sync like the production loader: send_file invokes it via to_thread.
        return object()

    monkeypatch.setattr("app.channels.telegram._load_telegram_input_file", fake_load)
    attachment = SimpleNamespace(
        filename="out.png",
        actual_path="/tmp/out.png",
        size=1024,
        is_image=True,
    )
    asyncio.run(channel.send_file(_outbound(GROUP_CHAT, text="see attachment"), attachment))

    assert store.calls, "the attachment message id must be bound as a reply topic"
    for _channel_name, _chat, topic in store.calls:
        assert asyncio.run(store.get_thread_id("telegram", GROUP_CHAT, topic)) == "thread-1"


def test_no_thread_identity_binds_nothing():
    store = RecordingStore()
    channel = _channel(store=store)

    asyncio.run(channel.send(_outbound(GROUP_CHAT, thread_id="", text="rejection copy")))

    assert store.calls == []


def test_stream_chunks_bind_the_placeholder_alias_once_per_reply():
    store = RecordingStore()
    channel = _channel(store=store)
    bot = channel._application.bot

    for _ in range(3):
        asyncio.run(channel.send(_outbound(GROUP_CHAT, is_final=False, text="partial")))
    placeholder_id = str(bot._next_id)  # the first sent message (601)

    writes = [topic for (_channel_name, _chat, topic) in store.calls if topic == placeholder_id]
    assert len(writes) == 1, "non-final chunks must bind each alias once per reply, not once per update"

    # The final outbound rewrites the alias (channels AGENTS per-reply rule).
    asyncio.run(channel.send(_outbound(GROUP_CHAT, text="final answer")))
    writes = [topic for (_channel_name, _chat, topic) in store.calls if topic == placeholder_id]
    assert len(writes) == 2
