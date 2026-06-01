"""Run state repository contract."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from ..domain import Run, RunId, ThreadId, UserId

if TYPE_CHECKING:
    from ..application.dto import RunSnapshot


class RunRepository(Protocol):
    """Persistence boundary for run state snapshots."""

    async def save(self, run: Run) -> None: ...

    async def get(self, run_id: RunId, *, user_id: UserId | None = None) -> Run | None: ...

    async def list_by_thread(
        self,
        thread_id: ThreadId,
        *,
        user_id: UserId | None = None,
        limit: int = 100,
    ) -> list[RunSnapshot]: ...

    async def delete(self, run_id: RunId) -> bool: ...


__all__ = [
    "RunRepository",
]
