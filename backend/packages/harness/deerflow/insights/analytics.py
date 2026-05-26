"""Feedback analytics engine.

Aggregates feedback patterns from SQL FeedbackRepository by joining with
ThreadMetaRow (tenant isolation) and AgentUsageRow (agent correlation).
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.insights.models import FeedbackTrend, InsightAlert
from deerflow.persistence.agent.usage_model import AgentUsageRow
from deerflow.persistence.feedback.model import FeedbackRow
from deerflow.persistence.thread_meta.model import ThreadMetaRow

if TYPE_CHECKING:
    from deerflow.insights.cache import InsightsCache

STOP_WORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "was", "are", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "will", "would",
    "could", "should", "may", "might", "must", "shall", "can", "need",
    "it", "its", "this", "that", "these", "those", "i", "you", "he", "she",
    "we", "they", "me", "him", "her", "us", "them", "my", "your", "his",
    "our", "their", "not", "no", "yes",
}


class FeedbackAggregator:
    """Aggregates feedback patterns by agent with dual JOIN paths.

    Tenant isolation: FeedbackRow.thread_id → ThreadMetaRow.thread_id
    Agent correlation: FeedbackRow.run_id → AgentUsageRow.run_id (nullable)
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        cache: InsightsCache,
    ) -> None:
        self._sf = session_factory
        self._cache = cache

    async def aggregate(
        self,
        tenant_id: str,
        window_days: int = 30,
    ) -> list[FeedbackTrend]:
        """Aggregate feedback metrics per agent for a tenant.

        Args:
            tenant_id: Tenant to aggregate
            window_days: Time window (7 or 30 days typical)

        Returns:
            List of FeedbackTrend for each agent with feedback
        """
        cutoff = datetime.now(UTC) - timedelta(days=window_days)

        async with self._sf() as session:
            stmt = (
                select(
                    AgentUsageRow.agent_name,
                    func.count(FeedbackRow.feedback_id).label("total"),
                    func.sum(func.iif(FeedbackRow.rating == 1, 1, 0)).label("positive"),
                    func.sum(func.iif(FeedbackRow.rating == -1, 1, 0)).label("negative"),
                )
                .join(ThreadMetaRow, FeedbackRow.thread_id == ThreadMetaRow.thread_id)
                .outerjoin(AgentUsageRow, FeedbackRow.run_id == AgentUsageRow.run_id)
                .where(
                    ThreadMetaRow.tenant_id == tenant_id,
                    FeedbackRow.created_at >= cutoff,
                )
                .group_by(AgentUsageRow.agent_name)
            )
            result = await session.execute(stmt)
            rows = result.all()

        trends = []
        for agent_name, total, positive, negative in rows:
            agent_label = agent_name or "unknown"
            ratio = positive / total if total > 0 else 0.0
            trend_dir = self._compute_trend_direction(positive, negative)

            comments = await self._fetch_comments(
                tenant_id, agent_name, window_days
            )
            top_complaints = self._extract_keywords(comments)

            trend = FeedbackTrend(
                agent_name=agent_label,
                positive_count=positive or 0,
                negative_count=negative or 0,
                positive_ratio=ratio,
                trend_direction=trend_dir,
                window_days=window_days,
                top_complaints=top_complaints[:5],
            )
            trends.append(trend)

        self._cache.set(
            tenant_id,
            f"feedback_trends_{window_days}d",
            [t.model_dump(mode="json") for t in trends],
        )
        return trends

    def _compute_trend_direction(
        self, positive: int, negative: int
    ) -> str:
        """Determine trend direction from positive/negative counts."""
        if positive == 0 and negative == 0:
            return "stable"
        ratio = positive / (positive + negative) if (positive + negative) > 0 else 0.5
        if ratio >= 0.7:
            return "improving"
        elif ratio <= 0.3:
            return "declining"
        return "stable"

    async def _fetch_comments(
        self,
        tenant_id: str,
        agent_name: str | None,
        window_days: int,
    ) -> list[str]:
        """Fetch comment text for keyword extraction."""
        cutoff = datetime.now(UTC) - timedelta(days=window_days)

        async with self._sf() as session:
            stmt = (
                select(FeedbackRow.comment)
                .join(ThreadMetaRow, FeedbackRow.thread_id == ThreadMetaRow.thread_id)
                .outerjoin(AgentUsageRow, FeedbackRow.run_id == AgentUsageRow.run_id)
                .where(
                    ThreadMetaRow.tenant_id == tenant_id,
                    FeedbackRow.created_at >= cutoff,
                    FeedbackRow.comment.isnot(None),
                    FeedbackRow.comment != "",
                )
            )
            if agent_name:
                stmt = stmt.where(AgentUsageRow.agent_name == agent_name)
            else:
                stmt = stmt.where(AgentUsageRow.agent_name.is_(None))

            result = await session.execute(stmt)
            return [row[0] for row in result.all() if row[0]]

    def _extract_keywords(self, comments: list[str]) -> list[tuple[str, int]]:
        """Extract top keywords from comment text."""
        words: list[str] = []
        for comment in comments:
            tokens = re.findall(r"\b\w+\b", comment.lower())
            words.extend(t for t in tokens if t not in STOP_WORDS and len(t) > 2)

        counter = Counter(words)
        return counter.most_common(10)

    async def detect_clusters(
        self,
        tenant_id: str,
        threshold: int = 5,
        window_minutes: int = 60,
    ) -> list[InsightAlert]:
        """Detect negative feedback clusters within a time window.

        Args:
            tenant_id: Tenant to check
            threshold: Minimum negative count to trigger alert
            window_minutes: Time window for cluster detection

        Returns:
            List of InsightAlert for detected clusters
        """
        cutoff = datetime.now(UTC) - timedelta(minutes=window_minutes)

        async with self._sf() as session:
            stmt = (
                select(
                    AgentUsageRow.agent_name,
                    func.count(FeedbackRow.feedback_id).label("negative_count"),
                    func.group_concat(FeedbackRow.feedback_id).label("feedback_ids"),
                )
                .join(ThreadMetaRow, FeedbackRow.thread_id == ThreadMetaRow.thread_id)
                .outerjoin(AgentUsageRow, FeedbackRow.run_id == AgentUsageRow.run_id)
                .where(
                    ThreadMetaRow.tenant_id == tenant_id,
                    FeedbackRow.rating == -1,
                    FeedbackRow.created_at >= cutoff,
                )
                .group_by(AgentUsageRow.agent_name)
                .having(func.count(FeedbackRow.feedback_id) >= threshold)
            )
            result = await session.execute(stmt)
            rows = result.all()

        alerts = []
        for agent_name, count, ids_str in rows:
            agent_label = agent_name or "unknown"
            feedback_ids = ids_str.split(",") if ids_str else []

            alert = InsightAlert(
                agent_name=agent_label,
                alert_type="negative_cluster",
                negative_count=count,
                time_window_minutes=window_minutes,
                contributing_feedback_ids=feedback_ids,
            )
            alerts.append(alert)

        if alerts:
            self._cache.set(
                tenant_id,
                f"cluster_alerts_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}",
                [a.model_dump(mode="json") for a in alerts],
            )

        return alerts

    def get_skill_correlation_flag(self) -> dict[str, bool]:
        """Return metadata flag indicating skill dimension is deferred."""
        return {"skill_correlation_available": False}
