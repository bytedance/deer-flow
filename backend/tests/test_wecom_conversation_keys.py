"""WeCom conversations: a group is keyed by its chatid, a private chat by the sender.

Group messages used to be keyed like private ones (``chat_id`` and ``topic_id``
both the sender's ``userid``). Wherever no group connection kept them apart
(auth-disabled mode, ``require_bound_identity: false``, legacy group
bindings), a member's private chat and every group they wrote in shared one
DeerFlow thread, and a reply in one group could draw on another chat.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from app.channels.connection_identity import lookup_thread_id
from app.channels.manager import ChannelManager
from app.channels.message_bus import InboundMessage, MessageBus, OutboundMessage
from app.channels.store import JsonChannelStore
from app.channels.wecom import WeComChannel
from deerflow.persistence.channel_connections import ChannelConnectionRepository
from deerflow.persistence.engine import close_engine, get_session_factory, init_engine

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def repo(tmp_path):
    await init_engine("sqlite", url=f"sqlite+aiosqlite:///{tmp_path / 'wecom.db'}", sqlite_dir=str(tmp_path))
    try:
        yield ChannelConnectionRepository(get_session_factory())
    finally:
        await close_engine()


def _channel(bus: MessageBus, repo: ChannelConnectionRepository | None = None) -> WeComChannel:
    channel = WeComChannel(bus, {"connection_repo": repo} if repo is not None else {})
    channel._ws_client = SimpleNamespace(reply=AsyncMock(), reply_stream=AsyncMock(), send_message=AsyncMock())
    return channel


async def _receive(channel: WeComChannel, bus: MessageBus, msgid: str, *, chatid: str | None = None, user: str = "alice") -> InboundMessage:
    body = {"aibotid": "bot-1", "chattype": "group" if chatid else "single", "msgid": msgid, "from": {"userid": user}, "text": {"content": "hi"}}
    if chatid:
        body["chatid"] = chatid
    await channel._publish_ws_inbound({"body": body}, "hi")
    return bus.get_inbound_nowait()


async def test_group_and_private_messages_get_their_own_conversation_keys():
    bus = MessageBus()
    channel = _channel(bus)

    private = await _receive(channel, bus, "m1")
    group_a = await _receive(channel, bus, "m2", chatid="wr-team-a")
    group_b = await _receive(channel, bus, "m3", chatid="wr-team-b")
    other_member = await _receive(channel, bus, "m4", chatid="wr-team-a", user="bob")

    assert (private.chat_id, private.topic_id) == ("alice", "alice")
    assert (group_a.chat_id, group_a.topic_id) == ("wr-team-a", "alice")
    assert (group_b.chat_id, group_b.topic_id) == ("wr-team-b", "alice")
    assert (other_member.chat_id, other_member.topic_id) == ("wr-team-a", "bob")


async def test_reply_without_its_frame_goes_to_the_group_not_the_sender():
    # The frame is gone after a Gateway restart, so a recovered run's reply
    # is pushed to the conversation's chat_id instead.
    bus = MessageBus()
    channel = _channel(bus)
    message = await _receive(channel, bus, "m1", chatid="wr-team-a")
    channel._ws_frames.clear()

    await channel.send(OutboundMessage(channel_name="wecom", chat_id=message.chat_id, thread_id="thread-1", text="answer", thread_ts=message.thread_ts, is_final=True))

    channel._ws_client.send_message.assert_awaited_once()
    assert channel._ws_client.send_message.await_args.args[0] == "wr-team-a"


def _client() -> MagicMock:
    created = iter(f"thread-{index}" for index in range(1, 10))
    client = MagicMock()
    client.threads.create = AsyncMock(side_effect=lambda **_kwargs: {"thread_id": next(created)})
    client.threads.update = AsyncMock(return_value={})
    client.threads.get = AsyncMock(side_effect=lambda thread_id, **_kwargs: {"thread_id": thread_id})

    def stream(*_args, **_kwargs):
        async def events():
            yield SimpleNamespace(event="values", data={"messages": [{"type": "ai", "content": "ok"}]})

        return events()

    client.runs.stream = MagicMock(side_effect=stream)
    return client


async def test_unbound_private_chat_and_groups_run_in_separate_threads(monkeypatch):
    # Auth-disabled mode: no connection scopes the conversation, only its key.
    monkeypatch.setattr("app.channels.manager._auth_disabled_owner_user_id", lambda: "default")
    bus = MessageBus()
    channel = _channel(bus)
    manager = ChannelManager(bus=bus, store=JsonChannelStore(path=Path(tempfile.mkdtemp()) / "store.json"), max_concurrency=1, shutdown_grace_period_seconds=0)
    manager._client = client = _client()

    for msgid, chatid in (("m1", None), ("m2", "wr-team-a"), ("m3", "wr-team-b"), ("m4", "wr-team-a"), ("m5", None)):
        await manager._handle_message(await _receive(channel, bus, msgid, chatid=chatid))

    threads = [call.args[0] for call in client.runs.stream.call_args_list]
    assert threads == ["thread-1", "thread-2", "thread-3", "thread-2", "thread-1"]


async def _bind_group(repo: ChannelConnectionRepository, chatid: str) -> dict:
    return await repo.upsert_connection(
        owner_user_id="owner",
        provider="wecom",
        external_account_id="alice",
        workspace_id=f"bot-1:group:{chatid}",
        metadata={"aibotid": "bot-1", "chattype": "group", "chatid": chatid},
    )


async def _bind_sender_keyed_thread(repo: ChannelConnectionRepository, connection: dict, thread_id: str) -> None:
    await repo.set_thread_id(connection_id=connection["id"], owner_user_id="owner", provider="wecom", external_conversation_id="alice", external_topic_id="alice", thread_id=thread_id)


async def test_bound_group_keeps_the_thread_it_had_under_the_sender_key(repo):
    group_a = await _bind_group(repo, "wr-team-a")
    group_b = await _bind_group(repo, "wr-team-b")
    await _bind_sender_keyed_thread(repo, group_a, "team-a-thread")
    await _bind_sender_keyed_thread(repo, group_b, "team-b-thread")
    bus = MessageBus()
    channel = _channel(bus, repo)

    first_a = await _receive(channel, bus, "m1", chatid="wr-team-a")
    first_b = await _receive(channel, bus, "m2", chatid="wr-team-b")

    assert first_a.connection_id == group_a["id"]
    assert await lookup_thread_id(first_a, repo=repo, store=None) == "team-a-thread"
    assert await lookup_thread_id(first_b, repo=repo, store=None) == "team-b-thread"

    # A rebinding under the group key (``/new``) is never overwritten.
    await repo.set_thread_id(connection_id=group_a["id"], owner_user_id="owner", provider="wecom", external_conversation_id="wr-team-a", external_topic_id="alice", thread_id="fresh-thread")
    later_a = await _receive(channel, bus, "m3", chatid="wr-team-a")
    assert await lookup_thread_id(later_a, repo=repo, store=None) == "fresh-thread"


async def test_legacy_group_binding_does_not_continue_its_sender_keyed_thread(repo):
    legacy = await repo.upsert_connection(owner_user_id="owner", provider="wecom", external_account_id="alice", workspace_id="bot-1", metadata={"aibotid": "bot-1", "chattype": "group"})
    await _bind_sender_keyed_thread(repo, legacy, "existing-thread")
    bus = MessageBus()
    channel = _channel(bus, repo)

    group_a = await _receive(channel, bus, "m1", chatid="wr-team-a")
    group_b = await _receive(channel, bus, "m2", chatid="wr-team-b")

    # The binding still authorizes its owner in every group of the bot, but
    # its thread may hold any of them, so no group continues it.
    assert group_a.connection_id == group_b.connection_id == legacy["id"]
    assert group_a.owner_user_id == "owner"
    assert await lookup_thread_id(group_a, repo=repo, store=None) is None
    assert await lookup_thread_id(group_b, repo=repo, store=None) is None
