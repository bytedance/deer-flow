"""Insights subsystem — closes the feedback loop.

This package transforms collected feedback and closure data into actionable
improvements that flow back into the agent system:

- **Analytics**: Aggregate feedback patterns by agent, detect negative clusters
- **Knowledge Extraction**: Convert verified closure resolutions into KB entries
- **Improvement Engine**: Generate ranked improvement suggestions
- **Memory Integration**: Feed improvements into agent memory for adaptive behavior
"""

from deerflow.insights.cache import InsightsCache, JsonFileInsightsCache
from deerflow.insights.models import (
    ClosureMetrics,
    FeedbackTrend,
    ImprovementEvidence,
    ImprovementSuggestion,
    InsightAlert,
    KBCandidate,
)
from deerflow.insights.permissions import (
    INSIGHTS_PERMISSIONS,
    INSIGHTS_READ,
    INSIGHTS_WRITE,
)

__all__ = [
    "ClosureMetrics",
    "FeedbackTrend",
    "ImprovementEvidence",
    "ImprovementSuggestion",
    "InsightAlert",
    "InsightsCache",
    "JsonFileInsightsCache",
    "KBCandidate",
    "INSIGHTS_PERMISSIONS",
    "INSIGHTS_READ",
    "INSIGHTS_WRITE",
]
