"""Telegram reply routing through real stores, with an offline Bot API double."""

from __future__ import annotations

import asyncio
import logging
from itertools import count
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.channels.manager import ChannelManager
from app.channels.message_bus import MessageBus, OutboundMessage, ResolvedAttachment
from app.channels.store import JsonChannelStore, SqlChannelStore
from app.channels.telegram import TelegramChannel

pytestmark = pytest.mark.anyio


@pytest.fixture(params=["json", "sqlite", "bound"])
async def routing(request, tmp_path):
    repo = None
    connection = None
    session_factory = None
    if request.param != "json":
        from deerflow.persistence.channel_connections import ChannelConnectionRepository, ChannelCredentialCipher
        from deerflow.persistence.engine import close_engine, get_session_factory, init_engine

        await init_engine("sqlite", url=f"sqlite+aiosqlite:///{tmp_path / 'channel.db'}", sqlite_dir=str(tmp_path))
        session_factory = get_session_factory()
        if request.param == "bound":
            repo = ChannelConnectionRepository(session_factory, cipher=ChannelCredentialCipher.from_key("test-key"))
            connection = await repo.upsert_connection(
                owner_user_id="owner-a",
                provider="telegram",
                external_account_id="42",
                workspace_id="-10042",
            )
    store = SqlChannelStore(session_factory) if session_factory else JsonChannelStore(tmp_path / "store.json")
    bus = MessageBus()
    channel = TelegramChannel(bus=bus, config={"bot_token": "test-token", "channel_store": store, "connection_repo": repo})
    channel._main_loop = asyncio.get_running_loop()
    message_ids = count(100)
    sent_ids = []

    async def send(**kwargs):
        message_id = next(message_ids)
        sent_ids.append(message_id)
        return SimpleNamespace(message_id=message_id)

    async def rich(endpoint, api_kwargs):
        if endpoint == "editMessageText":
            return {"message_id": api_kwargs["message_id"]}
        return {"message_id": (await send()).message_id}

    bot = SimpleNamespace(send_message=AsyncMock(side_effect=send), edit_message_text=AsyncMock(), do_api_request=AsyncMock(side_effect=rich), send_photo=AsyncMock(side_effect=send), send_document=AsyncMock(side_effect=send))
    channel._application = SimpleNamespace(bot=bot)
    thread_ids = count(1)
    client = SimpleNamespace(threads=SimpleNamespace(create=AsyncMock(side_effect=lambda **kw: {"thread_id": f"thread-{next(thread_ids)}"})))
    manager = ChannelManager(bus=bus, store=store, connection_repo=repo)

    async def incoming(message_id, reply_id=None, *, chat_type="supergroup", user_id=42):
        chat_id = 42 if chat_type == "private" else -10042
        update = SimpleNamespace(
            effective_chat=SimpleNamespace(id=chat_id, type=chat_type),
            effective_user=SimpleNamespace(id=user_id),
            message=SimpleNamespace(text="question", caption=None, photo=[], document=None, message_id=message_id, reply_to_message=SimpleNamespace(message_id=reply_id) if reply_id else None),
        )
        await channel._on_text(update, None)
        return await asyncio.wait_for(bus.get_inbound(), timeout=5)

    def outbound(inbound, thread_id, **kwargs):
        return OutboundMessage(
            channel_name="telegram",
            chat_id=inbound.chat_id,
            thread_id=thread_id,
            thread_ts=inbound.thread_ts,
            connection_id=inbound.connection_id,
            owner_user_id=inbound.owner_user_id,
            metadata=inbound.metadata,
            text=kwargs.pop("text", "Answer"),
            **kwargs,
        )

    harness = SimpleNamespace(channel=channel, bot=bot, bus=bus, store=store, repo=repo, connection=connection, manager=manager, client=client, incoming=incoming, outbound=outbound, sent_ids=sent_ids)
    try:
        yield harness
    finally:
        await channel._close_and_drain_threadsafe_futures()
        if session_factory:
            await close_engine()


@pytest.mark.parametrize("chat_type", ["private", "group", "supergroup"])
@pytest.mark.parametrize("reply_to_bot", [False, True])
async def test_reply_reuses_conversation(routing, chat_type, reply_to_bot):
    h = routing
    first = await h.incoming(10, chat_type=chat_type)
    thread_id, _ = await h.manager._get_or_create_thread(h.client, first)
    await h.channel.send(h.outbound(first, thread_id))
    response_id = h.bot.edit_message_text.await_args.kwargs["message_id"]
    followup = await h.incoming(11, response_id if reply_to_bot else 10, chat_type=chat_type)
    assert await h.manager._get_or_create_thread(h.client, followup) == (thread_id, False)
    h.client.threads.create.assert_awaited_once()


