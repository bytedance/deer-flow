"""Stable, read-only run evidence contracts for extension services."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


class InvalidRunEvidenceCursor(ValueError):
    """The cursor is malformed, unsupported, or belongs to another scope."""


@dataclass(frozen=True)
class RunStatusView:
    """Authoritative lifecycle projection for one visible run."""

    thread_id: str = ""
    run_id: str = ""
    status: str = ""
    created_at: str = ""
    updated_at: str = ""
    error: str | None = None
    stop_reason: str | None = None


@dataclass(frozen=True)
class RunEventView:
    """Persisted evidence envelope; ``seq`` is monotonic within its thread."""

    thread_id: str = ""
    run_id: str = ""
    seq: int = 0
    event_type: str = ""
    category: str = ""
    content: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""


@dataclass(frozen=True)
class RunPage:
    """Changed runs plus the opaque cursor represented by this page."""

    items: tuple[RunStatusView, ...] = ()
    next_cursor: str | None = None
    has_more: bool = False


@dataclass(frozen=True)
class RunEventPage:
    """One forward page from a known run's persisted event stream."""

    items: tuple[RunEventView, ...] = ()
    next_after_seq: int | None = None
    has_more: bool = False


class RunEvidenceReader(Protocol):
    """Host-bound evidence reader; implementations never expose writes."""

    async def list_changed_runs(self, *, cursor: str | None, limit: int) -> RunPage:
        """Return visible runs changed after ``cursor`` in stable order.

        Callers persist ``next_cursor`` only after their own output is durable.
        Reusing the input cursor is valid and may replay items. An empty page
        means caught up; unsupported hosts omit the reader instead.
        """
        raise NotImplementedError("the host does not provide changed-run discovery")

    async def list_run_events(
        self,
        *,
        thread_id: str,
        run_id: str,
        after_seq: int | None,
        limit: int,
    ) -> RunEventPage:
        """Return events with thread-scoped ``seq > after_seq``.

        A missing or invisible run returns an empty page, preventing identity
        probing across the reader's host-bound scope.
        """
        raise NotImplementedError("the host does not provide run-event reading")

    async def get_run_status(self, *, thread_id: str, run_id: str) -> RunStatusView | None:
        """Return authoritative status, or ``None`` when not visible."""
        raise NotImplementedError("the host does not provide run-status reading")
