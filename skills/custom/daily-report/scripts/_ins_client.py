"""Direct InS client wrapper for daily report scripts.

Thin wrapper around ``features-tool``'s ``InsApiClient``.
No dependency on ``deerflow.integrations``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Endpoint series / event type routing (self-contained, no integrations import)
# ---------------------------------------------------------------------------

ENDPOINT_SERIES_BY_EQ_TYPE: dict[str, str] = {
    "rotating_machinery": "8k",
    "reciprocating_machinery": "9k",
    "pump": "2k",
    "static_equipment": "6k",
}

FEATURES_BY_SERIES: dict[str, list[str]] = {
    "8k": ["speed", "pp_value", "value"],
    "9k": ["speed", "pp_value", "value"],
    "2k": ["v_rms", "a_peak", "kurtosis", "temperature"],
    "6k": ["corrosionRate", "thickness", "temperature"],
}

EVENT_TYPES_BY_EQ_TYPE: dict[str, list[int]] = {
    "rotating_machinery": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18],
    "reciprocating_machinery": [1, 2, 3, 14, 15],
    "pump": [1, 2, 3],
}

# ---------------------------------------------------------------------------
# Event type → (label, severity) — consistent with weekly/monthly reports
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

# ---------------------------------------------------------------------------
# Availability detection
# ---------------------------------------------------------------------------

_features_client: Any = None
_availability_reason: str | None = None
_features_root: str = ""


def _init_features_client() -> None:
    """Try to import and construct the features-tool InsApiClient (once)."""
    global _features_client, _availability_reason, _features_root

    if _features_client is not None or _availability_reason is not None:
        return

    root = os.environ.get("FEATURES_TOOL_ROOT", "/mnt/skills/custom/features-tool")
    _features_root = root

    if not os.path.isdir(root):
        _availability_reason = f"features-tool not found at {root}"
        return

    if root not in sys.path:
        sys.path.insert(0, root)

    try:
        from ins import InsApiClient, load_ins_settings

        settings = load_ins_settings()
        _features_client = InsApiClient(settings)
        logger.info("features-tool InsApiClient loaded from %s", root)
    except ImportError as e:
        _availability_reason = f"cannot import ins from {root}: {e}"
    except Exception as e:
        _availability_reason = f"failed to initialize InsApiClient: {e}"


def is_available() -> bool:
    """Return True if features-tool InsApiClient is importable and constructed."""
    _init_features_client()
    return _features_client is not None


def get_availability_reason() -> str:
    """Return a human-readable reason why features-tool is unavailable, or empty string."""
    _init_features_client()
    return _availability_reason or ""


def _get_client() -> Any:
    """Return the initialized InsApiClient, raising if unavailable."""
    _init_features_client()
    if _features_client is None:
        reason = _availability_reason or "features-tool not available"
        raise RuntimeError(reason)
    return _features_client


# ---------------------------------------------------------------------------
# Measurement point selection
# ---------------------------------------------------------------------------


def _select_points_by_series(
    components: list[dict[str, Any]],
    target_series: str,
) -> list[dict[str, Any]]:
    """Select measurement points matching target endpoint series.

    Stack-based traversal — once a node has ``endpoint_series``, children are skipped.
    """
    selected: list[dict[str, Any]] = []
    stack: list[dict[str, Any]] = list(components)

    while stack:
        node = stack.pop()
        if not isinstance(node, dict):
            continue

        node_series = node.get("endpoint_series")
        if node_series is not None:
            if node_series == target_series:
                selected.append(node)
            continue

        for key in ("children", "points"):
            for child in node.get(key) or []:
                if isinstance(child, dict):
                    stack.append(child)

    return selected


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def fetch_trend_data_async(
    client: Any,
    equipment_ids: list[str],
    start_time: str,
    end_time: str,
    eq_type: str = "rotating_machinery",
) -> dict[str, list[dict[str, Any]]]:
    """Async version of fetch_trend_data. Uses provided client.

    Supports both real async client methods and mock methods that return plain values.
    """
    target_series = ENDPOINT_SERIES_BY_EQ_TYPE.get(eq_type, "8k")
    features = FEATURES_BY_SERIES.get(target_series, ["speed", "pp_value", "value"])

    start_ms = str(int(datetime.fromisoformat(start_time).timestamp() * 1000))
    end_ms = str(int(datetime.fromisoformat(end_time).timestamp() * 1000))

    results: dict[str, list[dict[str, Any]]] = {}

    for eq_id in equipment_ids:
        print(f"[数据查询] 趋势数据 -> {eq_id}...", file=sys.stderr)
        try:
            maybe_coro = client.get_slim_components(eq_id)
            components = await maybe_coro if asyncio.iscoroutine(maybe_coro) else maybe_coro
        except Exception as e:
            logger.warning("Failed to get components for %s: %s", eq_id, e)
            results[eq_id] = []
            continue

        points = _select_points_by_series(components or [], target_series)
        if not points:
            logger.warning("No %s points found for equipment %s", target_series, eq_id)
            results[eq_id] = []
            continue

        point_ids = [str(p["id"]) for p in points if p.get("id")]
        if not point_ids:
            results[eq_id] = []
            continue

        try:
            maybe_coro = client.get_trend_data(
                ",".join(point_ids),
                start_ms,
                end_ms,
                features,
                endpoint_series=target_series,
            )
            rows = await maybe_coro if asyncio.iscoroutine(maybe_coro) else maybe_coro
            results[eq_id] = rows or []
        except Exception as e:
            logger.warning("Failed to get trend data for %s: %s", eq_id, e)
            results[eq_id] = []

    return results


def fetch_trend_data(
    equipment_ids: list[str],
    start_time: str,
    end_time: str,
    eq_type: str = "rotating_machinery",
) -> dict[str, list[dict[str, Any]]]:
    """Fetch trend time-series data for one or more pieces of equipment.

    Args:
        equipment_ids: List of equipment IDs.
        start_time: ISO-format start time (e.g., ``"2026-06-01T00:00:00"``).
        end_time: ISO-format end time.
        eq_type: Equipment type key (rotating_machinery, pump, etc.).

    Returns:
        ``{equipment_id: [trend_row, ...]}`` where each row has
        ``time_ms``, ``time``, and ``values`` dict.
    """
    client = _get_client()
    return _run_async(fetch_trend_data_async(client, equipment_ids, start_time, end_time, eq_type))


def _format_machine_drop_entry(
    entry: dict[str, Any], equipment_id: str
) -> dict[str, Any] | None:
    """Parse a raw getMachineDrops entry into a structured alarm dict.

    Returns None when the entry has no recognized event type.
    """
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
        time_str = str(datatime or entry.get("time") or entry.get("dropTime") or "")

    return {
        "time": time_str,
        "equipment": str(entry.get("posName") or entry.get("posId") or equipment_id),
        "level": level,
        "message": f"[{label}] {entry.get('posName') or equipment_id}",
        "event_type": primary_type,
        "event_label": label,
        "pos_id": str(entry.get("posId") or ""),
    }


async def fetch_alarm_events_async(
    client: Any,
    equipment_ids: list[str],
    start_time: str,
    end_time: str,
    eq_type: str = "rotating_machinery",
) -> list[dict[str, Any]]:
    """Async version of fetch_alarm_events. Uses provided client.

    Supports both real async client methods and mock methods that return plain values.
    """
    target_series = ENDPOINT_SERIES_BY_EQ_TYPE.get(eq_type, "8k")

    # 6k (static equipment) does not support getMachineDrops endpoint
    if target_series not in _MACHINE_DROPS_SUPPORTED_SERIES:
        return []

    event_types = EVENT_TYPES_BY_EQ_TYPE.get(eq_type, [1, 2, 3, 14, 15])

    start_ms = str(int(datetime.fromisoformat(start_time).timestamp() * 1000))
    end_ms = str(int(datetime.fromisoformat(end_time).timestamp() * 1000))

    alarms: list[dict[str, Any]] = []
    for eq_id in equipment_ids:
        print(f"[数据查询] 告警事件 -> {eq_id}...", file=sys.stderr)
        try:
            maybe_coro = client.get_machine_drops(
                eq_id,
                start_ms,
                end_ms,
                event_types,
                endpoint_series=target_series,
            )
            raw_events = await maybe_coro if asyncio.iscoroutine(maybe_coro) else maybe_coro
        except Exception as e:
            logger.warning("Failed to get machine drops for %s: %s", eq_id, e)
            continue

        for event in raw_events or []:
            formatted = _format_machine_drop_entry(event, eq_id)
            if formatted is not None:
                alarms.append(formatted)

    return alarms


_MACHINE_DROPS_SUPPORTED_SERIES: frozenset[str] = frozenset({"8k", "9k"})


def fetch_alarm_events(
    equipment_ids: list[str],
    start_time: str,
    end_time: str,
    eq_type: str = "rotating_machinery",
) -> list[dict[str, Any]]:
    """Fetch machine drop (alarm) events.

    Args:
        equipment_ids: List of equipment IDs.
        start_time: ISO-format start time.
        end_time: ISO-format end time.
        eq_type: Equipment type key.

    Returns:
        List of alarm dicts with ``time``, ``equipment``, ``level``, ``message`` fields.
        Returns empty list on failure (alarm fetch is non-critical).
    """
    target_series = ENDPOINT_SERIES_BY_EQ_TYPE.get(eq_type, "8k")
    # 6k (static equipment) does not support getMachineDrops endpoint
    if target_series not in _MACHINE_DROPS_SUPPORTED_SERIES:
        return []

    client = _get_client()
    return _run_async(fetch_alarm_events_async(client, equipment_ids, start_time, end_time, eq_type))


async def _create_client_and_fetch(
    equipment_ids: list[str],
    start_time: str,
    end_time: str,
    eq_type: str = "rotating_machinery",
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    """Create a fresh client, fetch data, and close the client.

    This ensures each fetch operation has its own event loop context.
    """
    from ins import InsApiClient, load_ins_settings
    settings = load_ins_settings()
    client = InsApiClient(settings)
    try:
        trend_data = await fetch_trend_data_async(client, equipment_ids, start_time, end_time, eq_type)
        alarms = await fetch_alarm_events_async(client, equipment_ids, start_time, end_time, eq_type)
        return trend_data, alarms
    finally:
        maybe_coro = client.close()
        if asyncio.iscoroutine(maybe_coro):
            await maybe_coro


def fetch_all(
    equipment_ids: list[str],
    start_time: str,
    end_time: str,
    eq_type: str = "rotating_machinery",
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    """Fetch both trend data and alarm events with a fresh client each time.

    This avoids event loop issues when calling multiple async operations.
    """
    return _run_async(_create_client_and_fetch(equipment_ids, start_time, end_time, eq_type))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_async(maybe_coro: Any) -> Any:
    """Run a coroutine if needed, otherwise return the value as-is.

    InsApiClient methods are async; this lets the same code work with both
    real clients and test mocks that return plain values.
    """
    if asyncio.iscoroutine(maybe_coro):
        return asyncio.run(maybe_coro)
    return maybe_coro
