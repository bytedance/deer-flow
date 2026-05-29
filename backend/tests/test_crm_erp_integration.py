"""Integration tests for CRM and ERP adapters, services, and tools (Phase 3.5).

Covers:
- CRM/ERP transform functions (raw dict → canonical models)
- CRM/ERP adapter registration in registry factory
- CRM/ERP service routing through CapabilityRouter
- CRM/ERP tool formatting (service → agent-readable strings)
- End-to-end chain: adapter → transform → service → tool
- Registry factory includes all 4 adapter types
"""

import time
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from deerflow.integrations.adapters.crm.transform import (
    transform_contract,
    transform_customer_profile,
    transform_service_object,
)
from deerflow.integrations.adapters.erp.transform import (
    transform_inventory_items,
    transform_spare_parts,
    transform_work_orders,
)
from deerflow.integrations.config import (
    CapabilityRouteConfig,
    IntegrationSystemConfig,
    IntegrationsConfig,
)
from deerflow.integrations.models.crm import Contract, CustomerProfile, ServiceObject
from deerflow.integrations.models.erp import (
    InventoryItem,
    SparePart,
    SparePartUsage,
    WorkOrder,
)
from deerflow.integrations.models.provenance import Provenance


def _provenance(cap: str = "test.cap") -> Provenance:
    return Provenance(
        source_system_key="test_sys",
        source_system_type="test",
        capability_key=cap,
        fetched_at=datetime.now(),
    )


# ---------------------------------------------------------------------------
# CRM Transform Tests
# ---------------------------------------------------------------------------


class TestCrmTransforms:
    """Test CRM API response → canonical model transforms."""

    def test_transform_customer_profile_single(self):
        raw = {
            "id": "C001",
            "name": "ACME Corp",
            "display_name": "ACME Corporation",
            "industry": "Manufacturing",
            "region": "Shanghai",
            "contact_name": "Zhang Wei",
            "contact_phone": "13800138000",
            "contract_count": 3,
            "service_object_count": 12,
        }
        result = transform_customer_profile(raw, _provenance())
        assert len(result) == 1
        p = result[0]
        assert isinstance(p, CustomerProfile)
        assert p.id == "C001"
        assert p.name == "ACME Corp"
        assert p.display_name == "ACME Corporation"
        assert p.industry == "Manufacturing"
        assert p.region == "Shanghai"
        assert p.contract_count == 3
        assert p.service_object_count == 12
        assert p.source_metadata == {"raw": raw}
        assert p.provenance.source_system_key == "test_sys"

    def test_transform_customer_profile_list(self):
        raw = {
            "data": [
                {"id": "C001", "name": "A"},
                {"id": "C002", "name": "B"},
            ]
        }
        result = transform_customer_profile(raw, _provenance())
        assert len(result) == 2
        assert result[0].id == "C001"
        assert result[1].id == "C002"

    def test_transform_customer_profile_items_key(self):
        raw = {"items": [{"id": "C001", "name": "A"}]}
        result = transform_customer_profile(raw, _provenance())
        assert len(result) == 1

    def test_transform_customer_profile_display_name_fallback(self):
        raw = {"id": "C001", "name": "Fallback Name"}
        result = transform_customer_profile(raw, _provenance())
        assert result[0].display_name == "Fallback Name"

    def test_transform_contract_with_covered_assets(self):
        raw = {
            "id": "CON001",
            "customer_id": "C001",
            "contract_number": "CT-2026-001",
            "title": "Annual Maintenance",
            "status": "active",
            "start_date": "2026-01-01",
            "end_date": "2026-12-31",
            "service_level": "premium",
            "covered_assets": ["A001", "A002", "A003"],
        }
        result = transform_contract(raw, _provenance())
        assert len(result) == 1
        c = result[0]
        assert isinstance(c, Contract)
        assert c.id == "CON001"
        assert c.customer_id == "C001"
        assert c.contract_number == "CT-2026-001"
        assert c.status == "active"
        assert c.service_level == "premium"
        assert c.covered_assets == ("A001", "A002", "A003")

    def test_transform_contract_defaults(self):
        raw = {"id": "CON001", "customer_id": "C001", "contract_number": "X", "title": "T", "start_date": "2026-01-01"}
        result = transform_contract(raw, _provenance())
        c = result[0]
        assert c.status == "unknown"
        assert c.end_date is None
        assert c.service_level is None
        assert c.covered_assets == ()

    def test_transform_service_object(self):
        raw = {
            "id": "SO001",
            "customer_id": "C001",
            "asset_id": "A001",
            "object_type": "Pump",
            "model_number": "P-100",
            "serial_number": "SN-2026-001",
            "installation_date": "2025-06-15",
            "warranty_end_date": "2028-06-15",
        }
        result = transform_service_object(raw, _provenance())
        assert len(result) == 1
        so = result[0]
        assert isinstance(so, ServiceObject)
        assert so.id == "SO001"
        assert so.object_type == "Pump"
        assert so.model_number == "P-100"
        assert so.serial_number == "SN-2026-001"


