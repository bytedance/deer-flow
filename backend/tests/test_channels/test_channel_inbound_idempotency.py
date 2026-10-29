"""IM inbound dedupe and run idempotency across replicas, restarts and late redeliveries.

The inbound dedupe store absorbs a redelivery only inside its 10-minute window
and only while the store remembers the key: an in-process store forgets it on
restart, and the shared Postgres store fails open on a database error. Past
that window the manager used to start a second run for a message the Gateway
had already admitted. Every keyed run request now carries an ``Idempotency-Key``
derived from the inbound dedupe key, with a human message id derived from the
same key so the retry's input is identical: the Gateway reuses the admitted run
and the redelivery attaches to its outcome instead of running the turn twice.

Discord gets a dedupe key for direct messages (no guild) and one that does not
depend on replica-local thread routing, and two replicas that each create a
thread for one new conversation converge on the first one bound.
"""

from __future__ import annotations

import asyncio
import tempfile
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from langgraph_sdk.errors import ConflictError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.channels.dedupe_store import MemoryInboundDedupeStore
from app.channels.manager import ALREADY_ADMITTED_MESSAGE, THREAD_BUSY_MESSAGE, ChannelManager
from app.channels.message_bus import InboundMessage, MessageBus, OutboundMessage
from app.channels.store import JsonChannelStore, SqlChannelStore
from app.gateway.internal_auth import INTERNAL_OWNER_USER_ID_HEADER_NAME
from deerflow.persistence.base import Base
from deerflow.persistence.channel_thread_bindings import ChannelThreadBindingRow

pytestmark = pytest.mark.asyncio


def _manager(*, dedupe: MemoryInboundDedupeStore | None = None, store=None, get_stream_bridge=None) -> ChannelManager:
    return ChannelManager(
        bus=MessageBus(),
        store=store or JsonChannelStore(path=Path(tempfile.mkdtemp()) / "store.json"),
        inbound_dedupe_store=dedupe or MemoryInboundDedupeStore(),
        max_concurrency=1,
        shutdown_grace_period_seconds=0,
        get_stream_bridge=get_stream_bridge,
    )


def _client(thread_id: str = "thread-1") -> MagicMock:
    client = MagicMock()
    client.threads.create = AsyncMock(return_value={"thread_id": thread_id})
    client.threads.update = AsyncMock(return_value={"thread_id": thread_id})
    client.threads.get = AsyncMock(return_value={"thread_id": thread_id})
    client.threads.delete = AsyncMock(return_value=None)
    client.runs.wait = AsyncMock(return_value={"messages": [{"type": "human", "content": "hi"}, {"type": "ai", "content": "fresh answer"}]})
    client.runs.create = AsyncMock(return_value={"run_id": "run-1", "status": "pending"})
    return client


def _slack(event_id: str = "evt-1", *, team_id: str | None = "T1") -> InboundMessage:
    metadata = {"event_id": event_id}
    if team_id:
        metadata["team_id"] = team_id
    return InboundMessage(channel_name="slack", chat_id="C1", user_id="U1", text="hi", metadata=metadata)


def _feishu() -> InboundMessage:
    return InboundMessage(channel_name="feishu", chat_id="oc-1", user_id="ou-1", text="hi", metadata={"message_id": "om-1"})


def _github() -> InboundMessage:
    return InboundMessage(
        channel_name="github",
        chat_id="acme/repo",
        user_id="alice",
        owner_user_id="alice",
        text="@bot review",
        topic_id="7:reviewer",
        workspace_id="acme/repo",
        metadata={"message_id": "d1:alice:reviewer", "agent_name": "reviewer"},
    )


def _discord(*, chat_id: str, channel_id: str, guild_id: str | None, message_id: str = "1300000000000000001", topic_id: str | None = None) -> InboundMessage:
    return InboundMessage(
        channel_name="discord",
        chat_id=chat_id,
        user_id="42",
        text="hi",
        topic_id=topic_id,
        metadata={"guild_id": guild_id, "channel_id": channel_id, "message_id": message_id},
    )


def _outbounds(manager: ChannelManager) -> list[OutboundMessage]:
    sent: list[OutboundMessage] = []

    async def capture(msg: OutboundMessage) -> None:
        sent.append(msg)

    manager.bus.subscribe_outbound(capture)
    return sent


