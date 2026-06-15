"""Self-contained KPI aggregation functions for daily report scripts.

Pure functions — no I/O, no integrations imports.
Ported from ``deerflow.integrations.adapters.ins.kpi_aggregator``.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

__all__ = [
    "aggregate_trend_to_kpi",
    "hourly_runtime_rate",
    "aggregate_equipment_kpis",
    "compute_hourly_runtime_rate",
    "KPI_FEATURE_MAP",
]

# ---------------------------------------------------------------------------
# KPI feature map — declares HOW each report KPI is derived from trend rows
# ---------------------------------------------------------------------------

KPI_FEATURE_MAP: dict[str, dict[str, Any]] = {
    "vibration_velocity_rms": {
        "feature": "v_rms",
        "derivation": "mean",
    },
    "vibration_acceleration_peak": {
        "feature": "a_peak",
        "derivation": "mean",
    },
    "kurtosis_index": {
        "feature": "kurtosis",
        "derivation": "mean",
    },
    "vibration_level": {
        "feature": "pp_value",
        "derivation": "mean",
    },
    "bearing_temp": {
        "feature": "value",
        "feature_aliases": ["temperature"],
        "derivation": "mean",
        "value_scale": 0.01,
    },
    "valve_temp": {
        "feature": "value",
        "feature_aliases": ["temperature"],
        "derivation": "mean",
        "value_scale": 0.01,
    },
    "flow_rate": {
        "feature": "value",
        "feature_aliases": ["flow"],
        "derivation": "mean",
    },
    "outlet_pressure": {
        "feature": "value",
        "feature_aliases": ["pressure"],
        "derivation": "mean",
    },
    "runtime_rate": {
        "feature": "speed",
        "derivation": "runtime_rate",
    },
    "alarm_count": {
        "feature": "pp_value",
        "feature_aliases": ["v_rms"],
        "derivation": "alarm_count",
        "alarm_tier": "C",
    },
    "downtime_count": {
        "feature": "speed",
        "derivation": "downtime_count",
    },
    "corrosion_rate": {
        "feature": "corrosionRate",
        "derivation": "mean",
    },
    "thickness_loss": {
        "feature": "thickness",
        "derivation": "thickness_loss",
    },
}

# ---------------------------------------------------------------------------
# Row extraction helpers
# ---------------------------------------------------------------------------


def _row_value(row: dict[str, Any], feature: str) -> float | None:
    """Pull one numeric ``feature`` from a unified trend row."""
    if not isinstance(row, dict):
        return None
    values = row.get("values")
    if isinstance(values, dict) and feature in values:
        v = values[feature]
    else:
        v = row.get(feature)
    if v is None:
        return None
    if isinstance(v, (int, float)) and not (isinstance(v, float) and math.isnan(v)):
        return float(v)
    return None


def _row_first_value(row: dict[str, Any], features: list[str]) -> float | None:
    """Return the first non-null value from a list of feature candidates."""
    for feature in features:
        value = _row_value(row, feature)
        if value is not None:
            return value
    return None


def _row_time_ms(row: dict[str, Any]) -> int | None:
    """Extract timestamp in milliseconds from a trend row."""
    if not isinstance(row, dict):
        return None
    raw = row.get("time_ms") or row.get("datatime") or row.get("time")
    if isinstance(raw, (int, float)):
        return int(raw)
    if isinstance(raw, str) and raw.isdigit():
        return int(raw)
    return None


def _resolve_alarm_threshold(
    point_meta: dict[str, Any],
    feature: str,
    tier: str,
) -> float | None:
    """Pull a numeric threshold for a given (feature, tier)."""
    thresholds = point_meta.get("alarm_thresholds") or {}
    feature_tiers = thresholds.get(feature) or {}
    raw = feature_tiers.get(tier)
    if raw is None and point_meta.get("endpoint_series") == "8k":
        if tier == "C":
            raw = point_meta.get("h_alarm")
        elif tier == "D":
            raw = point_meta.get("hh_alarm")
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, str):
        try:
            return float(raw)
        except ValueError:
            return None
    return None


def _feature_candidates_for_spec(spec: dict[str, Any]) -> list[str]:
    """Return deduplicated list of feature name candidates (primary + aliases)."""
    names = [spec["feature"], *(spec.get("feature_aliases") or [])]
    seen: set[str] = set()
    deduped: list[str] = []
    for name in names:
        if not isinstance(name, str) or not name or name in seen:
            continue
        seen.add(name)
        deduped.append(name)
    return deduped


# ---------------------------------------------------------------------------
# Aggregation: trend rows → single KPI scalar / 24-bucket hourly array
# ---------------------------------------------------------------------------


def aggregate_trend_to_kpi(
    rows: list[dict[str, Any]],
    kpi_key: str,
    point_meta: dict[str, Any] | None = None,
) -> float | int | None:
    """Reduce a list of trend rows to one KPI scalar.

    Supports 6 derivation methods:
    - mean: arithmetic mean of non-null values
    - max: maximum of non-null values
    - runtime_rate: fraction of speed > 0 samples
    - downtime_count: count of speed > 0 → 0 falling edges
    - alarm_count: count of values exceeding the point's alarm threshold
    - thickness_loss: difference between first and last thickness reading
    """
    spec = KPI_FEATURE_MAP.get(kpi_key)
    if spec is None:
        raise ValueError(f"unmappable KPI key: {kpi_key!r}")

    feature_candidates = _feature_candidates_for_spec(spec)
    derivation = spec["derivation"]
    scale = spec.get("value_scale", 1.0)
    values = [
        v * scale if scale != 1.0 else v
        for v in (_row_first_value(r, feature_candidates) for r in rows)
        if v is not None
    ]

    if derivation == "mean":
        if not values:
            return None
        return round(sum(values) / len(values), 4)

    if derivation == "max":
        return round(max(values), 4) if values else None

    if derivation == "runtime_rate":
        if not values:
            return None
        running = sum(1 for v in values if v > 0)
        return round(running / len(values), 4)

    if derivation == "downtime_count":
        prev: float | None = None
        falls = 0
        for v in values:
            if prev is not None and prev > 0 and v <= 0:
                falls += 1
            prev = v
        return falls

    if derivation == "alarm_count":
        if point_meta is None:
            return 0
        tier = spec.get("alarm_tier", "C")
        feature = spec["feature"]
        threshold = _resolve_alarm_threshold(point_meta, feature, tier)
        if threshold is None:
            return 0
        return sum(1 for v in values if v > threshold)

    if derivation == "thickness_loss":
        if len(values) < 2:
            return 0.0 if values else None
        return round(values[0] - values[-1], 4)

    return None


def hourly_runtime_rate(rows: list[dict[str, Any]]) -> list[float]:
    """Bucket ``speed > 0`` ratios into 24 hourly slots. Empty hours emit 0.0."""
    buckets: list[list[float]] = [[] for _ in range(24)]
    for row in rows:
        ts_ms = _row_time_ms(row)
        speed = _row_value(row, "speed")
        if ts_ms is None or speed is None:
            continue
        try:
            hour = datetime.fromtimestamp(ts_ms / 1000).hour
        except (OSError, OverflowError, ValueError):
            continue
        buckets[hour].append(1.0 if speed > 0 else 0.0)
    return [round(sum(b) / len(b), 4) if b else 0.0 for b in buckets]


# ---------------------------------------------------------------------------
# Multi-equipment aggregation
# ---------------------------------------------------------------------------


def aggregate_equipment_kpis(
    trend_data_by_equipment: dict[str, list[dict[str, Any]]],
    kpi_keys: list[str],
    point_metadata: dict[str, dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Aggregate KPIs for multiple equipment from pre-fetched trend data.

    Returns:
        ``(kpis_by_equipment, union_speed_rows)``
    """
    kpis_by_equipment: dict[str, dict[str, Any]] = {}
    union_speed_rows: list[dict[str, Any]] = []

    for equipment_id, rows in trend_data_by_equipment.items():
        eq_kpis: dict[str, Any] = {}
        speed_rows_collected = False
        for kpi_key in kpi_keys:
            spec = KPI_FEATURE_MAP.get(kpi_key)
            if spec is None:
                eq_kpis[kpi_key] = None
                continue

            point_meta = None
            if spec["derivation"] == "alarm_count":
                for pt_id, pt_meta in point_metadata.items():
                    if pt_meta.get("alarm_thresholds"):
                        point_meta = pt_meta
                        break

            value = aggregate_trend_to_kpi(rows, kpi_key, point_meta)
            eq_kpis[kpi_key] = value

            if spec["feature"] == "speed" and not speed_rows_collected:
                union_speed_rows.extend(rows)
                speed_rows_collected = True

        kpis_by_equipment[equipment_id] = eq_kpis

    return kpis_by_equipment, union_speed_rows


def compute_hourly_runtime_rate(
    union_speed_rows: list[dict[str, Any]],
) -> list[float]:
    """Compute 24-hour runtime rate from union of speed rows across equipment."""
    return hourly_runtime_rate(union_speed_rows)
