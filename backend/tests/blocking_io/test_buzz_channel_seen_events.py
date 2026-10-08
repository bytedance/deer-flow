"""Regression coverage for Buzz replay persistence at the channel boundary, and
for the ``_start_channel`` wiring that gives the guard its store path."""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path

import pytest

from app.channels import buzz_nostr, buzz_seen_events
from app.channels.buzz import BuzzChannel
from app.channels.buzz_seen_events import BuzzSeenEventStore
from app.channels.message_bus import MessageBus
from app.channels.service import ChannelService

pytestmark = pytest.mark.asyncio

_BOT_PUBLIC = "f9308a019258c31049344f85f89d5229b531c845836f99b08601f113bce036f9"
_OWNER_PUBLIC = "11" * 32
_CHANNEL_ID = "136852ee-63e1-49c2-8927-413b5ee8e5f7"


def _event() -> dict:
    tags = [["h", _CHANNEL_ID], ["p", _BOT_PUBLIC]]
    created_at = 1_700_000_100
    content = "@DeerFlow hello"
    return {
        "id": buzz_nostr.event_id(_OWNER_PUBLIC, created_at, 9, tags, content),
        "pubkey": _OWNER_PUBLIC,
        "created_at": created_at,
        "kind": 9,
        "tags": tags,
        "content": content,
        # Signature verification is patched below. Keeping a correctly shaped
        # event makes this test independent of the optional ``buzz`` extra, so
        # the default blocking-I/O CI job cannot silently skip the regression.
        "sig": "00" * 64,
    }


def _channel(path: Path, *, seen_events: BuzzSeenEventStore | None = None) -> tuple[BuzzChannel, list]:
    channel = BuzzChannel(
        bus=MessageBus(),
        config={
            "relay_url": "wss://buzz.example.com",
            "private_key": "unused-by-this-test",
            "allowed_users": [_OWNER_PUBLIC],
            "seen_event_store": seen_events or BuzzSeenEventStore(path),
        },
    )
    channel._keys = buzz_nostr.NostrKeys(secret=b"", pubkey_hex=_BOT_PUBLIC)
    published = []

    async def publish(message) -> None:
        published.append(message)

    channel._publish = publish
    return channel, published