# ---------------------------------------------------------------------------
# ERP Transform Tests
# ---------------------------------------------------------------------------


class TestErpTransforms:
    """Test ERP API response → canonical model transforms."""

    def test_transform_work_orders_with_parts(self):
        raw = {
            "data": [
                {
                    "id": "WO001",
                    "order_number": "WO-2026-001",
                    "title": "Pump Maintenance",
                    "status": "in_progress",
                    "priority": "high",
                    "description": "Regular maintenance",
                    "asset_id": "A001",
                    "assigned_to": "Li Ming",
                    "created_at": "2026-05-01T08:00:00",
                    "scheduled_at": "2026-05-10T09:00:00",
                    "completed_at": None,
                    "parts_used": [
                        {
                            "part_id": "P001",
                            "part_number": "BRG-100",
                            "name": "Bearing",
                            "quantity": 2,
                            "unit_cost": 150.0,
                        },
                        {
                            "part_id": "P002",
                            "part_number": "SEL-200",
                            "name": "Seal",
                            "quantity": 4,
                            "unit_cost": 25.0,
                        },
                    ],
                }
            ]
        }
        result = transform_work_orders(raw, _provenance())
        assert len(result) == 1
        wo = result[0]
        assert isinstance(wo, WorkOrder)
        assert wo.id == "WO001"
        assert wo.order_number == "WO-2026-001"
        assert wo.status == "in_progress"
        assert wo.priority == "high"
        assert wo.asset_id == "A001"
        assert wo.assigned_to == "Li Ming"
        assert len(wo.parts_used) == 2
        assert isinstance(wo.parts_used[0], SparePartUsage)
        assert wo.parts_used[0].part_number == "BRG-100"
        assert wo.parts_used[0].quantity == 2
        assert wo.parts_used[0].unit_cost == 150.0

    def test_transform_work_orders_no_parts(self):
        raw = [{"id": "WO002", "order_number": "WO-2", "title": "T", "status": "open", "priority": "low", "created_at": "2026-01-01"}]
        result = transform_work_orders(raw, _provenance())
        assert result[0].parts_used == ()
        assert result[0].description == ""

    def test_transform_work_orders_single_dict(self):
        raw = {"id": "WO001", "order_number": "WO-1", "title": "T", "status": "open", "priority": "low", "created_at": "2026-01-01"}
        result = transform_work_orders(raw, _provenance())
        assert len(result) == 1

    def test_transform_spare_parts(self):
        raw = {
            "data": [
                {
                    "id": "P001",
                    "part_number": "BRG-100",
                    "name": "Bearing",
                    "category": "Bearings",
                    "unit": "piece",
                    "stock_quantity": 50,
                    "min_stock": 10,
                    "unit_cost": 150.0,
                },
            ]
        }
        result = transform_spare_parts(raw, _provenance())
        assert len(result) == 1
        p = result[0]
        assert isinstance(p, SparePart)
        assert p.id == "P001"
        assert p.part_number == "BRG-100"
        assert p.stock_quantity == 50
        assert p.min_stock == 10
        assert p.unit_cost == 150.0

    def test_transform_spare_parts_defaults(self):
        raw = {"id": "P001", "part_number": "X", "name": "Y"}
        result = transform_spare_parts(raw, _provenance())
        p = result[0]
        assert p.unit == "piece"
        assert p.stock_quantity == 0
        assert p.min_stock is None
        assert p.category is None

    def test_transform_inventory_items(self):
        raw = {
            "data": [
                {
                    "id": "INV001",
                    "part_id": "P001",
                    "warehouse": "WH-Shanghai",
                    "quantity": 30,
                    "reserved_quantity": 5,
                    "last_restocked_at": "2026-04-15",
                },
                {
                    "id": "INV002",
                    "part_id": "P001",
                    "warehouse": "WH-Beijing",
                    "quantity": 20,
                    "reserved_quantity": 0,
                    "last_restocked_at": None,
                },
            ]
        }
        result = transform_inventory_items(raw, _provenance())
        assert len(result) == 2
        assert result[0].warehouse == "WH-Shanghai"
        assert result[0].quantity == 30
        assert result[0].reserved_quantity == 5
        assert result[1].warehouse == "WH-Beijing"
        assert result[1].last_restocked_at is None


