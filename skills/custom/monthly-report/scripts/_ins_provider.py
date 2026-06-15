"""InS (神固云) provider for monthly equipment reports.

This adapter sits between query_monthly.py and the features-tool ``InsApiClient``.

Architecture:
    1. ``_KPI_FEATURE_MAP`` declares how every KPI is sourced from InS endpoint
       families: 2K (pump vibration), 6K (corrosion), 8K/9K (rotating/reciprocating).

    2. ``_select_points_for_kpi`` walks the slim component tree, filters by
       ``positionType`` + name keywords, returns each point's metadata.

    3. ``_aggregate_trend_to_kpi`` collapses raw trend rows into a single KPI value.

    4. ``_async_fetch_daily_series_payload`` fetches consecutive day payloads
       reusing one InS client + component cache across all days.

    5. ``fetch_daily_series_payload`` is the sync wrapper consumed by
       ``InsMonthlyProvider``. Any failure surfaces as ``HttpProviderError``.

The module is designed to be **importable even when features-tool is not on
the path** (e.g. unit tests outside the sandbox). In that case
``_FEATURES_TOOL_AVAILABLE`` is ``False`` and any call raises
``HttpProviderError`` immediately.
"""
from __future__ import annotations

import asyncio
import importlib.util
import math
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Optional features-tool import — keep import-time failures non-fatal so
# unit tests outside the sandbox can still import this module.
# ---------------------------------------------------------------------------

_FEATURES_TOOL_ROOT = os.environ.get("FEATURES_TOOL_ROOT", "/opt/features-tool")
if _FEATURES_TOOL_ROOT and _FEATURES_TOOL_ROOT not in sys.path:
    sys.path.insert(0, _FEATURES_TOOL_ROOT)

try:
    from ins import InsApiClient, load_ins_settings  # type: ignore[import-not-found]
    _FEATURES_TOOL_AVAILABLE = True
    _FEATURES_TOOL_IMPORT_ERROR: str | None = None
except Exception as exc:  # noqa: BLE001 - import path may legitimately fail
    InsApiClient = None  # type: ignore[assignment, misc]
    load_ins_settings = None  # type: ignore[assignment]
    _FEATURES_TOOL_AVAILABLE = False
    _FEATURES_TOOL_IMPORT_ERROR = f"{type(exc).__name__}: {exc}"

# Attempt to import HttpProviderError from sibling _data_providers; if this
# module is loaded standalone (e.g. importlib.util.spec_from_file_location
# without _data_providers on sys.path), fall back to RuntimeError.
try:
    from _data_providers import HttpProviderError  # type: ignore[import-not-found]
except Exception:
    class HttpProviderError(RuntimeError):  # type: ignore[no-redef]
        pass

# Optional INS_FACTORY_ID — every ``get_trend_data`` call passes it through.
_INS_FACTORY_ID: str | None = os.environ.get("INS_FACTORY_ID") or None
INS_CONCURRENCY_LIMIT: int = int(os.environ.get("INS_CONCURRENCY_LIMIT", "4"))

# ---------------------------------------------------------------------------
# KPI feature map — declares HOW each report KPI is sourced from InS
# ---------------------------------------------------------------------------
#
# Each entry's keys:
#   position_types : iterable of positionType ints to match (None = match any)
#   feature        : the InS feature column name to fetch (8k/9k field, 2k
#                    Chinese-name-mapped key, or 6k key like ``corrosionRate``)
#   feature_aliases: optional fallback feature names to request/read when the
#                    primary feature is absent in a given endpoint family
#   expected_series: "2k" / "6k" / "8k" / "9k" (used to bucket trend calls)
#   derivation     : how to roll up multiple samples into one KPI scalar
#                    one of: "mean" | "max" | "alarm_count" | "runtime_rate" |
#                    "downtime_count" | "thickness_loss"
#   alarm_tier     : (2k only) which threshold tier ``B`` / ``C`` / ``D`` to
#                    use for ``alarm_count``; defaults to ``"C"``
#   name_keywords  : optional list of substrings to further narrow point
#                    selection by Chinese name (used when positionType
#                    ranges overlap multiple physical signals)
#
# ---------------------------------------------------------------------------
# Machine drop event type → (label, severity_level) mapping.
# 8K (rotating_machinery) supports all 18 types.
# 9K (reciprocating_machinery) supports types 1,2,3,14,15 only.
# ---------------------------------------------------------------------------
_EVENT_TYPE_MAP: dict[int, tuple[str, str]] = {
    1: ("主报警", "high"),
    2: ("预报警", "warning"),
    3: ("启停机", "info"),
    4: ("黑匣子", "info"),
    5: ("正反进动", "info"),
    6: ("通频值/过程量偏差", "warning"),
    7: ("1X偏差", "warning"),
    8: ("2X偏差", "warning"),
    9: ("0.5X偏差", "warning"),
    10: ("可选偏差", "warning"),
    11: ("残余量偏差", "warning"),
    12: ("振动波动", "warning"),
    13: ("诊断事件", "info"),
    14: ("预警", "warning"),
    15: ("偏差报警", "high"),
    16: ("诊断事件-D", "info"),
    17: ("诊断事件-C", "info"),
    18: ("诊断事件-B", "info"),
}

