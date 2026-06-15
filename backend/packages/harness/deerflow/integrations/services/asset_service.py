"""Asset service for integration layer.

Provides high-level asset operations: catalog, context, and overview.
"""

import logging
from typing import Any

from deerflow.integrations.adapters.base import AuthContext
from deerflow.integrations.errors import IntegrationError
from deerflow.integrations.models.asset import AssetContext
from deerflow.integrations.models.overview import AssetOverview
from deerflow.integrations.models.queries import (
    AssetCatalogQuery,
    AssetContextQuery,
    AssetOverviewQuery,
)
from deerflow.integrations.routing import CapabilityRouter, ServiceResult

logger = logging.getLogger(__name__)


class AssetService:
    """Service layer for asset operations.

    Orchestrates capability calls through CapabilityRouter to provide
    high-level asset queries and composite overview aggregation.
    """

    def __init__(self, router: CapabilityRouter) -> None:
        self._router = router

    async def get_catalog(
        self,
        query: AssetCatalogQuery,
        auth_context: AuthContext,
    ) -> ServiceResult:
        """Get asset catalog with optional filtering.

        Args:
            query: Catalog query with filters (asset_type, status, search_text, etc.)
            auth_context: Authentication context for downstream calls

        Returns:
            ServiceResult containing tuple[Asset, ...]
        """
        logger.info("Getting asset catalog with filters: %s", query)
        return await self._router.route(
            capability_key="asset.catalog",
            query=query,
            auth_context=auth_context,
        )

    async def get_context(
        self,
        query: AssetContextQuery,
        auth_context: AuthContext,
    ) -> ServiceResult:
        """Get detailed context for a single asset.

        Args:
            query: Context query with asset_id and include flags
            auth_context: Authentication context for downstream calls

        Returns:
            ServiceResult containing AssetContext
        """
        logger.info("Getting asset context for: %s", query.asset_id)
        return await self._router.route(
            capability_key="asset.context",
            query=query,
            auth_context=auth_context,
        )

    async def get_overview(
        self,
        query: AssetOverviewQuery,
        auth_context: AuthContext,
    ) -> ServiceResult:
        """Get composite asset overview.

        Orchestrates multiple capability calls:
        1. asset.context - get asset structure and measurement points
        2. health.assessment - get health scores and risk items
        3. monitoring.alarm_history - get recent alarms

        Args:
            query: Overview query with asset_id and include flags
            auth_context: Authentication context for downstream calls

        Returns:
            ServiceResult containing AssetOverview with aggregated data
        """
        logger.info("Getting asset overview for: %s", query.asset_id)

        # Step 1: Get asset context (always needed)
        context_query = AssetContextQuery(
            tenant_id=query.tenant_id,
            asset_id=query.asset_id,
            include_children=True,
            include_measurement_points=True,
        )
        context_result = await self._router.route(
            capability_key="asset.context",
            query=context_query,
            auth_context=auth_context,
        )

        asset_context: AssetContext = context_result.data

        # Step 2: Get health assessment (if enabled)
        health_assessment = None
        if query.include_health_assessment:
            try:
                from deerflow.integrations.models.queries import HealthAssessmentQuery

                health_query = HealthAssessmentQuery(
                    tenant_id=query.tenant_id,
                    asset_id=query.asset_id,
                )
                health_result = await self._router.route(
                    capability_key="health.assessment",
                    query=health_query,
                    auth_context=auth_context,
                )
                health_assessment = health_result.data
            except IntegrationError as e:
                logger.warning(
                    "Failed to get health assessment for %s: %s",
                    query.asset_id,
                    e,
                )

        # Step 3: Get recent alarms (if enabled)
        recent_alarms: tuple[Any, ...] = ()
        if query.include_recent_alarms:
            try:
                from datetime import datetime, timedelta

                from deerflow.integrations.models.queries import AlarmHistoryQuery

                # Default to last 24 hours
                end_time = datetime.now()
                start_time = end_time - timedelta(hours=24)

                alarm_query = AlarmHistoryQuery(
                    tenant_id=query.tenant_id,
                    asset_id=query.asset_id,
                    start_time=start_time,
                    end_time=end_time,
                    limit=10,
                )
                alarm_result = await self._router.route(
                    capability_key="monitoring.alarm_history",
                    query=alarm_query,
                    auth_context=auth_context,
                )
                recent_alarms = alarm_result.data
            except IntegrationError as e:
                logger.warning(
                    "Failed to get alarm history for %s: %s",
                    query.asset_id,
                    e,
                )

        # Build composite overview
        overview = AssetOverview(
            asset=asset_context.asset,
            context=asset_context,
            health_assessment=health_assessment,
            recent_alarms=recent_alarms,
        )

        return ServiceResult(
            data=overview,
            source_system_keys=context_result.source_system_keys,
        )
