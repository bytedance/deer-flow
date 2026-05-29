"""Xiaoshouyi (销售易) service for integration layer.

Provides high-level operations for querying product outbound details
and service event records.
"""

import logging

from deerflow.integrations.adapters.base import AuthContext
from deerflow.integrations.models.queries import OutboundDetailQuery, ServiceEventQuery
from deerflow.integrations.routing import CapabilityRouter, ServiceResult

logger = logging.getLogger(__name__)


class XsyService:
    """Service layer for Xiaoshouyi CRM operations.

    Delegates capability calls through CapabilityRouter.
    """

    def __init__(self, router: CapabilityRouter) -> None:
        self._router = router

    async def query_outbound(
        self,
        query: OutboundDetailQuery,
        auth_context: AuthContext,
    ) -> ServiceResult:
        """Query product outbound details."""
        logger.info("Querying outbound details (tenant=%s)", query.tenant_id)
        return await self._router.route(
            capability_key="outbound.query",
            query=query,
            auth_context=auth_context,
        )

    async def get_outbound_statistics(
        self,
        query: OutboundDetailQuery,
        auth_context: AuthContext,
    ) -> ServiceResult:
        """Get outbound statistics."""
        logger.info("Getting outbound statistics (tenant=%s)", query.tenant_id)
        return await self._router.route(
            capability_key="outbound.statistics",
            query=query,
            auth_context=auth_context,
        )

    async def query_service_events(
        self,
        query: ServiceEventQuery,
        auth_context: AuthContext,
    ) -> ServiceResult:
        """Query service event details."""
        logger.info("Querying service events (tenant=%s)", query.tenant_id)
        return await self._router.route(
            capability_key="service_event.query",
            query=query,
            auth_context=auth_context,
        )

    async def get_service_event_statistics(
        self,
        query: ServiceEventQuery,
        auth_context: AuthContext,
    ) -> ServiceResult:
        """Get service event statistics."""
        logger.info("Getting service event statistics (tenant=%s)", query.tenant_id)
        return await self._router.route(
            capability_key="service_event.statistics",
            query=query,
            auth_context=auth_context,
        )

    async def detect_event_anomalies(
        self,
        query: ServiceEventQuery,
        auth_context: AuthContext,
    ) -> ServiceResult:
        """Detect service event anomalies."""
        logger.info("Detecting event anomalies (tenant=%s)", query.tenant_id)
        return await self._router.route(
            capability_key="service_event.anomaly",
            query=query,
            auth_context=auth_context,
        )

    async def generate_report(
        self,
        query: OutboundDetailQuery,
        auth_context: AuthContext,
    ) -> ServiceResult:
        """Generate cross-table report data."""
        logger.info("Generating XSY report (tenant=%s)", query.tenant_id)
        return await self._router.route(
            capability_key="xsy.report",
            query=query,
            auth_context=auth_context,
        )