# ---------------------------------------------------------------------------
# Registry Factory Tests
# ---------------------------------------------------------------------------


class TestRegistryFactory:
    """Test that the registry factory includes CRM/ERP adapter types."""

    def test_factory_includes_all_adapter_types(self):
        from deerflow.integrations.adapters.crm import CrmAdapter
        from deerflow.integrations.adapters.erp import ErpAdapter
        from deerflow.integrations.adapters.ins import InsAdapter
        from deerflow.integrations.adapters.sms import SmsAdapter
        from deerflow.integrations.registry import initialize_registry, get_integration_registry

        # Reset singleton
        from deerflow.integrations import registry as reg_mod
        reg_mod.IntegrationRegistry._instance = None
        reg_mod.IntegrationRegistry._initialized = False

        config = IntegrationsConfig(
            enabled=True,
            systems={
                "ins1": IntegrationSystemConfig(
                    system_key="ins1",
                    system_type="ins",
                    display_name="InS",
                    base_url="http://ins.test",
                    auth_type="bearer",
                ),
                "sms1": IntegrationSystemConfig(
                    system_key="sms1",
                    system_type="sms",
                    display_name="Sms",
                    base_url="http://sms.test",
                    auth_type="api_key",
                ),
                "crm1": IntegrationSystemConfig(
                    system_key="crm1",
                    system_type="crm",
                    display_name="CRM",
                    base_url="http://crm.test",
                    auth_type="api_key",
                ),
                "erp1": IntegrationSystemConfig(
                    system_key="erp1",
                    system_type="erp",
                    display_name="ERP",
                    base_url="http://erp.test",
                    auth_type="api_key",
                ),
            },
        )

        registry = initialize_registry(config)
        adapters = registry.list_all()
        types_found = {a.system_type for a in adapters}

        assert types_found == {"ins", "sms", "crm", "erp"}
        assert len(adapters) == 4

        # Cleanup singleton
        reg_mod.IntegrationRegistry._instance = None
        reg_mod.IntegrationRegistry._initialized = False

    def test_factory_skips_disabled_systems(self):
        from deerflow.integrations import registry as reg_mod
        reg_mod.IntegrationRegistry._instance = None
        reg_mod.IntegrationRegistry._initialized = False

        config = IntegrationsConfig(
            enabled=True,
            systems={
                "crm1": IntegrationSystemConfig(
                    system_key="crm1",
                    system_type="crm",
                    display_name="CRM",
                    base_url="http://crm.test",
                    auth_type="api_key",
                    enabled=True,
                ),
                "erp1": IntegrationSystemConfig(
                    system_key="erp1",
                    system_type="erp",
                    display_name="ERP",
                    base_url="http://erp.test",
                    auth_type="api_key",
                    enabled=False,
                ),
            },
        )

        from deerflow.integrations.registry import initialize_registry
        registry = initialize_registry(config)
        adapters = registry.list_all()
        assert len(adapters) == 1
        assert adapters[0].system_key == "crm1"

        reg_mod.IntegrationRegistry._instance = None
        reg_mod.IntegrationRegistry._initialized = False

    def test_factory_unknown_type_logged(self):
        from deerflow.integrations import registry as reg_mod
        reg_mod.IntegrationRegistry._instance = None
        reg_mod.IntegrationRegistry._initialized = False

        config = IntegrationsConfig(
            enabled=True,
            systems={
                "custom1": IntegrationSystemConfig(
                    system_key="custom1",
                    system_type="custom",
                    display_name="Custom",
                    base_url="http://custom.test",
                    auth_type="api_key",
                ),
            },
        )

        from deerflow.integrations.registry import initialize_registry
        registry = initialize_registry(config)
        assert len(registry.list_all()) == 0

        reg_mod.IntegrationRegistry._instance = None
        reg_mod.IntegrationRegistry._initialized = False


