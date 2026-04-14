from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from deerflow.agents.memory.retrieval_trace import CandidateFact


@dataclass(slots=True)
class RankedFact:
    fact_id: str
    category: str
    original_rank: int
    new_rank: int
    score: float
    score_components: dict[str, float]
    included: bool
    token_cost: int


@dataclass(slots=True)
class ReplayResult:
    trace_id: str
    strategy_name: str
    ranked_facts: list[RankedFact]
    selected_count: int
    dropped_count: int
    tokens_used: int
    tokens_remaining: int


@dataclass(slots=True)
class ComparisonResult:
    trace_id: str
    baseline_strategy: str
    comparison_strategy: str
    baseline_metrics: dict[str, float]
    comparison_metrics: dict[str, float]
    deltas: dict[str, float]


class RankingStrategy(Protocol):
    @property
    def name(self) -> str: ...

    def rank(self, candidates: list[CandidateFact], *, max_tokens: int) -> list[RankedFact]: ...


class OutputFormatter(Protocol):
    def format(self, results: list[ComparisonResult]) -> str: ...
