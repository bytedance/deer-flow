"""Tests for Telegram deep-link channel connections."""

from __future__ import annotations

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
    update = _telegram_update(text=f"/start {state}")
    context = MagicMock()
    context.args = [state]

    await channel._cmd_start(update, context)

    connections = await repo.list_connections("deerflow-user-1")
    assert len(connections) == 1
    assert connections[0]["provider"] == "telegram"
    assert connections[0]["external_account_id"] == "42"
    assert connections[0]["external_account_name"] == "Alice Example"
    assert connections[0]["workspace_id"] == "100"
    assert connections[0]["metadata"]["chat_type"] == "private"
    update.message.reply_text.assert_awaited_once()
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
    channel._main_loop = __import__("asyncio").get_event_loop()
    channel._send_running_reply = AsyncMock()

    await channel._on_text(_telegram_update(text="hello"), None)
    inbound = await bus.get_inbound()

    assert inbound.connection_id == connection["id"]
    assert inbound.owner_user_id == "deerflow-user-1"
    assert inbound.workspace_id == "100"
    assert inbound.user_id == "42"
    assert inbound.chat_id == "100"
    assert inbound.text == "hello"
