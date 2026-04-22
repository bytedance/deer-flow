"""Row shape and protocol for model feedback stores."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class ModelFeedbackRow:
    """Counters for one configured model name (``ModelSubConfig.name``)."""

    model_name: str
    call_count: int
    success_count: int
    failure_count: int
    positive_feedback_count: int
    negative_feedback_count: int
    updated_at: float | None = None


@runtime_checkable
class ModelFeedbackStore(Protocol):
    """Pluggable persistence for model feedback counters."""

    async def increment(
        self,
        model_name: str,
        *,
        call_count: int = 0,
        success_count: int = 0,
        failure_count: int = 0,
        positive_feedback_count: int = 0,
        negative_feedback_count: int = 0,
    ) -> None:
        """Atomically add non-negative deltas to counters for *model_name*."""
        ...

    async def list_rows(self) -> list[ModelFeedbackRow]:
        """Return all rows (order undefined)."""
        ...