def _stream(*parts):
    def factory(*_args, **_kwargs):
        async def gen():
            for event, data in parts:
                yield SimpleNamespace(event=event, data=data)

        return gen()

    return MagicMock(side_effect=factory)


def _request_headers(call) -> dict:
    return dict(call.kwargs.get("headers") or {})


def _human_message(call) -> dict:
    [message] = call.kwargs["input"]["messages"]
    return message


# -- Discord dedupe key --------------------------------------------------------


async def test_discord_direct_message_gets_a_dedupe_key():
    """A DM has no guild, so it used to get no key at all and every replica ran it."""
    dm = _discord(chat_id="1200000000000000009", channel_id="1200000000000000009", guild_id=None)

    assert ChannelManager._inbound_dedupe_key(dm) == ("discord", "dm", "1200000000000000009", "1300000000000000001")


async def test_discord_key_does_not_depend_on_replica_local_thread_routing():
    """A replica that tracks thread T routes a reply in T to its parent channel;
    one that does not treats T as an orphan and routes it to T itself. Both must
    see one message."""
    tracked = _discord(chat_id="parent-1", channel_id="thread-T", guild_id="guild-1", topic_id="thread-T")
    orphaned = _discord(chat_id="thread-T", channel_id="thread-T", guild_id="guild-1", topic_id="thread-new")

    assert ChannelManager._inbound_dedupe_key(tracked) == ChannelManager._inbound_dedupe_key(orphaned)
    assert ChannelManager._inbound_dedupe_key(tracked) == ("discord", "guild-1", "thread-T", "1300000000000000001")


async def test_discord_guild_channel_key_keeps_its_shape():
    msg = _discord(chat_id="chan-1", channel_id="chan-1", guild_id="guild-1")

    assert ChannelManager._inbound_dedupe_key(msg) == ("discord", "guild-1", "chan-1", "1300000000000000001")


async def test_worker_runs_a_message_the_adapter_already_claimed_and_drops_its_redelivery():
    """An adapter-claimed message has its key recorded already; the worker must
    not read its own claim as a duplicate, but a second delivery still is one."""
    manager = _manager()
    manager._client = client = _client()
    claimed = _discord(chat_id="chan-1", channel_id="chan-1", guild_id="guild-1")
    assert await manager.bus.claim_inbound(claimed) is True
    assert claimed.dedupe_claimed is True
    redelivery = _discord(chat_id="chan-1", channel_id="chan-1", guild_id="guild-1")
    assert await manager.bus.claim_inbound(redelivery) is False

    await manager.start()
    try:
        await manager.bus.publish_inbound(claimed)
        await manager.bus.publish_inbound(_discord(chat_id="chan-1", channel_id="chan-1", guild_id="guild-1"))
        await asyncio.wait_for(manager.bus.join_inbound(), timeout=5)
    finally:
        await manager.stop()

    assert client.runs.wait.await_count == 1


@pytest.mark.parametrize("cancelled", [False, True], ids=["grace-expired", "shutdown-cancelled"])
async def test_shutdown_gives_back_the_claim_of_a_queued_message_it_discards(cancelled):
    """An adapter-claimed message waiting in the queue owns a dedupe key no
    worker recorded. Shutdown discards it unprocessed, so it must release the
    key, or a peer drops the redelivery for the rest of the TTL."""
    dedupe = MemoryInboundDedupeStore()
    manager = _manager(dedupe=dedupe)
    manager._client = client = _client()
    busy = asyncio.Event()

    async def run_forever(*_args, **_kwargs):
        busy.set()
        await asyncio.Event().wait()

    client.runs.wait = AsyncMock(side_effect=run_forever)
    await manager.start()
    await manager.bus.publish_inbound(_slack("evt-busy"))
    await asyncio.wait_for(busy.wait(), timeout=5)
    queued = _discord(chat_id="chan-1", channel_id="chan-1", guild_id="guild-1")
    assert await manager.bus.claim_inbound(queued) is True
    await manager.bus.publish_inbound(queued)

    if cancelled:
        manager._shutdown_grace_period_seconds = 30
        stopping = asyncio.create_task(manager.stop())
        await asyncio.sleep(0)  # stop() is now waiting out the grace period
        stopping.cancel()
        with pytest.raises(asyncio.CancelledError):
            await stopping
    else:
        await manager.stop()

    assert ChannelManager._inbound_dedupe_key(queued) not in dedupe._store
    if cancelled:
        await manager.stop()