_EVENT_TYPES_8K: tuple[int, ...] = tuple(range(1, 19))
_EVENT_TYPES_9K: tuple[int, ...] = (1, 2, 3, 14, 15)

_EVENT_TYPES_BY_EQ_TYPE: dict[str, tuple[int, ...]] = {
    "rotating_machinery": _EVENT_TYPES_8K,
    "reciprocating_machinery": _EVENT_TYPES_9K,
}

_MACHINE_DROPS_PATH_BY_SERIES: dict[str, str] = {
    "8k": "ins-os-view/sg8kData/getMachineDrops",
    "9k": "ins-os-view/sg9kData/getMachineDrops",
}

_RM_POSITION_TYPES = tuple(range(81, 84))
_RC_POSITION_TYPES = tuple(range(91, 100))
_RM_RC_POSITION_TYPES = _RM_POSITION_TYPES + _RC_POSITION_TYPES


_KPI_FEATURE_MAP: dict[str, dict[str, Any]] = {
    # ---- 2K vibration (multi-feature, machine 4 = PUMP) ----
    # PositionType 22 carries temperature ("当前值"), 23-30 carry vibration.
    "vibration_velocity_rms": {
        "position_types": tuple(range(22, 31)),
        "position_types_by_type": {
            "pump": tuple(range(23, 31)),
        },
        "feature": "v_rms",
        "expected_series": "2k",
        "derivation": "mean",
    },
    "vibration_acceleration_peak": {
        "position_types": tuple(range(22, 31)),
        "position_types_by_type": {
            "pump": tuple(range(23, 31)),
        },
        "feature": "a_peak",
        "expected_series": "2k",
        "derivation": "mean",
    },
    "kurtosis_index": {
        "position_types": tuple(range(22, 31)),
        "position_types_by_type": {
            "pump": tuple(range(23, 31)),
        },
        "feature": "kurtosis",
        "expected_series": "2k",
        "derivation": "mean",
    },

    # ---- 8K / 9K rotating / reciprocating KPIs ----
    # Business mapping is explicit: rotating_machinery => 8k, and
    # reciprocating_machinery => 9k. We still keep the tuple fallback for
    # mixed/all selections, because the InS field schemas for pp_value /
    # speed / temperature / flow / pressure are identical between 8k and 9k.
    "vibration_level": {
        "position_types": _RM_RC_POSITION_TYPES,
        "position_types_by_type": {
            "rotating_machinery": _RM_POSITION_TYPES,
            "reciprocating_machinery": _RC_POSITION_TYPES,
        },
        "feature": "pp_value",
        "expected_series": ("8k", "9k"),
        "expected_series_by_type": {
            "rotating_machinery": "8k",
            "reciprocating_machinery": "9k",
        },
        "derivation": "mean",
    },
    "bearing_temp": {
        "position_types": (22,) + _RM_RC_POSITION_TYPES,
        "position_types_by_type": {
            "rotating_machinery": _RM_POSITION_TYPES,
            "reciprocating_machinery": _RC_POSITION_TYPES,
            "pump": (22,),
        },
        "feature": "value",
        "feature_aliases": ["temperature"],
        "name_keywords": ["轴承"],
        "name_keywords_by_type": {
            "all": [],  # when type is undetermined, don't filter by name
            "pump": [],
        },
        "expected_series": ("2k", "8k", "9k"),
        "expected_series_by_type": {
            "rotating_machinery": "8k",
            "reciprocating_machinery": "9k",
            "pump": "2k",
        },
        "derivation": "mean",
        "value_scale": 0.01,
    },
    "valve_temp": {
        "position_types": _RM_RC_POSITION_TYPES,
        "position_types_by_type": {
            "rotating_machinery": _RM_POSITION_TYPES,
            "reciprocating_machinery": _RC_POSITION_TYPES,
        },
        "feature": "value",
        "feature_aliases": ["temperature"],
        "name_keywords": ["阀", "气缸"],
        "expected_series": ("8k", "9k"),
        "expected_series_by_type": {
            "rotating_machinery": "8k",
            "reciprocating_machinery": "9k",
        },
        "derivation": "mean",
        "value_scale": 0.01,
    },
    "flow_rate": {
        "position_types": _RM_RC_POSITION_TYPES,
        "position_types_by_type": {
            "rotating_machinery": _RM_POSITION_TYPES,
            "reciprocating_machinery": _RC_POSITION_TYPES,
        },
        "feature": "value",
        "feature_aliases": ["flow"],
        "expected_series": ("8k", "9k"),
        "expected_series_by_type": {
            "rotating_machinery": "8k",
            "reciprocating_machinery": "9k",
        },
        "derivation": "mean",
    },
    "outlet_pressure": {
        "position_types": _RM_RC_POSITION_TYPES,
        "position_types_by_type": {
            "rotating_machinery": _RM_POSITION_TYPES,
            "reciprocating_machinery": _RC_POSITION_TYPES,
        },
        "feature": "value",
        "feature_aliases": ["pressure"],
        "name_keywords": ["出口"],
        "expected_series": ("8k", "9k"),
        "expected_series_by_type": {
            "rotating_machinery": "8k",
            "reciprocating_machinery": "9k",
        },
        "derivation": "mean",
    },
    "runtime_rate": {
        "position_types": _RM_RC_POSITION_TYPES,
        "position_types_by_type": {
            "rotating_machinery": _RM_POSITION_TYPES,
            "reciprocating_machinery": _RC_POSITION_TYPES,
        },
        "feature": "speed",
        "expected_series": ("8k", "9k"),
        "expected_series_by_type": {
            "rotating_machinery": "8k",
            "reciprocating_machinery": "9k",
        },
        "derivation": "runtime_rate",
    },
    "alarm_count": {
        "position_types": _RM_RC_POSITION_TYPES,
        "position_types_by_type": {
            "rotating_machinery": _RM_POSITION_TYPES,
            "reciprocating_machinery": _RC_POSITION_TYPES,
        },
        "feature": "pp_value",
        "expected_series": ("8k", "9k"),
        "expected_series_by_type": {
            "rotating_machinery": "8k",
            "reciprocating_machinery": "9k",
        },
        "derivation": "alarm_count",
    },
    "downtime_count": {
        "position_types": _RM_RC_POSITION_TYPES,
        "position_types_by_type": {
            "rotating_machinery": _RM_POSITION_TYPES,
            "reciprocating_machinery": _RC_POSITION_TYPES,
        },
        "feature": "speed",
        "expected_series": ("8k", "9k"),
        "expected_series_by_type": {
            "rotating_machinery": "8k",
            "reciprocating_machinery": "9k",
        },
        "derivation": "downtime_count",
    },

    # ---- 6K corrosion KPIs (machine 6 = PIPELINE) ----
    "corrosion_rate": {
        "position_types": tuple(range(61, 65)),
        "feature": "corrosionRate",
        "expected_series": "6k",
        "derivation": "mean",
    },
    "thickness_loss": {
        "position_types": tuple(range(61, 65)),
        "feature": "thickness",
        "expected_series": "6k",
        "derivation": "thickness_loss",
    },
    "thinning_rate": {
        "position_types": tuple(range(61, 65)),
        "feature": "thinningRate",
        "expected_series": "6k",
        "derivation": "mean",
    },
    "process_temperature": {
        "position_types": tuple(range(61, 65)),
        "feature": "temperature",
        "expected_series": "6k",
        "derivation": "mean",
    },
}


