"""Assessment canonical models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from deerflow.integrations.models.provenance import Provenance


@dataclass(frozen=True)
class RiskItem:
    """Individual risk finding."""

    risk_id: str
    asset_id: str
    risk_type: str
    severity: str
    description: str
    recommendation: str = ""
    detected_at: datetime | None = None
    confidence: float = 1.0
    source_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HealthAssessment:
    """Equipment health assessment."""

    assessment_id: str
    asset_id: str
    overall_score: float
    overall_status: str
    summary: str
    dimensions: dict[str, float] = field(default_factory=dict)
    risk_items: tuple[RiskItem, ...] = ()
    assessed_at: datetime | None = None
    assessor: str = ""
    source_metadata: dict[str, Any] = field(default_factory=dict)
    provenance: Provenance | None = None

    def with_provenance(self, provenance: Provenance) -> HealthAssessment:
        """Return new HealthAssessment with provenance."""
        return HealthAssessment(
            assessment_id=self.assessment_id,
            asset_id=self.asset_id,
            overall_score=self.overall_score,
            overall_status=self.overall_status,
            summary=self.summary,
            dimensions=self.dimensions,
            risk_items=self.risk_items,
            assessed_at=self.assessed_at,
            assessor=self.assessor,
            source_metadata=self.source_metadata,
            provenance=provenance,
        )


@dataclass(frozen=True)
class AnomalyStats:
    """Anomaly detection statistics."""

    stats_id: str
    asset_id: str
    total_anomalies: int
    anomaly_rate: float
    by_severity: dict[str, int] = field(default_factory=dict)
    by_type: dict[str, int] = field(default_factory=dict)
    time_range_start: datetime | None = None
    time_range_end: datetime | None = None
    source_metadata: dict[str, Any] = field(default_factory=dict)
    provenance: Provenance | None = None

    def with_provenance(self, provenance: Provenance) -> AnomalyStats:
        """Return new AnomalyStats with provenance."""
        return AnomalyStats(
            stats_id=self.stats_id,
            asset_id=self.asset_id,
            total_anomalies=self.total_anomalies,
            anomaly_rate=self.anomaly_rate,
            by_severity=self.by_severity,
            by_type=self.by_type,
            time_range_start=self.time_range_start,
            time_range_end=self.time_range_end,
            source_metadata=self.source_metadata,
            provenance=provenance,
        )


@dataclass(frozen=True)
class EquipmentRisk:
    """Equipment-level risk summary."""

    asset_id: str
    asset_name: str
    risk_level: str
    risk_score: float
    top_risks: tuple[str, ...] = ()
    last_assessed_at: datetime | None = None


@dataclass(frozen=True)
class RiskRanking:
    """Risk ranking across equipment."""

    ranking_id: str
    tenant_id: str
    rankings: tuple[EquipmentRisk, ...]
    generated_at: datetime | None = None
    scope: str = ""
    source_metadata: dict[str, Any] = field(default_factory=dict)
    provenance: Provenance | None = None

    def with_provenance(self, provenance: Provenance) -> RiskRanking:
        """Return new RiskRanking with provenance."""
        return RiskRanking(
            ranking_id=self.ranking_id,
            tenant_id=self.tenant_id,
            rankings=self.rankings,
            generated_at=self.generated_at,
            scope=self.scope,
            source_metadata=self.source_metadata,
            provenance=provenance,
        )


# ---------------------------------------------------------------------------
# Abnormal (SMS) models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AbnormalPoint:
    """SMS abnormal event point / measurement point reference."""

    point_id: str
    point_name: str
    value_type: str
    point_type: int


@dataclass(frozen=True)
class AbnormalEvent:
    """Single abnormal event within an anomaly."""

    time: int  # 毫秒时间戳
    health: float | None
    type: str  # sensor / t / w / k / d
    run_status: str
    event_level: int
    desc: str
    points: tuple[AbnormalPoint, ...]
    time_range_start: int  # jumpParams.startTime
    time_range_end: int  # jumpParams.endTime
    factory_id: str


@dataclass(frozen=True)
class AbnormalItem:
    """Single row in the abnormal list."""

    abnormal_id: str
    process_status: str
    mac_path: str
    mac_name: str
    component_name: str
    mac_id: str
    component_id: str
    serious_health: float
    latest_health: float
    first_event_time: int
    lastest_event_time: int
    serious_level: int
    latest_level: int
    event_count: int
    recorder: str = ""
    run_status: str = ""
    process_duration: int = 0
    mac_type: int = 1
    defect_transfer_status: int = 0
    fault_transfer_status: int = 0


@dataclass(frozen=True)
class AbnormalDetail:
    """Full detail of a single anomaly."""

    abnormal_id: str
    process_status: str
    mac_path: str
    mac_name: str
    component_name: str
    events: tuple[AbnormalEvent, ...]
    logs: tuple[dict[str, Any], ...] = ()
    ai_analyse: dict[str, Any] | None = None
    risk_assessment: dict[str, Any] | None = None
    # 以下字段从列表侧带入（详情接口不返回）
    mac_id: str = ""
    component_id: str = ""
