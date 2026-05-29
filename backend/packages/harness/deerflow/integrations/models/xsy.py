"""Xiaoshouyi (销售易) canonical models.

Frozen dataclasses for CRM domain entities following the same
conventions as existing models (frozen + source_metadata + provenance).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from deerflow.integrations.models.provenance import Provenance


@dataclass(frozen=True)
class OutboundDetail:
    """产品出库明细记录."""

    id: str
    quantity: float                         # customItem3__c
    spec_model: str | None = None           # customItem5__c
    created_at: datetime | None = None      # createdAt (ms→datetime)
    source_metadata: dict[str, Any] = field(default_factory=dict)
    provenance: Provenance | None = None

    def with_provenance(self, provenance: Provenance) -> "OutboundDetail":
        """Return new instance with provenance attached."""
        return OutboundDetail(
            id=self.id,
            quantity=self.quantity,
            spec_model=self.spec_model,
            created_at=self.created_at,
            source_metadata=self.source_metadata,
            provenance=provenance,
        )


@dataclass(frozen=True)
class ServiceEventDetail:
    """服务事件明细记录."""

    id: str
    unit_name: str | None = None            # customItem6__c (设备名称)
    event_name: str | None = None           # name (工单名称)
    event_time: datetime | None = None      # createdAt (customItem8__c 故障时间 is lookup, unusable in WHERE)
    source_metadata: dict[str, Any] = field(default_factory=dict)
    provenance: Provenance | None = None

    def with_provenance(self, provenance: Provenance) -> "ServiceEventDetail":
        """Return new instance with provenance attached."""
        return ServiceEventDetail(
            id=self.id,
            unit_name=self.unit_name,
            event_name=self.event_name,
            event_time=self.event_time,
            source_metadata=self.source_metadata,
            provenance=provenance,
        )


@dataclass(frozen=True)
class OutboundStatistics:
    """出库数据统计分析结果."""

    total_records: int
    total_quantity: float
    avg_quantity: float
    min_quantity: float
    max_quantity: float
    by_spec_model: dict[str, float]         # 规格型号 → 总数量
    by_period: dict[str, float]             # 周期 → 总数量
    source_metadata: dict[str, Any] = field(default_factory=dict)
    provenance: Provenance | None = None


@dataclass(frozen=True)
class ServiceEventStatistics:
    """服务事件统计分析结果."""

    total_records: int
    by_unit: dict[str, int]                 # 机组 → 事件数
    by_event_type: dict[str, int]           # 事件类型 → 事件数
    by_period: dict[str, int]               # 周期 → 事件数
    frequency_per_unit: dict[str, float]    # 机组 → 频率（次/天）
    source_metadata: dict[str, Any] = field(default_factory=dict)
    provenance: Provenance | None = None


@dataclass(frozen=True)
class ServiceEventAnomaly:
    """服务事件异常检测结果."""

    anomaly_type: str                       # "frequency_spike" | "new_event_type" | "high_frequency_unit"
    unit_name: str | None
    event_name: str | None
    description: str
    severity: str                           # "low" | "medium" | "high"
    event_count: int
    baseline_count: int | None = None
    deviation_ratio: float | None = None
    source_metadata: dict[str, Any] = field(default_factory=dict)
    provenance: Provenance | None = None