async def test_channel_stop_persists_replay_guard_without_blocking(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A clean stop suppresses the same relay event after channel restart."""
    monkeypatch.setattr(buzz_nostr, "verify_event", lambda _event: True)
    path = tmp_path / "buzz-seen-events.json"
    event_frame = json.dumps(["EVENT", "buzz-chat", _event()])

    first, first_messages = _channel(path)
    await first.handle_relay_frame(event_frame)
    assert len(first_messages) == 1

    first._running = True
    first.bus.subscribe_outbound(first._on_outbound)
    await first.stop()

    restarted, restarted_messages = _channel(path)
    await restarted.handle_relay_frame(event_frame)

    assert restarted_messages == []


async def test_channel_stop_retries_seen_event_flush_after_cancellation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A Gateway timeout must leave seen-event cleanup retryable."""
    path = tmp_path / "buzz-seen-events.json"
    seen_events = BuzzSeenEventStore(path)
    channel, _ = _channel(path, seen_events=seen_events)
    write_started = threading.Event()
    release_write = threading.Event()
    retry_write_started = threading.Event()
    write_snapshot = seen_events._write_snapshot
    write_count = 0

    def fail_cancelled_write(payload: dict[str, list[str]]) -> bool:
        nonlocal write_count
        write_count += 1
        if write_count == 1:
            write_started.set()
            assert release_write.wait(timeout=2)
            return False
        retry_write_started.set()
        return write_snapshot(payload)

    seen_events._write_snapshot = fail_cancelled_write
    monkeypatch.setattr(buzz_seen_events, "FLUSH_DELAY_SECONDS", 60)
    await seen_events.arecord(_CHANNEL_ID, "event-1")
    channel._running = True
    channel.bus.subscribe_outbound(channel._on_outbound)

    first_stop = asyncio.create_task(channel.stop())
    assert await asyncio.to_thread(write_started.wait, 2)
    first_stop.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first_stop

    retry_stop = asyncio.create_task(channel.stop())
    assert not await asyncio.to_thread(retry_write_started.wait, 0.05)
    release_write.set()
    await retry_stop

    restarted = BuzzSeenEventStore(path)
    assert await restarted.aseen(_CHANNEL_ID, "event-1")


async def test_abandoned_relay_records_are_drained_by_retried_stop_or_restart(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Late relay records stay unscheduled but remain reachable to cleanup."""
    path = tmp_path / "buzz-seen-events.json"
    seen_events = BuzzSeenEventStore(path)
    channel, _ = _channel(path, seen_events=seen_events)
    relay_started = asyncio.Event()
    release_abandoned_relay = asyncio.Event()

    async def cancellation_resistant_relay() -> None:
        relay_started.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            await release_abandoned_relay.wait()
            await seen_events.arecord(_CHANNEL_ID, "late-event")

    monkeypatch.setattr("app.channels.buzz.STOP_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(buzz_seen_events, "FLUSH_DELAY_SECONDS", 0.01)
    channel._task = asyncio.create_task(cancellation_resistant_relay())
    channel._running = True
    channel.bus.subscribe_outbound(channel._on_outbound)
    await relay_started.wait()

    abandoned_relay = channel._task
    assert abandoned_relay is not None
    await channel.stop()
    release_abandoned_relay.set()
    await abandoned_relay
    assert await seen_events.aseen(_CHANNEL_ID, "late-event")

    assert seen_events._flush_handle is None
    assert seen_events._flush_task is None
    stopped_view = BuzzSeenEventStore(path)
    assert not await stopped_view.aseen(_CHANNEL_ID, "late-event")

    await channel.stop()
    retried_stop_view = BuzzSeenEventStore(path)
    assert await retried_stop_view.aseen(_CHANNEL_ID, "late-event")

    await seen_events.arecord(_CHANNEL_ID, "restart-event")
    assert seen_events._flush_handle is None
    assert seen_events._flush_task is None
    still_stopped_view = BuzzSeenEventStore(path)
    assert not await still_stopped_view.aseen(_CHANNEL_ID, "restart-event")

    flush_completed = asyncio.Event()
    original_flush_once = seen_events._flush_once

    async def tracked_flush_once() -> bool:
        saved = await original_flush_once()
        flush_completed.set()
        return saved

    monkeypatch.setattr(seen_events, "_flush_once", tracked_flush_once)
    monkeypatch.setattr(buzz_nostr, "parse_private_key", lambda _value: buzz_nostr.NostrKeys(secret=b"", pubkey_hex=_BOT_PUBLIC))
    channel._spawn_connection = lambda: None
    await channel.start()
    try:
        # Wait for the automatically resumed write, not a fixed disk/executor
        # latency. Calling aflush() here would hide a broken resume() path.
        await asyncio.wait_for(flush_completed.wait(), timeout=5)
        restarted_view = BuzzSeenEventStore(path)
        assert await restarted_view.aseen(_CHANNEL_ID, "restart-event")
    finally:
        await channel.stop()


async def test_start_channel_resolves_seen_store_path_off_the_loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Every channel start wires the Buzz replay guard its default store path, and
    # ``Paths.base_dir`` is a realpath call — so this resolution has to leave the
    # loop. It is reachable per request: ``POST /api/channels/{name}/restart``
    # restarts a running channel through ``restart_channel`` on the Gateway loop.
    #
    # The offline twin of this test (``test_service_wiring_injects_persistent_store_path``)
    # replaces ``get_paths`` with a stub whose ``base_dir`` is a plain string, so
    # it cannot see the syscall at all; here the real ``Paths`` object stays in
    # place and is isolated through ``DEER_FLOW_HOME`` instead.
    captured: dict[str, object] = {}

    class StubChannel:
        def __init__(self, bus, config):
            captured.update(config)
            self.is_running = True

        async def start(self):
            pass

    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)
    monkeypatch.setattr("deerflow.reflection.resolve_class", lambda _path, base_class=None: StubChannel)

    # Construction is IO-free by contract: ``start_channel_service`` builds the
    # service in a worker thread because ``ChannelStore`` resolves its JSON file
    # path there. The test mirrors that boundary so only ``_start_channel``'s own
    # resolution is exercised on the loop.
    service = await asyncio.to_thread(ChannelService, channels_config={})
    started = await service._start_channel("buzz", {"relay_url": "wss://buzz.example.com", "private_key": "unused-by-this-test"})

    # ``_start_channel`` keeps a blanket ``except Exception`` around the whole
    # wiring, so a regression onto the loop arrives here as a failed start plus a
    # logged ``BlockingError: Blocking call to os.path.abspath`` (see the captured
    # log of the red run) rather than as a raised gate error.
    assert started is True
    assert captured["seen_event_store_path"] == str(tmp_path / "channels" / "buzz_seen_events.json")