async def test_stream_aliases_are_not_rewritten_and_new_keeps_its_binding(routing):
    h = routing
    first = await h.incoming(10)
    thread_id, _ = await h.manager._get_or_create_thread(h.client, first)
    repository = h.repo or h.store
    claim = repository.claim_thread_id
    repository.claim_thread_id = AsyncMock(wraps=claim)
    await h.channel.send(h.outbound(first, thread_id, text="Partial", is_final=False))
    calls = repository.claim_thread_id.await_count
    assert calls == 2  # Source message and bot preview.
    await h.channel.send(h.outbound(first, thread_id, text="Partial", is_final=False))
    assert repository.claim_thread_id.await_count == calls

    command = await h.incoming(11, h.sent_ids[0])
    new_thread = await h.manager._create_thread(h.client, command)
    assert new_thread != thread_id
    await h.channel.send(h.outbound(first, thread_id, text="Old run finished"))
    assert await h.manager._lookup_thread_id(command) == new_thread


@pytest.mark.parametrize("delivery", ["plain", "rich", "split", "fallback"])
async def test_stream_binding_outage_logs_once_per_answer(routing, caplog, delivery):
    h = routing
    first = await h.incoming(10)
    thread_id, _ = await h.manager._get_or_create_thread(h.client, first)
    repository = h.repo or h.store
    repository.claim_thread_id = AsyncMock(side_effect=RuntimeError("store unavailable"))

    with caplog.at_level(logging.DEBUG, logger="app.channels.telegram"):
        for index in range(20):
            await h.channel.send(h.outbound(first, thread_id, text=f"Partial {index}", is_final=False))
        if delivery == "rich":
            h.channel.config["rich_messages"] = True
        if delivery == "fallback":
            h.bot.edit_message_text.side_effect = RuntimeError("edit unavailable")
        text = "x" * 9000 if delivery == "split" else "Final answer"
        await h.channel.send(h.outbound(first, thread_id, text=text))

        failures = [record for record in caplog.records if record.name == "app.channels.telegram" and "thread mapping" in record.getMessage()]
        assert len(failures) == repository.claim_thread_id.await_count
        assert len(failures) >= 21, "every failed update must keep retrying the mapping"
        assert sum(record.levelno == logging.ERROR for record in failures) == 1
        assert failures[0].exc_info is not None
        assert all(record.levelno == logging.DEBUG and record.exc_info is None for record in failures[1:])
        assert len(h.sent_ids) == {"plain": 1, "rich": 1, "split": 3, "fallback": 2}[delivery]

        # Finalization retires the per-answer log state. A subsequent answer
        # must report its first outage even on the same conversation key.
        await h.channel.send(h.outbound(first, thread_id, text="Next answer", is_final=False))
        errors = [record for record in caplog.records if record.name == "app.channels.telegram" and "thread mapping" in record.getMessage() and record.levelno == logging.ERROR]
        assert len(errors) == 2
        await h.channel.send(h.outbound(first, thread_id, text="Next answer"))


async def test_binding_failure_does_not_fail_delivery_and_stream_retries(routing, caplog):
    h = routing
    first = await h.incoming(10)
    thread_id, _ = await h.manager._get_or_create_thread(h.client, first)
    repository = h.repo or h.store
    claim = repository.claim_thread_id
    repository.claim_thread_id = AsyncMock(side_effect=RuntimeError("store unavailable"))
    await h.channel.send(h.outbound(first, thread_id, is_final=False))
    assert h.bot.edit_message_text.await_count == 1
    assert "thread mapping" in caplog.text
    if h.repo:
        assert await h.store.list_entries() == []
    repository.claim_thread_id = claim
    await h.channel.send(h.outbound(first, thread_id, is_final=False))
    followup = await h.incoming(11, h.sent_ids[0])
    assert await h.manager._get_or_create_thread(h.client, followup) == (thread_id, False)


