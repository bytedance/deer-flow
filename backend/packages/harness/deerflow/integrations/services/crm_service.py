"""CRM service for integration layer.

Provides high-level CRM operations: customer profile, contract, and service object lookup.
"""

import logging

from deerflow.integrations.adapters.base import AuthContext
from deerflow.integrations.models.queries import (
    ContractQuery,
    CustomerProfileQuery,
    ServiceObjectQuery,
)
from deerflow.integrations.routing import CapabilityRouter, ServiceResult

logger = logging.getLogger(__name__)


class CrmService:
    """Service layer for CRM operations.

    Delegates capability calls through CapabilityRouter to provide
    high-level customer, contract, and service object queries.
    """

    def __init__(self, router: CapabilityRouter) -> None:
        self._router = router

    async def get_customer_profile(
        self,
        query: CustomerProfileQuery,
        auth_context: AuthContext,
    ) -> ServiceResult:
        """Get customer profile by ID or search criteria.

        Args:
            query: Customer profile query with customer_id
            auth_context: Authentication context for downstream calls

        Returns:
            ServiceResult containing tuple[CustomerProfile, ...]
        """
        logger.info("Getting customer profile: %s", query.customer_id)
        return await self._router.route(
            capability_key="customer.get_profile",
            query=query,
            auth_context=auth_context,
        )

    async def search_customers(
        self,
        query: CustomerProfileQuery,
        auth_context: AuthContext,
    ) -> ServiceResult:
        """Search customers by name, industry, or region.

        Args:
            query: Customer profile query with search_text, industry, or region
            auth_context: Authentication context for downstream calls

        Returns:
            ServiceResult containing tuple[CustomerProfile, ...]
        """
        logger.info("Searching customers: %s", query.search_text)
        return await self._router.route(
            capability_key="customer.search",
            query=query,
            auth_context=auth_context,
        )

    async def get_contract_detail(
        self,
        query: ContractQuery,
        auth_context: AuthContext,
    ) -> ServiceResult:
        """Get contract details by contract ID.

        Args:
            query: Contract query with contract_id
            auth_context: Authentication context for downstream calls

        Returns:
            ServiceResult containing tuple[Contract, ...]
        """
        logger.info("Getting contract detail: %s", query.contract_id)
        return await self._router.route(
            capability_key="contract.get_detail",
            query=query,
            auth_context=auth_context,
        )

    async def list_contracts_by_customer(
        self,
        query: ContractQuery,
        auth_context: AuthContext,
    ) -> ServiceResult:
        """List all contracts for a customer.

        Args:
            query: Contract query with customer_id
            auth_context: Authentication context for downstream calls

        Returns:
            ServiceResult containing tuple[Contract, ...]
        """
        logger.info("Listing contracts for customer: %s", query.customer_id)
        return await self._router.route(
            capability_key="contract.list_by_customer",
            query=query,
            auth_context=auth_context,
        )

    async def get_service_object_detail(
        self,
        query: ServiceObjectQuery,
        auth_context: AuthContext,
    ) -> ServiceResult:
        """Get service object details.

        Args:
            query: Service object query with service_object_id
            auth_context: Authentication context for downstream calls

        Returns:
            ServiceResult containing tuple[ServiceObject, ...]
        """
        logger.info("Getting service object detail: %s", query.service_object_id)
        return await self._router.route(
            capability_key="service_object.get_detail",
            query=query,
            auth_context=auth_context,
        )

    async def list_service_objects_by_customer(
        self,
        query: ServiceObjectQuery,
        auth_context: AuthContext,
    ) -> ServiceResult:
        """List service objects for a customer.

        Args:
            query: Service object query with customer_id
            auth_context: Authentication context for downstream calls

        Returns:
            ServiceResult containing tuple[ServiceObject, ...]
        """
        logger.info("Listing service objects for customer: %s", query.customer_id)
        return await self._router.route(
            capability_key="service_object.list_by_customer",
            query=query,
            auth_context=auth_context,
        )
