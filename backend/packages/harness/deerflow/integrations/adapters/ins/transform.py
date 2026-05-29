"""Transform functions: Ins responses → canonical models.

Pure functions that transform Ins-specific response shapes into
platform canonical models, populating source_metadata and provenance.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from deerflow.integrations.models.asset import Asset, AssetContext, MeasurementPoint
from deerflow.integrations.models.monitoring import (
    AlarmEvent,
    OrbitPayload,
    TimeRange,
    TrendPoint,
    TrendSeries,
    TrendStatistics,
    WaveformPayload,
)
from deerflow.integrations.models.provenance import Provenance


def _build_provenance(
    system_key: str,
    capability_key: str,
    query_params: dict[str, Any] | None = None,
) -> Provenance:
    """Build a Provenance instance for Ins data."""
    return Provenance(
        source_system_key=system_key,
        source_system_type="ins",
        capability_key=capability_key,
        fetched_at=datetime.now(),
        query_params=query_params or {},
    )


def transform_asset_catalog(
    raw_data: dict[str, Any],
    system_key: str,
) -> tuple[Asset, ...]:
    """Transform MachineServiceClient.get_machine_detail_info() to Asset tuple.

    Args:
        raw_data: Response from get_machine_detail_info (AjaxResult wrapper).
        system_key: The system key for provenance.

    Returns:
        Tuple of Asset instances.
    """
    provenance = _build_provenance(system_key, "asset.catalog")
    records = raw_data.get("records") or raw_data.get("list") or []
    if isinstance(raw_data, list):
        records = raw_data

    assets: list[Asset] = []
    for rec in records:
        asset = Asset(
            asset_id=str(rec.get("macId") or rec.get("id") or ""),
            asset_code=str(rec.get("macCode") or rec.get("code") or ""),
            asset_name=str(rec.get("macName") or rec.get("name") or ""),
            asset_type=str(rec.get("macTypeName") or rec.get("typeName") or "unknown"),
            status=str(rec.get("macStatus") or "active"),
            location=str(rec.get("location") or rec.get("deviceName") or ""),
            manufacturer=str(rec.get("producer") or ""),
            model=str(rec.get("macModel") or rec.get("model") or ""),
            serial_number=str(rec.get("serialNumber") or ""),
            description=str(rec.get("description") or ""),
            source_metadata={
                "raw_status": rec.get("macStatus"),
                "alarm_status": rec.get("alarmStatus"),
                "org_id": rec.get("orgId"),
            },
            provenance=provenance,
        )
        assets.append(asset)

    return tuple(assets)


def transform_asset_context(
    raw_data: dict[str, Any],
    system_key: str,
) -> AssetContext:
    """Transform equipment context response to AssetContext.

    Args:
        raw_data: Combined response with equipment + components + children.
        system_key: The system key for provenance.

    Returns:
        AssetContext instance.
    """
    provenance = _build_provenance(system_key, "asset.context")

    # Build primary asset
    asset = Asset(
        asset_id=str(raw_data.get("macId") or raw_data.get("id") or ""),
        asset_code=str(raw_data.get("macCode") or raw_data.get("code") or ""),
        asset_name=str(raw_data.get("macName") or raw_data.get("name") or ""),
        asset_type=str(raw_data.get("macTypeName") or "unknown"),
        status=str(raw_data.get("macStatus") or "active"),
        location=str(raw_data.get("location") or ""),
        manufacturer=str(raw_data.get("producer") or ""),
        model=str(raw_data.get("macModel") or ""),
        source_metadata={"raw": {k: v for k, v in raw_data.items() if not isinstance(v, (list, dict))}},
        provenance=provenance,
    )

    # Build measurement points from components
    measurement_points: list[MeasurementPoint] = []
    for comp in raw_data.get("components") or []:
        mp = MeasurementPoint(
            point_id=str(comp.get("id") or ""),
            point_code=str(comp.get("code") or comp.get("posCode") or ""),
            point_name=str(comp.get("name") or comp.get("posName") or ""),
            point_type=str(comp.get("endpoint_series") or "unknown"),
            unit=str(comp.get("unit") or ""),
            direction=str(comp.get("direction") or ""),
            description=str(comp.get("description") or ""),
            extra={
                "position_type": comp.get("position_type"),
                "alarm_thresholds": comp.get("alarm_thresholds"),
            },
        )
        if mp.point_id:
            measurement_points.append(mp)

    # Build child assets
    child_assets: list[Asset] = []
    for child in raw_data.get("children") or []:
        child_asset = Asset(
            asset_id=str(child.get("macId") or child.get("id") or ""),
            asset_code=str(child.get("macCode") or ""),
            asset_name=str(child.get("macName") or child.get("name") or ""),
            asset_type=str(child.get("macTypeName") or "unknown"),
            status=str(child.get("macStatus") or "active"),
            provenance=provenance,
        )
        if child_asset.asset_id:
            child_assets.append(child_asset)

    return AssetContext(
        asset=asset,
        parent_asset_id=str(raw_data.get("parentId")) if raw_data.get("parentId") else None,
        child_assets=tuple(child_assets),
        measurement_points=tuple(measurement_points),
        operational_context={
            "org_id": raw_data.get("orgId"),
            "alarm_status": raw_data.get("alarmStatus"),
        },
        provenance=provenance,
    )


def transform_trend_series(
    raw_rows: list[dict[str, Any]],
    query: Any,
    system_key: str,
) -> TrendSeries:
    """Transform Ins trend data rows to TrendSeries.

    Args:
        raw_rows: List of trend rows from Ins API.
        query: The original TrendQuery.
        system_key: The system key for provenance.

    Returns:
        TrendSeries instance.
    """
    provenance = _build_provenance(
        system_key,
        "monitoring.trend",
        query_params={"asset_id": getattr(query, "asset_id", ""), "measurement_point_id": getattr(query, "measurement_point_id", "")},
    )

    points: list[TrendPoint] = []
    values: list[float] = []
    for row in raw_rows:
        ts = _extract_timestamp(row)
        val = _extract_numeric(row, "value")
        if ts is not None and val is not None:
            points.append(TrendPoint(timestamp=ts, value=val))
            values.append(val)

    statistics = None
    if values:
        statistics = TrendStatistics(
            min_value=min(values),
            max_value=max(values),
            avg_value=round(sum(values) / len(values), 4),
            std_dev=_compute_std_dev(values),
            sample_count=len(values),
        )

    time_range = None
    if hasattr(query, "start_time") and hasattr(query, "end_time"):
        time_range = TimeRange(start=query.start_time, end=query.end_time)

    return TrendSeries(
        series_id=f"{getattr(query, 'asset_id', '')}:{getattr(query, 'measurement_point_id', '')}",
        asset_id=str(getattr(query, "asset_id", "")),
        measurement_point_id=str(getattr(query, "measurement_point_id", "")),
        points=tuple(points),
        statistics=statistics,
        time_range=time_range,
        unit=str(getattr(query, "extra_params", {}).get("unit", "")),
        source_metadata={"row_count": len(raw_rows)},
        provenance=provenance,
    )


def transform_waveform(
    raw_data: dict[str, Any],
    query: Any,
    system_key: str,
) -> WaveformPayload:
    """Transform Ins waveform response to WaveformPayload.

    Args:
        raw_data: Waveform data from Ins API.
        query: The original WaveformQuery.
        system_key: The system key for provenance.

    Returns:
        WaveformPayload instance.
    """
    provenance = _build_provenance(
        system_key,
        "monitoring.waveform",
        query_params={"asset_id": getattr(query, "asset_id", "")},
    )

    wave_x = tuple(float(v) for v in (raw_data.get("waveX") or raw_data.get("wave_x") or []))
    wave_y = tuple(float(v) for v in (raw_data.get("waveY") or raw_data.get("wave_y") or []))
    spec_x = tuple(float(v) for v in (raw_data.get("specX") or raw_data.get("spec_x") or []))
    spec_y = tuple(float(v) for v in (raw_data.get("specY") or raw_data.get("spec_y") or []))

    captured_at = None
    raw_ts = raw_data.get("capturedAt") or raw_data.get("datatime")
    if raw_ts:
        captured_at = _parse_timestamp(raw_ts)

    return WaveformPayload(
        waveform_id=str(raw_data.get("id") or f"{getattr(query, 'asset_id', '')}:{getattr(query, 'measurement_point_id', '')}"),
        asset_id=str(getattr(query, "asset_id", "")),
        measurement_point_id=str(getattr(query, "measurement_point_id", "")),
        wave_x=wave_x,
        wave_y=wave_y,
        spec_x=spec_x,
        spec_y=spec_y,
        speed_rpm=float(raw_data["speedRpm"]) if raw_data.get("speedRpm") is not None else None,
        sample_rate=float(raw_data["sampleRate"]) if raw_data.get("sampleRate") is not None else None,
        captured_at=captured_at,
        source_metadata={"wave_length": len(wave_y), "spec_length": len(spec_y)},
        provenance=provenance,
    )


def transform_orbit(
    raw_data: dict[str, Any],
    query: Any,
    system_key: str,
) -> OrbitPayload:
    """Transform Ins orbit response to OrbitPayload.

    Args:
        raw_data: Orbit data from Ins API.
        query: The original OrbitQuery.
        system_key: The system key for provenance.

    Returns:
        OrbitPayload instance.
    """
    provenance = _build_provenance(
        system_key,
        "monitoring.orbit",
        query_params={"asset_id": getattr(query, "asset_id", "")},
    )

    probe_ids = tuple(str(p) for p in (raw_data.get("probeIds") or []))
    points = tuple(
        (float(p[0]), float(p[1]))
        for p in (raw_data.get("points") or [])
        if len(p) >= 2
    )
    points_1x = tuple(
        (float(p[0]), float(p[1]))
        for p in (raw_data.get("points1x") or [])
        if len(p) >= 2
    )
    points_2x = tuple(
        (float(p[0]), float(p[1]))
        for p in (raw_data.get("points2x") or [])
        if len(p) >= 2
    )

    captured_at = None
    raw_ts = raw_data.get("capturedAt") or raw_data.get("datatime")
    if raw_ts:
        captured_at = _parse_timestamp(raw_ts)

    return OrbitPayload(
        orbit_id=str(raw_data.get("id") or f"{getattr(query, 'asset_id', '')}:{getattr(query, 'measurement_point_id', '')}"),
        asset_id=str(getattr(query, "asset_id", "")),
        measurement_point_id=str(getattr(query, "measurement_point_id", "")),
        probe_ids=probe_ids,
        points=points,
        points_1x=points_1x,
        points_2x=points_2x,
        speed_rpm=float(raw_data["speedRpm"]) if raw_data.get("speedRpm") is not None else None,
        captured_at=captured_at,
        source_metadata={"point_count": len(points)},
        provenance=provenance,
    )


def transform_alarm_history(
    raw_events: list[dict[str, Any]],
    system_key: str,
    asset_id: str = "",
) -> tuple[AlarmEvent, ...]:
    """Transform Ins machine drop events to AlarmEvent tuple.

    Args:
        raw_events: Raw event data from Ins getMachineDrops.
        system_key: The system key for provenance.
        asset_id: Asset ID for provenance.

    Returns:
        Tuple of AlarmEvent instances.
    """
    from deerflow.integrations.adapters.ins.kpi_map import EVENT_TYPE_MAP

    provenance = _build_provenance(
        system_key,
        "monitoring.alarm_history",
        query_params={"asset_id": asset_id},
    )

    alarms: list[AlarmEvent] = []
    for entry in raw_events:
        types: list[int] = entry.get("types") or []
        if not types:
            continue
        primary_type = types[0]
        label, severity = EVENT_TYPE_MAP.get(
            primary_type, (f"未知事件({primary_type})", "info")
        )

        datatime = entry.get("datatime")
        triggered_at = _parse_timestamp(datatime) or datetime.now()

        ended_at = None
        ended_raw = entry.get("endedAt")
        if ended_raw:
            ended_at = _parse_timestamp(ended_raw)

        duration_seconds = None
        if ended_at and triggered_at:
            duration_seconds = (ended_at - triggered_at).total_seconds()

        pos_name = str(entry.get("posName") or entry.get("posId") or "")
        pos_id = str(entry.get("posId") or "")

        alarm = AlarmEvent(
            event_id=str(entry.get("id") or f"{pos_id}:{triggered_at.timestamp()}"),
            asset_id=asset_id or pos_id,
            event_type=label,
            severity=severity,
            message=f"[{label}] {pos_name}",
            triggered_at=triggered_at,
            ended_at=ended_at,
            duration_seconds=duration_seconds,
            source_metadata={
                "pos_id": pos_id,
                "event_type_code": primary_type,
            },
            provenance=provenance,
        )
        alarms.append(alarm)

    return tuple(alarms)


# --- Helper functions ---

def _extract_timestamp(row: dict[str, Any]) -> datetime | None:
    """Extract timestamp from a trend row."""
    raw = row.get("time_ms") or row.get("datatime") or row.get("time")
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        try:
            return datetime.fromtimestamp(raw / 1000 if raw > 1e12 else raw)
        except (OSError, OverflowError, ValueError):
            return None
    if isinstance(raw, str) and raw.isdigit():
        return _extract_timestamp({"time": int(raw)})
    return None


def _extract_numeric(row: dict[str, Any], key: str) -> float | None:
    """Extract a numeric value from a row, handling nested 'values' dict."""
    values = row.get("values")
    if isinstance(values, dict) and key in values:
        v = values[key]
    else:
        v = row.get(key)
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    return None


def _parse_timestamp(raw: Any) -> datetime | None:
    """Parse various timestamp formats."""
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw
    if isinstance(raw, (int, float)):
        try:
            return datetime.fromtimestamp(raw / 1000 if raw > 1e12 else raw)
        except (OSError, OverflowError, ValueError):
            return None
    if isinstance(raw, str):
        if raw.isdigit():
            return _parse_timestamp(int(raw))
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(raw, fmt)
            except ValueError:
                continue
    return None


def _compute_std_dev(values: list[float]) -> float | None:
    """Compute standard deviation."""
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    variance = sum((x - mean) ** 2 for x in values) / (len(values) - 1)
    return round(variance ** 0.5, 4)