@pytest.mark.parametrize("routing", ["bound"], indirect=True)
async def test_bound_reply_does_not_expose_thread_to_another_owner(routing):
    h = routing
    first = await h.incoming(10)
    thread_id, _ = await h.manager._get_or_create_thread(h.client, first)
    await h.channel.send(h.outbound(first, thread_id))
    response_id = h.sent_ids[0]
    assert await h.store.list_entries() == []
    await h.repo.upsert_connection(owner_user_id="owner-b", provider="telegram", external_account_id="43", workspace_id="-10042")
    other = await h.incoming(11, response_id, user_id=43)
    assert other.owner_user_id == "owner-b"
    assert await h.manager._lookup_thread_id(other) is None
    unbound = await h.incoming(12, response_id, user_id=44)
    assert unbound.connection_id is None
    assert await h.manager._lookup_thread_id(unbound) is None
    h.client.threads.create.assert_awaited_once()


@pytest.mark.parametrize("delivery", ["split", "fallback", "rich", "rich-new", "rich-fallback", "plain-new", "preview", "preview-fallback"])
async def test_every_delivered_reply_keeps_thread(routing, delivery):
    h = routing
    first = await h.incoming(10)
    thread_id, _ = await h.manager._get_or_create_thread(h.client, first)
    placeholder_id = h.sent_ids[0]
    if delivery.endswith("new"):
        h.channel._stream_messages.clear()
    if delivery == "fallback":
        h.bot.edit_message_text.side_effect = RuntimeError("edit unavailable")
    if delivery.startswith("rich"):
        h.channel.config["rich_messages"] = True
    if delivery == "rich-fallback":
        from telegram.error import BadRequest

        h.bot.do_api_request.side_effect = BadRequest("unsupported")
    text = "x" * 9000 if delivery == "split" else "**Answer**"
    await h.channel.send(h.outbound(first, thread_id, text=text, is_final=not delivery.startswith("preview")))
    if delivery == "preview-fallback":
        h.channel._stream_messages[f"{first.chat_id}:{first.thread_ts}"]["last_edit_at"] = 0.0
        h.bot.edit_message_text.side_effect = RuntimeError("edit unavailable")
        await h.channel.send(h.outbound(first, thread_id, text="Next chunk", is_final=False))
    reply_ids = h.sent_ids[1:] if delivery.endswith("new") or delivery == "fallback" else list(h.sent_ids)
    assert reply_ids
    for reply_id in reply_ids:
        followup = await h.incoming(200 + reply_id, reply_id)
        assert await h.manager._get_or_create_thread(h.client, followup) == (thread_id, False)
    if delivery == "split":
        assert placeholder_id in reply_ids and len(reply_ids) == 3


async def test_followup_source_alias_and_restart(routing):
    h = routing
    first = await h.incoming(10)
    thread_id, _ = await h.manager._get_or_create_thread(h.client, first)
    await h.channel.send(h.outbound(first, thread_id))
    followup = await h.incoming(11, h.sent_ids[0])
    assert await h.manager._get_or_create_thread(h.client, followup) == (thread_id, False)
    await h.channel.send(h.outbound(followup, thread_id))
    store = JsonChannelStore(h.store.path) if isinstance(h.store, JsonChannelStore) else h.store
    restarted = ChannelManager(bus=h.bus, store=store, connection_repo=h.repo)
    for reply_id in (11, h.sent_ids[-1]):
        incoming = await h.incoming(300 + reply_id, reply_id)
        assert await restarted._get_or_create_thread(h.client, incoming) == (thread_id, False)
    unrelated = await h.incoming(900)
    assert (await restarted._get_or_create_thread(h.client, unrelated))[0] != thread_id


@pytest.mark.parametrize("image", [False, True])
async def test_reply_to_attachment_keeps_thread(routing, tmp_path, image):
    h = routing
    first = await h.incoming(10)
    thread_id, _ = await h.manager._get_or_create_thread(h.client, first)
    path = tmp_path / ("chart.png" if image else "report.txt")
    path.write_bytes(b"fixture")
    attachment = ResolvedAttachment(virtual_path=f"/mnt/user-data/outputs/{path.name}", actual_path=path, filename=path.name, size=7, mime_type="image/png" if image else "text/plain", is_image=image)
    assert await h.channel.send_file(h.outbound(first, thread_id), attachment)
    followup = await h.incoming(11, h.sent_ids[-1])
    assert await h.manager._get_or_create_thread(h.client, followup) == (thread_id, False)
