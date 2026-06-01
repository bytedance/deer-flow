"""Durable run event log contract."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from ..domain import RunEvent, RunId, ThreadId

if TYPE_CHECKING:
    from ..application.dto import RunMessageView, StoredRunEvent


class RunEventLog(Protocol):
    """Persistence boundary for run messages and execution trace events."""

    async def append(self, events: list[RunEvent]) -> list[StoredRunEvent]: ...

    async def list_messages_by_run(
        self,
        thread_id: ThreadId,
        run_id: RunId,
        *,
        limit: int = 50,
        before_seq: int | None = None,
        after_seq: int | None = None,
    ) -> list[RunMessageView]: ...

    async def list_events_by_run(
        self,
        thread_id: ThreadId,
        run_id: RunId,
        *,
        limit: int = 500,
    ) -> list[StoredRunEvent]: ...


__all__ = [
    "RunEventLog",
]
