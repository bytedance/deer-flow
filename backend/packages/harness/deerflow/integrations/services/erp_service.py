"""ERP service for integration layer.

Provides high-level ERP operations: work order, spare part, and inventory lookup.
"""

import logging

from deerflow.integrations.adapters.base import AuthContext
from deerflow.integrations.models.queries import (
    InventoryQuery,
    SparePartQuery,
    WorkOrderQuery,
)
from deerflow.integrations.routing import CapabilityRouter, ServiceResult

logger = logging.getLogger(__name__)


class ErpService:
    """Service layer for ERP operations.

    Delegates capability calls through CapabilityRouter to provide
    high-level work order, spare part, and inventory queries.
    """

    def __init__(self, router: CapabilityRouter) -> None:
        self._router = router

    async def get_work_orders(
        self,
        query: WorkOrderQuery,
        auth_context: AuthContext,
    ) -> ServiceResult:
        """Get work orders by asset, status, or date range.

        Args:
            query: Work order query with filters
            auth_context: Authentication context for downstream calls

        Returns:
            ServiceResult containing tuple[WorkOrder, ...]
        """
        logger.info("Getting work orders: asset_id=%s, status=%s", query.asset_id, query.status)
        return await self._router.route(
            capability_key="maintenance.get_work_orders",
            query=query,
            auth_context=auth_context,
        )

    async def get_work_order_detail(
        self,
        query: WorkOrderQuery,
        auth_context: AuthContext,
    ) -> ServiceResult:
        """Get single work order detail with parts usage.

        Args:
            query: Work order query with work_order_id
            auth_context: Authentication context for downstream calls

        Returns:
            ServiceResult containing tuple[WorkOrder, ...]
        """
        logger.info("Getting work order detail: %s", query.work_order_id)
        return await self._router.route(
            capability_key="maintenance.get_work_order_detail",
            query=query,
            auth_context=auth_context,
        )

    async def get_parts(
        self,
        query: SparePartQuery,
        auth_context: AuthContext,
    ) -> ServiceResult:
        """Search spare parts by category, name, or part number.

        Args:
            query: Spare part query with filters
            auth_context: Authentication context for downstream calls

        Returns:
            ServiceResult containing tuple[SparePart, ...]
        """
        logger.info("Getting spare parts: category=%s", query.category)
        return await self._router.route(
            capability_key="inventory.get_parts",
            query=query,
            auth_context=auth_context,
        )

    async def get_part_detail(
        self,
        query: SparePartQuery,
        auth_context: AuthContext,
    ) -> ServiceResult:
        """Get spare part detail with inventory levels.

        Args:
            query: Spare part query with part_id
            auth_context: Authentication context for downstream calls

        Returns:
            ServiceResult containing tuple[SparePart, ...]
        """
        logger.info("Getting spare part detail: %s", query.part_id)
        return await self._router.route(
            capability_key="inventory.get_part_detail",
            query=query,
            auth_context=auth_context,
        )

    async def check_availability(
        self,
        query: InventoryQuery,
        auth_context: AuthContext,
    ) -> ServiceResult:
        """Check part availability across warehouses.

        Args:
            query: Inventory query with part_id and optional warehouse
            auth_context: Authentication context for downstream calls

        Returns:
            ServiceResult containing tuple[InventoryItem, ...]
        """
        logger.info("Checking inventory availability: part_id=%s", query.part_id)
        return await self._router.route(
            capability_key="inventory.check_availability",
            query=query,
            auth_context=auth_context,
        )