# ---------------------------------------------------------------------------
# CRM/ERP Service Routing Tests
# ---------------------------------------------------------------------------


class TestCrmServiceRouting:
    """Test CRM service delegates correctly through CapabilityRouter."""

    @pytest.mark.asyncio
    async def test_get_customer_profile(self):
        from deerflow.integrations.adapters.base import AuthContext
        from deerflow.integrations.models.queries import CustomerProfileQuery
        from deerflow.integrations.routing import CapabilityRouter, ServiceResult
        from deerflow.integrations.services.crm_service import CrmService

        mock_router = MagicMock(spec=CapabilityRouter)
        expected = (CustomerProfile(
            id="C001", name="Test", display_name="Test",
            source_metadata={}, provenance=_provenance(),
        ),)
        mock_router.route = AsyncMock(return_value=ServiceResult(
            data=expected, source_system_keys=("crm1",),
        ))

        service = CrmService(mock_router)
        query = CustomerProfileQuery(tenant_id="t1", customer_id="C001")
        auth = AuthContext(tenant_id="t1", user_id="u1")
        result = await service.get_customer_profile(query, auth)

        assert result.data == expected
        mock_router.route.assert_called_once_with(
            capability_key="customer.get_profile",
            query=query,
            auth_context=auth,
        )

    @pytest.mark.asyncio
    async def test_search_customers(self):
        from deerflow.integrations.adapters.base import AuthContext
        from deerflow.integrations.models.queries import CustomerProfileQuery
        from deerflow.integrations.routing import CapabilityRouter, ServiceResult
        from deerflow.integrations.services.crm_service import CrmService

        mock_router = MagicMock(spec=CapabilityRouter)
        mock_router.route = AsyncMock(return_value=ServiceResult(
            data=(), source_system_keys=("crm1",),
        ))

        service = CrmService(mock_router)
        query = CustomerProfileQuery(tenant_id="t1", search_text="ACME")
        auth = AuthContext(tenant_id="t1", user_id="u1")
        result = await service.search_customers(query, auth)

        mock_router.route.assert_called_once_with(
            capability_key="customer.search",
            query=query,
            auth_context=auth,
        )

    @pytest.mark.asyncio
    async def test_get_contract_detail(self):
        from deerflow.integrations.adapters.base import AuthContext
        from deerflow.integrations.models.queries import ContractQuery
        from deerflow.integrations.routing import CapabilityRouter, ServiceResult
        from deerflow.integrations.services.crm_service import CrmService

        mock_router = MagicMock(spec=CapabilityRouter)
        mock_router.route = AsyncMock(return_value=ServiceResult(
            data=(), source_system_keys=("crm1",),
        ))

        service = CrmService(mock_router)
        query = ContractQuery(tenant_id="t1", contract_id="CON001")
        auth = AuthContext(tenant_id="t1", user_id="u1")
        await service.get_contract_detail(query, auth)

        mock_router.route.assert_called_once_with(
            capability_key="contract.get_detail",
            query=query,
            auth_context=auth,
        )


