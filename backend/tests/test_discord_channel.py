"""Tests for Discord channel integration wiring."""

from __future__ import annotations

import sys
import types

_langgraph_sdk = types.ModuleType("langgraph_sdk")
_langgraph_sdk_errors = types.ModuleType("langgraph_sdk.errors")


class _ConflictError(Exception):
    pass


_langgraph_sdk_errors.ConflictError = _ConflictError
_langgraph_sdk.errors = _langgraph_sdk_errors
sys.modules.setdefault("langgraph_sdk", _langgraph_sdk)
sys.modules.setdefault("langgraph_sdk.errors", _langgraph_sdk_errors)

from app.channels.discord import DiscordChannel  # noqa: E402
from app.channels.manager import CHANNEL_CAPABILITIES  # noqa: E402
from app.channels.message_bus import MessageBus  # noqa: E402
from app.channels.service import _CHANNEL_REGISTRY  # noqa: E402


def test_discord_channel_registered() -> None:
    assert "discord" in _CHANNEL_REGISTRY


def test_discord_channel_capabilities() -> None:
    assert "discord" in CHANNEL_CAPABILITIES


def test_discord_channel_init() -> None:
    bus = MessageBus()
    channel = DiscordChannel(bus=bus, config={"bot_token": "token"})

    assert channel.name == "discord"
