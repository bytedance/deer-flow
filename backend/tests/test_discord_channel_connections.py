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
        await _on_discord_loop(channel._on_message(_discord_message("hello")), discord_loop)
        await asyncio.wait_for(lookup_started.wait(), timeout=5)

        await channel._close_and_drain_threadsafe_futures()
    finally:
        _stop_discord_loop(discord_loop, thread)

    # The cancelled lookup must hand the intake slot back to the shared bus.
    await bus.publish_inbound(InboundMessage(channel_name="slack", chat_id="C1", user_id="U1", text="capacity was released"))
    assert bus.inbound_queue.qsize() == 1


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
