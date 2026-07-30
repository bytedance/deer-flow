"""Tests for Discord channel integration wiring."""

from __future__ import annotations

import asyncio
import builtins
import threading
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.channels.discord import DiscordChannel
from app.channels.manager import CHANNEL_CAPABILITIES
from app.channels.message_bus import InboundMessageType, MessageBus, OutboundMessage, ResolvedAttachment
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


# ---------------------------------------------------------------------------
# send_file file-handle lifecycle
# ---------------------------------------------------------------------------


def _start_bg_loop() -> tuple[asyncio.AbstractEventLoop, threading.Thread]:
    """Spin up a real background event loop, mirroring ``DiscordChannel._discord_loop``.

    ``send_file`` schedules work onto ``_discord_loop`` via
    ``run_coroutine_threadsafe`` and awaits the result with ``wrap_future``, so a
    real running loop is the most faithful way to exercise that path.
    """
    loop = asyncio.new_event_loop()
    ready = threading.Event()

    def _runner() -> None:
        loop.call_soon(ready.set)
        loop.run_forever()

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    ready.wait()
    return loop, thread


def _stop_bg_loop(loop: asyncio.AbstractEventLoop, thread: threading.Thread) -> None:
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=5)
    loop.close()


def _build_send_file_channel(bg_loop: asyncio.AbstractEventLoop) -> DiscordChannel:
    channel = DiscordChannel(bus=MessageBus(), config={"bot_token": "token"})
    channel._discord_loop = bg_loop
    channel._discord_module = SimpleNamespace(File=lambda fp, filename=None: fp)

    async def _noop(*_args, **_kwargs):
        return None

    channel._stop_typing = _noop
    return channel


def _tracking_open():
    """Wrap ``builtins.open`` to record every handle it returns."""
    handles: list = []
    real_open = builtins.open

    def _open(path, *args, **kwargs):
        handle = real_open(path, *args, **kwargs)
        handles.append(handle)
        return handle

    return handles, _open


async def _noop_coro(*_args, **_kwargs):
    return None


def _resolve_to(target):
    async def _resolve_target(_msg):
        return target

    return _resolve_target


@pytest.mark.asyncio
async def test_send_file_closes_file_handle(tmp_path) -> None:
    """The file handle opened for upload is closed once send_file returns (success path)."""
    bg_loop, bg_thread = _start_bg_loop()
    try:
        channel = _build_send_file_channel(bg_loop)
        target = SimpleNamespace(send=_noop_coro)
        channel._resolve_target = _resolve_to(target)

        path = tmp_path / "upload.txt"
        path.write_bytes(b"hello")
        att = ResolvedAttachment("/mnt/user-data/outputs/upload.txt", path, "upload.txt", "text/plain", 5, False)
        msg = OutboundMessage(channel_name="discord", chat_id="c1", thread_id="t1", text="t")

        handles, tracking_open = _tracking_open()
        with patch("builtins.open", tracking_open):
            result = await channel.send_file(msg, att)

        assert result is True
        assert len(handles) == 1
        assert handles[0].closed is True
    finally:
        _stop_bg_loop(bg_loop, bg_thread)


@pytest.mark.asyncio
async def test_send_file_closes_handle_when_send_fails(tmp_path) -> None:
    """The file handle is still closed when target.send raises (failure path)."""
    bg_loop, bg_thread = _start_bg_loop()
    try:
        channel = _build_send_file_channel(bg_loop)

        async def _failing_send(*, file=None):
            raise RuntimeError("upload failed")

        target = SimpleNamespace(send=_failing_send)
        channel._resolve_target = _resolve_to(target)

        path = tmp_path / "upload.txt"
        path.write_bytes(b"hello")
        att = ResolvedAttachment("/mnt/user-data/outputs/upload.txt", path, "upload.txt", "text/plain", 5, False)
        msg = OutboundMessage(channel_name="discord", chat_id="c1", thread_id="t1", text="t")

        handles, tracking_open = _tracking_open()
        with patch("builtins.open", tracking_open):
            result = await channel.send_file(msg, att)

        assert result is False
        assert len(handles) == 1
        assert handles[0].closed is True
    finally:
        _stop_bg_loop(bg_loop, bg_thread)