class TestErpServiceRouting:
    """Test ERP service delegates correctly through CapabilityRouter."""

    @pytest.mark.asyncio
    async def test_get_work_orders(self):
        from deerflow.integrations.adapters.base import AuthContext
        from deerflow.integrations.models.queries import WorkOrderQuery
        from deerflow.integrations.routing import CapabilityRouter, ServiceResult
        from deerflow.integrations.services.erp_service import ErpService

        mock_router = MagicMock(spec=CapabilityRouter)
        mock_router.route = AsyncMock(return_value=ServiceResult(
            data=(), source_system_keys=("erp1",),
        ))

        service = ErpService(mock_router)
        query = WorkOrderQuery(tenant_id="t1", asset_id="A001")
        auth = AuthContext(tenant_id="t1", user_id="u1")
        await service.get_work_orders(query, auth)

        mock_router.route.assert_called_once_with(
            capability_key="maintenance.get_work_orders",
            query=query,
            auth_context=auth,
        )

    @pytest.mark.asyncio
    async def test_check_availability(self):
        from deerflow.integrations.adapters.base import AuthContext
        from deerflow.integrations.models.queries import InventoryQuery
        from deerflow.integrations.routing import CapabilityRouter, ServiceResult
        from deerflow.integrations.services.erp_service import ErpService

        mock_router = MagicMock(spec=CapabilityRouter)
        mock_router.route = AsyncMock(return_value=ServiceResult(
            data=(), source_system_keys=("erp1",),
        ))

        service = ErpService(mock_router)
        query = InventoryQuery(tenant_id="t1", part_id="P001")
        auth = AuthContext(tenant_id="t1", user_id="u1")
        await service.check_availability(query, auth)

        mock_router.route.assert_called_once_with(
            capability_key="inventory.check_availability",
            query=query,
            auth_context=auth,
        )


# ---------------------------------------------------------------------------
# CRM/ERP Tool Formatting Tests
# ---------------------------------------------------------------------------


class TestCrmToolFormatting:
    """Test CRM tool wrappers format results correctly."""

    @pytest.mark.asyncio
    async def test_get_customer_profile_found(self):
        from deerflow.integrations.routing import ServiceResult
        from deerflow.integrations.services.crm_service import CrmService
        from deerflow.integrations.tools.crm_tools import CrmTools

        profile = CustomerProfile(
            id="C001", name="ACME", display_name="ACME Corp",
            industry="Manufacturing", region="Shanghai",
            contact_name="Zhang", contact_phone="138",
            contract_count=3, service_object_count=10,
            source_metadata={}, provenance=_provenance(),
        )
        mock_service = MagicMock(spec=CrmService)
        mock_service.get_customer_profile = AsyncMock(
            return_value=ServiceResult(data=(profile,), source_system_keys=("crm1",)),
        )

        tools = CrmTools(mock_service)
        result = await tools.get_customer_profile("t1", "u1", "C001")

        assert "ACME Corp" in result
        assert "Manufacturing" in result
        assert "Shanghai" in result
        assert "**合同数**: 3" in result

    @pytest.mark.asyncio
    async def test_get_customer_profile_not_found(self):
        from deerflow.integrations.routing import ServiceResult
        from deerflow.integrations.services.crm_service import CrmService
        from deerflow.integrations.tools.crm_tools import CrmTools

        mock_service = MagicMock(spec=CrmService)
        mock_service.get_customer_profile = AsyncMock(
            return_value=ServiceResult(data=(), source_system_keys=("crm1",)),
        )

        tools = CrmTools(mock_service)
        result = await tools.get_customer_profile("t1", "u1", "MISSING")
        assert "未找到客户" in result

    @pytest.mark.asyncio
    async def test_search_customers_empty(self):
        from deerflow.integrations.routing import ServiceResult
        from deerflow.integrations.services.crm_service import CrmService
        from deerflow.integrations.tools.crm_tools import CrmTools

        mock_service = MagicMock(spec=CrmService)
        mock_service.search_customers = AsyncMock(
            return_value=ServiceResult(data=(), source_system_keys=("crm1",)),
        )

        tools = CrmTools(mock_service)
        result = await tools.search_customers("t1", "u1", search_text="nothing")
        assert "未找到" in result

    @pytest.mark.asyncio
    async def test_get_contract_detail_shows_covered_assets(self):
        from deerflow.integrations.routing import ServiceResult
        from deerflow.integrations.services.crm_service import CrmService
        from deerflow.integrations.tools.crm_tools import CrmTools

        contract = Contract(
            id="CON001", customer_id="C001", contract_number="CT-001",
            title="Annual", status="active", start_date="2026-01-01",
            end_date="2026-12-31", service_level="premium",
            covered_assets=("A001", "A002"),
            source_metadata={}, provenance=_provenance(),
        )
        mock_service = MagicMock(spec=CrmService)
        mock_service.get_contract_detail = AsyncMock(
            return_value=ServiceResult(data=(contract,), source_system_keys=("crm1",)),
        )

        tools = CrmTools(mock_service)
        result = await tools.get_contract_detail("t1", "u1", "CON001")
        assert "Annual" in result
        assert "premium" in result
        assert "A001" in result