# ---------------------------------------------------------------------------
# Slim-component tree walking
# ---------------------------------------------------------------------------


def _iter_points(components: list[dict[str, Any]]):
    """Yield every point-like node (has ``endpoint_series``) in the tree."""
    stack: list[dict[str, Any]] = list(components)
    while stack:
        node = stack.pop()
        if not isinstance(node, dict):
            continue
        if node.get("endpoint_series") is not None:
            yield node
            continue
        for key in ("children", "points"):
            for child in node.get(key) or []:
                if isinstance(child, dict):
                    stack.append(child)


def _select_points_for_kpi(
    components: list[dict[str, Any]],
    kpi_key: str,
    eq_type: str = "all",
) -> list[dict[str, Any]]:
    """Return all points in ``components`` that match the KPI's filters.

    Each returned dict carries:
        id, endpoint_series, alarm_thresholds (2k tier dict, may be empty),
        h_alarm, hh_alarm (8k legacy thresholds, may be None), name.
    """
    spec = _KPI_FEATURE_MAP.get(kpi_key)
    if spec is None:
        raise HttpProviderError(f"unmappable KPI key: {kpi_key!r}")

    pos_filter = _position_filter_for_spec(spec, eq_type)
    name_keywords: list[str] = _name_keywords_for_spec(spec, eq_type)
    expected = _expected_series_for_spec(spec, eq_type)
    allowed_series: tuple[str, ...] = (
        (expected,) if isinstance(expected, str) else tuple(expected)
    )

    selected: list[dict[str, Any]] = []
    for point in _iter_points(components):
        # ``position_type`` is the point-level selector carried by slim_component.
        # ``type_num`` is the owning node's own type, so it must not be used for
        # point routing.
        series = point.get("endpoint_series")
        if series not in allowed_series:
            continue
        pt_raw = point.get("position_type")
        if isinstance(pos_filter, (tuple, list)) and pt_raw is not None:
            try:
                pt_int = int(pt_raw)
            except (TypeError, ValueError):
                pt_int = None
            if pt_int is not None and pt_int not in pos_filter:
                continue
        elif pt_raw is None:
            pt_raw = point.get("type_num")
            if isinstance(pos_filter, (tuple, list)) and pt_raw is not None:
                try:
                    pt_int = int(pt_raw)
                except (TypeError, ValueError):
                    pt_int = None
                if pt_int is not None and pt_int not in pos_filter:
                    continue

        if name_keywords:
            name = str(point.get("name") or "")
            if not any(kw in name for kw in name_keywords):
                continue

        selected.append({
            "id": str(point.get("id") or ""),
            "endpoint_series": series,
            "alarm_thresholds": dict(point.get("alarm_thresholds") or {}),
            "h_alarm": point.get("h_alarm"),
            "hh_alarm": point.get("hh_alarm"),
            "name": point.get("name"),
        })

    return [p for p in selected if p["id"]]


