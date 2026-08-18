"""Tests for the Buzz connector's persistent replay guard (seen-event store)."""

import asyncio
import json

import pytest

pytest.importorskip("coincurve")

from app.channels import buzz_nostr
from app.channels.buzz import BuzzChannel
from app.channels.buzz_seen_events import MAX_IDS_PER_CHANNEL, BuzzSeenEventStore
from app.channels.message_bus import MessageBus

# Keypairs mirror tests/test_buzz_channel.py: inbound events are
# signature-verified, so fixture authors must be real keypairs.
SK3_HEX = "0000000000000000000000000000000000000000000000000000000000000003"
PK3_HEX = "f9308a019258c31049344f85f89d5229b531c845836f99b08601f113bce036f9"
SK_OWNER = "0000000000000000000000000000000000000000000000000000000000000005"
OWNER = buzz_nostr.parse_private_key(SK_OWNER).pubkey_hex
CHANNEL = "136852ee-63e1-49c2-8927-413b5ee8e5f7"


def _event(*, sk=SK_OWNER, kind=9, content="@DeerFlow hello", channel=CHANNEL, mentions=(PK3_HEX,), reply_to=None, created_at=1700000100):
    tags = [["h", channel]]
    if reply_to:
        tags.append(["e", reply_to])
    tags.extend(["p", m] for m in mentions)
    return buzz_nostr.sign_event(buzz_nostr.parse_private_key(sk), kind, tags, content, created_at)


# -- store ------------------------------------------------------------------


def test_memory_only_store_records_without_touching_disk(tmp_path):
    store = BuzzSeenEventStore(None)
    store.record(CHANNEL, "e1")
    assert store.seen(CHANNEL, "e1")
    assert not store.seen(CHANNEL, "e2")
    assert list(tmp_path.iterdir()) == []  # nothing written anywhere we can observe


def test_persistent_store_round_trips_across_instances(tmp_path):
    path = tmp_path / "seen.json"
    store = BuzzSeenEventStore(path)
    store.record(CHANNEL, "e1")
    store.record(CHANNEL, "e2")
    reloaded = BuzzSeenEventStore(path)
    assert reloaded.seen(CHANNEL, "e1") and reloaded.seen(CHANNEL, "e2")
    assert not reloaded.seen(CHANNEL, "e3")
    assert not reloaded.seen("other-channel", "e1")


def test_per_channel_id_cap_evicts_oldest(tmp_path):
    path = tmp_path / "seen.json"
    store = BuzzSeenEventStore(path)
    for i in range(MAX_IDS_PER_CHANNEL + 5):
        store.record(CHANNEL, f"id-{i}")
    assert not store.seen(CHANNEL, "id-0")
    assert store.seen(CHANNEL, f"id-{MAX_IDS_PER_CHANNEL + 4}")
    # The persisted form respects the cap too.
    persisted = json.loads(path.read_text())
    assert len(persisted[CHANNEL]) == MAX_IDS_PER_CHANNEL


def test_corrupt_store_file_fails_open_to_empty(tmp_path):
    path = tmp_path / "seen.json"
    path.write_text("{not json", encoding="utf-8")
    store = BuzzSeenEventStore(path)
    assert not store.seen(CHANNEL, "e1")
    store.record(CHANNEL, "e1")  # recovers by overwriting on next record
    assert BuzzSeenEventStore(path).seen(CHANNEL, "e1")


def test_empty_event_id_is_never_seen_or_recorded(tmp_path):
    store = BuzzSeenEventStore(tmp_path / "seen.json")
    store.record(CHANNEL, "")
    assert not store.seen(CHANNEL, "")