# -- Idempotency-Key on IM run requests ----------------------------------------


async def test_wait_request_carries_an_idempotency_key_stable_across_redeliveries():
    clients = []
    for _ in range(2):
        # A fresh dedupe store per delivery: the window expired, or the process restarted.
        manager = _manager()
        manager._client = client = _client()
        await manager._handle_message(_slack())
        clients.append(client)

    first, retry = (client.runs.wait.call_args for client in clients)
    key = _request_headers(first)["Idempotency-Key"]
    assert key == ChannelManager._run_idempotency_key(_slack())
    assert _request_headers(retry)["Idempotency-Key"] == key
    # The Gateway reuses a keyed run only for an identical input, so the
    # human message id must be the same on the redelivery too.
    assert _human_message(first) == _human_message(retry)
    uuid.UUID(_human_message(first)["id"])


async def test_distinct_messages_get_distinct_keys_and_message_ids():
    manager = _manager()
    manager._client = client = _client()

    await manager._handle_message(_slack("evt-1"))
    await manager._handle_message(_slack("evt-2"))

    first, second = client.runs.wait.call_args_list
    assert _request_headers(first)["Idempotency-Key"] != _request_headers(second)["Idempotency-Key"]
    assert _human_message(first)["id"] != _human_message(second)["id"]


async def test_message_without_a_dedupe_key_sends_no_idempotency_key():
    manager = _manager()
    manager._client = client = _client()

    await manager._handle_message(_slack(team_id=None))
    await manager._handle_message(_slack(team_id=None))

    first, second = client.runs.wait.call_args_list
    assert "Idempotency-Key" not in _request_headers(first)
    assert _human_message(first)["id"] != _human_message(second)["id"]


async def test_stream_request_carries_the_idempotency_key():
    manager = _manager()
    manager._client = client = _client()
    client.runs.stream = _stream(("values", {"messages": [{"type": "human", "content": "hi"}, {"type": "ai", "content": "streamed"}]}))

    await manager._handle_message(_feishu())

    assert _request_headers(client.runs.stream.call_args)["Idempotency-Key"] == ChannelManager._run_idempotency_key(_feishu())


async def test_fire_and_forget_create_carries_the_idempotency_key():
    import app.gateway.github.run_policy  # noqa: F401 — registers GitHub's fire-and-forget policy

    manager = _manager()
    manager._client = client = _client()

    await manager._handle_message(_github())

    assert _request_headers(client.runs.create.call_args)["Idempotency-Key"] == ChannelManager._run_idempotency_key(_github())


async def test_idempotency_key_rides_along_with_the_owner_headers():
    import app.gateway.github.run_policy  # noqa: F401

    msg = _github()
    manager = _manager()
    manager._client = client = _client()

    await manager._handle_message(msg)

    headers = _request_headers(client.runs.create.call_args)
    assert headers["Idempotency-Key"] == ChannelManager._run_idempotency_key(msg)
    assert headers.get(INTERNAL_OWNER_USER_ID_HEADER_NAME) == "alice"


# -- attaching a redelivery to the admitted run --------------------------------


def _state_with_turns(manager_msg: InboundMessage) -> dict:
    """Thread state where this message's turn sits between an older and a later turn."""
    ours = str(ChannelManager._human_message_id(manager_msg))
    return {
        "values": {
            "messages": [
                {"type": "human", "id": "older", "content": "older question"},
                {"type": "ai", "content": "older answer"},
                {"type": "human", "id": ours, "content": "hi"},
                {"type": "ai", "content": "the admitted run's answer"},
                {"type": "human", "id": "later", "content": "a later question"},
                {"type": "ai", "content": "a later answer"},
            ]
        }
    }


async def test_reused_wait_run_replies_with_this_messages_turn_from_thread_state():
    """``/wait`` on a reused run returns status only (the thread head may be a
    later run). The manager reads this message's own turn instead."""
    msg = _slack()
    manager = _manager()
    manager._client = client = _client()
    client.runs.wait = AsyncMock(return_value={"status": "success", "error": None})
    client.threads.get_state = AsyncMock(return_value=_state_with_turns(msg))
    sent = _outbounds(manager)

    await manager._handle_message(msg)

    assert [out.text for out in sent] == ["the admitted run's answer"]


