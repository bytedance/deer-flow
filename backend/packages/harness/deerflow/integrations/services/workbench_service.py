"""Workbench service for integration layer.

Provides high-level operations for querying workbench todo statistics.
"""

import logging

from deerflow.integrations.adapters.base import AuthContext
from deerflow.integrations.routing import CapabilityRouter, ServiceResult

logger = logging.getLogger(__name__)


class WorkbenchService:
    """Service layer for 服务平台 (workbench) operations.

    Delegates capability calls through CapabilityRouter.
    """

    def __init__(self, router: CapabilityRouter) -> None:
        self._router = router

    async def get_todo_stats(
        self,
        auth_context: AuthContext,
    ) -> ServiceResult:
        """Fetch workbench todo statistics (anomaly/startup/shutdown pending counts)."""
        logger.info("Getting todo stats (tenant=%s)", auth_context.tenant_id)
        return await self._router.route(
            capability_key="todo_stats.get",
            query=None,
            auth_context=auth_context,
        )
