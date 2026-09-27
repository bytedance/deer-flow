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

Writes are coalesced: ``arecord()`` marks the store dirty and schedules one
flush per ``FLUSH_DELAY_SECONDS`` on the running event loop, so a reconnect
backlog burst pays one O(store) file write instead of one per event. The timer
captures an immutable payload on the event loop and writes it through
``asyncio.to_thread``; a generation counter keeps records that arrive during
that write dirty for the next flush. ``aseen()`` likewise offloads the initial
file load, and ``BuzzChannel.stop()`` awaits ``aflush()`` so clean shutdown is
durable before it returns. That final flush is bounded: it waits for an existing
write and attempts at most one newer snapshot, leaving any still-moving
generation dirty for fail-open replay rather than hanging shutdown. The
in-flight worker write is shielded and retained if Gateway cancellation
interrupts shutdown, so a retried stop awaits it instead of racing it with a
second snapshot; every final attempt also removes its coalescing timer before
returning. ``BuzzChannel`` quiesces automatic scheduling before stop and resumes
it after start, so a timed-out relay task that records after the stop boundary
leaves data dirty for fail-open replay without creating detached file work. The
synchronous ``seen()`` / ``record()`` / ``flush()`` methods remain for tests and
tooling that run outside an event loop.
"""

from __future__ import annotations

import asyncio
import json
import logging
import tempfile
import threading
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
    """Bounded, JSON-persisted map of channel id -> recently processed event ids.

    Gateway event-loop callers must use ``aseen()``, ``arecord()``, and
    ``aflush()`` so filesystem access stays on a worker thread.
    """

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
        self._load_lock = threading.Lock()
        self._dirty = False
        self._generation = 0
        self._quiesced = False
        self._flush_handle: asyncio.TimerHandle | None = None
        self._flush_task: asyncio.Task[bool] | None = None
        # The loop the pending handle was scheduled on. TimerHandle has no
        # public get_loop(), so it is tracked here to detect a stale handle.
        self._flush_loop: asyncio.AbstractEventLoop | None = None

    # -- persistence ---------------------------------------------------------

    def _ensure_loaded(self) -> None:
        with self._load_lock:
            if self._loaded:
                return
            try:
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
            finally:
                # Publish only after every loaded entry is visible. Async hot
                # paths may read this flag without taking ``_load_lock``.
                self._loaded = True

    def _snapshot(self) -> dict[str, list[str]]:
        return {channel: list(ids) for channel, ids in self._ids.items()}

    def _write_snapshot(self, payload: dict[str, list[str]]) -> bool:
        if self._path is None:
            return True
        tmp_name: str | None = None
        try:
            path = self._path
            path.parent.mkdir(parents=True, exist_ok=True)
            # Atomic same-directory replace, matching ChannelStore._save: a
            # crash mid-write must never truncate the store (a truncated store
            # would fail open into replay on the next start, which is
            # recoverable — but there is no reason to accept even that).
            with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, suffix=".tmp", delete=False, encoding="utf-8") as fh:
                tmp_name = fh.name
                json.dump(payload, fh)
            Path(tmp_name).replace(path)
            return True
        except Exception:
            # Mirror ChannelStore._save: never leave the temp file behind, or a
            # persistently failing write accumulates one *.tmp per attempt.
            if tmp_name is not None:
                Path(tmp_name).unlink(missing_ok=True)
            logger.warning("[buzz] failed to persist seen-event store (will retry on next flush)", exc_info=True)
            return False

    def _save(self) -> None:
        if self._write_snapshot(self._snapshot()):
            self._dirty = False

    async def _flush_once(self) -> bool:
        if not self._dirty:
            return True
        generation = self._generation
        saved = await asyncio.to_thread(self._write_snapshot, self._snapshot())
        if saved and generation == self._generation:
            self._dirty = False
        return saved

    def _request_flush(self) -> None:
        """Coalesce persistence: at most one write per FLUSH_DELAY_SECONDS.

        With no running event loop (tests, tooling) the write happens
        synchronously, preserving the immediate-durability semantics direct
        callers had before coalescing existed.
        """
        self._dirty = True
        if self._quiesced:
            return
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

    def quiesce(self) -> None:
        """Disable automatic persistence while retaining late records as dirty."""
        self._quiesced = True
        if self._flush_handle is not None:
            self._flush_handle.cancel()
            self._flush_handle = None

    def resume(self) -> None:
        """Resume automatic persistence and schedule any retained dirty state."""
        if not self._quiesced:
            return
        self._quiesced = False
        if self._dirty:
            self._request_flush()

    def _flush_task_on_current_loop(self) -> asyncio.Task[bool] | None:
        """Return the pending flush only when it belongs to the running loop."""
        pending = self._flush_task
        if pending is not None and pending.get_loop() is not asyncio.get_running_loop():
            self._flush_task = None
            return None
        return pending

    def _flush_scheduled(self) -> None:
        self._flush_handle = None
        if not self._dirty:
            return
        pending = self._flush_task_on_current_loop()
        if pending is not None and not pending.done():
            return
        self._flush_task = asyncio.create_task(self._flush_once())
        self._flush_task.add_done_callback(self._flush_finished)

    def _flush_finished(self, task: asyncio.Task[bool]) -> None:
        if self._flush_task is task:
            self._flush_task = None
        try:
            saved = task.result()
        except asyncio.CancelledError:
            return
        except Exception:
            logger.warning("[buzz] unexpected seen-event flush failure", exc_info=True)
            return
        # A successful snapshot may be stale when another event arrived while
        # the worker thread was writing it. Schedule that newer generation for
        # the next coalescing window. A failed write deliberately waits for the
        # next record or explicit flush, preserving the store's fail-open retry
        # policy instead of spinning on a broken filesystem every second.
        if saved and self._dirty:
            self._request_flush()

    def _final_flush_finished(self, task: asyncio.Task[bool]) -> None:
        """Retire a stop-owned write without scheduling work after stop."""
        if self._flush_task is task:
            self._flush_task = None
        try:
            task.result()
        except asyncio.CancelledError:
            return
        except Exception:
            logger.warning("[buzz] unexpected final seen-event flush failure", exc_info=True)

    async def aflush(self) -> None:
        """Make one bounded final persist without blocking the event loop."""
        if self._flush_handle is not None:
            self._flush_handle.cancel()
            self._flush_handle = None

        try:
            pending = self._flush_task_on_current_loop()
            if pending is not None and pending is not asyncio.current_task():
                if not pending.cancelled():
                    # This scheduled write now belongs to channel teardown.
                    # Its normal callback would arm another timer when the
                    # snapshot is stale, possibly after a cancelled aflush()
                    # has already run its timer cleanup.
                    pending.remove_done_callback(self._flush_finished)
                    pending.remove_done_callback(self._final_flush_finished)
                    pending.add_done_callback(self._final_flush_finished)
                    try:
                        # Cancelling channel stop must not cancel the worker
                        # write: the thread keeps running regardless, and a
                        # retried stop must await that same write rather than
                        # start a concurrent stale snapshot.
                        await asyncio.shield(pending)
                    except asyncio.CancelledError:
                        current = asyncio.current_task()
                        if current is not None and current.cancelling():
                            raise
                        logger.warning("[buzz] in-flight seen-event flush was cancelled during final persist; retrying")
                    except Exception:
                        logger.warning("[buzz] in-flight seen-event flush failed during final persist; retrying", exc_info=True)
                if self._flush_task is pending and pending.done():
                    self._flush_task = None

            # One final snapshot keeps shutdown bounded even if an abandoned
            # relay task is still recording. Track and shield it so a Gateway
            # timeout leaves one retryable write instead of an untracked worker
            # thread that can race the next stop attempt.
            if self._dirty:
                final = asyncio.create_task(self._flush_once())
                self._flush_task = final
                final.add_done_callback(self._final_flush_finished)
                try:
                    await asyncio.shield(final)
                except asyncio.CancelledError:
                    current = asyncio.current_task()
                    if current is not None and current.cancelling():
                        raise
                    logger.warning("[buzz] final seen-event flush was cancelled; leaving store dirty")
                except Exception:
                    logger.warning("[buzz] final seen-event flush failed; leaving store dirty", exc_info=True)
                if self._flush_task is final and final.done():
                    self._flush_task = None
        finally:
            # ``aflush`` is the channel-stop boundary: never leave a timer
            # owned by a stopped channel. A record that raced the final
            # snapshot remains dirty so a retried stop can persist it.
            if self._flush_handle is not None:
                self._flush_handle.cancel()
                self._flush_handle = None

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

    async def aseen(self, channel_id: str, event_id: str) -> bool:
        """Async counterpart of :meth:`seen` for Gateway event-loop callers."""
        if not event_id:
            return False
        if not self._loaded:
            await asyncio.to_thread(self._ensure_loaded)
        return event_id in self._sets.get(channel_id, ())

    def record(self, channel_id: str, event_id: str) -> None:
        """Record a fully processed event and schedule a coalesced persist."""
        if not channel_id or not event_id:
            return
        self._ensure_loaded()
        self._record_loaded(channel_id, event_id)

    async def arecord(self, channel_id: str, event_id: str) -> None:
        """Record an event without performing file IO on the event loop."""
        if not channel_id or not event_id:
            return
        if not self._loaded:
            await asyncio.to_thread(self._ensure_loaded)
        self._record_loaded(channel_id, event_id)

    def _record_loaded(self, channel_id: str, event_id: str) -> None:
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
        self._generation += 1
        self._request_flush()