def _position_filter_for_spec(spec: dict[str, Any], eq_type: str):
    by_type = spec.get("position_types_by_type") or {}
    return by_type.get(eq_type, spec.get("position_types"))


def _name_keywords_for_spec(spec: dict[str, Any], eq_type: str) -> list[str]:
    by_type = spec.get("name_keywords_by_type") or {}
    return by_type.get(eq_type, spec.get("name_keywords") or [])


def _expected_series_for_spec(spec: dict[str, Any], eq_type: str):
    by_type = spec.get("expected_series_by_type") or {}
    return by_type.get(eq_type, spec["expected_series"])


def _feature_candidates_for_spec(spec: dict[str, Any]) -> list[str]:
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


def _row_value(row: dict[str, Any], feature: str) -> float | None:
    """Pull one numeric ``feature`` from a unified trend row.

    Unified row shape (post-wrappers): ``{component_id, time_ms, time, values}``.
    Some 2k/6k flat rows may still have feature at top level — handle both.
    """
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
    for feature in features:
        value = _row_value(row, feature)
        if value is not None:
            return value
    return None


def _row_time_ms(row: dict[str, Any]) -> int | None:
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
    """Pull a numeric threshold for a given (feature, tier).

    For 2k points: read ``point_meta["alarm_thresholds"][feature][tier]``.
    For 8k points: tier C falls back to ``h_alarm``, tier D to ``hh_alarm``.
    """
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