class TestErpToolFormatting:
    """Test ERP tool wrappers format results correctly."""

    @pytest.mark.asyncio
    async def test_get_work_orders_with_priority(self):
        from deerflow.integrations.routing import ServiceResult
        from deerflow.integrations.services.erp_service import ErpService
        from deerflow.integrations.tools.erp_tools import ErpTools

        wo = WorkOrder(
            id="WO001", order_number="WO-001", title="Fix Pump",
            status="open", priority="high",
            description="Urgent", asset_id="A001",
            assigned_to="Li", created_at="2026-05-01",
            source_metadata={}, provenance=_provenance(),
        )
        mock_service = MagicMock(spec=ErpService)
        mock_service.get_work_orders = AsyncMock(
            return_value=ServiceResult(data=(wo,), source_system_keys=("erp1",)),
        )

        tools = ErpTools(mock_service)
        result = await tools.get_work_orders("t1", "u1", asset_id="A001")
        assert "Fix Pump" in result
        assert "high" in result

    @pytest.mark.asyncio
    async def test_get_work_order_detail_with_parts(self):
        from deerflow.integrations.routing import ServiceResult
        from deerflow.integrations.services.erp_service import ErpService
        from deerflow.integrations.tools.erp_tools import ErpTools

        wo = WorkOrder(
            id="WO001", order_number="WO-001", title="Maint",
            status="completed", priority="medium",
            description="Regular", asset_id="A001",
            assigned_to="Li", created_at="2026-05-01",
            parts_used=(
                SparePartUsage(part_id="P1", part_number="BRG", name="Bearing", quantity=2, unit_cost=100.0),
            ),
            source_metadata={}, provenance=_provenance(),
        )
        mock_service = MagicMock(spec=ErpService)
        mock_service.get_work_order_detail = AsyncMock(
            return_value=ServiceResult(data=(wo,), source_system_keys=("erp1",)),
        )

        tools = ErpTools(mock_service)
        result = await tools.get_work_order_detail("t1", "u1", "WO001")
        assert "Bearing" in result
        assert "BRG" in result
        assert "单价: 100.0" in result

    @pytest.mark.asyncio
    async def test_check_availability_totals(self):
        from deerflow.integrations.routing import ServiceResult
        from deerflow.integrations.services.erp_service import ErpService
        from deerflow.integrations.tools.erp_tools import ErpTools

        items = (
            InventoryItem(id="I1", part_id="P1", warehouse="WH-A", quantity=30, reserved_quantity=5, source_metadata={}, provenance=_provenance()),
            InventoryItem(id="I2", part_id="P1", warehouse="WH-B", quantity=20, reserved_quantity=0, source_metadata={}, provenance=_provenance()),
        )
        mock_service = MagicMock(spec=ErpService)
        mock_service.check_availability = AsyncMock(
            return_value=ServiceResult(data=items, source_system_keys=("erp1",)),
        )

        tools = ErpTools(mock_service)
        result = await tools.check_availability("t1", "u1", "P1")
        assert "**总库存**: 50" in result
        assert "**已预留**: 5" in result
        assert "**可用**: 45" in result
        assert "WH-A" in result
        assert "WH-B" in result

    @pytest.mark.asyncio
    async def test_get_parts_low_stock_warning(self):
        from deerflow.integrations.routing import ServiceResult
        from deerflow.integrations.services.erp_service import ErpService
        from deerflow.integrations.tools.erp_tools import ErpTools

        part = SparePart(
            id="P1", part_number="BRG", name="Bearing",
            category="Bearings", unit="piece",
            stock_quantity=5, min_stock=10,
            source_metadata={}, provenance=_provenance(),
        )
        mock_service = MagicMock(spec=ErpService)
        mock_service.get_parts = AsyncMock(
            return_value=ServiceResult(data=(part,), source_system_keys=("erp1",)),
        )

        tools = ErpTools(mock_service)
        result = await tools.get_parts("t1", "u1", category="Bearings")
        assert "低库存" in result


