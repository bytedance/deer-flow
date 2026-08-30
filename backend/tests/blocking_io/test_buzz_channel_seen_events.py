"""Regression coverage for Buzz replay persistence at the channel boundary."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.channels import buzz_nostr
from app.channels.buzz import BuzzChannel
from app.channels.buzz_seen_events import BuzzSeenEventStore
from app.channels.message_bus import MessageBus

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


def _channel(path: Path) -> tuple[BuzzChannel, list]:
    channel = BuzzChannel(
        bus=MessageBus(),
        config={
            "relay_url": "wss://buzz.example.com",
            "private_key": "unused-by-this-test",
            "allowed_users": [_OWNER_PUBLIC],
            "seen_event_store": BuzzSeenEventStore(path),
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
