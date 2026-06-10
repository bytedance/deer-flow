"""Abstract stream bridge protocol.

StreamBridge decouples agent workers (producers) from SSE endpoints
(consumers), aligning with LangGraph Platform's Queue + StreamManager
architecture.
"""

from __future__ import annotations

import abc
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any


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


HEARTBEAT_SENTINEL = StreamEvent(id="", event="__heartbeat__", data=None)
END_SENTINEL = StreamEvent(id="", event="__end__", data=None)


class StreamBridge(abc.ABC):
    """Abstract base for stream bridges."""

    @property
    def supports_cross_process_subscribe(self) -> bool:
        """Whether subscribers on a different worker can read this run's events.

        ``False`` for in-process backends (memory).  Backends that share
        events across processes (redis) return ``True`` so routers can allow
        ``store_only`` runs to be joined/streamed without knowing the concrete
        backend type.
        """
        return False

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
        heartbeat_interval: float = 15.0,
    ) -> AsyncIterator[StreamEvent]:
        """Async iterator that yields events for *run_id* (consumer side).

        Yields :data:`HEARTBEAT_SENTINEL` when no event arrives within
        *heartbeat_interval* seconds.  Yields :data:`END_SENTINEL` once
        the producer calls :meth:`publish_end`.
        """

    @abc.abstractmethod
    async def cleanup(self, run_id: str, *, delay: float = 0) -> None:
        """Release resources associated with *run_id*.

        If *delay* > 0 the implementation should wait before releasing,
        giving late subscribers a chance to drain remaining events.
        """

    async def close(self) -> None:
        """Release backend resources.  Default is a no-op."""

    async def refresh_ttl(self, run_id: str) -> None:
        """Refresh the retention TTL for a still-running stream.

        Default is a no-op for backends without a TTL concept (memory).
        """

    async def has_retained_stream(self, run_id: str) -> bool:
        """Whether the backend still retains replayable events for *run_id*.

        Used by terminal short-circuit logic to avoid hanging late joins on
        a run whose retained stream has already been cleaned up.  Default
        returns ``True`` (conservative: assume events may exist, fall through
        to a normal subscribe).
        """
        return True

    async def has_events_after(self, run_id: str, last_event_id: str | None) -> bool:
        """Whether any unconsumed event exists strictly after *last_event_id*.

        Used by the service-layer terminal reconciliation to decide whether a
        synthetic end is safe.  Default returns ``True`` (conservative).
        """
        return True

    async def ping(self) -> None:
        """Startup health check.  Default is a no-op."""

