"""Run execution supervision contract."""

from __future__ import annotations

from typing import Protocol

from ..domain import CancelAction, RunId


class RunSupervisor(Protocol):
    """Controls lifecycle operations for already scheduled runs."""

    async def cancel(self, run_id: RunId, *, action: CancelAction = CancelAction.interrupt) -> bool: ...


__all__ = [
    "RunSupervisor",
]
