"""KPI feature mapping for Ins adapter.

Extracted from _ins_provider.py for reuse in the integration layer.
"""

from __future__ import annotations

from typing import Any

# Event type mapping for machine drop events
EVENT_TYPE_MAP: dict[int, tuple[str, str]] = {
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

EVENT_TYPES_8K: tuple[int, ...] = tuple(range(1, 19))
EVENT_TYPES_9K: tuple[int, ...] = (1, 2, 3, 14, 15)
EVENT_TYPES_2K: tuple[int, ...] = (1, 2, 3)

EVENT_TYPES_BY_EQ_TYPE: dict[str, tuple[int, ...]] = {
    "rotating_machinery": EVENT_TYPES_8K,
    "reciprocating_machinery": EVENT_TYPES_9K,
    "pump": EVENT_TYPES_2K,
}

MACHINE_DROPS_PATH_BY_SERIES: dict[str, str] = {
    "8k": "ins-os-view/sg8kData/getMachineDrops",
    "9k": "ins-os-view/sg9kData/getMachineDrops",
    "2k": "ins-os-view/sg2kData/getMachineDrops",
}

ENDPOINT_SERIES_BY_EQ_TYPE: dict[str, str] = {
    "rotating_machinery": "8k",
    "reciprocating_machinery": "9k",
    "pump": "2k",
}

RM_POSITION_TYPES = tuple(range(81, 84))
RC_POSITION_TYPES = tuple(range(91, 100))
RM_RC_POSITION_TYPES = RM_POSITION_TYPES + RC_POSITION_TYPES


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


def select_points_for_kpi(
    components: list[dict[str, Any]],
    kpi_key: str,
    eq_type: str = "all",
) -> list[dict[str, Any]]:
    """Return all points in ``components`` that match the KPI's filters.

    Each returned dict carries:
        id, endpoint_series, alarm_thresholds (2k tier dict, may be empty),
        h_alarm, hh_alarm (8k legacy thresholds, may be None), name.
    """
    spec = KPI_FEATURE_MAP.get(kpi_key)
    if spec is None:
        raise ValueError(f"unmappable KPI key: {kpi_key!r}")

    pos_filter = _position_filter_for_spec(spec, eq_type)
    name_keywords: list[str] = _name_keywords_for_spec(spec, eq_type)
    expected = _expected_series_for_spec(spec, eq_type)
    allowed_series: tuple[str, ...] = (
        (expected,) if isinstance(expected, str) else tuple(expected)
    )

    selected: list[dict[str, Any]] = []
    for point in _iter_points(components):
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


# KPI feature map — declares HOW each report KPI is sourced from InS
KPI_FEATURE_MAP: dict[str, dict[str, Any]] = {
    # ---- 2K vibration (multi-feature, machine 4 = PUMP) ----
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
    "vibration_level": {
        "position_types": RM_RC_POSITION_TYPES,
        "position_types_by_type": {
            "rotating_machinery": RM_POSITION_TYPES,
            "reciprocating_machinery": RC_POSITION_TYPES,
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
        "position_types": (22,) + RM_RC_POSITION_TYPES,
        "position_types_by_type": {
            "rotating_machinery": RM_POSITION_TYPES,
            "reciprocating_machinery": RC_POSITION_TYPES,
            "pump": (22,),
        },
        "feature": "value",
        "feature_aliases": ["temperature"],
        "name_keywords": ["轴承"],
        "name_keywords_by_type": {
            "all": [],
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
        "position_types": RM_RC_POSITION_TYPES,
        "position_types_by_type": {
            "rotating_machinery": RM_POSITION_TYPES,
            "reciprocating_machinery": RC_POSITION_TYPES,
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
        "position_types": RM_RC_POSITION_TYPES,
        "position_types_by_type": {
            "rotating_machinery": RM_POSITION_TYPES,
            "reciprocating_machinery": RC_POSITION_TYPES,
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
        "position_types": RM_RC_POSITION_TYPES,
        "position_types_by_type": {
            "rotating_machinery": RM_POSITION_TYPES,
            "reciprocating_machinery": RC_POSITION_TYPES,
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
        "position_types": RM_RC_POSITION_TYPES,
        "position_types_by_type": {
            "rotating_machinery": RM_POSITION_TYPES,
            "reciprocating_machinery": RC_POSITION_TYPES,
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
        "position_types": RM_RC_POSITION_TYPES,
        "position_types_by_type": {
            "rotating_machinery": RM_POSITION_TYPES,
            "reciprocating_machinery": RC_POSITION_TYPES,
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
        "position_types": RM_RC_POSITION_TYPES,
        "position_types_by_type": {
            "rotating_machinery": RM_POSITION_TYPES,
            "reciprocating_machinery": RC_POSITION_TYPES,
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
