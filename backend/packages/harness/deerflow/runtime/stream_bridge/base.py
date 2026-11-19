"""Abstract stream bridge protocol.

StreamBridge decouples agent workers (producers) from SSE endpoints
(consumers), aligning with LangGraph Platform's Queue + StreamManager
architecture.
"""

from __future__ import annotations

import abc
import math
from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from deerflow.config.stream_bridge_config import DEFAULT_HEARTBEAT_INTERVAL_SECONDS, MAX_HEARTBEAT_INTERVAL_SECONDS


@dataclass(frozen=True)
class StreamEvent:
    """Single stream event.

    Attributes:
        id: Monotonically increasing event ID (used as SSE ``id:`` field,
            supports ``Last-Event-ID`` reconnection).
        event: SSE event name, e.g. ``"metadata"``, ``"updates"``,
            ``"events"``, ``"error"``, ``"end"``.
        data: JSON-serialisable payload.
    """

    id: str
    event: str
    data: Any


@dataclass(frozen=True)
class StreamGap:
    """A subscriber cursor can no longer be replayed completely.

    ``requested_event_id`` is the reconnect cursor, or the most recently
    delivered event for a live subscriber that fell behind.  The retained
    bounds let callers reload durable state and resume at the current tail
    without mistaking a partial replay for a complete one.  When nothing is
    retained in the buffer, the bounds are ``None``.
    """

    requested_event_id: str | None
    earliest_available_event_id: str | None
    latest_available_event_id: str | None


HEARTBEAT_SENTINEL = StreamEvent(id="", event="__heartbeat__", data=None)
END_SENTINEL = StreamEvent(id="", event="__end__", data=None)
type StreamItem = StreamEvent | StreamGap


class StreamProducerLeaseState(StrEnum):
    """Cross-process liveness state for a run's stream producer."""

    untracked = "untracked"
    active = "active"
    expired = "expired"


class StreamBridge(abc.ABC):
    """Abstract base for stream bridges."""

    supports_cross_process: bool = False
    producer_lease_recovery_enabled: bool = False

    def __init__(self, *, heartbeat_interval: float = DEFAULT_HEARTBEAT_INTERVAL_SECONDS) -> None:
        self._heartbeat_interval = self._validate_heartbeat_interval(heartbeat_interval)

    @property
    def heartbeat_interval(self) -> float:
        """Default number of idle seconds between subscriber heartbeats."""
        return self._heartbeat_interval

    def _resolve_heartbeat_interval(self, heartbeat_interval: float | None) -> float:
        if heartbeat_interval is None:
            return self._heartbeat_interval
        return self._validate_heartbeat_interval(heartbeat_interval)

    @staticmethod
    def _validate_heartbeat_interval(heartbeat_interval: float) -> float:
        if isinstance(heartbeat_interval, bool) or not isinstance(heartbeat_interval, (int, float)) or not math.isfinite(heartbeat_interval) or heartbeat_interval <= 0 or heartbeat_interval > MAX_HEARTBEAT_INTERVAL_SECONDS:
            raise ValueError(f"heartbeat_interval must be a positive finite number no greater than {MAX_HEARTBEAT_INTERVAL_SECONDS:g} seconds")
        return float(heartbeat_interval)

    @abc.abstractmethod
    async def publish(self, run_id: str, event: str, data: Any) -> None:
        """Enqueue a single event for *run_id* (producer side)."""

    @abc.abstractmethod
    async def publish_end(self, run_id: str) -> None:
        """Signal that no more events will be produced for *run_id*."""

    @abc.abstractmethod
    def subscribe(
        self,
        run_id: str,
        *,
        last_event_id: str | None = None,
        heartbeat_interval: float | None = None,
    ) -> AsyncIterator[StreamItem]:
        """Async iterator that yields events for *run_id* (consumer side).

        Yields :data:`HEARTBEAT_SENTINEL` when no event arrives within
        *heartbeat_interval* seconds, or the bridge's configured default when
        omitted. Yields :data:`END_SENTINEL` once the producer calls
        :meth:`publish_end`. Yields :class:`StreamGap` and stops when the
        subscriber has fallen behind retained history.
        """

    @abc.abstractmethod
    async def cleanup(self, run_id: str, *, delay: float = 0) -> None:
        """Release resources associated with *run_id*.

        If *delay* > 0 the implementation should wait before releasing,
        giving late subscribers a chance to drain remaining events.
        """

    async def ping(self) -> bool:
        """Return whether the bridge's external backend is reachable right now.

        Used by the gateway readiness probe. The default is for bridges with
        no external backend: the in-process memory bridge has nothing to
        probe and is always reachable. A bridge that sets
        :attr:`supports_cross_process` talks to a shared backend and should
        override this with a bounded round trip, answering ``False`` (not
        raising) when the backend is down.
        """
        return True

    async def start_producer_lease(self, run_id: str) -> bool:
        """Start producer liveness tracking; return whether it is active."""
        return False

    async def finish_producer_lease(self, run_id: str) -> None:
        """Stop producer liveness tracking when supported."""

    async def abort_producer_lease(self, run_id: str) -> None:
        """Discard tracking for a producer whose run was never admitted."""
        await self.finish_producer_lease(run_id)

    def transfer_producer_lease(
        self,
        run_id: str,
        owner_task: Any,
    ) -> None:
        """Transfer cancellation ownership to the task publishing the tail."""

    async def producer_lease_state(self, run_id: str) -> StreamProducerLeaseState:
        """Return producer liveness without inferring it from stream contents."""
        return StreamProducerLeaseState.untracked

    async def cleanup_expired_producer(self, run_id: str) -> bool:
        """Delete an expired producer marker without touching an active owner."""
        return False

    async def close(self) -> None:
        """Release backend resources.  Default is a no-op."""
