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
failed write is logged and retried on the next flush (costing replay, never a
skip). The id lists are bounded per channel and the channel map is bounded like
the connector's other remote-fed maps. That per-channel bound also bounds the
restart protection itself: after a gateway restart ``_seen_created_at`` is
empty, the resubscribe REQ carries no ``since``, and the relay's default
backlog replays — only the newest ``MAX_IDS_PER_CHANNEL`` processed ids per
channel are dropped, so a relay backlog deeper than that would re-answer the
tail. If a relay ever serves a deeper default backlog, raise
``MAX_IDS_PER_CHANNEL`` here.

Writes are coalesced: ``record()`` marks the store dirty and schedules one
flush per ``FLUSH_DELAY_SECONDS`` on the running event loop, so a reconnect
backlog burst pays one O(store) file write instead of one per event. With no
running loop (tests, tooling) ``record()`` flushes synchronously, and
``BuzzChannel.stop()`` flushes pending state on shutdown. This class is not
thread-safe by design: everything runs on the single channel event loop
(mutation in ``_handle_chat_event``, the coalesced flush via ``call_later`` on
that same loop). Anyone adding an off-loop user — e.g. a threaded flusher —
must add a lock around ``_ids``/``_sets`` first, as ChannelStore does.
"""

from __future__ import annotations

import asyncio
import json
import logging
import tempfile
from collections import OrderedDict, deque
from pathlib import Path

logger = logging.getLogger(__name__)

# Coalescing window for persisting the store. Losing this window's records in a
# crash only costs replay (fail-open), never a skip.
FLUSH_DELAY_SECONDS = 1.0

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
        self._dirty = False
        self._flush_handle: asyncio.TimerHandle | None = None
        # The loop the pending handle was scheduled on. TimerHandle has no
        # public get_loop(), so it is tracked here to detect a stale handle.
        self._flush_loop: asyncio.AbstractEventLoop | None = None

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
        tmp_name: str | None = None
        try:
            path = self._path
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {channel: list(ids) for channel, ids in self._ids.items()}
            # Atomic same-directory replace, matching ChannelStore._save: a
            # crash mid-write must never truncate the store (a truncated store
            # would fail open into replay on the next start, which is
            # recoverable — but there is no reason to accept even that).
            with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, suffix=".tmp", delete=False, encoding="utf-8") as fh:
                tmp_name = fh.name
                json.dump(payload, fh)
            Path(tmp_name).replace(path)
            self._dirty = False
        except Exception:
            # Mirror ChannelStore._save: never leave the temp file behind, or a
            # persistently failing write accumulates one *.tmp per attempt.
            if tmp_name is not None:
                Path(tmp_name).unlink(missing_ok=True)
            logger.warning("[buzz] failed to persist seen-event store (will retry on next flush)", exc_info=True)

    def _request_flush(self) -> None:
        """Coalesce persistence: at most one write per FLUSH_DELAY_SECONDS.

        With no running event loop (tests, tooling) the write happens
        synchronously, preserving the immediate-durability semantics direct
        callers had before coalescing existed.
        """
        self._dirty = True
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self.flush()
            return
        # A pending handle pinned to a since-closed loop would otherwise block
        # scheduling forever, silently stopping persistence until an explicit
        # flush() (only reachable when callers span loops, e.g. tests).
        if self._flush_handle is None or self._flush_loop is not loop:
            if self._flush_handle is not None:
                self._flush_handle.cancel()
            self._flush_loop = loop
            self._flush_handle = loop.call_later(FLUSH_DELAY_SECONDS, self._flush_scheduled)

    def _flush_scheduled(self) -> None:
        self._flush_handle = None
        if self._dirty:
            self._save()

    def flush(self) -> None:
        """Persist pending records now (no-op when nothing is dirty).

        Called on channel stop so a clean shutdown never loses records to the
        coalescing window; a crash inside the window only costs replay.
        """
        if self._flush_handle is not None:
            self._flush_handle.cancel()
            self._flush_handle = None
        if self._dirty:
            self._save()

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
        """Record a fully processed event and schedule a coalesced persist."""
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
        self._request_flush()
