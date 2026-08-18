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
    store1 = BuzzSeenEventStore(path)
    ch1, captured1 = _started_with_store(store1)
    _dispatch(ch1, ev)
    assert len(captured1) == 1
    store1.flush()  # what BuzzChannel.stop() does on a clean shutdown

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


def test_channel_cap_evicts_least_recently_recorded(tmp_path):
    from app.channels.buzz_seen_events import MAX_CHANNELS

    store = BuzzSeenEventStore(tmp_path / "seen.json")
    for i in range(MAX_CHANNELS):
        store.record(f"chan-{i}", f"id-{i}")
    # Touch the oldest channel so LRU ordering (move_to_end) protects it.
    store.record("chan-0", "id-0b")
    store.record("chan-new", "id-new")  # overflows the map by one
    assert store.seen("chan-0", "id-0")  # refreshed -> survived
    assert store.seen("chan-new", "id-new")
    assert not store.seen("chan-1", "id-1")  # now the least recently used -> evicted
    # The persisted form respects the cap too.
    persisted = json.loads((tmp_path / "seen.json").read_text())
    assert len(persisted) == MAX_CHANNELS
    assert "chan-1" not in persisted


def test_saves_are_coalesced_under_a_running_loop(tmp_path):
    """One timer (and at most one file write) per burst, not one write per record."""
    from app.channels import buzz_seen_events

    path = tmp_path / "seen.json"
    store = BuzzSeenEventStore(path)
    saves = []
    original_save = store._save

    def counting_save():
        saves.append(1)
        original_save()

    store._save = counting_save

    async def burst():
        for i in range(50):
            store.record(CHANNEL, f"id-{i}")
        assert saves == []  # nothing written yet: flush is pending on the loop
        assert store._flush_handle is not None
        await asyncio.sleep(buzz_seen_events.FLUSH_DELAY_SECONDS + 0.1)

    asyncio.run(burst())
    assert len(saves) == 1
    persisted = json.loads(path.read_text())
    assert len(persisted[CHANNEL]) == 50


def test_flush_persists_pending_records_and_is_idempotent(tmp_path):
    path = tmp_path / "seen.json"
    store = BuzzSeenEventStore(path)

    async def record_only():
        store.record(CHANNEL, "e1")
        assert not path.exists()  # still inside the coalescing window

    asyncio.run(record_only())
    store.flush()
    assert BuzzSeenEventStore(path).seen(CHANNEL, "e1")
    mtime = path.stat().st_mtime_ns
    store.flush()  # nothing dirty -> no rewrite
    assert path.stat().st_mtime_ns == mtime


def test_failed_save_leaves_no_tmp_files(tmp_path, monkeypatch):
    """A persistent write failure must not accumulate *.tmp files (ChannelStore parity)."""
    path = tmp_path / "seen.json"
    store = BuzzSeenEventStore(path)

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("app.channels.buzz_seen_events.json.dump", boom)
    for i in range(3):
        store.record(CHANNEL, f"id-{i}")  # sync context -> each record attempts a save
    assert not path.exists()
    assert [p.name for p in tmp_path.iterdir()] == []  # no *.tmp litter
    monkeypatch.undo()
    store.record(CHANNEL, "id-3")  # recovery: next flush persists everything
    assert json.loads(path.read_text())[CHANNEL] == ["id-0", "id-1", "id-2", "id-3"]


def test_channel_stop_flushes_pending_records(tmp_path):
    """A clean stop must not lose records still inside the coalescing window."""
    path = tmp_path / "seen.json"
    store = BuzzSeenEventStore(path)
    ch, captured = _started_with_store(store)
    ev = _event()

    async def dispatch_then_stop():
        await ch.handle_relay_frame(json.dumps(["EVENT", "sub1", ev]))
        assert not path.exists()  # flush still pending
        ch._running = True  # stop() is a no-op on a never-started channel
        ch.bus.subscribe_outbound(ch._on_outbound)
        await ch.stop()

    asyncio.run(dispatch_then_stop())
    assert len(captured) == 1
    assert BuzzSeenEventStore(path).seen(CHANNEL, str(ev["id"]))


def test_service_wiring_injects_persistent_store_path(tmp_path, monkeypatch):
    """The _start_channel wiring is what makes real deployments durable — a
    silent regression there would revert to memory-only with all unit tests green."""
    from app.channels.service import ChannelService

    captured_config = {}

    class StubChannel:
        def __init__(self, bus, config):
            captured_config.update(config)
            self.is_running = True

        async def start(self):
            pass

    class StubPaths:
        base_dir = str(tmp_path)

    monkeypatch.setattr("deerflow.config.paths.get_paths", lambda: StubPaths())
    monkeypatch.setattr("deerflow.reflection.resolve_class", lambda path, base_class=None: StubChannel)

    service = ChannelService(channels_config={})
    started = asyncio.run(service._start_channel("buzz", {"relay_url": "wss://x", "private_key": SK3_HEX}))
    assert started
    expected = str(tmp_path / "channels" / "buzz_seen_events.json")
    assert captured_config["seen_event_store_path"] == expected
    # An explicitly configured path must win over the default wiring.
    captured_config.clear()
    asyncio.run(service._start_channel("buzz", {"relay_url": "wss://x", "private_key": SK3_HEX, "seen_event_store_path": "/custom/seen.json"}))
    assert captured_config["seen_event_store_path"] == "/custom/seen.json"


def test_stale_timer_from_closed_loop_does_not_block_rescheduling(tmp_path):
    """A pending flush timer pinned to a since-closed loop must not stop the
    store from scheduling on a new loop (it would silently stop persisting)."""
    from app.channels import buzz_seen_events

    path = tmp_path / "seen.json"
    store = BuzzSeenEventStore(path)

    async def record_and_abandon():
        store.record(CHANNEL, "e1")  # schedules a timer on THIS loop...

    asyncio.run(record_and_abandon())  # ...which closes before the timer fires
    assert store._flush_handle is not None  # the stale handle survives the loop

    async def record_on_new_loop():
        store.record(CHANNEL, "e2")
        assert store._flush_loop is asyncio.get_running_loop()
        await asyncio.sleep(buzz_seen_events.FLUSH_DELAY_SECONDS + 0.1)

    asyncio.run(record_on_new_loop())
    persisted = json.loads(path.read_text())
    assert persisted[CHANNEL] == ["e1", "e2"]  # both records made it to disk
