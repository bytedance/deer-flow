## FUTURE Requirements

> This spec defines canonical models and capability keys for CRM and ERP integrations planned for Phase 3+. These are forward-looking contracts — implementations SHALL follow the same three-layer pattern (Adapter → Service → Tool) established for Ins and Sms.

### Requirement: CRM canonical models

The system SHALL define frozen dataclasses for CRM domain entities when the CRM adapter is implemented. All models SHALL follow the same conventions as Ins/Sms canonical models (frozen, `source_metadata`, `provenance`).

```python
# deerflow/integrations/models/crm.py (future)

@dataclass(frozen=True)
class CustomerProfile:
    id: str                        # platform unified ID, e.g. "customer:tenant-a:001"
    name: str                      # customer short name
    display_name: str              # human-readable name
    industry: str | None           # e.g. "petrochemical", "power_generation"
    region: str | None             # e.g. "华东", "华北"
    contact_name: str | None       # primary contact
    contact_phone: str | None      # primary contact phone
    contract_count: int            # number of active contracts
    service_object_count: int      # number of installed service objects
    source_metadata: dict[str, Any]
    provenance: Provenance

@dataclass(frozen=True)
class Contract:
    id: str                        # platform unified ID
    customer_id: str               # reference to CustomerProfile.id
    contract_number: str           # CRM contract number
    title: str                     # contract title
    status: str                    # "active", "expired", "pending"
    start_date: str                # ISO 8601
    end_date: str | None           # ISO 8601
    service_level: str | None      # e.g. "premium", "standard", "basic"
    covered_assets: tuple[str, ...]  # asset_ids covered by this contract
    source_metadata: dict[str, Any]
    provenance: Provenance

@dataclass(frozen=True)
class ServiceObject:
    id: str                        # platform unified ID
    customer_id: str               # reference to CustomerProfile.id
    asset_id: str | None           # link to canonical Asset.id (via EntityLink)
    object_type: str               # e.g. "pump", "compressor", "turbine"
    model_number: str | None
    serial_number: str | None
    installation_date: str | None  # ISO 8601
    warranty_end_date: str | None  # ISO 8601
    source_metadata: dict[str, Any]
    provenance: Provenance
```

### Requirement: CRM capability keys

The CRM adapter SHALL declare support for these capability keys:

- `customer.get_profile` — fetch customer profile by ID or search criteria
- `customer.search` — search customers by name, industry, region
- `contract.get_detail` — fetch contract details by contract ID
- `contract.list_by_customer` — list all contracts for a customer
- `service_object.get_detail` — fetch service object details
- `service_object.list_by_customer` — list service objects for a customer

#### Scenario: CRM adapter capability declaration

- **WHEN** `CrmAdapter` is instantiated
- **THEN** `system_type` returns `"crm"`
- **THEN** `capabilities` includes `["customer.get_profile", "customer.search", "contract.get_detail", "contract.list_by_customer", "service_object.get_detail", "service_object.list_by_customer"]`

#### Scenario: CRM tools available

- **WHEN** the CRM adapter is configured and healthy
- **THEN** the following tools are available for Agent injection:
  - `customer_get_profile` — wraps customer profile lookup
  - `contract_get_detail` — wraps contract detail lookup
  - `service_object_get_detail` — wraps service object lookup

### Requirement: ERP canonical models

The system SHALL define frozen dataclasses for ERP domain entities when the ERP adapter is implemented.

```python
# deerflow/integrations/models/erp.py (future)

@dataclass(frozen=True)
class WorkOrder:
    id: str                        # platform unified ID, e.g. "wo:tenant-a:001"
    order_number: str              # ERP work order number
    title: str                     # work order title
    status: str                    # "open", "in_progress", "completed", "cancelled"
    priority: str                  # "critical", "high", "medium", "low"
    asset_id: str | None           # link to canonical Asset.id (via EntityLink)
    assigned_to: str | None        # technician/team name
    created_at: str                # ISO 8601
    scheduled_at: str | None       # ISO 8601
    completed_at: str | None       # ISO 8601
    description: str               # work order description
    parts_used: tuple[SparePartUsage, ...]
    source_metadata: dict[str, Any]
    provenance: Provenance

@dataclass(frozen=True)
class SparePartUsage:
    part_id: str
    part_number: str
    name: str
    quantity: int
    unit_cost: float | None

@dataclass(frozen=True)
class SparePart:
    id: str                        # platform unified ID
    part_number: str               # ERP part number
    name: str                      # part name
    category: str | None           # e.g. "bearing", "seal", "filter"
    unit: str                      # e.g. "piece", "set", "meter"
    stock_quantity: int            # current stock level
    min_stock: int | None          # minimum stock threshold
    unit_cost: float | None
    source_metadata: dict[str, Any]
    provenance: Provenance

@dataclass(frozen=True)
class InventoryItem:
    id: str                        # platform unified ID
    part_id: str                   # reference to SparePart.id
    warehouse: str                 # warehouse/location code
    quantity: int                  # available quantity
    reserved_quantity: int         # reserved for pending work orders
    last_restocked_at: str | None  # ISO 8601
    source_metadata: dict[str, Any]
    provenance: Provenance
```

