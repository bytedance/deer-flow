"""Discord connection routing tests."""

from __future__ import annotations

import asyncio
import sys
import threading
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.channels.discord import DiscordChannel
from app.channels.message_bus import InboundMessage, MessageBus


@pytest.fixture
async def repo(tmp_path):
    from deerflow.persistence.channel_connections import ChannelConnectionRepository, ChannelCredentialCipher
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine

    await init_engine("sqlite", url=f"sqlite+aiosqlite:///{tmp_path / 'discord.db'}", sqlite_dir=str(tmp_path))
    try:
        yield ChannelConnectionRepository(
            get_session_factory(),
            cipher=ChannelCredentialCipher.from_key("discord-secret"),
        )
    finally:
        await close_engine()


@pytest.mark.anyio
async def test_discord_inbound_attaches_owner_identity_from_user_level_connection(repo):
    connection = await repo.upsert_connection(
        owner_user_id="alice",
        provider="discord",
        external_account_id="987",
        external_account_name="Alice",
        status="connected",
    )
    channel = DiscordChannel(
        bus=MessageBus(),
        config={"bot_token": "discord-bot", "connection_repo": repo},
    )
    inbound = InboundMessage(
        channel_name="discord",
        chat_id="C123",
        user_id="987",
        text="hello",
    )

    attached = await channel._attach_connection_identity(inbound, guild_id="G123")

    assert attached.connection_id == connection["id"]
    assert attached.owner_user_id == "alice"
    assert attached.workspace_id is None


@pytest.mark.anyio
async def test_discord_connect_command_binds_gateway_identity(repo):
    state = "discord-bind-code"
    await repo.create_oauth_state(
        owner_user_id="deerflow-user-1",
        provider="discord",
        state=state,
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    channel = DiscordChannel(
        bus=MessageBus(),
        config={"bot_token": "discord-bot", "connection_repo": repo},
    )
    message = MagicMock()
    message.author.id = 987
    message.author.display_name = "Alice"
    message.guild.id = 123
    message.guild.name = "Deer Guild"
    message.channel.id = 456
    message.channel.send = AsyncMock()

    async def _passthrough(coro):
        return await coro

    channel._run_on_discord_loop = AsyncMock(side_effect=_passthrough)

    handled = await channel._bind_connection_from_connect_code_on_main(message, state)

    connections = await repo.list_connections("deerflow-user-1")
    assert handled is True
    assert len(connections) == 1
    assert connections[0]["provider"] == "discord"
    assert connections[0]["external_account_id"] == "987"
    assert connections[0]["external_account_name"] == "Alice"
    assert connections[0]["workspace_id"] == "123"
    assert connections[0]["workspace_name"] == "Deer Guild"
    assert connections[0]["metadata"]["channel_id"] == "456"
    message.channel.send.assert_awaited_once()


# ---------------------------------------------------------------------------
# Connection repository calls stay on the Gateway loop
# ---------------------------------------------------------------------------
#
# discord.py runs ``_on_message`` on a private loop in the client thread, while
# the repository's SQLAlchemy engine and pool belong to the Gateway loop.
# Awaiting the repository from the Discord loop fails with asyncpg ("attached to
# a different loop") and binds the pool's wait queue to the wrong loop under
# aiosqlite contention, so every repository call must run on ``_main_loop``.


class _LoopRecordingRepo:
    """Delegate to the real repository, recording the loop of every call."""

    def __init__(self, repo) -> None:
        self._repo = repo
        self.calls: list[tuple[str, asyncio.AbstractEventLoop]] = []

    def __getattr__(self, name: str):
        method = getattr(self._repo, name)

        async def _recorded(*args, **kwargs):
            self.calls.append((name, asyncio.get_running_loop()))
            return await method(*args, **kwargs)

        return _recorded


def _start_discord_loop() -> tuple[asyncio.AbstractEventLoop, threading.Thread]:
    """A real background loop standing in for discord.py's client loop."""
    loop = asyncio.new_event_loop()
    ready = threading.Event()

    def _runner() -> None:
        loop.call_soon(ready.set)
        loop.run_forever()

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    ready.wait()
    return loop, thread


def _stop_discord_loop(loop: asyncio.AbstractEventLoop, thread: threading.Thread) -> None:
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=5)
    loop.close()


