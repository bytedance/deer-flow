"""Tests for Discord channel integration wiring."""

from __future__ import annotations

import asyncio
import builtins
import gc
import threading
import weakref
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.channels.discord import DiscordChannel
from app.channels.manager import CHANNEL_CAPABILITIES
from app.channels.message_bus import InboundMessage, InboundMessageType, MessageBus, OutboundMessage, ResolvedAttachment
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
    channel._running = True
    channel._client = SimpleNamespace(user=SimpleNamespace(id=999, mention="<@999>"))
    channel._discord_module = SimpleNamespace(Thread=type("FakeThread", (), {}))
    channel._main_loop = asyncio.get_running_loop()

    async def noop(*_args, **_kwargs):
        return None

    channel._start_typing = noop
    channel._add_reaction = noop

    await channel._on_message(_make_discord_message("<@999> /data-analysis analyze uploads/foo.csv"))
    await asyncio.sleep(0)

    inbound = bus.get_inbound_nowait()
    bus.inbound_task_done()
    assert inbound.text == "/data-analysis analyze uploads/foo.csv"
    assert inbound.msg_type == InboundMessageType.CHAT
    assert inbound.topic_id == "456"


@pytest.mark.asyncio
async def test_discord_bot_mention_known_command_routes_as_command() -> None:
    bus = MessageBus()
    channel = DiscordChannel(bus=bus, config={"bot_token": "token"})
    channel._running = True
    channel._client = SimpleNamespace(user=SimpleNamespace(id=999, mention="<@999>"))
    channel._discord_module = SimpleNamespace(Thread=type("FakeThread", (), {}))
    channel._main_loop = asyncio.get_running_loop()

    async def noop(*_args, **_kwargs):
        return None

    channel._start_typing = noop
    channel._add_reaction = noop

    await channel._on_message(_make_discord_message("<@999> /help"))
    await asyncio.sleep(0)

    inbound = bus.get_inbound_nowait()
    bus.inbound_task_done()
    assert inbound.text == "/help"
    assert inbound.msg_type == InboundMessageType.COMMAND
    assert inbound.topic_id == "456"


@pytest.mark.asyncio
async def test_discord_full_queue_rejects_before_thread_or_identity_side_effects() -> None:
    bus = MessageBus(inbound_queue_maxsize=1)
    await bus.publish_inbound(
        InboundMessage(
            channel_name="slack",
            chat_id="C1",
            user_id="U1",
            text="already queued",
        )
    )
    channel = DiscordChannel(bus=bus, config={"bot_token": "token", "thread_mode": True})
    channel._running = True
    channel._client = SimpleNamespace(user=SimpleNamespace(id=999, mention="<@999>"))
    channel._discord_module = SimpleNamespace(Thread=type("FakeThread", (), {}))
    channel._main_loop = asyncio.get_running_loop()
    channel._create_thread = AsyncMock()
    channel._attach_connection_identity = AsyncMock()

    await channel._on_message(_make_discord_message("hello"))

    channel._create_thread.assert_not_awaited()
    channel._attach_connection_identity.assert_not_awaited()
    assert channel._active_threads == {}
    assert bus.inbound_queue.qsize() == 1


@pytest.mark.asyncio
async def test_discord_releases_early_reservation_when_thread_creation_raises() -> None:
    bus = MessageBus(inbound_queue_maxsize=1)
    channel = DiscordChannel(bus=bus, config={"bot_token": "token", "thread_mode": True})
    channel._running = True
    channel._client = SimpleNamespace(user=SimpleNamespace(id=999, mention="<@999>"))
    channel._discord_module = SimpleNamespace(Thread=type("FakeThread", (), {}))
    channel._main_loop = asyncio.get_running_loop()
    channel._create_thread = AsyncMock(side_effect=RuntimeError("thread create failed"))

    with pytest.raises(RuntimeError, match="thread create failed"):
        await channel._on_message(_make_discord_message("hello"))

    # The exception path must return the capacity slot to the shared bus.
    await bus.publish_inbound(
        InboundMessage(
            channel_name="slack",
            chat_id="C1",
            user_id="U1",
            text="capacity was released",
        )
    )
    assert bus.inbound_queue.qsize() == 1


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


@pytest.mark.asyncio
async def test_ack_reaction_task_retained_under_gc() -> None:
    """The ack-reaction task is retained and runs to completion.

    This pins the retention contract (scheduled → in the set, done →
    discarded): the fake coroutine never suspends on an unrooted future, so
    actual mid-flight GC cannot be reproduced deterministically here — the
    same limitation the #4928 precedent test has.

    A bare ``asyncio.create_task`` holds only a weak loop reference, so the
    ✅ acknowledgment could be garbage-collected mid-flight. The instance-level
    retention set keeps the task strongly referenced until completion (same
    pattern as #4928 / #4931).
    """
    bus = MessageBus()
    channel = DiscordChannel(bus=bus, config={"bot_token": "token"})

    reacted = asyncio.Event()

    async def _add_reaction(_emoji: str) -> None:
        reacted.set()

    message = SimpleNamespace(id=111, add_reaction=_add_reaction)

    task = channel._schedule_ack_reaction(message)
    weak_task = weakref.ref(task)
    del task
    gc.collect()

    retained = weak_task()
    assert retained is not None, "ack reaction task was garbage-collected mid-flight"
    assert retained in channel._ack_reaction_tasks

    await asyncio.wait_for(retained, timeout=1.0)
    assert reacted.is_set()
    # Completed tasks are discarded so the retention set cannot grow unboundedly.
    assert retained not in channel._ack_reaction_tasks


