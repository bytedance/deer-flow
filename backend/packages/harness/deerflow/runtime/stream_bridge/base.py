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


class StreamBridge(abc.ABC):
    """Abstract base for stream bridges."""

    supports_cross_process: bool = False

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

    async def close(self) -> None:
        """Release backend resources.  Default is a no-op."""