async def test_reused_wait_run_still_in_flight_says_it_is_already_handled_and_keeps_the_key():
    msg = _slack()
    dedupe = MemoryInboundDedupeStore()
    manager = _manager(dedupe=dedupe)
    manager._client = client = _client()
    client.runs.wait = AsyncMock(return_value={"status": "running", "error": None})
    sent = _outbounds(manager)
    assert await manager._is_duplicate_inbound(msg) is False

    await manager._handle_message(msg)

    assert [out.text for out in sent] == [ALREADY_ADMITTED_MESSAGE]
    assert ChannelManager._inbound_dedupe_key(msg) in dedupe._store


async def test_reused_stream_with_a_replay_gap_replies_from_thread_state():
    msg = _feishu()
    manager = _manager()
    manager._client = client = _client()
    client.runs.stream = _stream(("gap", {"code": "stream_replay_gap", "recovery": "reload_durable_state"}))
    client.threads.get_state = AsyncMock(return_value=_state_with_turns(msg))
    sent = _outbounds(manager)

    await manager._handle_message(msg)

    assert [out.text for out in sent if out.is_final] == ["the admitted run's answer"]


@pytest.mark.parametrize(
    "detail",
    [
        "Idempotency-Key already used with a different request",
        "Run 3f2a is not active on this worker and cannot be streamed",
    ],
    ids=["input-mismatch", "foreign-active-run"],
)
async def test_conflict_from_an_admitted_keyed_run_is_not_reported_as_a_busy_thread(detail):
    """A 409 that names the keyed run (re-ingested attachments changed the
    input; the run is live on a peer) means the message was already admitted:
    keep the key and do not tell the user to retry."""
    msg = _slack()
    dedupe = MemoryInboundDedupeStore()
    manager = _manager(dedupe=dedupe)
    manager._client = client = _client()
    request = httpx.Request("POST", "http://gateway/api/threads/thread-1/runs/wait")
    client.runs.wait = AsyncMock(side_effect=ConflictError(detail, response=httpx.Response(409, request=request), body={"detail": detail}))
    sent = _outbounds(manager)
    assert await manager._is_duplicate_inbound(msg) is False

    await manager._handle_message(msg)

    assert [out.text for out in sent] == [ALREADY_ADMITTED_MESSAGE]
    assert ChannelManager._inbound_dedupe_key(msg) in dedupe._store


async def test_busy_thread_conflict_keeps_its_reply_and_releases_the_key():
    msg = _slack()
    dedupe = MemoryInboundDedupeStore()
    manager = _manager(dedupe=dedupe)
    manager._client = client = _client()
    request = httpx.Request("POST", "http://gateway/api/threads/thread-1/runs/wait")
    detail = "Thread thread-1 already has an active run"
    client.runs.wait = AsyncMock(side_effect=ConflictError(detail, response=httpx.Response(409, request=request), body={"detail": detail}))
    sent = _outbounds(manager)
    assert await manager._is_duplicate_inbound(msg) is False

    await manager._handle_message(msg)

    assert [out.text for out in sent] == [THREAD_BUSY_MESSAGE]
    assert ChannelManager._inbound_dedupe_key(msg) not in dedupe._store


@pytest.mark.parametrize(("status", "watched"), [("pending", True), ("running", True), ("success", False), ("error", False)])
async def test_followup_watcher_only_follows_a_live_run(status, watched):
    """A redelivered GitHub event gets the admitted run back; once that run has
    ended its stream may be gone, and a watcher would wait on it forever."""
    import app.gateway.github.run_policy  # noqa: F401

    manager = _manager(get_stream_bridge=lambda: MagicMock())
    manager._client = client = _client()
    client.runs.create = AsyncMock(return_value={"run_id": "run-1", "status": status})
    spawned: list[str] = []
    manager._watch_run_and_drain_followups = AsyncMock(side_effect=lambda thread_id, run_id, msg: spawned.append(run_id))

    await manager._handle_message(_github())
    await asyncio.sleep(0)

    assert spawned == (["run-1"] if watched else [])


