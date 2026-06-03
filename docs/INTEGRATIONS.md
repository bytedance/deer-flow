# Integration System Architecture

The integration layer (`packages/harness/deerflow/integrations/`) provides a unified adapter-service-tool architecture for connecting external enterprise systems (InS, Sms, CRM, ERP) to the DeerFlow AI agent platform.

## Overview

```
External System → Adapter → Transform → Canonical Model → Service → Tool → Agent
```

The integration layer follows a **three-layer architecture**:

1. **Adapter** — connects to external systems, handles auth, HTTP transport, and error mapping
2. **Service** — orchestrates capability calls through `CapabilityRouter` with primary/enrich/fallback routing
3. **Tool** — formats `ServiceResult` data into agent-readable strings (Markdown)

## Supported Systems

| System | Type | Capabilities |
|--------|------|-------------|
| **InS** | `ins` | Asset catalog, asset context, monitoring (trend, waveform, orbit, alarm history) |
| **Sms** | `sms` | Health assessment, anomaly statistics, risk ranking |
| **CRM** | `crm` | Customer profile, contract, service object |
| **ERP** | `erp` | Work orders, spare parts, inventory |

## Module Structure

```
integrations/
├── adapters/              # External system adapters
│   ├── base.py            # IntegrationAdapter protocol, AuthContext, HealthStatus
│   ├── ins/               # InS adapter + transforms
│   ├── sms/               # Sms adapter + transforms
│   ├── crm/               # CRM adapter + transforms
│   └── erp/               # ERP adapter + transforms
├── services/              # Business logic orchestration
│   ├── asset_service.py   # Asset catalog, context, overview (composite)
│   ├── monitoring_service.py  # Trend, waveform, orbit, alarms
│   ├── assessment_service.py  # Health assessment, risk ranking
│   ├── crm_service.py     # Customer, contract, service object
│   └── erp_service.py     # Work orders, spare parts, inventory
├── tools/                 # Agent-facing tool wrappers
│   ├── asset_tools.py     # get_asset_catalog, get_asset_context, get_asset_overview
│   ├── monitoring_tools.py # get_trend, get_waveform, get_orbit, get_alarm_history
│   ├── assessment_tools.py  # get_health_assessment
│   ├── crm_tools.py       # get_customer_profile, search_customers, get_contract_detail, etc.
│   ├── erp_tools.py       # get_work_orders, get_work_order_detail, get_parts, check_availability
│   └── registry.py        # ToolRegistry — creates service + tool instances
├── models/                # Canonical frozen dataclasses
│   ├── asset.py           # Asset, AssetContext
│   ├── monitoring.py      # TrendSeries, WaveformData, OrbitData, AlarmEvent
│   ├── assessment.py      # HealthAssessment
│   ├── crm.py             # CustomerProfile, Contract, ServiceObject
│   ├── erp.py             # WorkOrder, SparePart, InventoryItem, SparePartUsage
│   ├── provenance.py      # Provenance, PartialFailure
│   ├── queries.py         # Query dataclasses (AssetCatalogQuery, WorkOrderQuery, etc.)
│   └── overview.py        # AssetOverview (composite)
├── registry.py            # IntegrationRegistry — adapter lifecycle + factory
├── routing.py             # CapabilityRouter — primary/enrich/fallback routing
├── config.py              # IntegrationsConfig, CapabilityRouteConfig, EntityLinkConfig
├── errors.py              # IntegrationError hierarchy
└── cli.py                 # Subprocess CLI bridge (integration-cli)
```

## Configuration

Integration systems are configured in `config.yaml` under the `integrations` key:

```yaml
integrations:
  enabled: true
  systems:
    ins_prod:
      system_type: ins
      display_name: "InS Production"
      base_url: "http://ins.example.com"
      auth_type: bearer
      secret_ref: "$INS_TOKEN"
      capabilities: [asset.catalog, monitoring.trend, ...]
    crm_prod:
      system_type: crm
      display_name: "CRM Production"
      base_url: "http://crm.example.com"
      auth_type: api_key
      secret_ref: "$CRM_API_KEY"
      capabilities: [customer.get_profile, contract.get_detail, ...]
  routes:
    monitoring.trend: ins_prod
    customer.get_profile: crm_prod
    asset.overview:
      primary: ins_prod
      enrich: [sms_prod]
      merge_policy: primary_plus_enrich
```

### Capability Routes

Routes support three modes:

- **Simple**: `"capability.key": "system_key"` — single primary system
- **Full**: primary + enrich + fallback systems with merge policies
- **Disabled**: `enabled: false` on any route

### Entity Links

Cross-system entity ID mappings (`EntityLinkConfig`) support these entity types:

- `asset`, `measurement_point` (InS/Sms)
- `customer`, `contract` (CRM)
- `work_order`, `spare_part`, `inventory_item` (ERP)

## Adding a New Adapter

### 1. Define canonical models

Create `models/<system>.py` with frozen dataclasses. Every model must include:

```python
@dataclass(frozen=True)
class MyModel:
    id: str
    # ... domain fields ...
    source_metadata: dict[str, Any] = field(default_factory=dict)
    provenance: Provenance = field(default_factory=lambda: ...)
```

### 2. Create transform functions

Create `adapters/<system>/transform.py` with pure functions:

```python
def transform_my_data(raw: dict[str, Any], provenance: Provenance) -> tuple[MyModel, ...]:
    items = raw.get("data", [raw])
    return tuple(MyModel(id=str(i["id"]), ..., source_metadata={"raw": i}, provenance=provenance) for i in items)
```

### 3. Implement the adapter

Create `adapters/<system>/adapter.py` following the `InsAdapter`/`SmsAdapter` pattern:

```python
class MyAdapter:
    def __init__(self, config: IntegrationSystemConfig) -> None: ...
    async def initialize(self) -> None: ...
    async def shutdown(self) -> None: ...
    async def call(self, capability_key, query, auth_context) -> Any: ...
    async def health_check(self) -> HealthStatus: ...
```

### 4. Register the adapter factory

In `registry.py`, add to the `adapter_factories` dict:

```python
adapter_factories = {
    "ins": InsAdapter,
    "sms": SmsAdapter,
    "crm": CrmAdapter,
    "erp": ErpAdapter,
    "mysystem": MyAdapter,  # Add here
}
```

### 5. Create service + tools

- `services/my_service.py` — delegates to `CapabilityRouter`
- `tools/my_tools.py` — formats results for agent consumption
- Register in `tools/registry.py` `initialize()` method

### 6. Add configuration

Add system and routes to `config.example.yaml`:

```yaml
systems:
  mysystem_prod:
    system_type: mysystem
    ...
routes:
  mysystem.capability: mysystem_prod
```

## Report Script Integration

Report query scripts (`skills/custom/daily-report/scripts/`) use the integration layer via a CLI bridge:

1. Script checks `USE_PLATFORM=true` env var
2. If set, calls `_platform_bridge.call_capability()` which invokes `integration-cli` subprocess
3. CLI subprocess initializes `IntegrationRegistry` + `CapabilityRouter` and routes the call
4. On bridge failure, scripts fall back to legacy `_ins_provider.py` (deprecated)

The DSL `data_steps` support a `provider` field (`"platform"`, `"ins"`, `"demo"`, `"http"`) to control which data source path the report runtime uses.

## Rollback

- Set `integrations.enabled: false` → all integration tools disabled, zero impact
- Set `USE_PLATFORM=false` (or unset) → report scripts use legacy features-tool path
