"""Run execution scheduler contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..domain import RunId


@dataclass(frozen=True)
class RunExecutionHandle:
    run_id: RunId


class RunExecutionScheduler(Protocol):
    """Starts background execution for an accepted run."""

    async def start(self, run_id: RunId) -> RunExecutionHandle:
        pass


__all__ = [
    "RunExecutionHandle",
    "RunExecutionScheduler",
]