def _aggregate_trend_to_kpi(
    rows: list[dict[str, Any]],
    kpi_key: str,
    point_meta: dict[str, Any] | None = None,
) -> float | int | None:
    """Reduce a list of trend rows to one KPI scalar.

    ``point_meta`` is optional — required only for ``alarm_count`` (to read
    the alarm threshold).
    """
    spec = _KPI_FEATURE_MAP[kpi_key]
    feature = spec["feature"]
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
        # Speed > 0 fraction over all sampled rows that had a numeric speed.
        if not values:
            return None
        running = sum(1 for v in values if v > 0)
        return round(running / len(values), 4)

    if derivation == "downtime_count":
        # Count falling edges of speed (>0 → ==0).
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
        threshold = _resolve_alarm_threshold(point_meta, feature, tier)
        if threshold is None:
            return 0
        return sum(1 for v in values if v > threshold)

    if derivation == "thickness_loss":
        if len(values) < 2:
            return 0.0 if values else None
        # Use chronological first vs last reading (rows assumed sorted by ts).
        return round(values[0] - values[-1], 4)

    return None


# ---------------------------------------------------------------------------
# Async orchestrator: components + bucketed trend calls
# ---------------------------------------------------------------------------


def _date_to_ms_range(date_str: str) -> tuple[str, str]:
    """Return (start_ms, end_ms) covering the full day for ``YYYY-MM-DD``."""
    start = datetime.strptime(date_str, "%Y-%m-%d")
    end = start + timedelta(days=1)
    return str(int(start.timestamp() * 1000)), str(int(end.timestamp() * 1000))


async def _fetch_components_cached(
    client: Any,
    cache: dict[str, list[dict[str, Any]]],
    equipment_id: str,
) -> list[dict[str, Any]]:
    if equipment_id not in cache:
        cache[equipment_id] = await client.get_slim_components(equipment_id)
    return cache[equipment_id]