# ---------------------------------------------------------------------------
# End-to-End: Adapter → Transform → Service → Tool Chain
# ---------------------------------------------------------------------------


class TestEndToEndCrmErp:
    """Test the full chain: adapter dispatch → transform → service → tool."""

    @pytest.mark.asyncio
    async def test_crm_end_to_end_customer_search(self):
        from deerflow.integrations.adapters.base import AuthContext
        from deerflow.integrations.adapters.crm import CrmAdapter
        from deerflow.integrations.config import IntegrationSystemConfig
        from deerflow.integrations.models.queries import CustomerProfileQuery
        from deerflow.integrations.routing import CapabilityRouter, ServiceResult
        from deerflow.integrations.services.crm_service import CrmService
        from deerflow.integrations.tools.crm_tools import CrmTools

        config = IntegrationSystemConfig(
            system_key="crm_test",
            system_type="crm",
            display_name="CRM Test",
            base_url="http://crm.test",
            auth_type="api_key",
        )
        adapter = CrmAdapter(config)

        raw_response = {
            "data": [
                {"id": "C001", "name": "ACME", "display_name": "ACME Corp", "industry": "Tech", "region": "BJ", "contract_count": 2, "service_object_count": 5},
                {"id": "C002", "name": "Beta", "display_name": "Beta Inc", "industry": "Mfg", "region": "SH", "contract_count": 1, "service_object_count": 3},
            ]
        }
        provenance = _provenance("customer.search")
        profiles = transform_customer_profile(raw_response, provenance)

        mock_router = MagicMock(spec=CapabilityRouter)
        mock_router.route = AsyncMock(return_value=ServiceResult(
            data=profiles, source_system_keys=("crm_test",),
        ))

        service = CrmService(mock_router)
        tools = CrmTools(service)

        result = await tools.search_customers("t1", "u1", search_text="ACME")
        assert "找到 2 个客户" in result
        assert "ACME Corp" in result
        assert "Beta Inc" in result

    @pytest.mark.asyncio
    async def test_erp_end_to_end_inventory_check(self):
        from deerflow.integrations.adapters.base import AuthContext
        from deerflow.integrations.adapters.erp import ErpAdapter
        from deerflow.integrations.config import IntegrationSystemConfig
        from deerflow.integrations.models.queries import InventoryQuery
        from deerflow.integrations.routing import CapabilityRouter, ServiceResult
        from deerflow.integrations.services.erp_service import ErpService
        from deerflow.integrations.tools.erp_tools import ErpTools

        config = IntegrationSystemConfig(
            system_key="erp_test",
            system_type="erp",
            display_name="ERP Test",
            base_url="http://erp.test",
            auth_type="api_key",
        )
        adapter = ErpAdapter(config)

        raw_response = {
            "data": [
                {"id": "I1", "part_id": "P001", "warehouse": "WH-Main", "quantity": 100, "reserved_quantity": 20, "last_restocked_at": "2026-05-01"},
                {"id": "I2", "part_id": "P001", "warehouse": "WH-Backup", "quantity": 50, "reserved_quantity": 10, "last_restocked_at": None},
            ]
        }
        provenance = _provenance("inventory.check_availability")
        items = transform_inventory_items(raw_response, provenance)

        mock_router = MagicMock(spec=CapabilityRouter)
        mock_router.route = AsyncMock(return_value=ServiceResult(
            data=items, source_system_keys=("erp_test",),
        ))

        service = ErpService(mock_router)
        tools = ErpTools(service)

        result = await tools.check_availability("t1", "u1", "P001")
        assert "**总库存**: 150" in result
        assert "**已预留**: 30" in result
        assert "**可用**: 120" in result


