"""Run lifecycle observer types for decoupled observation.

Defines the RunObserver protocol and lifecycle event types that allow
the harness layer to emit notifications without directly calling
storage implementations.

The app layer provides concrete observers (e.g., StorageObserver) that
map lifecycle events to persistence operations.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from .types import RunStatus

# Callback type for lightweight observer registration
type RunEventCallback = Callable[["RunLifecycleEvent"], Awaitable[None]]


class LifecycleEventType(str, Enum):
    """Lifecycle event types emitted during run execution."""

    # Run lifecycle
    RUN_STARTED = "run_started"
    RUN_COMPLETED = "run_completed"
    RUN_FAILED = "run_failed"
    RUN_CANCELLED = "run_cancelled"

    # Human message (for event store)
    HUMAN_MESSAGE = "human_message"

    # Thread status updates
    THREAD_STATUS_UPDATED = "thread_status_updated"


@dataclass(frozen=True)
class RunLifecycleEvent:
    """A single lifecycle event emitted during run execution.

    Attributes:
        event_type: The type of lifecycle event.
        run_id: The run that emitted this event.
        thread_id: The thread this run belongs to.
        payload: Event-specific data (varies by event_type).
    """

    event_id: str
    event_type: LifecycleEventType
    run_id: str
    thread_id: str
    sequence: int
    occurred_at: datetime
    payload: Mapping[str, Any] = field(default_factory=dict)


@dataclass
class RunResult:
    """Minimal result returned after run execution.

    Contains only the data needed for the caller to understand
    what happened. Detailed events are delivered via observer.

    Attributes:
        run_id: The run ID.
        thread_id: The thread ID.
        status: Final status (success, error, interrupted, etc.).
        error: Error message if status is error.
        completion_data: Token usage and message counts from journal.
        title: Thread title extracted from checkpoint (if available).
    """

    run_id: str
    thread_id: str
    status: RunStatus
    error: str | None = None
    completion_data: dict[str, Any] = field(default_factory=dict)
    title: str | None = None


@runtime_checkable
class RunObserver(Protocol):
    """Protocol for observing run lifecycle events.

    Implementations receive events as they occur during execution
    and can perform side effects (storage, logging, metrics, etc.)
    without coupling the worker to specific implementations.

    Methods are async to support IO-bound operations like database writes.
    """

    async def on_event(self, event: RunLifecycleEvent) -> None:
        """Called when a lifecycle event occurs.

        Args:
            event: The lifecycle event with type, IDs, and payload.

        Implementations should be explicit about failure handling.
        CompositeObserver can be configured to either swallow or raise
        observer failures based on each binding's ``required`` flag.
        """
        ...


@dataclass(frozen=True)
class ObserverBinding:
    """Observer registration with failure policy.

    Attributes:
        observer: Observer instance to invoke.
        required: When True, observer failures are raised to the caller.
            When False, failures are logged and dispatch continues.
    """

    observer: RunObserver
    required: bool = False


class CompositeObserver:
    """Observer that delegates to multiple child observers.

    Useful for combining storage, metrics, and logging observers.
    Optional observers are logged on failure; required observers raise.
    """

    def __init__(
        self,
        observers: list[RunObserver | ObserverBinding] | None = None,
    ) -> None:
        self._observers: list[ObserverBinding] = [
            obs if isinstance(obs, ObserverBinding) else ObserverBinding(obs)
            for obs in (observers or [])
        ]

    def add(self, observer: RunObserver, *, required: bool = False) -> None:
        """Add an observer to the composite."""
        self._observers.append(ObserverBinding(observer=observer, required=required))

    async def on_event(self, event: RunLifecycleEvent) -> None:
        """Dispatch event to all child observers."""
        logger = logging.getLogger(__name__)
        for binding in self._observers:
            try:
                await binding.observer.on_event(event)
            except Exception:
                if binding.required:
                    raise
                logger.warning(
                    "Observer %s failed on event %s",
                    type(binding.observer).__name__,
                    event.event_type.value,
                    exc_info=True,
                )


class NullObserver:
    """No-op observer for when no observation is needed."""

    async def on_event(self, event: RunLifecycleEvent) -> None:
        """Do nothing."""
        pass


@dataclass(slots=True)
class CallbackObserver:
    """Adapter that wraps a callback function as a RunObserver.

    Allows lightweight callback functions to participate in the
    observer protocol without defining a full class.
    """

    callback: RunEventCallback

    async def on_event(self, event: RunLifecycleEvent) -> None:
        """Invoke the wrapped callback with the event."""
        await self.callback(event)


type ObserverLike = RunObserver | RunEventCallback | None


def ensure_observer(observer: ObserverLike) -> RunObserver:
    """Normalize an observer-like value to a RunObserver.

    Args:
        observer: Can be:
            - None: returns NullObserver
            - A callable: wraps in CallbackObserver
            - A RunObserver: returns as-is

    Returns:
        A RunObserver instance.
    """
    if observer is None:
        return NullObserver()
    if callable(observer) and not isinstance(observer, RunObserver):
        return CallbackObserver(observer)
    return observer
