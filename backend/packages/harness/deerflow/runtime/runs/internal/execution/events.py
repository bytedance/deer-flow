"""Lifecycle event helpers for run execution."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ...observer import LifecycleEventType, RunLifecycleEvent, RunObserver


class RunEventEmitter:
    """Build and dispatch lifecycle events for a single run."""

    def __init__(
        self,
        *,
        run_id: str,
        thread_id: str,
        observer: RunObserver,
    ) -> None:
        self._run_id = run_id
        self._thread_id = thread_id
        self._observer = observer
        self._sequence = 0

    @property
    def sequence(self) -> int:
        return self._sequence

    async def emit(
        self,
        event_type: LifecycleEventType,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self._sequence += 1
        event = RunLifecycleEvent(
            event_id=f"{self._run_id}:{event_type.value}:{self._sequence}",
            event_type=event_type,
            run_id=self._run_id,
            thread_id=self._thread_id,
            sequence=self._sequence,
            occurred_at=datetime.now(UTC),
            payload=payload or {},
        )
        await self._observer.on_event(event)