async def test_redelivery_after_new_rebinds_the_conversation_meets_the_admitted_run(tmp_path):
    """``/new`` points the conversation at a fresh thread, so a late redelivery
    is requested there. It carries the same key, which the Gateway scopes by
    owner only for this internal caller, and its 409 must not start a run or
    read as a busy thread."""
    engine = await _shared_sql_store(tmp_path)
    try:
        store = SqlChannelStore(async_sessionmaker(engine, expire_on_commit=False))
        msg = _slack()
        first = _manager(store=store)
        first._client = first_client = _client("thread-old")
        await first._handle_message(msg)
        await first._create_thread(_client("thread-new"), _slack("evt-new-command"))  # /new

        dedupe = MemoryInboundDedupeStore()  # the dedupe window expired
        redelivery = _manager(dedupe=dedupe, store=store)
        redelivery._client = client = _client("thread-unused")
        request = httpx.Request("POST", "http://gateway/api/threads/thread-new/runs/wait")
        detail = "Idempotency-Key already used with a different request"
        client.runs.wait = AsyncMock(side_effect=ConflictError(detail, response=httpx.Response(409, request=request), body={"detail": detail}))
        sent = _outbounds(redelivery)
        assert await redelivery._is_duplicate_inbound(msg) is False

        await redelivery._handle_message(msg)

        assert client.runs.wait.call_args.args[0] == "thread-new"
        assert _request_headers(client.runs.wait.call_args)["Idempotency-Key"] == _request_headers(first_client.runs.wait.call_args)["Idempotency-Key"]
        assert [out.text for out in sent] == [ALREADY_ADMITTED_MESSAGE]
        assert ChannelManager._inbound_dedupe_key(msg) in dedupe._store
    finally:
        await engine.dispose()


# -- converging on one thread across replicas ----------------------------------


async def _shared_sql_store(tmp_path: Path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'bindings.db').as_posix()}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=[ChannelThreadBindingRow.__table__])
    return engine


async def test_replica_that_lost_the_first_binding_adopts_the_winner_and_discards_its_thread(tmp_path):
    engine = await _shared_sql_store(tmp_path)
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        manager_a, manager_b = _manager(store=SqlChannelStore(factory)), _manager(store=SqlChannelStore(factory))
        client_a, client_b = _client("thread-a"), _client("thread-b")
        msg = _slack()

        assert await manager_a._get_or_create_thread(client_a, msg) == ("thread-a", True)
        # B looked the conversation up before A's binding committed.
        manager_b._lookup_thread_id = AsyncMock(return_value=None)
        assert await manager_b._get_or_create_thread(client_b, msg) == ("thread-a", False)

        client_b.threads.delete.assert_awaited_once()
        assert client_b.threads.delete.await_args.args == ("thread-b",)
        assert await SqlChannelStore(factory).get_thread_id("slack", "C1") == "thread-a"
    finally:
        await engine.dispose()


async def test_new_command_still_rebinds_the_conversation(tmp_path):
    engine = await _shared_sql_store(tmp_path)
    try:
        store = SqlChannelStore(async_sessionmaker(engine, expire_on_commit=False))
        manager = _manager(store=store)
        msg = _slack()
        await manager._get_or_create_thread(_client("thread-first"), msg)

        assert await manager._create_thread(_client("thread-after-new"), msg) == "thread-after-new"

        assert await store.get_thread_id("slack", "C1") == "thread-after-new"
    finally:
        await engine.dispose()


async def test_connection_bound_conversation_converges_through_the_repository(tmp_path):
    from deerflow.persistence.channel_connections import ChannelConnectionRepository, ChannelCredentialCipher
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine

    await init_engine("sqlite", url=f"sqlite+aiosqlite:///{tmp_path / 'connections.db'}", sqlite_dir=str(tmp_path))
    try:
        repo = ChannelConnectionRepository(get_session_factory(), cipher=ChannelCredentialCipher.from_key("k"))
        connection = await repo.upsert_connection(owner_user_id="alice", provider="slack", external_account_id="U1", workspace_id="T1")
        msg = _slack()
        msg.connection_id, msg.owner_user_id = connection["id"], "alice"
        manager_a, manager_b = _manager(), _manager()
        manager_a._connection_repo = manager_b._connection_repo = repo
        client_b = _client("thread-b")

        assert await manager_a._get_or_create_thread(_client("thread-a"), msg) == ("thread-a", True)
        manager_b._lookup_thread_id = AsyncMock(return_value=None)
        assert await manager_b._get_or_create_thread(client_b, msg) == ("thread-a", False)

        assert client_b.threads.delete.await_args.args == ("thread-b",)
        assert await repo.get_thread_id(connection["id"], "C1") == "thread-a"
    finally:
        await close_engine()