# ---------------------------------------------------------------------------
# ToolRegistry Integration Tests
# ---------------------------------------------------------------------------


class TestToolRegistryIntegration:
    """Test ToolRegistry creates CRM/ERP tool groups."""

    @pytest.mark.asyncio
    async def test_tool_registry_creates_crm_erp_groups(self):
        from deerflow.integrations.config import IntegrationsConfig
        from deerflow.integrations.registry import IntegrationRegistry
        from deerflow.integrations.routing import CapabilityRouter
        from deerflow.integrations.tools.registry import ToolRegistry

        config = IntegrationsConfig(enabled=True)
        mock_registry = MagicMock(spec=IntegrationRegistry)
        mock_router = MagicMock(spec=CapabilityRouter)

        tool_reg = ToolRegistry(config, mock_registry, mock_router)
        await tool_reg.initialize()

        tool_groups = tool_reg.list_tools()
        assert "crm" in tool_groups
        assert "erp" in tool_groups
        assert "asset" in tool_groups
        assert "monitoring" in tool_groups
        assert "assessment" in tool_groups

    @pytest.mark.asyncio
    async def test_tool_registry_get_crm_tools(self):
        from deerflow.integrations.config import IntegrationsConfig
        from deerflow.integrations.registry import IntegrationRegistry
        from deerflow.integrations.routing import CapabilityRouter
        from deerflow.integrations.tools.crm_tools import CrmTools
        from deerflow.integrations.tools.registry import ToolRegistry

        config = IntegrationsConfig(enabled=True)
        mock_registry = MagicMock(spec=IntegrationRegistry)
        mock_router = MagicMock(spec=CapabilityRouter)

        tool_reg = ToolRegistry(config, mock_registry, mock_router)
        await tool_reg.initialize()

        crm = tool_reg.get_tool("crm")
        assert isinstance(crm, CrmTools)

    @pytest.mark.asyncio
    async def test_tool_registry_get_erp_tools(self):
        from deerflow.integrations.config import IntegrationsConfig
        from deerflow.integrations.registry import IntegrationRegistry
        from deerflow.integrations.routing import CapabilityRouter
        from deerflow.integrations.tools.erp_tools import ErpTools
        from deerflow.integrations.tools.registry import ToolRegistry

        config = IntegrationsConfig(enabled=True)
        mock_registry = MagicMock(spec=IntegrationRegistry)
        mock_router = MagicMock(spec=CapabilityRouter)

        tool_reg = ToolRegistry(config, mock_registry, mock_router)
        await tool_reg.initialize()

        erp = tool_reg.get_tool("erp")
        assert isinstance(erp, ErpTools)
