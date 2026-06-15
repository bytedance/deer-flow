"""Asset overview composite model."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from deerflow.integrations.models.assessment import HealthAssessment
from deerflow.integrations.models.asset import Asset, AssetContext
from deerflow.integrations.models.monitoring import AlarmEvent
from deerflow.integrations.models.provenance import PartialFailure, Provenance


@dataclass(frozen=True)
class AssetOverview:
    """Composite asset overview aggregating multiple data sources."""

    asset: Asset
    context: AssetContext | None = None
    health_assessment: HealthAssessment | None = None
    recent_alarms: tuple[AlarmEvent, ...] = ()
    partial_failures: tuple[PartialFailure, ...] = ()
    source_metadata: dict[str, Any] = field(default_factory=dict)
    provenance: Provenance | None = None

    def with_provenance(self, provenance: Provenance) -> AssetOverview:
        """Return new AssetOverview with provenance."""
        return AssetOverview(
            asset=self.asset,
            context=self.context,
            health_assessment=self.health_assessment,
            recent_alarms=self.recent_alarms,
            partial_failures=self.partial_failures,
            source_metadata=self.source_metadata,
            provenance=provenance,
        )
