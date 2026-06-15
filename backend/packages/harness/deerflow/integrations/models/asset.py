"""Asset canonical models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from deerflow.integrations.models.provenance import Provenance


@dataclass(frozen=True)
class MeasurementPoint:
    """Equipment measurement point."""

    point_id: str
    point_code: str
    point_name: str
    point_type: str
    unit: str = ""
    direction: str = ""
    description: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Asset:
    """Equipment asset."""

    asset_id: str
    asset_code: str
    asset_name: str
    asset_type: str
    status: str = "active"
    location: str = ""
    manufacturer: str = ""
    model: str = ""
    serial_number: str = ""
    installed_at: datetime | None = None
    description: str = ""
    tags: tuple[str, ...] = ()
    source_metadata: dict[str, Any] = field(default_factory=dict)
    provenance: Provenance | None = None

    def with_provenance(self, provenance: Provenance) -> Asset:
        """Return new Asset with provenance."""
        return Asset(
            asset_id=self.asset_id,
            asset_code=self.asset_code,
            asset_name=self.asset_name,
            asset_type=self.asset_type,
            status=self.status,
            location=self.location,
            manufacturer=self.manufacturer,
            model=self.model,
            serial_number=self.serial_number,
            installed_at=self.installed_at,
            description=self.description,
            tags=self.tags,
            source_metadata=self.source_metadata,
            provenance=provenance,
        )


@dataclass(frozen=True)
class AssetContext:
    """Asset with contextual relationships."""

    asset: Asset
    parent_asset_id: str | None = None
    child_assets: tuple[Asset, ...] = ()
    measurement_points: tuple[MeasurementPoint, ...] = ()
    related_assets: tuple[Asset, ...] = ()
    operational_context: dict[str, Any] = field(default_factory=dict)
    source_metadata: dict[str, Any] = field(default_factory=dict)
    provenance: Provenance | None = None

    def with_provenance(self, provenance: Provenance) -> AssetContext:
        """Return new AssetContext with provenance."""
        return AssetContext(
            asset=self.asset,
            parent_asset_id=self.parent_asset_id,
            child_assets=self.child_assets,
            measurement_points=self.measurement_points,
            related_assets=self.related_assets,
            operational_context=self.operational_context,
            source_metadata=self.source_metadata,
            provenance=provenance,
        )
