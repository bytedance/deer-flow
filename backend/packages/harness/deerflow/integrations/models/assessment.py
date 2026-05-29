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

    def with_provenance(self, provenance: Provenance) -> "HealthAssessment":
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

    def with_provenance(self, provenance: Provenance) -> "AnomalyStats":
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

    def with_provenance(self, provenance: Provenance) -> "RiskRanking":
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
