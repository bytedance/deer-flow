"""Tests for Discord channel integration wiring."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.channels.discord import DiscordChannel
from app.channels.manager import CHANNEL_CAPABILITIES
from app.channels.message_bus import InboundMessageType, MessageBus
from app.channels.service import _CHANNEL_REGISTRY


def test_discord_channel_registered() -> None:
    assert "discord" in _CHANNEL_REGISTRY


def test_discord_channel_capabilities() -> None:
    assert "discord" in CHANNEL_CAPABILITIES


def test_discord_channel_init() -> None:
    bus = MessageBus()
    channel = DiscordChannel(bus=bus, config={"bot_token": "token"})

    assert channel.name == "discord"


def _make_discord_message(text: str):
    return SimpleNamespace(
        id=111,
        content=text,
        author=SimpleNamespace(id=123, bot=False, display_name="alice"),
        guild=SimpleNamespace(id=321),
        channel=SimpleNamespace(id=456),
        add_reaction=lambda _emoji: None,
    )


@pytest.mark.asyncio
async def test_discord_bot_mention_slash_skill_routes_as_chat() -> None:
    bus = MessageBus()
    channel = DiscordChannel(bus=bus, config={"bot_token": "token"})
    captured = []
    channel._running = True
    channel._client = SimpleNamespace(user=SimpleNamespace(id=999, mention="<@999>"))
    channel._discord_module = SimpleNamespace(Thread=type("FakeThread", (), {}))
    channel._publish = captured.append

    async def noop(*_args, **_kwargs):
        return None

    channel._start_typing = noop
    channel._add_reaction = noop

    await channel._on_message(_make_discord_message("<@999> /data-analysis analyze uploads/foo.csv"))

    assert len(captured) == 1
    inbound = captured[0]
    assert inbound.text == "/data-analysis analyze uploads/foo.csv"
    assert inbound.msg_type == InboundMessageType.CHAT
    assert inbound.topic_id == "456"


@pytest.mark.asyncio
async def test_discord_bot_mention_known_command_routes_as_command() -> None:
    bus = MessageBus()
    channel = DiscordChannel(bus=bus, config={"bot_token": "token"})
    captured = []
    channel._running = True
    channel._client = SimpleNamespace(user=SimpleNamespace(id=999, mention="<@999>"))
    channel._discord_module = SimpleNamespace(Thread=type("FakeThread", (), {}))
    channel._publish = captured.append

    async def noop(*_args, **_kwargs):
        return None

    channel._start_typing = noop
    channel._add_reaction = noop

    await channel._on_message(_make_discord_message("<@999> /help"))

    assert len(captured) == 1
    inbound = captured[0]
    assert inbound.text == "/help"
    assert inbound.msg_type == InboundMessageType.COMMAND
    assert inbound.topic_id == "456"
