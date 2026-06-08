"""Tests for Discord channel integration wiring."""

from __future__ import annotations

from app.channels.discord import DiscordChannel
from app.channels.manager import CHANNEL_CAPABILITIES
from app.channels.message_bus import MessageBus
from app.channels.service import _CHANNEL_REGISTRY


def test_discord_channel_registered() -> None:
    assert "discord" in _CHANNEL_REGISTRY


def test_discord_channel_capabilities() -> None:
    assert "discord" in CHANNEL_CAPABILITIES


def test_discord_channel_init() -> None:
    bus = MessageBus()
    channel = DiscordChannel(bus=bus, config={"bot_token": "token"})

    assert channel.name == "discord"


def test_discord_mention_only_defaults_to_true() -> None:
    """Regression for #2846: bots that respond to every message are disruptive
    on shared servers.  mention_only must default to True so the bot only
    reacts when @-mentioned, matching standard Discord bot etiquette."""
    bus = MessageBus()
    channel = DiscordChannel(bus=bus, config={"bot_token": "token"})

    assert channel._mention_only is True


def test_discord_mention_only_can_be_disabled_via_config() -> None:
    """Operators can opt out of mention_only to get the all-messages behaviour."""
    bus = MessageBus()
    channel = DiscordChannel(bus=bus, config={"bot_token": "token", "mention_only": False})

    assert channel._mention_only is False


def test_discord_thread_mode_defaults_to_mention_only() -> None:
    """thread_mode defaults to the same value as mention_only (True)."""
    bus = MessageBus()
    channel = DiscordChannel(bus=bus, config={"bot_token": "token"})

    assert channel._thread_mode is True


def test_discord_thread_mode_can_be_overridden_independently() -> None:
    """thread_mode can be set independently of mention_only."""
    bus = MessageBus()
    channel = DiscordChannel(bus=bus, config={"bot_token": "token", "mention_only": True, "thread_mode": False})

    assert channel._mention_only is True
    assert channel._thread_mode is False
