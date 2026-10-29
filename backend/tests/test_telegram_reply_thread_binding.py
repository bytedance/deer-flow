"""Replying to a bot answer in a Telegram group must continue the original thread.

Regression tests for bytedance/deer-flow#7653: the delivery path never recorded
the bot-message-id -> thread association, so a group reply to a bot answer
looked up an unmapped topic and the manager created a new thread, dropping the
follow-up's context. The fix records the binding at delivery time, in the same
store/repo the manager resolves with.

Follow-ups for the maintainer P2 review on #7656: automatic aliases claim
instead of overwriting (so a /new issued mid-stream wins), and stream updates
bind the pre-registered inbound placeholder even though its message id never
changes during the stream.
"""

import asyncio
from types import SimpleNamespace

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.channels.connection_identity import lookup_thread_id
from app.channels.message_bus import InboundMessage, MessageBus, OutboundMessage
from app.channels.store import JsonChannelStore, SqlChannelStore
from app.channels.telegram import TelegramChannel
from deerflow.persistence.base import Base
from deerflow.persistence.channel_thread_bindings import ChannelThreadBindingRow

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
    """Captures claim_thread_id calls; answers get_thread_id from them.

    claim_thread_id is first-wins (like the SQL repo), while set_thread_id
    overwrites (like an explicit /new rebind).
    """

    def __init__(self) -> None:
        self.claim_calls: list[dict] = []
        self._bindings: dict[tuple, str] = {}

    async def claim_thread_id(self, **kwargs) -> str:
        self.claim_calls.append(kwargs)
        key = (kwargs["connection_id"], kwargs["external_conversation_id"], kwargs["external_topic_id"])
        if key not in self._bindings:
            self._bindings[key] = kwargs["thread_id"]
        return self._bindings[key]

    async def set_thread_id(self, **kwargs) -> None:
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
        assert repo.claim_calls == [
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
        async def claim_thread_id(self, *args, **kwargs):
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


def test_send_stream_with_inbound_placeholder_records_binding(tmp_path):
    """P2: stream updates must bind the pre-registered inbound placeholder.

    The inbound handler sends "Working on it..." and registers it as the
    stream target before the run publishes. Stream edits then keep the same
    message id for the whole stream, so requiring an id change skips binding
    throughout and a reply before completion still starts a new thread.
    """

    async def go():
        store = JsonChannelStore(tmp_path / "store.json")
        channel = _channel(store=store)
        # Inbound handler registers the placeholder (id 222) first.
        await channel._send_running_reply(CHAT, int(FIRST_USER_MSG))
        assert await store.get_thread_id("telegram", CHAT, topic_id=str(BOT_MSG_ID)) is None
        # Stream updates edit that same message; the binding must still land.
        await channel.send(_outbound(text="partial", is_final=False))
        assert await store.get_thread_id("telegram", CHAT, topic_id=str(BOT_MSG_ID)) == THREAD
        reply = _inbound_reply(str(BOT_MSG_ID))
        assert await lookup_thread_id(reply, repo=None, store=store) == THREAD

    _run(go())


def test_send_stream_with_inbound_placeholder_records_binding_in_repo(tmp_path):
    """P2, owned-connection path: same placeholder case through the repo."""

    async def go():
        store = JsonChannelStore(tmp_path / "store.json")
        repo = _FakeConnectionRepo()
        channel = _channel(store=store, repo=repo)
        await channel._send_running_reply(CHAT, int(FIRST_USER_MSG))
        assert await repo.get_thread_id("conn-1", CHAT, str(BOT_MSG_ID)) is None
        await channel.send(_outbound(text="partial", is_final=False, connection_id="conn-1", owner_user_id="owner-1"))
        assert await repo.get_thread_id("conn-1", CHAT, str(BOT_MSG_ID)) == THREAD
        reply = _inbound_reply(str(BOT_MSG_ID), connection_id="conn-1", owner_user_id="owner-1")
        assert await lookup_thread_id(reply, repo=repo, store=store) == THREAD

    _run(go())


def test_stale_automatic_alias_never_overwrites_explicit_rebind(tmp_path):
    """P2: an explicit /new rebind wins over the stale automatic alias.

    A /new issued while an answer streams rebinds the bot-message topic to
    a new thread. When the old answer finishes, its automatic recording must
    not clobber that newer binding and send replies back to the old thread.
    """

    async def go():
        store = JsonChannelStore(tmp_path / "store.json")
        channel = _channel(store=store)
        await channel._record_bot_message_thread(_outbound(), BOT_MSG_ID)
        assert await store.get_thread_id("telegram", CHAT, topic_id=str(BOT_MSG_ID)) == THREAD
        # Explicit /new rebind to a new thread.
        await store.set_thread_id("telegram", CHAT, "thread-new", topic_id=str(BOT_MSG_ID))
        # Stale automatic alias from the old answer finishing.
        await channel._record_bot_message_thread(_outbound(), BOT_MSG_ID)
        assert await store.get_thread_id("telegram", CHAT, topic_id=str(BOT_MSG_ID)) == "thread-new"

    _run(go())


def test_stale_automatic_alias_never_overwrites_explicit_rebind_in_repo(tmp_path):
    """P2, owned-connection path: same /new-wins case through the repo."""

    async def go():
        store = JsonChannelStore(tmp_path / "store.json")
        repo = _FakeConnectionRepo()
        channel = _channel(store=store, repo=repo)
        outbound = _outbound(connection_id="conn-1", owner_user_id="owner-1")
        await channel._record_bot_message_thread(outbound, BOT_MSG_ID)
        assert await repo.get_thread_id("conn-1", CHAT, str(BOT_MSG_ID)) == THREAD
        # Explicit /new rebind to a new thread.
        await repo.set_thread_id(connection_id="conn-1", owner_user_id="owner-1", provider="telegram", external_conversation_id=CHAT, external_topic_id=str(BOT_MSG_ID), thread_id="thread-new")
        # Stale automatic alias from the old answer finishing.
        await channel._record_bot_message_thread(outbound, BOT_MSG_ID)
        assert await repo.get_thread_id("conn-1", CHAT, str(BOT_MSG_ID)) == "thread-new"

    _run(go())


def test_stale_automatic_alias_never_overwrites_explicit_rebind_in_sqlite_store(tmp_path):
    """P2, SQLite path: same /new-wins case through SqlChannelStore."""

    async def setup():
        engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'bindings.db').as_posix()}")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all, tables=[ChannelThreadBindingRow.__table__], checkfirst=True)
        return engine

    engine = _run(setup())
    try:
        store = SqlChannelStore(async_sessionmaker(engine, expire_on_commit=False))

        async def go():
            channel = _channel(store=store)
            await channel._record_bot_message_thread(_outbound(), BOT_MSG_ID)
            assert await store.get_thread_id("telegram", CHAT, topic_id=str(BOT_MSG_ID)) == THREAD
            # Explicit /new rebind to a new thread.
            await store.set_thread_id("telegram", CHAT, "thread-new", topic_id=str(BOT_MSG_ID))
            # Stale automatic alias from the old answer finishing.
            await channel._record_bot_message_thread(_outbound(), BOT_MSG_ID)
            assert await store.get_thread_id("telegram", CHAT, topic_id=str(BOT_MSG_ID)) == "thread-new"

        _run(go())
    finally:
        _run(engine.dispose())
