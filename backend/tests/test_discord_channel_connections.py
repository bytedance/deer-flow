"""Discord connection routing tests."""

from __future__ import annotations

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