def _discord_channel_on_loops(bus: MessageBus, repo, discord_loop: asyncio.AbstractEventLoop) -> DiscordChannel:
    channel = DiscordChannel(bus=bus, config={"bot_token": "token", "connection_repo": repo})
    channel._running = True
    channel._client = SimpleNamespace(user=SimpleNamespace(id=999, mention="<@999>"))
    channel._discord_module = SimpleNamespace(Thread=type("FakeThread", (), {}))
    channel._main_loop = asyncio.get_running_loop()
    channel._discord_loop = discord_loop

    async def noop(*_args, **_kwargs):
        return None

    channel._start_typing = noop
    channel._add_reaction = noop
    return channel


def _discord_message(text: str, *, send=None):
    return SimpleNamespace(
        id=111,
        content=text,
        author=SimpleNamespace(id=987, bot=False, display_name="Alice", name="alice"),
        guild=SimpleNamespace(id=123, name="Deer Guild"),
        channel=SimpleNamespace(id=456, send=send or AsyncMock()),
        add_reaction=lambda _emoji: None,
    )


async def _on_discord_loop(coro, loop: asyncio.AbstractEventLoop):
    """Run *coro* on the Discord loop, as discord.py dispatches ``on_message``."""
    return await asyncio.wait_for(asyncio.wrap_future(asyncio.run_coroutine_threadsafe(coro, loop)), timeout=5)


@pytest.mark.anyio
async def test_discord_message_resolves_identity_on_gateway_loop(repo):
    connection = await repo.upsert_connection(
        owner_user_id="alice",
        provider="discord",
        external_account_id="987",
        external_account_name="Alice",
        status="connected",
    )
    recording = _LoopRecordingRepo(repo)
    bus = MessageBus()
    discord_loop, thread = _start_discord_loop()
    try:
        channel = _discord_channel_on_loops(bus, recording, discord_loop)
        await _on_discord_loop(channel._on_message(_discord_message("hello")), discord_loop)
        inbound = await asyncio.wait_for(bus.get_inbound(), timeout=5)
        bus.inbound_task_done()
    finally:
        _stop_discord_loop(discord_loop, thread)

    assert inbound.connection_id == connection["id"]
    assert inbound.owner_user_id == "alice"
    assert recording.calls, "identity lookup never reached the repository"
    assert all(loop is channel._main_loop for _name, loop in recording.calls)


