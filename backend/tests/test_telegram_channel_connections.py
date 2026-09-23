"""Tests for Telegram deep-link channel connections."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.channels.message_bus import MessageBus
from app.channels.telegram import TelegramChannel


@pytest.fixture
async def repo(tmp_path: Path):
    from deerflow.persistence.channel_connections import ChannelConnectionRepository, ChannelCredentialCipher
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine

    await init_engine("sqlite", url=f"sqlite+aiosqlite:///{tmp_path / 'telegram.db'}", sqlite_dir=str(tmp_path))
    try:
        yield ChannelConnectionRepository(
            get_session_factory(),
            cipher=ChannelCredentialCipher.from_key("telegram-secret"),
        )
    finally:
        await close_engine()


def _telegram_update(*, text: str = "/start", user_id: int = 42, chat_id: int = 100, chat_type: str = "private"):
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_user.username = "alice"
    update.effective_user.full_name = "Alice Example"
    update.effective_chat.id = chat_id
    update.effective_chat.type = chat_type
    update.message.text = text
    update.message.message_id = 55
    update.message.reply_to_message = None
    update.message.reply_text = AsyncMock()
    return update


async def _await_connections(repo, owner_user_id: str, *, timeout: float = 2.0) -> list:
    """Poll the connection repo until rows for the owner appear or the deadline passes.

    The bind runs as a scheduled task on the (test) main loop, so the test must
    yield until it completes. A deadline gives a loaded CI runner headroom for the
    aiosqlite thread hops in consume_oauth_state / upsert_connection instead of a
    fixed iteration count that can time out and mask the real bind failure.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    connections: list = []
    while loop.time() < deadline:
        connections = await repo.list_connections(owner_user_id)
        if connections:
            return connections
        await asyncio.sleep(0.01)
    return connections


async def _await_reply(reply_text, *, timeout: float = 2.0) -> None:
    """Yield until the bind task has dispatched its reply (the task's final step).

    The reply is sent right after the upsert, so the connection row can be visible
    before the reply has been awaited; wait for the reply explicitly instead of
    relying on an incidental extra await.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while reply_text.await_count == 0 and loop.time() < deadline:
        await asyncio.sleep(0.01)


@pytest.mark.anyio
async def test_start_with_deep_link_state_binds_telegram_chat(repo):
    state = "telegram-bind-state"
    await repo.create_oauth_state(
        owner_user_id="deerflow-user-1",
        provider="telegram",
        state=state,
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    channel = TelegramChannel(
        bus=MessageBus(),
        config={"bot_token": "test-token", "connection_repo": repo},
    )
    channel._main_loop = asyncio.get_running_loop()
    update = _telegram_update(text=f"/start {state}")
    context = MagicMock()
    context.args = [state]

    await channel._cmd_start(update, context)
    connections = await _await_connections(repo, "deerflow-user-1")
    await _await_reply(update.message.reply_text)

    assert len(connections) == 1
    assert connections[0]["provider"] == "telegram"
    assert connections[0]["external_account_id"] == "42"
    assert connections[0]["external_account_name"] == "Alice Example"
    assert connections[0]["workspace_id"] == "100"
    assert connections[0]["metadata"]["chat_type"] == "private"
    update.message.reply_text.assert_awaited_once()
    assert "connected" in update.message.reply_text.await_args.args[0].lower()


@pytest.mark.anyio
async def test_start_token_bypasses_allowed_users_filter(repo):
    # A newly allowlisted-but-unbound user must be able to bootstrap their first
    # bind via the deep-link start token even though their Telegram id is not yet
    # in allowed_users. The allowed_users gate must run after token handling.
    state = "telegram-bind-state"
    await repo.create_oauth_state(
        owner_user_id="deerflow-user-1",
        provider="telegram",
        state=state,
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    channel = TelegramChannel(
        bus=MessageBus(),
        config={
            "bot_token": "test-token",
            "connection_repo": repo,
            "allowed_users": [999],  # newcomer (42) is not whitelisted
        },
    )
    channel._main_loop = asyncio.get_running_loop()
    update = _telegram_update(text=f"/start {state}", user_id=42)
    context = MagicMock()
    context.args = [state]

    await channel._cmd_start(update, context)
    connections = await _await_connections(repo, "deerflow-user-1")
    await _await_reply(update.message.reply_text)

    assert len(connections) == 1
    assert connections[0]["external_account_id"] == "42"
    assert "connected" in update.message.reply_text.await_args.args[0].lower()


@pytest.mark.anyio
async def test_bound_telegram_message_publishes_connection_identity(repo):
    connection = await repo.upsert_connection(
        owner_user_id="deerflow-user-1",
        provider="telegram",
        external_account_id="42",
        external_account_name="Alice Example",
        workspace_id="100",
        metadata={"chat_type": "private"},
    )
    bus = MessageBus()
    channel = TelegramChannel(
        bus=bus,
        config={"bot_token": "test-token", "connection_repo": repo},
    )
    channel._main_loop = asyncio.get_running_loop()
    channel._send_running_reply = AsyncMock()

    await channel._on_text(_telegram_update(text="hello"), None)
    inbound = await bus.get_inbound()

    assert inbound.connection_id == connection["id"]
    assert inbound.owner_user_id == "deerflow-user-1"
    assert inbound.workspace_id == "100"
    assert inbound.user_id == "42"
    assert inbound.chat_id == "100"
    assert inbound.text == "hello"


@pytest.mark.anyio
async def test_bind_dispatcher_uses_submit_threadsafe_when_main_loop_running(repo):
    channel = TelegramChannel(
        bus=MessageBus(),
        config={"bot_token": "test-token", "connection_repo": repo},
    )
    channel._main_loop = asyncio.get_running_loop()

    def _fake_submit(coroutine, *args, **kwargs):
        coroutine.close()
        return True

    channel._submit_threadsafe_coroutine = MagicMock(side_effect=_fake_submit)
    channel._bind_connection_from_start_token_on_main = AsyncMock(return_value=True)

    handled = await channel._bind_connection_from_start_token(_telegram_update(), "bind-token")

    assert handled is True
    channel._submit_threadsafe_coroutine.assert_called_once()
    assert channel._submit_threadsafe_coroutine.call_args.kwargs["name"] == "bind_connection"
    channel._bind_connection_from_start_token_on_main.assert_called_once()
    channel._bind_connection_from_start_token_on_main.assert_not_awaited()


@pytest.mark.anyio
async def test_bind_on_main_replies_via_telegram_loop(repo):
    state = "telegram-bind-state"
    await repo.create_oauth_state(
        owner_user_id="deerflow-user-1",
        provider="telegram",
        state=state,
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    channel = TelegramChannel(
        bus=MessageBus(),
        config={"bot_token": "test-token", "connection_repo": repo},
    )

    async def _passthrough(coro):
        return await coro

    channel._run_on_telegram_loop = AsyncMock(side_effect=_passthrough)
    update = _telegram_update(text=f"/start {state}")

    assert await channel._bind_connection_from_start_token_on_main(update, state) is True

    channel._run_on_telegram_loop.assert_awaited_once()
    update.message.reply_text.assert_called_once()
    assert "connected" in update.message.reply_text.call_args.args[0].lower()
    connections = await repo.list_connections("deerflow-user-1")
    assert len(connections) == 1
