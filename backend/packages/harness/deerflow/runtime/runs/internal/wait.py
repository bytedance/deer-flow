"""Internal run wait helpers based on stream events."""

from __future__ import annotations

from typing import Any

from deerflow.runtime.stream_bridge import StreamEvent

from .streams import RunStreamService


class WaitTimeoutError(TimeoutError):
    """Raised when wait times out."""

    pass


class WaitErrorResult:
    """Represents an error result from wait."""

    def __init__(self, error: str, details: dict[str, Any] | None = None) -> None:
        self.error = error
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {"error": self.error, **self.details}


class RunWaitService:
    """
    Wait service for runs domain.

    Based on RunStreamService.subscribe(), implements wait semantics.

    Phase 1 behavior:
    - Records last 'values' event
    - On 'error', returns unified error structure
    - On 'end' only, returns last values
    """

    TERMINAL_EVENTS = frozenset({"end", "error", "cancel"})

    def __init__(self, stream_service: RunStreamService) -> None:
        self._stream_service = stream_service

    async def wait_for_terminal(
        self,
        run_id: str,
        *,
        last_event_id: str | None = None,
    ) -> StreamEvent | None:
        """Block until the next terminal event for a run is observed."""
        async for event in self._stream_service.subscribe(
            run_id,
            last_event_id=last_event_id,
        ):
            if event.event in self.TERMINAL_EVENTS:
                return event

        return None

    async def wait_for_values_or_error(
        self,
        run_id: str,
        *,
        last_event_id: str | None = None,
    ) -> dict[str, Any] | WaitErrorResult | None:
        """
        Wait for run to complete and return final values or error.

        Returns:
        - dict: Final values if successful
        - WaitErrorResult: If run failed
        - None: If no values were produced
        """
        last_values: dict[str, Any] | None = None

        async for event in self._stream_service.subscribe(
            run_id,
            last_event_id=last_event_id,
        ):
            if event.event == "values":
                last_values = event.data

            elif event.event == "error":
                return WaitErrorResult(
                    error=str(event.data) if event.data else "Unknown error",
                    details={"run_id": run_id},
                )

            elif event.event in self.TERMINAL_EVENTS:
                # Stream ended, return last values
                break

        return last_values
