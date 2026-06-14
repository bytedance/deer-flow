"""Run executor contract."""

from __future__ import annotations

from typing import Protocol

from ..domain import Run


class RunExecutor(Protocol):
    """Executes one run against the underlying agent or graph runtime."""

    async def execute(self, run: Run) -> None:
        pass


__all__ = [
    "RunExecutor",
]