@pytest.mark.asyncio
async def test_ack_reaction_retention_is_isolated_per_channel() -> None:
    """One channel's shutdown must not cancel another instance's in-flight reactions.

    The retention set is instance-level (matching ``_typing_tasks``): a
    module-level set would let ``stop()`` on one channel drain every other
    channel's pending ack tasks.
    """
    first = DiscordChannel(bus=MessageBus(), config={"bot_token": "token"})
    second = DiscordChannel(bus=MessageBus(), config={"bot_token": "token"})

    release = asyncio.Event()

    async def _hang(_emoji: str) -> None:
        await release.wait()

    task = second._schedule_ack_reaction(SimpleNamespace(id=666, add_reaction=_hang))
    await asyncio.sleep(0)  # let the task start and suspend
    assert task in second._ack_reaction_tasks
    assert task not in first._ack_reaction_tasks

    # Full shutdown of the first channel must leave the second instance's
    # in-flight reaction alone (the review asked for independent shutdown).
    await first.stop()

    assert not task.done()
    assert task in second._ack_reaction_tasks

    release.set()
    await asyncio.wait_for(task, timeout=1.0)


@pytest.mark.asyncio
async def test_ack_reaction_task_survives_reaction_failure() -> None:
    """A failing add_reaction completes quietly and is discarded from the set."""

    bus = MessageBus()
    channel = DiscordChannel(bus=bus, config={"bot_token": "token"})

    async def _boom(_emoji: str) -> None:
        raise RuntimeError("discord api down")

    message = SimpleNamespace(id=222, add_reaction=_boom)

    task = channel._schedule_ack_reaction(message)
    await asyncio.wait_for(task, timeout=1.0)
    assert task not in channel._ack_reaction_tasks


@pytest.mark.asyncio
async def test_stop_drains_in_flight_ack_reaction_tasks() -> None:
    """stop()'s cleanup path cancels in-flight ack reactions on the owning loop.

    Without the drain, a task interrupted mid-HTTP-call would sit in the
    module retention set forever, pinning the channel and Message graph.
    """
    release = asyncio.Event()

    async def _hang(_emoji: str) -> None:
        await release.wait()

    channel = DiscordChannel(bus=MessageBus(), config={"bot_token": "token"})
    message = SimpleNamespace(id=333, add_reaction=_hang)

    task = channel._schedule_ack_reaction(message)
    assert task in channel._ack_reaction_tasks
    # Yield once so the task actually starts and suspends inside _hang —
    # cancelling a never-started task would not exercise the mid-flight path.
    await asyncio.sleep(0)
    assert not task.done()

    await channel._cancel_ephemeral_tasks()

    assert task.cancelled()
    assert task not in channel._ack_reaction_tasks


@pytest.mark.asyncio
async def test_ack_reaction_task_failure_is_logged_and_discarded(caplog) -> None:
    """An exception escaping _add_reaction is logged at error and discarded."""
    bus = MessageBus()
    channel = DiscordChannel(bus=bus, config={"bot_token": "token"})

    async def _explode(_self, _message) -> None:
        raise RuntimeError("unexpected boom")

    with patch.object(DiscordChannel, "_add_reaction", _explode), caplog.at_level("ERROR", logger="app.channels.discord"):
        task = channel._schedule_ack_reaction(SimpleNamespace(id=444))
        with pytest.raises(RuntimeError, match="unexpected boom"):
            await asyncio.wait_for(task, timeout=1.0)

    assert task not in channel._ack_reaction_tasks
    assert any("ack reaction task failed" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_stop_wiring_drains_ack_tasks_across_loops() -> None:
    """The real stop() path (cross-loop branch) drains in-flight ack reactions.

    Guards the wiring itself: reverting stop() to typing-only cleanup must
    fail here, not just at the helper level.
    """
    bg_loop, bg_thread = _start_bg_loop()
    try:
        channel = DiscordChannel(bus=MessageBus(), config={"bot_token": "token"})
        channel._discord_loop = bg_loop

        release = asyncio.Event()

        async def _hang(_emoji: str) -> None:
            await release.wait()

        async def _schedule_on_bg_loop() -> asyncio.Task:
            task = channel._schedule_ack_reaction(SimpleNamespace(id=555, add_reaction=_hang))
            await asyncio.sleep(0.05)  # let the task start and suspend on the event
            return task

        schedule_future = asyncio.run_coroutine_threadsafe(_schedule_on_bg_loop(), bg_loop)
        task = await asyncio.wrap_future(schedule_future)
        assert task in channel._ack_reaction_tasks

        await channel.stop()

        assert task.cancelled()
        assert not channel._ack_reaction_tasks
    finally:
        _stop_bg_loop(bg_loop, bg_thread)
