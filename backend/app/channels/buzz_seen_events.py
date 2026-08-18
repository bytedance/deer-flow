"""Persistent record of Buzz chat events that were fully processed.

Why this exists
---------------
The Buzz connector's resubscribe filter deliberately replays rather than skips:
``since`` is the created_at of the last processed event and NIP-01 ``since`` is
inclusive, so every reconnect redelivers at least that event (see
``BuzzChannel._chat_filter``). The manager's inbound dedupe absorbs those
redeliveries — but its default store is in-process with a 10-minute TTL, so a
reconnect more than 10 minutes after the last message (or any gateway restart)
re-runs the agent on an already-answered message.

This store closes that gap at the connector: the ids of fully processed events
are persisted per channel, and a redelivered id is dropped before it reaches the
bus. Dedupe is by exact event id only — never by timestamp — so a genuinely new
event (which always has a fresh id, whatever its author-chosen created_at) can
never be skipped, preserving the connector's fail-toward-replay invariant.

Failure policy is fail-open in both directions: an unreadable file loads as
empty (costing at most one replayed answer, the pre-existing behavior) and a
failed write is logged and retried on the next record (costing replay, never a
skip). The id lists are bounded per channel and the channel map is bounded like
the connector's other remote-fed maps.
"""

from __future__ import annotations

import json
import logging
import tempfile
from collections import OrderedDict, deque
from pathlib import Path

logger = logging.getLogger(__name__)

# Ids retained per channel. Reconnect replay is normally the single watermark
# event; the deep case is a channel whose cursor was evicted, which replays the
# relay's default backlog window. Both are far below this bound.
MAX_IDS_PER_CHANNEL = 512
# Channel-map cap, mirroring the connector's other remote-fed maps
# (channel ids arrive in remote ``h`` tags).
MAX_CHANNELS = 512


class BuzzSeenEventStore:
    """Bounded, JSON-persisted map of channel id -> recently processed event ids."""

    def __init__(self, path: str | Path | None = None) -> None:
        # ``path=None`` means memory-only: no file is read or written, which is
        # exactly the pre-existing (non-durable) behavior. The channel service
        # wires the persistent path for real deployments; constructing a
        # channel directly (tests, tooling) must not create directories or
        # files as a side effect.
        self._path = Path(path) if path is not None else None
        self._ids: OrderedDict[str, deque[str]] = OrderedDict()
        self._sets: dict[str, set[str]] = {}
        self._loaded = False

    # -- persistence ---------------------------------------------------------

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if self._path is None:
            return
        try:
            if not self._path.exists():
                return
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("[buzz] unreadable seen-event store, starting fresh (costs at most one replayed reply)", exc_info=True)
            return
        if not isinstance(raw, dict):
            return
        for channel_id, ids in raw.items():
            if not isinstance(ids, list):
                continue
            clean = deque((str(i) for i in ids if i), maxlen=MAX_IDS_PER_CHANNEL)
            self._ids[str(channel_id)] = clean
            self._sets[str(channel_id)] = set(clean)
        self._enforce_channel_cap()

    def _save(self) -> None:
        if self._path is None:
            return
        try:
            path = self._path
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {channel: list(ids) for channel, ids in self._ids.items()}
            # Atomic same-directory replace, matching ChannelStore._save: a
            # crash mid-write must never truncate the store (a truncated store
            # would fail open into replay on the next start, which is
            # recoverable — but there is no reason to accept even that).
            with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, suffix=".tmp", delete=False, encoding="utf-8") as fh:
                json.dump(payload, fh)
                tmp_name = fh.name
            Path(tmp_name).replace(path)
        except Exception:
            logger.warning("[buzz] failed to persist seen-event store (will retry on next processed event)", exc_info=True)

    def _enforce_channel_cap(self) -> None:
        while len(self._ids) > MAX_CHANNELS:
            evicted, _ = self._ids.popitem(last=False)
            self._sets.pop(evicted, None)

    # -- api ----------------------------------------------------------------

    def seen(self, channel_id: str, event_id: str) -> bool:
        """True if *event_id* was already fully processed in *channel_id*."""
        if not event_id:
            return False
        self._ensure_loaded()
        return event_id in self._sets.get(channel_id, ())

    def record(self, channel_id: str, event_id: str) -> None:
        """Record a fully processed event and persist the store."""
        if not channel_id or not event_id:
            return
        self._ensure_loaded()
        ids = self._ids.get(channel_id)
        if ids is None:
            ids = deque(maxlen=MAX_IDS_PER_CHANNEL)
            self._ids[channel_id] = ids
            self._sets[channel_id] = set()
        id_set = self._sets[channel_id]
        if event_id in id_set:
            return
        if len(ids) == ids.maxlen:
            id_set.discard(ids[0])
        ids.append(event_id)
        id_set.add(event_id)
        # Move the channel to the back so the channel-cap eviction is LRU-ish.
        self._ids.move_to_end(channel_id)
        self._enforce_channel_cap()
        self._save()
