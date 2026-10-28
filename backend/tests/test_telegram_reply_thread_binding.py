"""Replying to a bot answer in a Telegram group must continue the original thread.

Regression tests for bytedance/deer-flow#7653: the delivery path never recorded
the bot-message-id -> thread association, so a group reply to a bot answer
looked up an unmapped topic and the manager created a new thread, dropping the
follow-up's context. The fix records the binding at delivery time, in the same
store/repo the manager resolves with.
"""

import asyncio
from types import SimpleNamespace

from app.channels.connection_identity import lookup_thread_id
from app.channels.message_bus import InboundMessage, MessageBus, OutboundMessage
from app.channels.store import JsonChannelStore
from app.channels.telegram import TelegramChannel

CHAT = "-100123"
FIRST_USER_MSG = "111"
BOT_MSG_ID = 222
THREAD = "thread-orig"


class _FakeBot:
    """Minimal stand-in for the python-telegram-bot Bot used by the channel."""

    def __init__(self, first_id: int = BOT_MSG_ID) -> None:
        self._next_id = first_id
        self.sent: list[dict] = []

    async def send_message(self, **kwargs):
        self.sent.append(kwargs)
        message_id = self._next_id
        self._next_id += 1
        return SimpleNamespace(message_id=message_id)

    async def edit_message_text(self, **kwargs):
        return None


class _FakeConnectionRepo:
    """Captures set_thread_id calls; answers get_thread_id from them."""

    def __init__(self) -> None:
        self.set_calls: list[dict] = []
        self._bindings: dict[tuple, str] = {}

    async def set_thread_id(self, **kwargs) -> None:
        self.set_calls.append(kwargs)
        key = (kwargs["connection_id"], kwargs["external_conversation_id"], kwargs["external_topic_id"])
        self._bindings[key] = kwargs["thread_id"]

    async def get_thread_id(self, connection_id, chat_id, topic_id):
        return self._bindings.get((connection_id, chat_id, topic_id))


def _channel(store=None, repo=None, first_bot_id: int = BOT_MSG_ID) -> TelegramChannel:
    config: dict = {"bot_token": "test-token"}
    if store is not None:
        config["channel_store"] = store
    if repo is not None:
        config["connection_repo"] = repo
    channel = TelegramChannel(bus=MessageBus(), config=config)
    channel._application = SimpleNamespace(bot=_FakeBot(first_id=first_bot_id))
    return channel


def _outbound(**overrides) -> OutboundMessage:
    kwargs = {
        "channel_name": "telegram",
        "chat_id": CHAT,
        "thread_id": THREAD,
        "thread_ts": FIRST_USER_MSG,
        "text": "answer",
        "is_final": True,
    }
    kwargs.update(overrides)
    return OutboundMessage(**kwargs)


def _inbound_reply(topic_id: str, **overrides) -> InboundMessage:
    kwargs = {
        "channel_name": "telegram",
        "chat_id": CHAT,
        "user_id": "u1",
        "text": "follow-up",
        "topic_id": topic_id,
    }
    kwargs.update(overrides)
    return InboundMessage(**kwargs)


def _run(coro):
    return asyncio.run(coro)


def test_record_binds_bot_message_id_in_global_store(tmp_path):
    async def go():
        store = JsonChannelStore(tmp_path / "store.json")
        channel = _channel(store=store)
        await channel._record_bot_message_thread(_outbound(), BOT_MSG_ID)
        assert await store.get_thread_id("telegram", CHAT, topic_id=str(BOT_MSG_ID)) == THREAD
        # The manager's own lookup path resolves a reply to the bot answer.
        reply = _inbound_reply(str(BOT_MSG_ID))
        assert await lookup_thread_id(reply, repo=None, store=store) == THREAD
        # Unrelated topics still start their own thread.
        assert await store.get_thread_id("telegram", CHAT, topic_id="999") is None

    _run(go())


def test_record_uses_connection_repo_for_owned_connections(tmp_path):
    async def go():
        store = JsonChannelStore(tmp_path / "store.json")
        repo = _FakeConnectionRepo()
        channel = _channel(store=store, repo=repo)
        outbound = _outbound(connection_id="conn-1", owner_user_id="owner-1")
        await channel._record_bot_message_thread(outbound, BOT_MSG_ID)
        assert repo.set_calls == [
            {
                "connection_id": "conn-1",
                "owner_user_id": "owner-1",
                "provider": "telegram",
                "external_conversation_id": CHAT,
                "external_topic_id": str(BOT_MSG_ID),
                "thread_id": THREAD,
            }
        ]
        # Owned connections resolve only in the repo, never the global store.
        assert await store.get_thread_id("telegram", CHAT, topic_id=str(BOT_MSG_ID)) is None
        reply = _inbound_reply(str(BOT_MSG_ID), connection_id="conn-1", owner_user_id="owner-1")
        assert await lookup_thread_id(reply, repo=repo, store=store) == THREAD

    _run(go())


def test_record_is_noop_without_store_or_repo_and_without_thread(tmp_path):
    async def go():
        # Directly constructed channels (tests, tooling) stay side-effect free.
        channel = _channel()
        await channel._record_bot_message_thread(_outbound(), BOT_MSG_ID)
        # Identity-rejection and other thread-less outbounds record nothing.
        store = JsonChannelStore(tmp_path / "store.json")
        channel = _channel(store=store)
        await channel._record_bot_message_thread(_outbound(thread_id=""), BOT_MSG_ID)
        assert await store.get_thread_id("telegram", CHAT, topic_id=str(BOT_MSG_ID)) is None

    _run(go())


def test_record_failure_never_breaks_delivery(tmp_path):
    class _FailingStore:
        async def set_thread_id(self, *args, **kwargs):
            raise RuntimeError("store down")

    async def go():
        channel = _channel(store=_FailingStore())
        await channel._record_bot_message_thread(_outbound(), BOT_MSG_ID)

    _run(go())


def test_send_final_plain_message_records_binding(tmp_path):
    async def go():
        store = JsonChannelStore(tmp_path / "store.json")
        channel = _channel(store=store)
        await channel.send(_outbound())
        assert await store.get_thread_id("telegram", CHAT, topic_id=str(BOT_MSG_ID)) == THREAD

    _run(go())


def test_send_stream_then_final_records_placeholder_binding(tmp_path):
    async def go():
        store = JsonChannelStore(tmp_path / "store.json")
        channel = _channel(store=store)
        # Streaming creates the "Working on it..." placeholder (id 222).
        await channel.send(_outbound(text="partial", is_final=False))
        assert await store.get_thread_id("telegram", CHAT, topic_id=str(BOT_MSG_ID)) == THREAD
        # The final edit keeps the same message id and the same binding.
        await channel.send(_outbound(text="complete answer"))
        assert await store.get_thread_id("telegram", CHAT, topic_id=str(BOT_MSG_ID)) == THREAD
        reply = _inbound_reply(str(BOT_MSG_ID))
        assert await lookup_thread_id(reply, repo=None, store=store) == THREAD

    _run(go())
