"""In-memory stream bridge backed by an in-process event log."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import AsyncIterator, Iterator
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from .base import DEFAULT_HEARTBEAT_INTERVAL_SECONDS, END_SENTINEL, HEARTBEAT_SENTINEL, StreamBridge, StreamEvent, StreamGap, StreamItem

logger = logging.getLogger(__name__)
_MEMORY_STREAM_ID_RE = re.compile(r"[0-9]+-([0-9]+)")
_SNAPSHOT_SCALAR_TYPES = frozenset((type(None), bool, int, float, str))


def _snapshot_payload(data: Any) -> Any:
    """Copy wire containers without recursing through their dict/list depth.

    Keep deepcopy's aliases, cycles and custom-type behavior. The canonical
    serializer emits plain dicts/lists; other objects retain deepcopy's own
    handling, including subclass hooks.
    """
    if type(data) not in (dict, list):
        return deepcopy(data)

    root = {} if type(data) is dict else []
    memo = {id(data): root}
    # A custom leaf's deepcopy may mutate its source container. Keep every
    # recorded source alive so an id in the memo cannot be reused.
    sources = [data]
    # Source, copy, children, parent copy, parent key. Attach a fresh child only
    # after visiting it, preserving deepcopy's value-before-key order.
    stack = [(data, root, _snapshot_children(data), None, None)]
    while stack:
        _source, target, children, parent, parent_key = stack[-1]
        for key, child in children:
            if type(child) in (dict, list):
                if id(child) in memo:
                    value = memo[id(child)]
                else:
                    value = {} if type(child) is dict else []
                    memo[id(child)] = value
                    sources.append(child)
                    stack.append((child, value, _snapshot_children(child), target, key))
                    break
            else:
                value = memo.get(id(child), child) if type(child) in _SNAPSHOT_SCALAR_TYPES else deepcopy(child, memo)
            _attach_snapshot(target, key, value, memo)
        else:
            stack.pop()
            memo[id(_source)] = target
            if parent is not None:
                _attach_snapshot(parent, parent_key, target, memo)
    return root


def _snapshot_children(source: dict | list) -> Iterator[tuple[Any, Any]]:
    return iter(source.items()) if type(source) is dict else enumerate(source)


def _attach_snapshot(target: dict | list, key: Any, value: Any, memo: dict[int, Any]) -> None:
    if type(target) is dict:
        target[memo.get(id(key), key) if type(key) in _SNAPSHOT_SCALAR_TYPES else deepcopy(key, memo)] = value
    else:
        target.append(value)


@dataclass
class _RunStream:
    events: list[StreamEvent] = field(default_factory=list)
    condition: asyncio.Condition = field(default_factory=asyncio.Condition)
    ended: bool = False
    start_offset: int = 0
    last_evicted_event_id: str | None = None
    retired: bool = False


class MemoryStreamBridge(StreamBridge):
    """Per-run in-memory event log implementation.

    Events are retained for a bounded time window per run so late subscribers
    and reconnecting clients can replay buffered events from ``Last-Event-ID``.
    """

    def __init__(self, *, queue_maxsize: int = 256, heartbeat_interval: float = DEFAULT_HEARTBEAT_INTERVAL_SECONDS) -> None:
        super().__init__(heartbeat_interval=heartbeat_interval)
        self._maxsize = max(1, queue_maxsize)
        self._streams: dict[str, _RunStream] = {}
        self._counters: dict[str, int] = {}

    # -- helpers ---------------------------------------------------------------

    def _get_or_create_stream(self, run_id: str) -> _RunStream:
        if run_id not in self._streams:
            self._streams[run_id] = _RunStream()
            self._counters[run_id] = 0
        return self._streams[run_id]

    def _next_id(self, run_id: str) -> str:
        self._counters[run_id] = self._counters.get(run_id, 0) + 1
        ts = int(time.time() * 1000)
        seq = self._counters[run_id] - 1
        return f"{ts}-{seq}"

    @staticmethod
    def _parse_event_seq(event_id: str) -> int | None:
        """Extract the per-run sequence number from a ``{ts}-{seq}`` event id.

        ``seq`` (assigned by :meth:`_next_id`) increases by one per published
        event, so it equals the event's absolute offset within the run. Returns
        ``None`` for ids that do not match the expected format.
        """
        match = _MEMORY_STREAM_ID_RE.fullmatch(event_id)
        if match is None:
            return None
        try:
            return int(match.group(1))
        except ValueError:
            # Numeric-looking reconnect ids can exceed Python's digit limit.
            return None

    @staticmethod
    def _make_gap(stream: _RunStream, requested_event_id: str | None) -> StreamGap:
        return StreamGap(
            requested_event_id=requested_event_id,
            earliest_available_event_id=stream.events[0].id if stream.events else None,
            latest_available_event_id=stream.events[-1].id if stream.events else None,
        )

    def _resolve_start_offset(self, stream: _RunStream, last_event_id: str | None) -> int | StreamGap:
        # Cleanup can win the Condition after a new reader captures this generation.
        if stream.retired:
            return StreamGap(last_event_id, None, None)
        if last_event_id is None:
            return stream.start_offset
        if last_event_id == stream.last_evicted_event_id:
            return stream.start_offset

        # Event ids embed a per-run, monotonically increasing ``seq`` that equals
        # the event's absolute offset, so locate the event by arithmetic in O(1)
        # rather than scanning the retained buffer. Retained ids are verified at
        # the computed index. The exact last evicted id is a known predecessor
        # whose successors are all retained. Other ids below the watermark cannot
        # be verified and take the conservative gap path. Unknown ids at or above the
        # watermark keep the legacy replay-from-earliest behavior.
        seq = self._parse_event_seq(last_event_id)
        if seq is not None:
            if seq < stream.start_offset:
                return self._make_gap(stream, last_event_id)
            local_index = seq - stream.start_offset
            if 0 <= local_index < len(stream.events) and stream.events[local_index].id == last_event_id:
                return stream.start_offset + local_index + 1

        if stream.events:
            logger.warning(
                "last_event_id=%s not found in retained buffer; replaying from earliest retained event",
                last_event_id,
            )
        return stream.start_offset

    async def stream_exists(self, run_id: str) -> bool:
        """Return whether the in-process event log still has data for *run_id*."""
        return run_id in self._streams

    # -- StreamBridge API ------------------------------------------------------

    async def publish(self, run_id: str, event: str, data: Any) -> None:
        data = _snapshot_payload(data)
        stream = self._get_or_create_stream(run_id)
        entry = StreamEvent(id=self._next_id(run_id), event=event, data=data)
        async with stream.condition:
            stream.events.append(entry)
            if len(stream.events) > self._maxsize:
                overflow = len(stream.events) - self._maxsize
                stream.last_evicted_event_id = stream.events[overflow - 1].id
                del stream.events[:overflow]
                stream.start_offset += overflow
            stream.condition.notify_all()

    async def publish_end(self, run_id: str) -> None:
        stream = self._get_or_create_stream(run_id)
        async with stream.condition:
            stream.ended = True
            stream.condition.notify_all()

    async def subscribe(
        self,
        run_id: str,
        *,
        last_event_id: str | None = None,
        heartbeat_interval: float | None = None,
    ) -> AsyncIterator[StreamItem]:
        heartbeat_interval = self._resolve_heartbeat_interval(heartbeat_interval)
        stream = self._get_or_create_stream(run_id)
        async with stream.condition:
            start = self._resolve_start_offset(stream, last_event_id)
            if isinstance(start, StreamGap):
                gap = start
                next_offset = stream.start_offset
            else:
                gap = None
                next_offset = start

        if gap is not None:
            yield gap
            return

        cursor_event_id = last_event_id

        while True:
            async with stream.condition:
                if stream.retired:
                    entry: StreamItem = END_SENTINEL if stream.ended and next_offset >= stream.start_offset else StreamGap(cursor_event_id, None, None)
                    should_stop = True
                elif next_offset < stream.start_offset:
                    logger.warning(
                        "subscriber for run %s fell behind retained buffer at offset %s",
                        run_id,
                        next_offset,
                    )
                    entry = self._make_gap(stream, cursor_event_id)
                    should_stop = True
                else:
                    should_stop = False

                    local_index = next_offset - stream.start_offset
                    if 0 <= local_index < len(stream.events):
                        entry = stream.events[local_index]
                        next_offset += 1
                        cursor_event_id = entry.id
                    elif stream.ended:
                        entry = END_SENTINEL
                    else:
                        try:
                            await asyncio.wait_for(stream.condition.wait(), timeout=heartbeat_interval)
                        except TimeoutError:
                            entry = HEARTBEAT_SENTINEL
                        else:
                            continue

            if entry is END_SENTINEL:
                yield END_SENTINEL
                return
            # Consumers identify sentinels with `is`; never deep-copy them.
            if isinstance(entry, StreamEvent) and entry is not HEARTBEAT_SENTINEL:
                data = _snapshot_payload(entry.data)
                yield deepcopy(entry, {id(entry.data): data})
            else:
                yield entry
            if should_stop:
                return

    async def cleanup(self, run_id: str, *, delay: float = 0) -> None:
        if delay > 0:
            await asyncio.sleep(delay)
        stream = self._streams.get(run_id)
        if stream is None:
            return
        async with stream.condition:
            # Established generators retain this object after registry removal.
            # Retire that generation, release its payloads, and wake readers so
            # they can reload durable state rather than waiting on an orphan.
            stream.retired = True
            stream.start_offset += len(stream.events)
            stream.events.clear()
            if self._streams.get(run_id) is stream:
                self._streams.pop(run_id, None)
                self._counters.pop(run_id, None)
            stream.condition.notify_all()

    async def close(self) -> None:
        for run_id in tuple(self._streams):
            await self.cleanup(run_id)
