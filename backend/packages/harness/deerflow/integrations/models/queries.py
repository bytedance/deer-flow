"""Query objects for integration capabilities."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class AssetCatalogQuery:
    """Query for asset catalog."""

    tenant_id: str
    asset_ids: tuple[str, ...] = ()
    asset_types: tuple[str, ...] = ()
    status: str | None = None
    search_text: str = ""
    limit: int = 100
    offset: int = 0
    extra_filters: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AssetContextQuery:
    """Query for single asset context."""

    tenant_id: str
    asset_id: str
    include_children: bool = True
    include_measurement_points: bool = True
    include_related: bool = False
    depth: int = 1
    extra_params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AssetOverviewQuery:
    """Query for composite asset overview."""

    tenant_id: str
    asset_id: str
    include_context: bool = True
    include_health_assessment: bool = True
    include_recent_alarms: bool = True
    alarm_time_range_hours: int = 24
    extra_params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TrendQuery:
    """Query for trend data."""

    tenant_id: str
    asset_id: str | None = None
    measurement_point_id: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    sample_interval: str | None = None
    aggregation: str | None = None
    equipment_ids: tuple[str, ...] = ()
    eq_type: str = "all"
    extra_params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WaveformQuery:
    """Query for waveform data."""

    tenant_id: str
    asset_id: str
    measurement_point_id: str
    captured_at: datetime | None = None
    speed_rpm: float | None = None
    include_spectrum: bool = True
    extra_params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OrbitQuery:
    """Query for orbit data."""

    tenant_id: str
    asset_id: str
    measurement_point_id: str
    captured_at: datetime | None = None
    speed_rpm: float | None = None
    include_harmonics: bool = True
    extra_params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AlarmHistoryQuery:
    """Query for alarm history."""

    tenant_id: str
    asset_id: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    severity: tuple[str, ...] = ()
    event_type: tuple[str, ...] = ()
    acknowledged: bool | None = None
    limit: int = 100
    offset: int = 0
    equipment_ids: tuple[str, ...] = ()
    eq_type: str = "all"
    extra_filters: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HealthAssessmentQuery:
    """Query for health assessment."""

    tenant_id: str
    asset_id: str
    assessed_at: datetime | None = None
    include_risk_items: bool = True
    min_confidence: float = 0.0
    extra_params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AnomalyStatsQuery:
    """Query for anomaly statistics."""

    tenant_id: str
    asset_id: str
    start_time: datetime | None = None
    end_time: datetime | None = None
    group_by: tuple[str, ...] = ()
    extra_params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RiskRankingQuery:
    """Query for risk ranking."""

    tenant_id: str
    scope: str = ""
    limit: int = 50
    min_risk_score: float = 0.0
    generated_after: datetime | None = None
    extra_filters: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# CRM queries
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CustomerProfileQuery:
    """Query for customer profile."""

    tenant_id: str
    customer_id: str | None = None
    search_text: str = ""
    industry: str | None = None
    region: str | None = None
    limit: int = 50
    offset: int = 0
    extra_filters: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ContractQuery:
    """Query for contract details."""

    tenant_id: str
    contract_id: str | None = None
    customer_id: str | None = None
    status: str | None = None
    limit: int = 50
    offset: int = 0
    extra_filters: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ServiceObjectQuery:
    """Query for service object details."""

    tenant_id: str
    service_object_id: str | None = None
    customer_id: str | None = None
    asset_id: str | None = None
    object_type: str | None = None
    limit: int = 50
    offset: int = 0
    extra_filters: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# ERP queries
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WorkOrderQuery:
    """Query for work orders."""

    tenant_id: str
    work_order_id: str | None = None
    asset_id: str | None = None
    status: str | None = None
    priority: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    limit: int = 50
    offset: int = 0
    extra_filters: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SparePartQuery:
    """Query for spare parts."""

    tenant_id: str
    part_id: str | None = None
    part_number: str | None = None
    category: str | None = None
    search_text: str = ""
    limit: int = 50
    offset: int = 0
    extra_filters: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class InventoryQuery:
    """Query for inventory availability."""

    tenant_id: str
    part_id: str | None = None
    warehouse: str | None = None
    min_quantity: int = 0
    limit: int = 50
    offset: int = 0
    extra_filters: dict[str, Any] = field(default_factory=dict)
