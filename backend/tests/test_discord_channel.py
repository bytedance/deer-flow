"""Tests for Discord channel integration wiring."""

from __future__ import annotations

import json

from app.channels.discord import _DISCORD_THREAD_MAPPING_TOPIC_ID, DiscordChannel
from app.channels.manager import CHANNEL_CAPABILITIES
from app.channels.message_bus import MessageBus
from app.channels.service import _CHANNEL_REGISTRY
from app.channels.store import ChannelStore


def test_discord_channel_registered() -> None:
    assert "discord" in _CHANNEL_REGISTRY


def test_discord_channel_capabilities() -> None:
    assert "discord" in CHANNEL_CAPABILITIES


def test_discord_channel_init() -> None:
    bus = MessageBus()
    channel = DiscordChannel(bus=bus, config={"bot_token": "token"})

    assert channel.name == "discord"


def test_discord_save_thread_persists_to_channel_store(tmp_path) -> None:
    bus = MessageBus()
    store = ChannelStore(path=tmp_path / "store.json")
    channel = DiscordChannel(bus=bus, config={"bot_token": "token", "channel_store": store})

    channel._save_thread("channel-1", "discord-thread-1")

    assert (
        store.get_thread_id(
            "discord",
            "channel-1",
            topic_id=_DISCORD_THREAD_MAPPING_TOPIC_ID,
        )
        == "discord-thread-1"
    )
    assert channel._active_threads["channel-1"] == "discord-thread-1"
    assert "discord-thread-1" in channel._active_thread_ids


def test_discord_load_active_threads_restores_from_channel_store(tmp_path) -> None:
    bus = MessageBus()
    store = ChannelStore(path=tmp_path / "store.json")
    store.set_thread_id(
        "discord",
        "channel-1",
        "discord-thread-1",
        topic_id=_DISCORD_THREAD_MAPPING_TOPIC_ID,
    )
    store.set_thread_id("discord", "channel-2", "deerflow-thread-2", topic_id="discord-topic-2")
    channel = DiscordChannel(bus=bus, config={"bot_token": "token", "channel_store": store})

    channel._load_active_threads()

    assert channel._active_threads == {"channel-1": "discord-thread-1"}
    assert channel._active_thread_ids == {"discord-thread-1"}


def test_discord_load_active_threads_migrates_legacy_file(tmp_path) -> None:
    bus = MessageBus()
    store = ChannelStore(path=tmp_path / "store.json")
    legacy_path = tmp_path / "discord_threads.json"
    legacy_path.write_text(json.dumps({"channel-legacy": "discord-thread-legacy"}), encoding="utf-8")
    channel = DiscordChannel(bus=bus, config={"bot_token": "token", "channel_store": store})

    channel._load_active_threads()

    assert channel._active_threads == {"channel-legacy": "discord-thread-legacy"}
    assert (
        store.get_thread_id(
            "discord",
            "channel-legacy",
            topic_id=_DISCORD_THREAD_MAPPING_TOPIC_ID,
        )
        == "discord-thread-legacy"
    )
