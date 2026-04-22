"""In-memory stream bridge implementation owned by the app layer."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal

from deerflow.runtime.stream_bridge import (
    CANCELLED_SENTINEL,
    END_SENTINEL,
    HEARTBEAT_SENTINEL,
    TERMINAL_STATES,
    ResumeResult,
    StreamBridge,
    StreamEvent,
    StreamStatus,
)
from deerflow.runtime.stream_bridge.exceptions import (
    BridgeClosedError,
    StreamCapacityExceededError,
    StreamTerminatedError,
)

logger = logging.getLogger(__name__)


@dataclass
class _RunStream:
    condition: asyncio.Condition = field(default_factory=asyncio.Condition)
    events: list[StreamEvent] = field(default_factory=list)
    id_to_offset: dict[str, int] = field(default_factory=dict)
    start_offset: int = 0
    current_bytes: int = 0
    seq: int = 0
    status: StreamStatus = StreamStatus.ACTIVE
    created_at: float = field(default_factory=time.monotonic)
    last_publish_at: float | None = None
    ended_at: float | None = None
    subscriber_count: int = 0
    last_subscribe_at: float | None = None
    awaiting_input: bool = False
    awaiting_since: float | None = None


class MemoryStreamBridge(StreamBridge):
    """Per-run in-memory event log implementation."""

    def __init__(
        self,
        *,
        max_events_per_stream: int = 256,
        max_bytes_per_stream: int = 10 * 1024 * 1024,
        max_active_streams: int = 1000,
        stream_eviction_policy: Literal["reject", "lru"] = "lru",
        terminal_retention_ttl: float = 300.0,
        active_no_publish_timeout: float = 600.0,
        orphan_timeout: float = 60.0,
        max_stream_age: float = 86400.0,
        hitl_extended_timeout: float = 7200.0,
        cleanup_interval: float = 30.0,
        queue_maxsize: int | None = None,
    ) -> None:
        if queue_maxsize is not None:
            max_events_per_stream = queue_maxsize

        self._max_events = max_events_per_stream
        self._max_bytes = max_bytes_per_stream
        self._max_streams = max_active_streams
        self._eviction_policy = stream_eviction_policy
        self._terminal_ttl = terminal_retention_ttl
        self._active_timeout = active_no_publish_timeout
        self._orphan_timeout = orphan_timeout
        self._max_age = max_stream_age
        self._hitl_timeout = hitl_extended_timeout
        self._cleanup_interval = cleanup_interval
        self._streams: dict[str, _RunStream] = {}
        self._registry_lock = asyncio.Lock()
        self._closed = False
        self._cleanup_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
            logger.info(
                "MemoryStreamBridge started (max_events=%d, max_bytes=%d, max_streams=%d)",
                self._max_events,
                self._max_bytes,
                self._max_streams,
            )

    async def close(self) -> None:
        async with self._registry_lock:
            self._closed = True
            if self._cleanup_task is not None:
                self._cleanup_task.cancel()
                try:
                    await self._cleanup_task
                except asyncio.CancelledError:
                    pass
                self._cleanup_task = None

            for stream in self._streams.values():
                async with stream.condition:
                    stream.status = StreamStatus.CLOSED
                    stream.condition.notify_all()

            self._streams.clear()
            logger.info("MemoryStreamBridge closed")

    async def _get_or_create_stream(self, run_id: str) -> _RunStream:
        stream = self._streams.get(run_id)
        if stream is not None:
            return stream

        async with self._registry_lock:
            if self._closed:
                raise BridgeClosedError("Stream bridge is closed")

            stream = self._streams.get(run_id)
            if stream is not None:
                return stream

            if len(self._streams) >= self._max_streams:
                if self._eviction_policy == "reject":
                    raise StreamCapacityExceededError(
                        f"Max {self._max_streams} active streams reached"
                    )
                evicted = self._evict_oldest_terminal()
                if evicted is None:
                    raise StreamCapacityExceededError("All streams active, cannot evict")
                logger.info("Evicted stream %s to make room", evicted)

            stream = _RunStream()
            self._streams[run_id] = stream
            logger.debug("Created stream for run %s", run_id)
            return stream

    def _evict_oldest_terminal(self) -> str | None:
        oldest_run_id: str | None = None
        oldest_ended_at: float = float("inf")
        for run_id, stream in self._streams.items():
            if stream.status in TERMINAL_STATES and stream.ended_at is not None:
                if stream.ended_at < oldest_ended_at:
                    oldest_ended_at = stream.ended_at
                    oldest_run_id = run_id
        if oldest_run_id is not None:
            del self._streams[oldest_run_id]
            return oldest_run_id
        return None

    def _next_id(self, stream: _RunStream) -> str:
        stream.seq += 1
        return f"{int(time.time() * 1000)}-{stream.seq}"

    def _estimate_size(self, event: StreamEvent) -> int:
        base = len(event.id) + len(event.event) + 100
        if event.data is None:
            return base
        if isinstance(event.data, str):
            return base + len(event.data)
        if isinstance(event.data, (dict, list)):
            try:
                return base + len(json.dumps(event.data, default=str))
            except (TypeError, ValueError):
                return base + 200
        return base + 50

    def _evict_overflow(self, stream: _RunStream) -> None:
        while len(stream.events) > self._max_events or stream.current_bytes > self._max_bytes:
            if not stream.events:
                break
            evicted = stream.events.pop(0)
            stream.id_to_offset.pop(evicted.id, None)
            stream.current_bytes -= self._estimate_size(evicted)
            stream.start_offset += 1

    async def publish(self, run_id: str, event: str, data: Any) -> str:
        stream = await self._get_or_create_stream(run_id)
        async with stream.condition:
            if stream.status != StreamStatus.ACTIVE:
                raise StreamTerminatedError(
                    f"Cannot publish to {stream.status.value} stream"
                )

            entry = StreamEvent(id=self._next_id(stream), event=event, data=data)
            absolute_offset = stream.start_offset + len(stream.events)
            stream.events.append(entry)
            stream.id_to_offset[entry.id] = absolute_offset
            stream.current_bytes += self._estimate_size(entry)
            stream.last_publish_at = time.monotonic()
            self._evict_overflow(stream)
            stream.condition.notify_all()
            return entry.id

    async def publish_end(self, run_id: str) -> str:
        return await self.publish_terminal(run_id, StreamStatus.ENDED)

    async def publish_terminal(
        self,
        run_id: str,
        kind: StreamStatus,
        data: Any = None,
    ) -> str:
        if kind not in TERMINAL_STATES:
            raise ValueError(f"Invalid terminal kind: {kind}")

        stream = await self._get_or_create_stream(run_id)
        async with stream.condition:
            if stream.status != StreamStatus.ACTIVE:
                for evt in reversed(stream.events):
                    if evt.event in ("end", "cancel", "error", "dead_letter"):
                        return evt.id
                return ""

            event_name = {
                StreamStatus.ENDED: "end",
                StreamStatus.CANCELLED: "cancel",
                StreamStatus.ERRORED: "error",
            }[kind]
            entry = StreamEvent(id=self._next_id(stream), event=event_name, data=data)
            absolute_offset = stream.start_offset + len(stream.events)
            stream.events.append(entry)
            stream.id_to_offset[entry.id] = absolute_offset
            stream.current_bytes += self._estimate_size(entry)
            stream.status = kind
            stream.ended_at = time.monotonic()
            stream.awaiting_input = False
            stream.condition.notify_all()
            logger.debug("Stream %s terminal: %s", run_id, kind.value)
            return entry.id

    async def cancel(self, run_id: str) -> None:
        await self.publish_terminal(run_id, StreamStatus.CANCELLED)

    async def subscribe(
        self,
        run_id: str,
        *,
        last_event_id: str | None = None,
        heartbeat_interval: float = 15.0,
    ) -> AsyncIterator[StreamEvent]:
        stream = await self._get_or_create_stream(run_id)
        resume = self._resolve_resume_point(stream, last_event_id)
        next_offset = resume.next_offset

        async with stream.condition:
            stream.subscriber_count += 1
            stream.last_subscribe_at = time.monotonic()

        try:
            while True:
                entry_to_yield: StreamEvent | None = None
                sentinel_to_yield: StreamEvent | None = None
                should_return = False
                should_wait = False

                async with stream.condition:
                    if self._closed or stream.status == StreamStatus.CLOSED:
                        sentinel_to_yield = CANCELLED_SENTINEL
                        should_return = True
                    elif next_offset < stream.start_offset:
                        next_offset = stream.start_offset
                    else:
                        local_index = next_offset - stream.start_offset
                        if 0 <= local_index < len(stream.events):
                            entry_to_yield = stream.events[local_index]
                            next_offset += 1
                            if entry_to_yield.event in ("end", "cancel", "error", "dead_letter"):
                                should_return = True
                        elif stream.status in TERMINAL_STATES:
                            sentinel_to_yield = END_SENTINEL
                            should_return = True
                        else:
                            should_wait = True
                            try:
                                await asyncio.wait_for(
                                    stream.condition.wait(),
                                    timeout=heartbeat_interval,
                                )
                            except TimeoutError:
                                pass

                if sentinel_to_yield is not None:
                    yield sentinel_to_yield
                    if should_return:
                        return
                    continue

                if entry_to_yield is not None:
                    yield entry_to_yield
                    if should_return:
                        return
                    continue

                if should_wait:
                    async with stream.condition:
                        local_index = next_offset - stream.start_offset
                        has_events = 0 <= local_index < len(stream.events)
                        is_terminal = stream.status in TERMINAL_STATES
                    if not has_events and not is_terminal:
                        yield HEARTBEAT_SENTINEL

        finally:
            async with stream.condition:
                stream.subscriber_count = max(0, stream.subscriber_count - 1)

    async def mark_awaiting_input(self, run_id: str) -> None:
        stream = self._streams.get(run_id)
        if stream is None:
            return
        async with stream.condition:
            if stream.status == StreamStatus.ACTIVE:
                stream.awaiting_input = True
                stream.awaiting_since = time.monotonic()
                logger.debug("Stream %s marked as awaiting input", run_id)

    async def cleanup(self, run_id: str, *, delay: float = 0) -> None:
        if delay > 0:
            await asyncio.sleep(delay)
        await self._do_cleanup(run_id, "manual")

    async def _do_cleanup(self, run_id: str, reason: str) -> None:
        async with self._registry_lock:
            stream = self._streams.pop(run_id, None)
            if stream is not None:
                async with stream.condition:
                    stream.status = StreamStatus.CLOSED
                    stream.condition.notify_all()
                logger.debug("Cleaned up stream %s (reason: %s)", run_id, reason)

    async def _mark_dead_letter(self, run_id: str, reason: str) -> None:
        stream = self._streams.get(run_id)
        if stream is None:
            return
        async with stream.condition:
            if stream.status != StreamStatus.ACTIVE:
                return
            entry = StreamEvent(
                id=self._next_id(stream),
                event="dead_letter",
                data={"reason": reason, "timestamp": time.time()},
            )
            absolute_offset = stream.start_offset + len(stream.events)
            stream.events.append(entry)
            stream.id_to_offset[entry.id] = absolute_offset
            stream.current_bytes += self._estimate_size(entry)
            stream.status = StreamStatus.ERRORED
            stream.ended_at = time.monotonic()
            stream.condition.notify_all()
        logger.warning("Stream %s marked as dead letter: %s", run_id, reason)

    async def _cleanup_loop(self) -> None:
        while not self._closed:
            try:
                await asyncio.sleep(self._cleanup_interval)
            except asyncio.CancelledError:
                break

            now = time.monotonic()
            to_cleanup: list[tuple[str, str]] = []
            to_mark_dead: list[tuple[str, str]] = []

            async with self._registry_lock:
                for run_id, stream in list(self._streams.items()):
                    if now - stream.created_at > self._max_age:
                        to_cleanup.append((run_id, "max_age_exceeded"))
                        continue

                    if stream.status == StreamStatus.ACTIVE:
                        timeout = self._hitl_timeout if stream.awaiting_input else self._active_timeout
                        last_activity = stream.last_publish_at or stream.created_at
                        if now - last_activity > timeout:
                            to_mark_dead.append((run_id, "no_publish_timeout"))
                            continue

                    if stream.status in TERMINAL_STATES and stream.ended_at:
                        if stream.subscriber_count > 0:
                            continue
                        last_sub = stream.last_subscribe_at or stream.ended_at
                        if now - last_sub > self._orphan_timeout:
                            to_cleanup.append((run_id, "orphan"))
                            continue
                        if now - stream.ended_at > self._terminal_ttl:
                            to_cleanup.append((run_id, "ttl_expired"))

            for run_id, reason in to_mark_dead:
                await self._mark_dead_letter(run_id, reason)
            for run_id, reason in to_cleanup:
                await self._do_cleanup(run_id, reason)

    def get_stats(self) -> dict[str, Any]:
        active = sum(1 for s in self._streams.values() if s.status == StreamStatus.ACTIVE)
        terminal = sum(1 for s in self._streams.values() if s.status in TERMINAL_STATES)
        total_events = sum(len(s.events) for s in self._streams.values())
        total_bytes = sum(s.current_bytes for s in self._streams.values())
        total_subs = sum(s.subscriber_count for s in self._streams.values())
        return {
            "total_streams": len(self._streams),
            "active_streams": active,
            "terminal_streams": terminal,
            "total_events": total_events,
            "total_bytes": total_bytes,
            "total_subscribers": total_subs,
            "closed": self._closed,
        }

    def _resolve_resume_point(
        self,
        stream: _RunStream,
        last_event_id: str | None,
    ) -> ResumeResult:
        if last_event_id is None:
            return ResumeResult(next_offset=stream.start_offset, status="fresh")
        if last_event_id in stream.id_to_offset:
            return ResumeResult(
                next_offset=stream.id_to_offset[last_event_id] + 1,
                status="resumed",
            )

        parts = last_event_id.split("-")
        if len(parts) != 2:
            return ResumeResult(next_offset=stream.start_offset, status="invalid")
        try:
            event_ts = int(parts[0])
            _event_seq = int(parts[1])
        except ValueError:
            return ResumeResult(next_offset=stream.start_offset, status="invalid")

        if stream.events:
            try:
                oldest_parts = stream.events[0].id.split("-")
                oldest_ts = int(oldest_parts[0])
                if event_ts < oldest_ts:
                    return ResumeResult(
                        next_offset=stream.start_offset,
                        status="evicted",
                        gap_count=stream.start_offset,
                    )
            except (ValueError, IndexError):
                pass

        return ResumeResult(next_offset=stream.start_offset, status="unknown")


__all__ = ["MemoryStreamBridge"]
