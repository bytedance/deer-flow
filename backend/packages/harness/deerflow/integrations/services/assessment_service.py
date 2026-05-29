"""Assessment service for integration layer.

Provides high-level health assessment operations: health scores, anomaly statistics, and risk rankings.
"""

import logging

from deerflow.integrations.adapters.base import AuthContext
from deerflow.integrations.models.queries import (
    AnomalyStatsQuery,
    HealthAssessmentQuery,
    RiskRankingQuery,
)
from deerflow.integrations.routing import CapabilityRouter, ServiceResult

logger = logging.getLogger(__name__)


class AssessmentService:
    """Service layer for health assessment operations.

    Delegates capability calls through CapabilityRouter to provide
    high-level health assessment and risk analysis queries.
    """

    def __init__(self, router: CapabilityRouter) -> None:
        self._router = router

    async def get_health_assessment(
        self,
        query: HealthAssessmentQuery,
        auth_context: AuthContext,
    ) -> ServiceResult:
        """Get health assessment for an asset.

        Args:
            query: Health assessment query with asset_id
            auth_context: Authentication context for downstream calls

        Returns:
            ServiceResult containing HealthAssessment
        """
        logger.info("Getting health assessment for %s", query.asset_id)
        return await self._router.route(
            capability_key="health.assessment",
            query=query,
            auth_context=auth_context,
        )

    async def get_anomaly_statistics(
        self,
        query: AnomalyStatsQuery,
        auth_context: AuthContext,
    ) -> ServiceResult:
        """Get anomaly statistics for an asset.

        Args:
            query: Anomaly statistics query with asset_id, time range
            auth_context: Authentication context for downstream calls

        Returns:
            ServiceResult containing AnomalyStatistics
        """
        logger.info("Getting anomaly statistics for %s", query.asset_id)
        return await self._router.route(
            capability_key="health.anomaly_statistics",
            query=query,
            auth_context=auth_context,
        )

    async def get_risk_ranking(
        self,
        query: RiskRankingQuery,
        auth_context: AuthContext,
    ) -> ServiceResult:
        """Get risk ranking for assets.

        Args:
            query: Risk ranking query with filters and sorting options
            auth_context: Authentication context for downstream calls

        Returns:
            ServiceResult containing list[RiskRanking]
        """
        logger.info("Getting risk ranking")
        return await self._router.route(
            capability_key="health.risk_ranking",
            query=query,
            auth_context=auth_context,
        )