async def _fetch_kpi_for_equipment(
    client: Any,
    equipment_id: str,
    kpi_keys: list[str],
    start_ms: str,
    end_ms: str,
    components_cache: dict[str, list[dict[str, Any]]],
    eq_type: str = "all",
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """For one equipment, fetch all requested KPIs.

    Returns ``(kpis_dict, raw_rows_for_runtime_hourly)``. The second value is
    the union of ``speed`` rows fetched for any 8k/9k point, used to derive
    the equipment's hourly runtime rate.
    """
    components = await _fetch_components_cached(client, components_cache, equipment_id)
    kpis: dict[str, Any] = {}
    speed_rows: list[dict[str, Any]] = []

    # Bucket (point_id, series) → list of features to request.
    request_buckets: dict[tuple[str, str], set[str]] = {}
    point_index: dict[str, dict[str, Any]] = {}
    kpi_to_points: dict[str, list[dict[str, Any]]] = {}
    for kpi_key in kpi_keys:
        if kpi_key not in _KPI_FEATURE_MAP:
            raise HttpProviderError(f"unmappable KPI key: {kpi_key!r}")
        points = _select_points_for_kpi(components, kpi_key, eq_type=eq_type)
        kpi_to_points[kpi_key] = points
        if not points:
            continue
        spec = _KPI_FEATURE_MAP[kpi_key]
        for point in points:
            point_index[point["id"]] = point
            bucket = (point["id"], point["endpoint_series"])
            request_buckets.setdefault(bucket, set()).update(_feature_candidates_for_spec(spec))

    # Group same-series + same-features points for batched InS calls.
    # Key: (series, frozenset(features)) → list of point_ids.
    batch_groups: dict[tuple[str, frozenset], list[str]] = {}
    for (point_id, series), features in request_buckets.items():
        key = (series, frozenset(features))
        batch_groups.setdefault(key, []).append(point_id)

    # Issue one ``get_trend_data`` call per (series, features) group with
    # comma-separated gpids. The InS API natively supports multi-gpid queries.
    trend_rows: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for (series, features_frozen), point_ids in batch_groups.items():
        features = sorted(features_frozen)
        kwargs: dict[str, Any] = {"endpoint_series": series}
        if _INS_FACTORY_ID is not None:
            kwargs["factory_id"] = _INS_FACTORY_ID
        combined_id = ",".join(point_ids)
        rows = await client.get_trend_data(
            combined_id,
            start_ms,
            end_ms,
            features,
            **kwargs,
        )
        # Filter out non-dict elements (InS API may return strings mixed in the list)
        rows = [r for r in (rows or []) if isinstance(r, dict)]
        # Demux combined response back to per-point rows.
        for point_id in point_ids:
            point_rows = [r for r in rows if r.get("component_id") == point_id]
            trend_rows[(point_id, series)] = point_rows

    # Reduce per-KPI: pick the rows from the matched points and aggregate.
    for kpi_key in kpi_keys:
        points = kpi_to_points.get(kpi_key) or []
        if not points:
            kpis[kpi_key] = None
            continue
        spec = _KPI_FEATURE_MAP[kpi_key]
        per_point_values: list[float | int] = []
        for point in points:
            rows = trend_rows.get((point["id"], point["endpoint_series"])) or []
            if spec["feature"] == "speed":
                speed_rows.extend(rows)
            value = _aggregate_trend_to_kpi(rows, kpi_key, point)
            if value is not None:
                per_point_values.append(value)
        if not per_point_values:
            kpis[kpi_key] = None
        elif spec["derivation"] in {"alarm_count", "downtime_count"}:
            kpis[kpi_key] = int(sum(per_point_values))
        else:
            kpis[kpi_key] = round(
                sum(per_point_values) / len(per_point_values), 4
            )

    return kpis, speed_rows


async def _async_fetch_daily_series_payload(
    *,
    start_date: str,
    day_count: int,
    equipment_ids: list[str],
    kpi_keys: list[str],
    eq_type: str,
    equipment_meta: dict[str, dict] | None,
) -> list[dict[str, Any]]:
    """Fetch consecutive day payloads while reusing one InS client + cache.

    Weekly reports need seven day-level payloads for the trend chart. Reusing
    one client avoids seven separate TCP/login handshakes, which lowers the
    chance of ConnectTimeout compared with routing through fetch_daily_payload()
    repeatedly.
    """
    if not _FEATURES_TOOL_AVAILABLE:
        raise HttpProviderError(
            f"features-tool not available (root={_FEATURES_TOOL_ROOT}); "
            f"import error: {_FEATURES_TOOL_IMPORT_ERROR}"
        )

    settings = load_ins_settings()
    client = InsApiClient(settings)
    components_cache: dict[str, list[dict[str, Any]]] = {}
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")

    try:
        daily_entries: list[dict[str, Any]] = []
        for offset in range(day_count):
            date_str = (start_dt + timedelta(days=offset)).strftime("%Y-%m-%d")
            start_ms, end_ms = _date_to_ms_range(date_str)

            semaphore = asyncio.Semaphore(INS_CONCURRENCY_LIMIT)

            async def _fetch_one(eid: str) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
                async with semaphore:
                    kpis, speed_rows = await _fetch_kpi_for_equipment(
                        client, eid, kpi_keys, start_ms, end_ms,
                        components_cache, eq_type=eq_type,
                    )
                    return eid, kpis, speed_rows

            fetched = await asyncio.gather(*[_fetch_one(eid) for eid in equipment_ids])
            per_equipment_kpis: dict[str, dict[str, Any]] = {}
            per_equipment_speed_rows: dict[str, list[dict[str, Any]]] = {}
            for eid, kpis, speed_rows in fetched:
                per_equipment_kpis[eid] = kpis
                per_equipment_speed_rows[eid] = speed_rows

            aggregated_kpis: dict[str, Any] = {}
            for kpi_key in kpi_keys:
                spec = _KPI_FEATURE_MAP[kpi_key]
                values = [
                    per_equipment_kpis[eid][kpi_key]
                    for eid in equipment_ids
                    if per_equipment_kpis[eid].get(kpi_key) is not None
                ]
                if not values:
                    aggregated_kpis[kpi_key] = None
                elif spec["derivation"] in {"alarm_count", "downtime_count"}:
                    aggregated_kpis[kpi_key] = int(sum(values))
                else:
                    aggregated_kpis[kpi_key] = round(sum(values) / len(values), 4)

            # Per-day event scoping for weekly report trend data.
            day_alarms = await _fetch_equipment_events(
                client, equipment_ids, start_ms, end_ms, eq_type=eq_type
            )

            daily_entries.append(
                {
                    "date": date_str,
                    "kpis": aggregated_kpis,
                    "kpi_units": _kpi_units_for(kpi_keys),
                    "alarms": day_alarms,
                }
            )

        return daily_entries
    finally:
        await client.close()


def _load_query_daily_module():
    module = sys.modules.get("query_daily")
    if module is not None:
        return module
    qd_path = Path(__file__).parent / "query_daily.py"
    if not qd_path.exists():
        return None
    spec = importlib.util.spec_from_file_location("query_daily", qd_path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules["query_daily"] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        if sys.modules.get("query_daily") is module:
            del sys.modules["query_daily"]
        return None
    return module


def _kpi_units_for(kpi_keys: list[str]) -> dict[str, str]:
    """Reuse ``query_daily.KPI_UNITS`` if importable; otherwise empty strings."""
    try:
        module = _load_query_daily_module()
        if module is not None:
            kpi_units = getattr(module, "KPI_UNITS", {})
            return {k: kpi_units.get(k, "") for k in kpi_keys}
    except Exception:
        pass
    return {k: "" for k in kpi_keys}


# ---------------------------------------------------------------------------
# Machine drop events — fetch from 8K / 9K getMachineDrops endpoint
# ---------------------------------------------------------------------------


def _event_series_for_eq_type(eq_type: str) -> str | None:
    if eq_type == "rotating_machinery":
        return "8k"
    if eq_type == "reciprocating_machinery":
        return "9k"
    return None


def _format_machine_drop_entry(entry: dict[str, Any]) -> dict[str, Any] | None:
    types: list[int] = entry.get("types") or []
    if not types:
        return None
    primary_type = types[0]
    label, level = _EVENT_TYPE_MAP.get(primary_type, (f"未知事件({primary_type})", "info"))

    datatime = entry.get("datatime")
    if isinstance(datatime, (int, float)):
        try:
            time_str = datetime.fromtimestamp(datatime / 1000).strftime("%Y-%m-%d %H:%M:%S")
        except (OSError, OverflowError, ValueError):
            time_str = str(datatime)
    else:
        time_str = str(datatime or "")

    pos_name = str(entry.get("posName") or entry.get("posId") or "")
    pos_id = str(entry.get("posId") or "")

    return {
        "time": time_str,
        "equipment": pos_name,
        "level": level,
        "message": f"[{label}] {pos_name}",
        "pos_id": pos_id,
        "event_type": primary_type,
        "event_label": label,
    }


async def _fetch_machine_drops(
    client: Any,
    equipment_id: str,
    start_ms: str,
    end_ms: str,
    eq_type: str,
) -> list[dict[str, Any]]:
    series = _event_series_for_eq_type(eq_type)
    if series is None:
        return []

    event_types = list(_EVENT_TYPES_BY_EQ_TYPE.get(eq_type, ()))
    if not event_types:
        return []

    raw_events = await client.get_machine_drops(
        equipment_id,
        start_ms,
        end_ms,
        event_types,
        endpoint_series=series,
        factory_id=_INS_FACTORY_ID,
    )
    if not raw_events:
        return []

    alarms: list[dict[str, Any]] = []
    for entry in raw_events:
        if not isinstance(entry, dict):
            continue
        formatted = _format_machine_drop_entry(entry)
        if formatted is not None:
            alarms.append(formatted)
    return alarms


async def _fetch_equipment_events(
    client: Any,
    equipment_ids: list[str],
    start_ms: str,
    end_ms: str,
    eq_type: str,
) -> list[dict[str, Any]]:
    series = _event_series_for_eq_type(eq_type)
    if series is None:
        return []

    all_alarms: list[dict[str, Any]] = []
    for eid in equipment_ids:
        try:
            alarms = await _fetch_machine_drops(client, eid, start_ms, end_ms, eq_type)
            all_alarms.extend(alarms)
        except Exception:
            # Graceful degradation: a single equipment's events failing
            # should not block the entire report.
            continue
    return all_alarms


# ---------------------------------------------------------------------------
# Sync wrappers — the public API consumed by InsMonthlyProvider
# ---------------------------------------------------------------------------


def _run_async(coro) -> Any:
    """Run an async coroutine in a fresh event loop. Wrap failures."""
    try:
        return asyncio.run(coro)
    except HttpProviderError:
        raise
    except Exception as exc:  # noqa: BLE001 - any failure surfaces as provider failure
        raise HttpProviderError(
            f"InS provider call failed: {type(exc).__name__}: {exc}"
        ) from exc


def fetch_daily_series_payload(
    start_date: str,
    day_count: int,
    equipment_ids: list[str],
    kpi_keys: list[str],
    eq_type: str = "all",
    equipment_meta: dict[str, dict] | None = None,
) -> list[dict[str, Any]]:
    return _run_async(
        _async_fetch_daily_series_payload(
            start_date=start_date,
            day_count=day_count,
            equipment_ids=equipment_ids,
            kpi_keys=kpi_keys,
            eq_type=eq_type,
            equipment_meta=equipment_meta,
        )
    )

