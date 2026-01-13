# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
Combined report evaluator orchestrating both automated metrics and LLM evaluation.
"""

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

from .llm_judge import EvaluationResult, LLMJudge
from .metrics import ReportMetrics, compute_metrics, get_word_count_target

logger = logging.getLogger(__name__)


@dataclass
class CombinedEvaluation:
    """Combined evaluation results from metrics and LLM judge."""

    metrics: ReportMetrics
    llm_evaluation: Optional[EvaluationResult]
    final_score: float
    grade: str
    summary: str

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary format."""
        return {
            "metrics": self.metrics.to_dict(),
            "llm_evaluation": (
                self.llm_evaluation.to_dict() if self.llm_evaluation else None
            ),
            "final_score": self.final_score,
            "grade": self.grade,
            "summary": self.summary,
        }


def score_to_grade(score: float) -> str:
    """Convert numeric score to letter grade."""
    if score >= 9.0:
        return "A+"
    elif score >= 8.5:
        return "A"
    elif score >= 8.0:
        return "A-"
    elif score >= 7.5:
        return "B+"
    elif score >= 7.0:
        return "B"
    elif score >= 6.5:
        return "B-"
    elif score >= 6.0:
        return "C+"
    elif score >= 5.5:
        return "C"
    elif score >= 5.0:
        return "C-"
    elif score >= 4.0:
        return "D"
    else:
        return "F"


class ReportEvaluator:
    """
    Combined report evaluator using both automated metrics and LLM-as-Judge.

    This evaluator provides comprehensive report quality assessment by:
    1. Computing automated metrics (fast, deterministic)
    2. Running LLM-based evaluation (nuanced, contextual)
    3. Combining both for a final score and grade
    """

    def __init__(self, llm: Any = None, use_llm: bool = True):
        """
        Initialize the evaluator.

        Args:
            llm: Optional LLM instance for LLM-as-Judge evaluation
            use_llm: Whether to use LLM evaluation (can be disabled for speed)
        """
        self.use_llm = use_llm
        self.llm_judge = LLMJudge(llm=llm) if use_llm else None

    def _compute_metrics_score(
        self, metrics: ReportMetrics, report_style: str
    ) -> float:
        """
        Convert automated metrics to a 0-10 score.

        Scoring breakdown:
        - Section coverage: 30%
        - Citation quality: 25%
        - Word count compliance: 20%
        - Source diversity: 15%
        - Image inclusion: 10%
        """
        score = 0.0

        section_score = metrics.section_coverage_score * 10
        score += section_score * 0.30

        citation_score = min(metrics.citation_count / 10, 1.0) * 10
        score += citation_score * 0.25

        target = get_word_count_target(report_style)
        if target:
            if target["min"] <= metrics.word_count <= target["max"]:
                word_score = 10.0
            elif metrics.word_count < target["min"]:
                word_score = (metrics.word_count / target["min"]) * 8
            else:
                excess_ratio = metrics.word_count / target["max"]
                word_score = max(10 - (excess_ratio - 1) * 5, 5)
            score += word_score * 0.20

        diversity_score = min(metrics.unique_sources / 5, 1.0) * 10
        score += diversity_score * 0.15

        image_score = min(metrics.image_count / 3, 1.0) * 10
        score += image_score * 0.10

        return round(score, 2)

    def _generate_summary(
        self,
        metrics: ReportMetrics,
        llm_eval: Optional[EvaluationResult],
        final_score: float,
        grade: str,
    ) -> str:
        """Generate a human-readable evaluation summary."""
        lines = [f"Report Grade: {grade} ({final_score}/10)", ""]

        lines.append("**Automated Metrics:**")
        lines.append(f"- Word Count: {metrics.word_count}")
        lines.append(f"- Citations: {metrics.citation_count}")
        lines.append(f"- Unique Sources: {metrics.unique_sources}")
        lines.append(f"- Images: {metrics.image_count}")
        lines.append(
            f"- Section Coverage: {metrics.section_coverage_score * 100:.0f}%"
        )

        if metrics.sections_missing:
            lines.append(f"- Missing Sections: {', '.join(metrics.sections_missing)}")

        if llm_eval:
            lines.append("")
            lines.append("**LLM Evaluation:**")
            for criterion, score in llm_eval.scores.items():
                lines.append(f"- {criterion.replace('_', ' ').title()}: {score}/10")

            if llm_eval.strengths:
                lines.append("")
                lines.append("**Strengths:**")
                for strength in llm_eval.strengths[:3]:
                    lines.append(f"- {strength}")

            if llm_eval.weaknesses:
                lines.append("")
                lines.append("**Areas for Improvement:**")
                for weakness in llm_eval.weaknesses[:3]:
                    lines.append(f"- {weakness}")

        return "\n".join(lines)

    async def evaluate(
        self,
        report: str,
        query: str,
        report_style: str = "default",
    ) -> CombinedEvaluation:
        """
        Evaluate a report using both metrics and LLM.

        Args:
            report: The report text to evaluate
            query: The original research query
            report_style: The style of report

        Returns:
            CombinedEvaluation with full results
        """
        metrics = compute_metrics(report, report_style)
        metrics_score = self._compute_metrics_score(metrics, report_style)

        llm_eval = None
        if self.use_llm and self.llm_judge:
            try:
                llm_eval = await self.llm_judge.evaluate(report, query, report_style)
            except Exception as e:
                logger.warning(f"LLM evaluation failed, using metrics only: {e}")

        if llm_eval and llm_eval.overall_score > 0:
            final_score = (metrics_score * 0.4) + (llm_eval.weighted_score * 0.6)
        else:
            final_score = metrics_score

        final_score = round(final_score, 2)
        grade = score_to_grade(final_score)

        summary = self._generate_summary(metrics, llm_eval, final_score, grade)

        return CombinedEvaluation(
            metrics=metrics,
            llm_evaluation=llm_eval,
            final_score=final_score,
            grade=grade,
            summary=summary,
        )

    def evaluate_sync(
        self,
        report: str,
        query: str,
        report_style: str = "default",
    ) -> CombinedEvaluation:
        """Synchronous version of evaluate."""
        import asyncio

        return asyncio.run(self.evaluate(report, query, report_style))

    def evaluate_metrics_only(
        self,
        report: str,
        report_style: str = "default",
    ) -> Dict[str, Any]:
        """
        Quick evaluation using only automated metrics (no LLM).

        Args:
            report: The report text to evaluate
            report_style: The style of report

        Returns:
            Dictionary with metrics and score
        """
        metrics = compute_metrics(report, report_style)
        metrics_score = self._compute_metrics_score(metrics, report_style)
        grade = score_to_grade(metrics_score)

        return {
            "metrics": metrics.to_dict(),
            "score": metrics_score,
            "grade": grade,
        }