def test_unwritable_path_fails_open(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("")  # a file where the store expects a parent directory
    store = BuzzSeenEventStore(blocker / "seen.json")
    store.record(CHANNEL, "e1")  # write fails, logged, no raise
    assert store.seen(CHANNEL, "e1")  # in-memory state still works


# -- connector integration ---------------------------------------------------


def _started_with_store(store: BuzzSeenEventStore):
    ch = BuzzChannel(
        bus=MessageBus(),
        config={
            "relay_url": "wss://buzz.example.com",
            "private_key": SK3_HEX,
            "allowed_users": [OWNER],
            "seen_event_store": store,
        },
    )
    ch._keys = buzz_nostr.parse_private_key(SK3_HEX)
    captured = []

    async def publish(msg):
        captured.append(msg)

    ch._publish = publish
    return ch, captured


def _dispatch(ch, ev):
    asyncio.run(ch.handle_relay_frame(json.dumps(["EVENT", "sub1", ev])))


def test_redelivered_event_is_dropped_within_one_process(tmp_path):
    ch, captured = _started_with_store(BuzzSeenEventStore(tmp_path / "seen.json"))
    ev = _event()
    _dispatch(ch, ev)
    assert len(captured) == 1
    _dispatch(ch, ev)  # relay replay of the same event (inclusive `since`)
    assert len(captured) == 1


def test_redelivered_event_is_dropped_across_restart(tmp_path):
    """The bug: a relay reconnect after a gateway restart re-answered the last message."""
    path = tmp_path / "seen.json"
    ev = _event()
    ch1, captured1 = _started_with_store(BuzzSeenEventStore(path))
    _dispatch(ch1, ev)
    assert len(captured1) == 1

    # Simulated restart: a fresh channel instance, fresh store object, same file.
    ch2, captured2 = _started_with_store(BuzzSeenEventStore(path))
    _dispatch(ch2, ev)
    assert captured2 == []


def test_new_event_at_same_created_at_is_still_processed(tmp_path):
    """Dedupe is by id only: a same-second new event must never be skipped."""
    ch, captured = _started_with_store(BuzzSeenEventStore(tmp_path / "seen.json"))
    _dispatch(ch, _event(content="@DeerFlow first", created_at=1700000100))
    _dispatch(ch, _event(content="@DeerFlow second", created_at=1700000100))
    assert len(captured) == 2


def test_older_created_at_new_event_is_still_processed(tmp_path):
    """A clock-skewed author's new event (older timestamp) must never be skipped."""
    ch, captured = _started_with_store(BuzzSeenEventStore(tmp_path / "seen.json"))
    _dispatch(ch, _event(content="@DeerFlow newer", created_at=1700000200))
    _dispatch(ch, _event(content="@DeerFlow older-clock", created_at=1700000100))
    assert len(captured) == 2


def test_dropped_event_is_not_recorded_and_stays_replayable(tmp_path):
    """Only fully processed events are recorded — a gated drop must not poison the id."""
    store = BuzzSeenEventStore(tmp_path / "seen.json")
    ch, captured = _started_with_store(store)
    ev = _event(content="no mention here", mentions=())  # dropped by the mention gate
    _dispatch(ch, ev)
    assert captured == []
    assert not store.seen(CHANNEL, str(ev["id"]))


def test_replayed_connect_is_not_reprocessed(tmp_path):
    """A replayed /connect must not be re-answered with 'code invalid or expired'."""
    store = BuzzSeenEventStore(tmp_path / "seen.json")
    ch, captured = _started_with_store(store)
    replies = []

    async def fake_bind(code, author, channel_id):
        replies.append(code)

    ch._bind_connection = fake_bind
    ch._connection_repo = object()  # /connect is only consulted when connections are configured
    ev = _event(sk=SK_OWNER, content="/connect abc123", mentions=(PK3_HEX,))
    _dispatch(ch, ev)
    assert replies == ["abc123"]
    _dispatch(ch, ev)  # replay
    assert replies == ["abc123"]


def test_default_config_uses_memory_only_store():
    """Direct construction (no service wiring) must not persist anywhere."""
    ch = BuzzChannel(
        bus=MessageBus(),
        config={"relay_url": "wss://buzz.example.com", "private_key": SK3_HEX, "allowed_users": [OWNER]},
    )
    assert isinstance(ch._seen_events, BuzzSeenEventStore)
    assert ch._seen_events._path is None