@pytest.mark.anyio
async def test_discord_connect_code_binds_on_gateway_loop_and_replies_on_discord_loop(repo):
    state = "discord-bind-code"
    await repo.create_oauth_state(
        owner_user_id="deerflow-user-1",
        provider="discord",
        state=state,
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    recording = _LoopRecordingRepo(repo)
    reply_loops: list[asyncio.AbstractEventLoop] = []
    replied = asyncio.Event()
    main_loop = asyncio.get_running_loop()

    async def _send(text: str) -> None:
        reply_loops.append(asyncio.get_running_loop())
        main_loop.call_soon_threadsafe(replied.set)

    bus = MessageBus()
    discord_loop, thread = _start_discord_loop()
    try:
        channel = _discord_channel_on_loops(bus, recording, discord_loop)
        await _on_discord_loop(channel._on_message(_discord_message(f"/connect {state}", send=_send)), discord_loop)
        await asyncio.wait_for(replied.wait(), timeout=5)
    finally:
        _stop_discord_loop(discord_loop, thread)

    connections = await repo.list_connections("deerflow-user-1")
    assert [c["external_account_id"] for c in connections] == ["987"]
    assert [name for name, _loop in recording.calls] == ["consume_oauth_state", "upsert_connection"]
    assert all(loop is main_loop for _name, loop in recording.calls)
    assert reply_loops == [discord_loop]
    # A consumed bind code is a control-plane command, never an agent turn.
    assert bus.inbound_queue.qsize() == 0


@pytest.mark.anyio
async def test_discord_stop_cancels_pending_identity_lookup_and_releases_intake(repo):
    lookup_started = asyncio.Event()

    class _BlockingRepo:
        async def find_connection_by_external_identity(self, **_kwargs):
            lookup_started.set()
            await asyncio.Event().wait()

    bus = MessageBus(inbound_queue_maxsize=1)
    discord_loop, thread = _start_discord_loop()
    try:
        channel = _discord_channel_on_loops(bus, _BlockingRepo(), discord_loop)
        # _on_message waits on the hand-off, so it stays pending with the lookup.
        on_message = asyncio.run_coroutine_threadsafe(channel._on_message(_discord_message("hello")), discord_loop)
        await asyncio.wait_for(lookup_started.wait(), timeout=5)

        await channel._close_and_drain_threadsafe_futures()
        # The drain settles the hand-off, so the Discord-side handler finishes too.
        await asyncio.wait_for(asyncio.wrap_future(on_message), timeout=5)
    finally:
        _stop_discord_loop(discord_loop, thread)

    # The cancelled lookup must hand the intake slot back to the shared bus.
    await bus.publish_inbound(InboundMessage(channel_name="slack", chat_id="C1", user_id="U1", text="capacity was released"))
    assert bus.inbound_queue.qsize() == 1


@pytest.mark.anyio
async def test_discord_unscheduled_bind_is_handled_but_leaves_code_unconsumed(repo):
    state = "discord-bind-code"
    await repo.create_oauth_state(
        owner_user_id="deerflow-user-1",
        provider="discord",
        state=state,
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    bus = MessageBus()
    channel = DiscordChannel(bus=bus, config={"bot_token": "token", "connection_repo": repo})
    channel._main_loop = None  # Gateway loop already gone

    handled = await channel._bind_connection_from_connect_code(_discord_message(f"/connect {state}"), state)

    # The message is swallowed rather than published as a chat turn, but the
    # one-time code was never consumed, so a retry after restart still binds.
    assert handled is True
    assert bus.inbound_queue.qsize() == 0
    assert await repo.consume_oauth_state(provider="discord", state=state) is not None


class _FailingIdentityRepo:
    async def find_connection_by_external_identity(self, **_kwargs):
        raise RuntimeError("database unavailable")


def _channel_with_real_typing(bus: MessageBus, repo, discord_loop: asyncio.AbstractEventLoop, reactions: list[int]) -> DiscordChannel:
    channel = _discord_channel_on_loops(bus, repo, discord_loop)
    del channel._start_typing  # exercise the real typing loop

    async def _record_reaction(message) -> None:
        reactions.append(message.id)

    channel._add_reaction = _record_reaction
    return channel


def _typing_message(text: str = "hello"):
    message = _discord_message(text)

    async def _typing() -> None:
        return None

    message.channel.typing = _typing
    return message


@pytest.mark.anyio
async def test_discord_failed_identity_lookup_stops_typing_and_skips_ack():
    # A raising lookup drops the message, so nothing may keep reporting that
    # the bot is working on it: no typing loop left behind, no ack reaction.
    reactions: list[int] = []
    bus = MessageBus(inbound_queue_maxsize=1)
    discord_loop, thread = _start_discord_loop()
    try:
        channel = _channel_with_real_typing(bus, _FailingIdentityRepo(), discord_loop, reactions)
        await _on_discord_loop(channel._on_message(_typing_message()), discord_loop)
        await _on_discord_loop(asyncio.sleep(0), discord_loop)
        typing_targets = list(channel._typing_tasks)
    finally:
        _stop_discord_loop(discord_loop, thread)

    assert typing_targets == []
    assert reactions == []
    assert bus.inbound_queue.qsize() == 0
    await bus.publish_inbound(InboundMessage(channel_name="slack", chat_id="C1", user_id="U1", text="capacity was released"))
    assert bus.inbound_queue.qsize() == 1


@pytest.mark.anyio
async def test_discord_failed_identity_lookup_keeps_another_messages_typing():
    reactions: list[int] = []
    bus = MessageBus()
    discord_loop, thread = _start_discord_loop()
    try:
        channel = _channel_with_real_typing(bus, _FailingIdentityRepo(), discord_loop, reactions)

        async def _register_in_flight_typing() -> asyncio.Task:
            # An earlier message to the same target already shows typing.
            await channel._start_typing(_typing_message().channel, "456")
            return channel._typing_tasks["456"]

        in_flight = await _on_discord_loop(_register_in_flight_typing(), discord_loop)
        await _on_discord_loop(channel._on_message(_typing_message()), discord_loop)
        still_registered = channel._typing_tasks.get("456") is in_flight
        await _on_discord_loop(channel._cancel_typing_tasks(), discord_loop)
    finally:
        _stop_discord_loop(discord_loop, thread)

    assert still_registered


@pytest.mark.anyio
async def test_discord_committed_message_keeps_typing_and_acks(repo):
    await repo.upsert_connection(owner_user_id="alice", provider="discord", external_account_id="987", status="connected")
    reactions: list[int] = []
    bus = MessageBus()
    discord_loop, thread = _start_discord_loop()
    try:
        channel = _channel_with_real_typing(bus, repo, discord_loop, reactions)
        await _on_discord_loop(channel._on_message(_typing_message()), discord_loop)
        await _on_discord_loop(asyncio.sleep(0), discord_loop)
        typing_targets = list(channel._typing_tasks)
        await _on_discord_loop(channel._cancel_typing_tasks(), discord_loop)
        inbound = await asyncio.wait_for(bus.get_inbound(), timeout=5)
        bus.inbound_task_done()
    finally:
        _stop_discord_loop(discord_loop, thread)

    assert inbound.owner_user_id == "alice"
    assert typing_targets == ["456"]
    assert reactions == [111]


@pytest.mark.anyio
async def test_discord_reply_stopping_typing_during_handoff_leaves_no_indicator():
    # A reply can stop typing while the hand-off is still settling. Typing is
    # registered before the hand-off, so that stop wins; starting it after the
    # hand-off resolved would leave an indicator nothing ever stops.
    reactions: list[int] = []
    bus = MessageBus()
    discord_loop, thread = _start_discord_loop()
    try:
        channel = None

        class _ReplyDuringLookupRepo:
            async def find_connection_by_external_identity(self, **_kwargs):
                asyncio.run_coroutine_threadsafe(channel._stop_typing("456"), discord_loop)
                return None

        channel = _channel_with_real_typing(bus, _ReplyDuringLookupRepo(), discord_loop, reactions)
        await _on_discord_loop(channel._on_message(_typing_message()), discord_loop)
        await _on_discord_loop(asyncio.sleep(0), discord_loop)
        typing_targets = list(channel._typing_tasks)
        await _on_discord_loop(channel._cancel_typing_tasks(), discord_loop)
        await asyncio.wait_for(bus.get_inbound(), timeout=5)
        bus.inbound_task_done()
    finally:
        _stop_discord_loop(discord_loop, thread)

    assert typing_targets == []
    assert reactions == [111]


@pytest.mark.anyio
async def test_discord_cancelled_handler_leaves_the_shared_handoff_to_settle():
    # discord.py may cancel a handler mid-wait. That must not cancel the shared
    # completion future, or the submission finalizer fails to settle it and the
    # already-running commit is reported as an error on the Gateway loop.
    main_loop = asyncio.get_running_loop()
    lookup_started = asyncio.Event()
    release = asyncio.Event()
    loop_errors: list[dict] = []

    class _GatedRepo:
        async def find_connection_by_external_identity(self, **_kwargs):
            lookup_started.set()
            await release.wait()
            return None

    previous_handler = main_loop.get_exception_handler()
    main_loop.set_exception_handler(lambda _loop, context: loop_errors.append(context))
    bus = MessageBus()
    discord_loop, thread = _start_discord_loop()
    try:
        channel = _discord_channel_on_loops(bus, _GatedRepo(), discord_loop)
        on_message = asyncio.run_coroutine_threadsafe(channel._on_message(_discord_message("hello")), discord_loop)
        await asyncio.wait_for(lookup_started.wait(), timeout=5)
        on_message.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(asyncio.wrap_future(on_message), timeout=5)

        release.set()
        inbound = await asyncio.wait_for(bus.get_inbound(), timeout=5)
        bus.inbound_task_done()
        await asyncio.sleep(0)
    finally:
        main_loop.set_exception_handler(previous_handler)
        _stop_discord_loop(discord_loop, thread)

    assert inbound.text == "hello"
    assert loop_errors == []


def _fake_discord_module() -> SimpleNamespace:
    class _Client:
        def __init__(self, **_kwargs) -> None:
            self.user = None

        def event(self, handler):
            return handler

    return SimpleNamespace(
        Intents=SimpleNamespace(default=lambda: SimpleNamespace()),
        AllowedMentions=SimpleNamespace(none=lambda: None),
        Client=_Client,
    )


@pytest.mark.anyio
async def test_discord_stop_closes_and_restart_reopens_threadsafe_submission_intake():
    channel = DiscordChannel(bus=MessageBus(), config={"bot_token": "token"})
    channel._running = True
    channel._discord_loop = None
    loop = asyncio.get_running_loop()

    async def _probe() -> None:
        return None

    await channel.stop()
    # stop() drains and closes intake, so a late SDK callback cannot start work.
    assert channel._submit_threadsafe_coroutine(_probe(), loop, name="probe", msg_id=None) is False

    with (
        patch.dict(sys.modules, {"discord": _fake_discord_module()}),
        patch.object(DiscordChannel, "_run_client") as run_client,
        patch.object(DiscordChannel, "_load_active_threads"),
    ):
        await channel.start()
        await asyncio.to_thread(channel._thread.join, 5)
    run_client.assert_called_once()

    # A restarted channel must accept work again, or every message is dropped.
    assert channel._submit_threadsafe_coroutine(_probe(), loop, name="probe", msg_id=None) is True
    await channel._close_and_drain_threadsafe_futures()
