"""Monitoring service for integration layer.

Provides high-level monitoring operations: trend, waveform, orbit, and alarm history.
"""

import logging

from deerflow.integrations.adapters.base import AuthContext
from deerflow.integrations.models.queries import (
    AlarmHistoryQuery,
    OrbitQuery,
    TrendQuery,
    WaveformQuery,
)
from deerflow.integrations.routing import CapabilityRouter, ServiceResult

logger = logging.getLogger(__name__)


class MonitoringService:
    """Service layer for monitoring operations.

    Delegates capability calls through CapabilityRouter to provide
    high-level monitoring data queries.
    """

    def __init__(self, router: CapabilityRouter) -> None:
        self._router = router

    async def get_trend(
        self,
        query: TrendQuery,
        auth_context: AuthContext,
    ) -> ServiceResult:
        """Get trend data for a measurement point.

        Args:
            query: Trend query with asset_id, measurement_point_id, time range
            auth_context: Authentication context for downstream calls

        Returns:
            ServiceResult containing TrendSeries
        """
        logger.info(
            "Getting trend data for %s/%s",
            query.asset_id,
            query.measurement_point_id,
        )
        return await self._router.route(
            capability_key="monitoring.trend",
            query=query,
            auth_context=auth_context,
        )

    async def get_waveform(
        self,
        query: WaveformQuery,
        auth_context: AuthContext,
    ) -> ServiceResult:
        """Get waveform data for a measurement point.

        Args:
            query: Waveform query with asset_id, measurement_point_id
            auth_context: Authentication context for downstream calls

        Returns:
            ServiceResult containing WaveformData
        """
        logger.info(
            "Getting waveform data for %s/%s",
            query.asset_id,
            query.measurement_point_id,
        )
        return await self._router.route(
            capability_key="monitoring.waveform",
            query=query,
            auth_context=auth_context,
        )

    async def get_orbit(
        self,
        query: OrbitQuery,
        auth_context: AuthContext,
    ) -> ServiceResult:
        """Get orbit data for a measurement point.

        Args:
            query: Orbit query with asset_id, measurement_point_id
            auth_context: Authentication context for downstream calls

        Returns:
            ServiceResult containing OrbitData
        """
        logger.info(
            "Getting orbit data for %s/%s",
            query.asset_id,
            query.measurement_point_id,
        )
        return await self._router.route(
            capability_key="monitoring.orbit",
            query=query,
            auth_context=auth_context,
        )

    async def get_alarm_history(
        self,
        query: AlarmHistoryQuery,
        auth_context: AuthContext,
    ) -> ServiceResult:
        """Get alarm history for an asset.

        Args:
            query: Alarm history query with asset_id, time range, filters
            auth_context: Authentication context for downstream calls

        Returns:
            ServiceResult containing list[AlarmEvent]
        """
        logger.info("Getting alarm history for %s", query.asset_id)
        return await self._router.route(
            capability_key="monitoring.alarm_history",
            query=query,
            auth_context=auth_context,
        )
