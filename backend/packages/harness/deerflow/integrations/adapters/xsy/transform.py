"""Xiaoshouyi (销售易) response transforms.

Pure functions that convert API response records to canonical frozen models.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from statistics import mean, median, stdev
from typing import Any

from deerflow.integrations.adapters.xsy.sql_builder import (
    OUTBOUND_FIELDS,
    SERVICE_EVENT_FIELDS,
)
from deerflow.integrations.models.provenance import Provenance
from deerflow.integrations.models.xsy import (
    OutboundDetail,
    OutboundStatistics,
    ServiceEventAnomaly,
    ServiceEventDetail,
    ServiceEventStatistics,
)


def transform_outbound_records(
    records: list[dict[str, Any]],
    provenance: Provenance,
) -> tuple[OutboundDetail, ...]:
    """Transform raw outbound records to canonical models."""
    results: list[OutboundDetail] = []

    for record in records:
        created_at_raw = record.get(OUTBOUND_FIELDS["created_at"])
        created_at = None
        if created_at_raw is not None:
            # 13-digit millisecond timestamp → datetime
            try:
                created_at = datetime.fromtimestamp(created_at_raw / 1000.0)
            except (ValueError, TypeError):
                pass

        detail = OutboundDetail(
            id=str(record.get("id", "")),
            quantity=float(record.get(OUTBOUND_FIELDS["quantity"], 0)),
            spec_model=record.get(OUTBOUND_FIELDS["spec_model"]),
            created_at=created_at,
            source_metadata={"raw": record},
            provenance=provenance,
        )
        results.append(detail)

    return tuple(results)


def transform_service_event_records(
    records: list[dict[str, Any]],
    provenance: Provenance,
) -> tuple[ServiceEventDetail, ...]:
    """Transform raw service event records to canonical models."""
    results: list[ServiceEventDetail] = []

    for record in records:
        event_time_raw = record.get(SERVICE_EVENT_FIELDS["event_time"])
        event_time = None
        if event_time_raw is not None:
            try:
                event_time = datetime.fromtimestamp(event_time_raw / 1000.0)
            except (ValueError, TypeError):
                pass

        detail = ServiceEventDetail(
            id=str(record.get("id", "")),
            unit_name=record.get(SERVICE_EVENT_FIELDS["unit_name"]),
            event_name=record.get(SERVICE_EVENT_FIELDS["event_name"]),
            event_time=event_time,
            source_metadata={"raw": record},
            provenance=provenance,
        )
        results.append(detail)

    return tuple(results)


def compute_outbound_statistics(
    records: tuple[OutboundDetail, ...],
    group_by: str | None = None,
    provenance: Provenance | None = None,
) -> OutboundStatistics:
    """Compute statistics from outbound records."""
    if not records:
        return OutboundStatistics(
            total_records=0,
            total_quantity=0.0,
            avg_quantity=0.0,
            min_quantity=0.0,
            max_quantity=0.0,
            by_spec_model={},
            by_period={},
            provenance=provenance,
        )

    quantities = [r.quantity for r in records]

    # Group by spec_model
    by_spec_model: dict[str, float] = {}
    if group_by == "spec_model" or group_by is None:
        spec_groups: dict[str, float] = defaultdict(float)
        for r in records:
            key = r.spec_model or "unknown"
            spec_groups[key] += r.quantity
        by_spec_model = dict(spec_groups)

    # Group by period
    by_period: dict[str, float] = {}
    if group_by in ("day", "week", "month"):
        period_groups: dict[str, float] = defaultdict(float)
        for r in records:
            if r.created_at:
                if group_by == "day":
                    key = r.created_at.strftime("%Y-%m-%d")
                elif group_by == "week":
                    key = r.created_at.strftime("%Y-W%U")
                else:  # month
                    key = r.created_at.strftime("%Y-%m")
                period_groups[key] += r.quantity
        by_period = dict(sorted(period_groups.items()))

    return OutboundStatistics(
        total_records=len(records),
        total_quantity=sum(quantities),
        avg_quantity=mean(quantities),
        min_quantity=min(quantities),
        max_quantity=max(quantities),
        by_spec_model=by_spec_model,
        by_period=by_period,
        provenance=provenance,
    )


def compute_service_event_statistics(
    records: tuple[ServiceEventDetail, ...],
    group_by: str | None = None,
    provenance: Provenance | None = None,
) -> ServiceEventStatistics:
    """Compute statistics from service event records."""
    if not records:
        return ServiceEventStatistics(
            total_records=0,
            by_unit={},
            by_event_type={},
            by_period={},
            frequency_per_unit={},
            provenance=provenance,
        )

    # Group by unit
    by_unit: dict[str, int] = {}
    unit_counts: dict[str, int] = defaultdict(int)
    for r in records:
        key = r.unit_name or "unknown"
        unit_counts[key] += 1
    by_unit = dict(unit_counts)

    # Group by event type
    by_event_type: dict[str, int] = {}
    if group_by == "event_name" or group_by is None:
        event_groups: dict[str, int] = defaultdict(int)
        for r in records:
            key = r.event_name or "unknown"
            event_groups[key] += 1
        by_event_type = dict(event_groups)

    # Group by period
    by_period: dict[str, int] = {}
    if group_by in ("day", "week", "month"):
        period_groups: dict[str, int] = defaultdict(int)
        for r in records:
            if r.event_time:
                if group_by == "day":
                    key = r.event_time.strftime("%Y-%m-%d")
                elif group_by == "week":
                    key = r.event_time.strftime("%Y-W%U")
                else:  # month
                    key = r.event_time.strftime("%Y-%m")
                period_groups[key] += 1
        by_period = dict(sorted(period_groups.items()))

    # Frequency per unit (events per day)
    frequency_per_unit: dict[str, float] = {}
    if records:
        # Calculate time span in days
        times = [r.event_time for r in records if r.event_time]
        if len(times) >= 2:
            min_time = min(times)
            max_time = max(times)
            span_days = max((max_time - min_time).total_seconds() / 86400.0, 1.0)
            for unit, count in unit_counts.items():
                frequency_per_unit[unit] = count / span_days

    return ServiceEventStatistics(
        total_records=len(records),
        by_unit=by_unit,
        by_event_type=by_event_type,
        by_period=by_period,
        frequency_per_unit=frequency_per_unit,
        provenance=provenance,
    )


def detect_service_event_anomalies(
    records: tuple[ServiceEventDetail, ...],
    threshold: float = 2.0,
    provenance: Provenance | None = None,
) -> tuple[ServiceEventAnomaly, ...]:
    """Detect anomalies in service event records.

    Detection methods:
    1. Frequency spike: events/day exceeds rolling avg + N * std_dev
    2. New event type: event_name not seen in baseline period
    3. High frequency unit: unit has disproportionate event count
    """
    if not records:
        return ()

    anomalies: list[ServiceEventAnomaly] = []

    # Group events by day
    events_by_day: dict[str, int] = defaultdict(int)
    for r in records:
        if r.event_time:
            day_key = r.event_time.strftime("%Y-%m-%d")
            events_by_day[day_key] += 1

    # 1. Frequency spike detection
    if len(events_by_day) >= 3:
        daily_counts = list(events_by_day.values())
        avg_count = mean(daily_counts)
        std_count = stdev(daily_counts) if len(daily_counts) > 1 else 0.0
        spike_threshold = avg_count + threshold * std_count

        for day, count in events_by_day.items():
            if count > spike_threshold and std_count > 0:
                deviation = (count - avg_count) / std_count
                severity = "high" if deviation > 3.0 else "medium" if deviation > 2.0 else "low"
                anomalies.append(
                    ServiceEventAnomaly(
                        anomaly_type="frequency_spike",
                        unit_name=None,
                        event_name=None,
                        description=f"事件频率突增: {day} 发生 {count} 次 (均值 {avg_count:.1f}, 阈值 {spike_threshold:.1f})",
                        severity=severity,
                        event_count=count,
                        baseline_count=int(avg_count),
                        deviation_ratio=deviation,
                        provenance=provenance,
                    )
                )

    # 2. New event type detection
    if len(records) >= 10:
        # Use first 70% as baseline
        baseline_size = int(len(records) * 0.7)
        baseline_events = records[:baseline_size]
        recent_events = records[baseline_size:]

        baseline_types = {r.event_name for r in baseline_events if r.event_name}
        for r in recent_events:
            if r.event_name and r.event_name not in baseline_types:
                anomalies.append(
                    ServiceEventAnomaly(
                        anomaly_type="new_event_type",
                        unit_name=r.unit_name,
                        event_name=r.event_name,
                        description=f"新事件类型: '{r.event_name}' 在基线期内未出现",
                        severity="medium",
                        event_count=1,
                        provenance=provenance,
                    )
                )
                baseline_types.add(r.event_name)  # Avoid duplicate reports

    # 3. High frequency unit detection
    unit_counts: dict[str, int] = defaultdict(int)
    for r in records:
        if r.unit_name:
            unit_counts[r.unit_name] += 1

    if len(unit_counts) >= 3:
        counts = list(unit_counts.values())
        median_count = median(counts)
        high_freq_threshold = median_count * 2.0

        for unit, count in unit_counts.items():
            if count > high_freq_threshold and median_count > 0:
                ratio = count / median_count
                severity = "high" if ratio > 3.0 else "medium"
                anomalies.append(
                    ServiceEventAnomaly(
                        anomaly_type="high_frequency_unit",
                        unit_name=unit,
                        event_name=None,
                        description=f"高频机组: '{unit}' 事件数 {count} 次 (中位数 {median_count:.1f}, 比值 {ratio:.2f})",
                        severity=severity,
                        event_count=count,
                        baseline_count=int(median_count),
                        deviation_ratio=ratio,
                        provenance=provenance,
                    )
                )

    return tuple(anomalies)
