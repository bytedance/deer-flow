"""Stream bridge contract and public types."""

from __future__ import annotations

import abc
from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import Enum
from typing import Literal

type JSONScalar = None | bool | int | float | str
type JSONValue = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]


class StreamStatus(str, Enum):
    """Stream lifecycle states."""

    ACTIVE = "active"
    ENDED = "ended"
    CANCELLED = "cancelled"
    ERRORED = "errored"
    CLOSED = "closed"


TERMINAL_STATES = frozenset({
    StreamStatus.ENDED,
    StreamStatus.CANCELLED,
    StreamStatus.ERRORED,
})


@dataclass(frozen=True, slots=True)
class StreamEvent:
    """Single stream event."""

    id: str
    event: str
    data: JSONValue


@dataclass(frozen=True, slots=True)
class ResumeResult:
    """Result of resolving Last-Event-ID."""

    next_offset: int
    status: Literal["fresh", "resumed", "evicted", "invalid", "unknown"]
    gap_count: int = 0


HEARTBEAT_SENTINEL = StreamEvent(id="", event="__heartbeat__", data=None)
END_SENTINEL = StreamEvent(id="", event="__end__", data=None)
CANCELLED_SENTINEL = StreamEvent(id="", event="__cancelled__", data=None)


class StreamBridge(abc.ABC):
    """Abstract base for stream bridges.

    ``StreamBridge`` defines runtime stream semantics, not storage semantics.
    Concrete backends may live outside the harness package and be injected by
    the application composition root.

    Important boundary rules:
    - Terminal run events (``end``/``cancel``/``error``) are real replayable
      events and belong to run-level semantics.
    - ``close()`` is bridge-level shutdown and must not be treated as a run
      cancellation signal.
    """

    @abc.abstractmethod
    async def publish(self, run_id: str, event: str, data: JSONValue) -> str:
        """Enqueue a single event for *run_id* and return its event ID."""

    @abc.abstractmethod
    async def publish_end(self, run_id: str) -> str:
        """Signal that no more events will be produced for *run_id*."""

    async def publish_terminal(
        self,
        run_id: str,
        kind: StreamStatus,
        data: JSONValue = None,
    ) -> str:
        """Publish a terminal event (end/cancel/error)."""
        await self.publish_end(run_id)
        return ""

    @abc.abstractmethod
    def subscribe(
        self,
        run_id: str,
        *,
        last_event_id: str | None = None,
        heartbeat_interval: float = 15.0,
    ) -> AsyncIterator[StreamEvent]:
        """Yield replayable stream events for *run_id*."""

    @abc.abstractmethod
    async def cleanup(self, run_id: str, *, delay: float = 0) -> None:
        """Release resources associated with *run_id*."""

    async def cancel(self, run_id: str) -> None:
        """Cancel a run and notify all subscribers."""
        await self.publish_terminal(run_id, StreamStatus.CANCELLED)

    async def mark_awaiting_input(self, run_id: str) -> None:
        """Mark stream as awaiting human input."""

    async def start(self) -> None:
        """Start background tasks, if needed."""

    async def close(self) -> None:
        """Release bridge-level backend resources."""
