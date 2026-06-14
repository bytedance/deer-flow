"""Domain policies for run concurrency and cancellation."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from .model import Run
from .value_objects import CancelAction, MultitaskStrategy, RunStatus


class MultitaskDecision(StrEnum):
    """Application-level decision produced by a multitask policy."""

    allow = "allow"
    reject = "reject"
    cancel_existing = "cancel_existing"
    enqueue = "enqueue"


@dataclass(frozen=True)
class MultitaskPolicy:
    strategy: MultitaskStrategy = MultitaskStrategy.reject

    def decide(self, active_runs: Sequence[Run]) -> MultitaskDecision:
        inflight = [run for run in active_runs if run.status in (RunStatus.pending, RunStatus.running)]
        if not inflight:
            return MultitaskDecision.allow
        if self.strategy == MultitaskStrategy.reject:
            return MultitaskDecision.reject
        if self.strategy in (MultitaskStrategy.interrupt, MultitaskStrategy.rollback):
            return MultitaskDecision.cancel_existing
        return MultitaskDecision.enqueue


@dataclass(frozen=True)
class CancelPolicy:
    action: CancelAction = CancelAction.interrupt

    @property
    def rolls_back_checkpoint(self) -> bool:
        return self.action == CancelAction.rollback


__all__ = [
    "CancelPolicy",
    "MultitaskDecision",
    "MultitaskPolicy",
]