### Requirement: ERP capability keys

The ERP adapter SHALL declare support for these capability keys:

- `maintenance.get_work_orders` — fetch work orders by asset, status, or date range
- `maintenance.get_work_order_detail` — fetch single work order with parts usage
- `inventory.get_parts` — search spare parts by category, name, or part number
- `inventory.get_part_detail` — fetch spare part with inventory levels
- `inventory.check_availability` — check part availability across warehouses

#### Scenario: ERP adapter capability declaration

- **WHEN** `ErpAdapter` is instantiated
- **THEN** `system_type` returns `"erp"`
- **THEN** `capabilities` includes `["maintenance.get_work_orders", "maintenance.get_work_order_detail", "inventory.get_parts", "inventory.get_part_detail", "inventory.check_availability"]`

#### Scenario: ERP tools available

- **WHEN** the ERP adapter is configured and healthy
- **THEN** the following tools are available for Agent injection:
  - `maintenance_get_work_orders` — wraps work order list query
  - `maintenance_get_work_order_detail` — wraps work order detail lookup
  - `inventory_get_parts` — wraps spare part search
  - `inventory_check_availability` — wraps part availability check

### Requirement: EntityLink extension for CRM/ERP

When CRM and ERP adapters are introduced, the `EntityLinkConfig` SHALL be extended to cover new entity types:

- `"customer"` — maps canonical customer IDs across CRM instances
- `"contract"` — maps canonical contract IDs
- `"work_order"` — maps canonical work order IDs
- `"inventory_item"` — maps canonical inventory item IDs
- `"spare_part"` — maps canonical spare part IDs

The existing `"asset"` and `"measurement_point"` entity types SHALL be extended to include CRM/ERP system mappings:

- CRM `ServiceObject.asset_id` → canonical `Asset.id` (via `EntityLink` with `entity_type: "asset"`)
- ERP `WorkOrder.asset_id` → canonical `Asset.id` (via `EntityLink` with `entity_type: "asset"`)

#### Scenario: Cross-system asset link

- **WHEN** an entity link maps `asset:tenant-a:pump-001` to:
  - `ins_prod` → `INS-10001`
  - `sms_prod` → `SMS-90088`
  - `crm_prod` → `SO-20045` (CRM ServiceObject)
  - `erp_prod` → `EQ-30012` (ERP equipment code)
- **THEN** `EntityLinkResolver.resolve("asset", "asset:tenant-a:pump-001", "erp_prod")` returns the ERP remote ID
- **THEN** `EntityLinkResolver.resolve("asset", "asset:tenant-a:pump-001", "crm_prod")` returns the CRM remote ID

### Requirement: CRM/ERP adapter implementation pattern

When CRM or ERP adapters are implemented, they SHALL follow the same pattern established by `InsAdapter` and `SmsAdapter`:

1. Implement `IntegrationAdapter` protocol in `deerflow/integrations/adapters/crm/` or `deerflow/integrations/adapters/erp/`
2. Provide `transform.py` with pure functions for system response → canonical model conversion
3. Register adapter factory in `IntegrationRegistry`: `{"crm": CrmAdapter, "erp": ErpAdapter}`
4. Add capability routes in `integrations.routes` config
5. Add corresponding service methods and tools
6. Update `config.example.yaml` with CRM/ERP example entries

No changes to the core architecture (CapabilityRouter, ServiceResult, Provenance) SHALL be required — the three-layer pattern absorbs new systems without modification.
