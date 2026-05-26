"""Signal-to-improvement bridge.

Generates ranked improvement suggestions from aggregated analytics and
closure pattern data.
"""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from deerflow.insights.models import (
    ClosureMetrics,
    FeedbackTrend,
    ImprovementEvidence,
    ImprovementSuggestion,
)

logger = logging.getLogger(__name__)


class ImprovementEngine:
    """Generate ranked improvement suggestions from analytics data."""

    def __init__(
        self,
        low_confidence_threshold: float = 0.3,
        model_name: str | None = None,
    ) -> None:
        self._threshold = low_confidence_threshold
        self._model_name = model_name

    def generate_suggestions(
        self,
        tenant_id: str,
        feedback_trends: list[FeedbackTrend],
        closure_metrics: list[ClosureMetrics] | None = None,
    ) -> list[ImprovementSuggestion]:
        """Generate improvement suggestions from aggregated data.

        Args:
            tenant_id: Tenant identifier
            feedback_trends: Aggregated feedback trends per agent
            closure_metrics: Optional closure metrics

        Returns:
            List of ranked ImprovementSuggestion objects
        """
        suggestions = []

        # Analyze feedback trends
        for trend in feedback_trends:
            if trend.trend_direction == "declining" or trend.positive_ratio < 0.5:
                suggestion = self._create_feedback_suggestion(trend)
                if suggestion and suggestion.confidence >= self._threshold:
                    suggestions.append(suggestion)

            # Check top complaints
            if trend.top_complaints:
                complaint_suggestion = self._create_complaint_suggestion(trend)
                if complaint_suggestion and complaint_suggestion.confidence >= self._threshold:
                    suggestions.append(complaint_suggestion)

        # Analyze closure patterns
        if closure_metrics:
            for metrics in closure_metrics:
                if metrics.overdue_count > 0 or (
                    metrics.sla_compliance_rate is not None
                    and metrics.sla_compliance_rate < 0.8
                ):
                    closure_suggestion = self._create_closure_suggestion(metrics)
                    if closure_suggestion and closure_suggestion.confidence >= self._threshold:
                        suggestions.append(closure_suggestion)

        # Sort by confidence descending
        suggestions.sort(key=lambda s: s.confidence, reverse=True)

        logger.info(
            "Generated %d improvement suggestions for tenant %s",
            len(suggestions),
            tenant_id,
        )
        return suggestions

    def _create_feedback_suggestion(
        self, trend: FeedbackTrend
    ) -> ImprovementSuggestion | None:
        """Create a suggestion from declining feedback trend."""
        total = trend.positive_count + trend.negative_count
        if total < 3:
            return None

        confidence = self._compute_confidence(
            evidence_count=total,
            consistency=trend.trend_direction == "declining",
            severity=trend.positive_ratio < 0.3,
        )

        suggestion_text = (
            f"Agent {trend.agent_name} has a {trend.positive_ratio:.0%} positive rate "
            f"over {trend.window_days} days ({trend.negative_count} negative, "
            f"{trend.positive_count} positive). Review agent configuration and prompts."
        )

        return ImprovementSuggestion(
            id=str(uuid.uuid4()),
            target=f"agent:{trend.agent_name}",
            issue_pattern="declining_feedback_ratio",
            suggestion=suggestion_text,
            confidence=confidence,
            evidence=ImprovementEvidence(
                metrics={
                    "positive_ratio": trend.positive_ratio,
                    "negative_count": trend.negative_count,
                    "window_days": trend.window_days,
                }
            ),
        )

    def _create_complaint_suggestion(
        self, trend: FeedbackTrend
    ) -> ImprovementSuggestion | None:
        """Create a suggestion from top complaint keywords."""
        if not trend.top_complaints:
            return None

        keyword, count = trend.top_complaints[0]
        if count < 2:
            return None

        confidence = self._compute_confidence(
            evidence_count=count,
            consistency=True,
            severity=count >= 5,
        )

        suggestion_text = (
            f"Agent {trend.agent_name} received {count} complaints mentioning "
            f"'{keyword}' over {trend.window_days} days. Investigate and address "
            f"the root cause."
        )

        return ImprovementSuggestion(
            id=str(uuid.uuid4()),
            target=f"agent:{trend.agent_name}",
            issue_pattern=f"complaint:{keyword}",
            suggestion=suggestion_text,
            confidence=confidence,
            evidence=ImprovementEvidence(
                metrics={
                    "complaint_keyword": keyword,
                    "complaint_count": count,
                    "window_days": trend.window_days,
                }
            ),
        )

    def _create_closure_suggestion(
        self, metrics: ClosureMetrics
    ) -> ImprovementSuggestion | None:
        """Create a suggestion from closure SLA issues."""
        total = metrics.open_count + metrics.closed_count
        if total < 5:
            return None

        confidence = self._compute_confidence(
            evidence_count=total,
            consistency=metrics.overdue_count > 0,
            severity=(
                metrics.sla_compliance_rate is not None
                and metrics.sla_compliance_rate < 0.6
            ),
        )

        issues = []
        if metrics.overdue_count > 0:
            issues.append(f"{metrics.overdue_count} overdue tickets")
        if metrics.sla_compliance_rate is not None and metrics.sla_compliance_rate < 0.8:
            issues.append(f"{metrics.sla_compliance_rate:.0%} SLA compliance")

        suggestion_text = (
            f"Closure workflow has {', '.join(issues)} over {metrics.window_days} days. "
            f"Review SLA configuration and assignee workload."
        )

        return ImprovementSuggestion(
            id=str(uuid.uuid4()),
            target="kb",
            issue_pattern="closure_sla_violation",
            suggestion=suggestion_text,
            confidence=confidence,
            evidence=ImprovementEvidence(
                metrics={
                    "overdue_count": metrics.overdue_count,
                    "sla_compliance_rate": metrics.sla_compliance_rate,
                    "window_days": metrics.window_days,
                }
            ),
        )

    def _compute_confidence(
        self,
        evidence_count: int,
        consistency: bool,
        severity: bool,
    ) -> float:
        """Compute confidence score based on evidence.

        Args:
            evidence_count: Number of data points
            consistency: Whether pattern is consistent
            severity: Whether issue is severe

        Returns:
            Confidence score between 0 and 1
        """
        # Base confidence from evidence volume
        volume_score = min(evidence_count / 20.0, 0.4)  # Max 0.4 from volume

        # Consistency bonus
        consistency_score = 0.3 if consistency else 0.0

        # Severity bonus
        severity_score = 0.3 if severity else 0.0

        confidence = volume_score + consistency_score + severity_score
        return min(confidence, 1.0)

    def deduplicate(
        self, existing: list[ImprovementSuggestion], new: list[ImprovementSuggestion]
    ) -> list[ImprovementSuggestion]:
        """Deduplicate suggestions by (target, issue_pattern).

        If a suggestion with the same (target, issue_pattern) exists,
        merge evidence and keep the higher confidence.
        """
        indexed = {
            (s.target, s.issue_pattern): s for s in existing if s.status == "pending"
        }

        result = []
        for suggestion in new:
            key = (suggestion.target, suggestion.issue_pattern)
            if key in indexed:
                # Merge: keep higher confidence, combine evidence
                existing_suggestion = indexed[key]
                merged = self._merge_suggestions(existing_suggestion, suggestion)
                indexed[key] = merged
                result.append(merged)
            else:
                indexed[key] = suggestion
                result.append(suggestion)

        return result

    def _merge_suggestions(
        self,
        a: ImprovementSuggestion,
        b: ImprovementSuggestion,
    ) -> ImprovementSuggestion:
        """Merge two suggestions with the same (target, issue_pattern)."""
        # Keep higher confidence
        confidence = max(a.confidence, b.confidence)

        # Merge evidence
        merged_evidence = ImprovementEvidence(
            feedback_ids=list(set(a.evidence.feedback_ids + b.evidence.feedback_ids)),
            closure_ticket_ids=list(
                set(a.evidence.closure_ticket_ids + b.evidence.closure_ticket_ids)
            ),
            metrics={**a.evidence.metrics, **b.evidence.metrics},
        )

        return a.model_copy(
            update={
                "confidence": confidence,
                "evidence": merged_evidence,
                "updated_at": datetime.now(UTC),
            }
        )

    def accept(self, suggestion: ImprovementSuggestion) -> ImprovementSuggestion:
        """Mark a suggestion as accepted."""
        return suggestion.model_copy(
            update={
                "status": "accepted",
                "updated_at": datetime.now(UTC),
            }
        )

    def apply(
        self,
        suggestion: ImprovementSuggestion,
        note: str | None = None,
    ) -> ImprovementSuggestion:
        """Mark a suggestion as applied."""
        return suggestion.model_copy(
            update={
                "status": "applied",
                "applied_note": note,
                "updated_at": datetime.now(UTC),
            }
        )

    def dismiss(
        self,
        suggestion: ImprovementSuggestion,
        reason: str,
    ) -> ImprovementSuggestion:
        """Dismiss a suggestion with a reason."""
        return suggestion.model_copy(
            update={
                "status": "dismissed",
                "dismiss_reason": reason,
                "updated_at": datetime.now(UTC),
            }
        )

    async def enrich_with_llm(
        self,
        suggestions: list[ImprovementSuggestion],
    ) -> list[ImprovementSuggestion]:
        """Enrich suggestion text using an LLM call (one call per cycle, low token budget).

        Falls back to the original template text if the LLM call fails or no model
        is configured. This keeps the pipeline resilient while still producing
        natural-language suggestions when possible.

        Args:
            suggestions: Template-generated suggestions to enrich

        Returns:
            Suggestions with LLM-improved text, or originals on failure
        """
        if not suggestions or self._model_name is None:
            return suggestions

        try:
            from deerflow.models import create_chat_model

            model = create_chat_model(self._model_name)
        except Exception:
            logger.warning(
                "Failed to resolve model %s for LLM enrichment; using template text",
                self._model_name,
                exc_info=True,
            )
            return suggestions

        evidence_summary = self._build_evidence_summary(suggestions)
        prompt = (
            "You are an improvement advisor for an AI agent system. "
            "Based on the following analytics evidence, rewrite each suggestion "
            "as a concise, actionable recommendation (1-2 sentences each). "
            "Return one line per suggestion, prefixed with its index number.\n\n"
            f"{evidence_summary}\n\n"
            "Respond with only the rewritten suggestions, one per line."
        )

        try:
            response = await model.ainvoke(
                [{"role": "user", "content": prompt}],
                config={"max_tokens": 256, "run_name": "insights_llm_enrichment"},
            )
            lines = [
                line.strip()
                for line in response.content.strip().split("\n")
                if line.strip()
            ]

            enriched = []
            for i, suggestion in enumerate(suggestions):
                if i < len(lines):
                    text = lines[i]
                    # Strip leading index like "1." or "1)"
                    if text and text[0].isdigit():
                        text = text.lstrip("0123456789.) ").strip()
                    enriched.append(
                        suggestion.model_copy(update={"suggestion": text or suggestion.suggestion})
                    )
                else:
                    enriched.append(suggestion)

            logger.info("LLM enrichment applied to %d suggestions", len(enriched))
            return enriched

        except Exception:
            logger.warning(
                "LLM enrichment failed; falling back to template text",
                exc_info=True,
            )
            return suggestions

    def _build_evidence_summary(self, suggestions: list[ImprovementSuggestion]) -> str:
        """Build a compact evidence summary for the LLM prompt."""
        parts = []
        for i, s in enumerate(suggestions, 1):
            parts.append(
                f"{i}. Target: {s.target}, Pattern: {s.issue_pattern}, "
                f"Confidence: {s.confidence:.2f}, "
                f"Current suggestion: {s.suggestion}"
            )
        return "\n".join(parts)
