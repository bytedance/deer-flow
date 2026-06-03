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
    target_series = ENDPOINT_SERIES_BY_EQ_TYPE.get(eq_type, "8k")
    features = FEATURES_BY_SERIES.get(target_series, ["speed", "pp_value", "value"])

    start_ms = str(int(datetime.fromisoformat(start_time).timestamp() * 1000))
    end_ms = str(int(datetime.fromisoformat(end_time).timestamp() * 1000))

    results: dict[str, list[dict[str, Any]]] = {}

    for eq_id in equipment_ids:
        try:
            components = _run_async(client.get_slim_components(eq_id))
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
            rows = _run_async(client.get_trend_data(
                ",".join(point_ids),
                start_ms,
                end_ms,
                features,
                endpoint_series=target_series,
            ))
            results[eq_id] = rows or []
        except Exception as e:
            logger.warning("Failed to get trend data for %s: %s", eq_id, e)
            results[eq_id] = []

    return results


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
    client = _get_client()
    target_series = ENDPOINT_SERIES_BY_EQ_TYPE.get(eq_type, "8k")
    event_types = EVENT_TYPES_BY_EQ_TYPE.get(eq_type, [1, 2, 3, 14, 15])

    start_ms = str(int(datetime.fromisoformat(start_time).timestamp() * 1000))
    end_ms = str(int(datetime.fromisoformat(end_time).timestamp() * 1000))

    alarms: list[dict[str, Any]] = []
    for eq_id in equipment_ids:
        try:
            raw_events = _run_async(client.get_machine_drops(
                eq_id,
                start_ms,
                end_ms,
                event_types,
                endpoint_series=target_series,
            ))
        except Exception as e:
            logger.warning("Failed to get machine drops for %s: %s", eq_id, e)
            continue

        for event in raw_events or []:
            alarms.append({
                "time": str(event.get("time") or event.get("dropTime") or ""),
                "equipment": eq_id,
                "level": _event_level(event.get("eventType", 0)),
                "message": str(event.get("eventName") or event.get("msg") or ""),
            })

    return alarms


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


_EVENT_LEVEL_MAP: dict[int, str] = {
    1: "high",
    2: "warning",
    3: "info",
    14: "warning",
    15: "high",
}


def _event_level(event_type: int) -> str:
    return _EVENT_LEVEL_MAP.get(event_type, "info")
