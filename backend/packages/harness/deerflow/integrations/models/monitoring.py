"""Monitoring canonical models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from deerflow.integrations.models.provenance import Provenance


@dataclass(frozen=True)
class TimeRange:
    """Time range for queries."""

    start: datetime
    end: datetime


@dataclass(frozen=True)
class TrendPoint:
    """Single trend data point."""

    timestamp: datetime
    value: float
    quality: str = "good"


@dataclass(frozen=True)
class TrendStatistics:
    """Statistical summary of trend data."""

    min_value: float
    max_value: float
    avg_value: float
    std_dev: float | None = None
    sample_count: int = 0


@dataclass(frozen=True)
class TrendSeries:
    """Time-series trend data."""

    series_id: str
    asset_id: str
    measurement_point_id: str
    points: tuple[TrendPoint, ...]
    statistics: TrendStatistics | None = None
    time_range: TimeRange | None = None
    unit: str = ""
    source_metadata: dict[str, Any] = field(default_factory=dict)
    provenance: Provenance | None = None

    def with_provenance(self, provenance: Provenance) -> TrendSeries:
        """Return new TrendSeries with provenance."""
        return TrendSeries(
            series_id=self.series_id,
            asset_id=self.asset_id,
            measurement_point_id=self.measurement_point_id,
            points=self.points,
            statistics=self.statistics,
            time_range=self.time_range,
            unit=self.unit,
            source_metadata=self.source_metadata,
            provenance=provenance,
        )


@dataclass(frozen=True)
class WaveformPayload:
    """Waveform and spectrum data."""

    waveform_id: str
    asset_id: str
    measurement_point_id: str
    wave_x: tuple[float, ...]
    wave_y: tuple[float, ...]
    spec_x: tuple[float, ...] = ()
    spec_y: tuple[float, ...] = ()
    speed_rpm: float | None = None
    sample_rate: float | None = None
    unit: str = ""
    captured_at: datetime | None = None
    source_metadata: dict[str, Any] = field(default_factory=dict)
    provenance: Provenance | None = None

    def with_provenance(self, provenance: Provenance) -> WaveformPayload:
        """Return new WaveformPayload with provenance."""
        return WaveformPayload(
            waveform_id=self.waveform_id,
            asset_id=self.asset_id,
            measurement_point_id=self.measurement_point_id,
            wave_x=self.wave_x,
            wave_y=self.wave_y,
            spec_x=self.spec_x,
            spec_y=self.spec_y,
            speed_rpm=self.speed_rpm,
            sample_rate=self.sample_rate,
            unit=self.unit,
            captured_at=self.captured_at,
            source_metadata=self.source_metadata,
            provenance=provenance,
        )


@dataclass(frozen=True)
class OrbitPayload:
    """Orbit (shaft centerline) data."""

    orbit_id: str
    asset_id: str
    measurement_point_id: str
    probe_ids: tuple[str, str]
    points: tuple[tuple[float, float], ...]
    points_1x: tuple[tuple[float, float], ...] = ()
    points_2x: tuple[tuple[float, float], ...] = ()
    speed_rpm: float | None = None
    unit: str = ""
    captured_at: datetime | None = None
    source_metadata: dict[str, Any] = field(default_factory=dict)
    provenance: Provenance | None = None

    def with_provenance(self, provenance: Provenance) -> OrbitPayload:
        """Return new OrbitPayload with provenance."""
        return OrbitPayload(
            orbit_id=self.orbit_id,
            asset_id=self.asset_id,
            measurement_point_id=self.measurement_point_id,
            probe_ids=self.probe_ids,
            points=self.points,
            points_1x=self.points_1x,
            points_2x=self.points_2x,
            speed_rpm=self.speed_rpm,
            unit=self.unit,
            captured_at=self.captured_at,
            source_metadata=self.source_metadata,
            provenance=provenance,
        )


@dataclass(frozen=True)
class AlarmEvent:
    """Alarm or event record."""

    event_id: str
    asset_id: str
    event_type: str
    severity: str
    message: str
    triggered_at: datetime
    ended_at: datetime | None = None
    duration_seconds: float | None = None
    acknowledged: bool = False
    acknowledged_by: str | None = None
    acknowledged_at: datetime | None = None
    source_metadata: dict[str, Any] = field(default_factory=dict)
    provenance: Provenance | None = None

    def with_provenance(self, provenance: Provenance) -> AlarmEvent:
        """Return new AlarmEvent with provenance."""
        return AlarmEvent(
            event_id=self.event_id,
            asset_id=self.asset_id,
            event_type=self.event_type,
            severity=self.severity,
            message=self.message,
            triggered_at=self.triggered_at,
            ended_at=self.ended_at,
            duration_seconds=self.duration_seconds,
            acknowledged=self.acknowledged,
            acknowledged_by=self.acknowledged_by,
            acknowledged_at=self.acknowledged_at,
            source_metadata=self.source_metadata,
            provenance=provenance,
        )
