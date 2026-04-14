from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from deerflow.agents.memory.eval.types import ReplayResult


@dataclass(slots=True)
class FeedbackRecord:
    trace_id: str
    fact_id: str
    user_rating: float | None
    was_useful: bool | None
    timestamp: str


@dataclass(slots=True)
class CorrelationResult:
    strategy_name: str
    total_traces: int
    correlated_count: int
    avg_usefulness: float | None
    correlation_notes: str


class FeedbackCorrelator(Protocol):
    def correlate(self, replay_results: list[ReplayResult], feedback: list[FeedbackRecord]) -> CorrelationResult: ...
    def load_feedback(self, path: Path) -> list[FeedbackRecord]: ...


# TODO(#1850): Implement when feedback data is available
class PlaceholderCorrelator:
    def correlate(self, replay_results: list[ReplayResult], feedback: list[FeedbackRecord]) -> CorrelationResult:
        raise NotImplementedError("Feedback correlation requires #1850 feedback data. See RFC #1908.")

    def load_feedback(self, path: Path) -> list[FeedbackRecord]:
        raise NotImplementedError("Feedback data loading requires #1850. See RFC #1908.")
