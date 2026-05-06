"""Evaluation runner — batch execution and report generation."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from deerflow.evaluation.dataset import EvalCase
from deerflow.evaluation.judge import LLMJudge


@dataclass
class CaseResult:
    case_index: int
    passed: bool
    scores: dict[str, float]
    overall_score: float
    min_score: float
    error: str | None = None


@dataclass
class EvalReport:
    """Aggregate evaluation report."""

    total_cases: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    pass_rate: float = 0.0
    avg_overall_score: float = 0.0
    dimension_averages: dict[str, float] = field(default_factory=dict)
    case_results: list[CaseResult] = field(default_factory=list)
    duration_seconds: float = 0.0

    def to_dict(self) -> dict:
        return {
            "total_cases": self.total_cases,
            "passed": self.passed,
            "failed": self.failed,
            "errors": self.errors,
            "pass_rate": self.pass_rate,
            "avg_overall_score": self.avg_overall_score,
            "dimension_averages": self.dimension_averages,
            "case_results": [
                {
                    "case_index": r.case_index,
                    "passed": r.passed,
                    "scores": r.scores,
                    "overall_score": r.overall_score,
                    "min_score": r.min_score,
                    "error": r.error,
                }
                for r in self.case_results
            ],
            "duration_seconds": self.duration_seconds,
        }

    def save(self, path: str | Path) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)


class EvalRunner:
    """Runs evaluation cases against an agent factory and produces reports."""

    def __init__(self, judge_model: str | None = None) -> None:
        self._judge = LLMJudge(model_name=judge_model)

    def run(
        self,
        dataset: list[EvalCase],
        agent_factory: Callable[[str], str],
    ) -> EvalReport:
        """Execute all cases and return an aggregated report.

        Args:
            dataset: List of evaluation cases.
            agent_factory: Function that takes a user message and returns the agent's response text.
        """
        start = time.monotonic()
        report = EvalReport()
        report.total_cases = len(dataset)

        for i, case in enumerate(dataset):
            try:
                user_msg = case.conversation[-1]["content"] if case.conversation else ""
                response = agent_factory(user_msg)

                criteria_parts: list[str] = []
                if case.expected_tools:
                    criteria_parts.append(f"Should use tools: {', '.join(case.expected_tools)}")
                if case.expected_topics:
                    criteria_parts.append(f"Should cover topics: {', '.join(case.expected_topics)}")
                criteria = "; ".join(criteria_parts)

                scores = self._judge.evaluate(response, criteria=criteria)
                overall = sum(scores.values()) / len(scores) if scores else 0.0
                passed = overall >= case.min_score

                cr = CaseResult(
                    case_index=i,
                    passed=passed,
                    scores=scores,
                    overall_score=overall,
                    min_score=case.min_score,
                )
                if passed:
                    report.passed += 1
                else:
                    report.failed += 1
                report.case_results.append(cr)

            except Exception as exc:
                report.errors += 1
                report.case_results.append(
                    CaseResult(
                        case_index=i,
                        passed=False,
                        scores={},
                        overall_score=0.0,
                        min_score=case.min_score,
                        error=str(exc),
                    )
                )

        report.pass_rate = report.passed / report.total_cases if report.total_cases > 0 else 0.0
        report.avg_overall_score = (
            sum(r.overall_score for r in report.case_results) / len(report.case_results)
            if report.case_results
            else 0.0
        )

        # Dimension averages
        dim_totals: dict[str, float] = {}
        dim_counts: dict[str, int] = {}
        for cr in report.case_results:
            for dim, score in cr.scores.items():
                dim_totals[dim] = dim_totals.get(dim, 0.0) + score
                dim_counts[dim] = dim_counts.get(dim, 0) + 1
        report.dimension_averages = {
            dim: dim_totals[dim] / dim_counts[dim] for dim in dim_totals
        }

        report.duration_seconds = time.monotonic() - start
        return report

    def compare(
        self,
        dataset: list[EvalCase],
        baseline_factory: Callable[[str], str],
        candidate_factory: Callable[[str], str],
    ) -> tuple[EvalReport, EvalReport]:
        """Run the same dataset against two agent versions and return both reports."""
        baseline = self.run(dataset, baseline_factory)
        candidate = self.run(dataset, candidate_factory)
        return baseline, candidate
