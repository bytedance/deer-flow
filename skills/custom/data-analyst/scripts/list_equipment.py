#!/usr/bin/env python
"""Query equipment catalog for ai-report--daily agent.

Returns matched equipment list and available KPIs by equipment type,
scope (all/area/specific), and optional filter.

When no real API is configured the script returns deterministic demo
data (4 types, 4 areas, ~2200 devices total).
"""

from __future__ import annotations

import argparse
import json
import re
import sys

VALID_TYPES = {"all", "static_equipment", "rotating_machinery", "pump", "reciprocating_machinery"}
VALID_SCOPES = {"all", "area", "specific"}
AREA_FILTER_PATTERN = re.compile(r"^[一-鿿＀-￯A-Za-z0-9_-]+$")
ID_FILTER_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")

TYPE_DISPLAY = {
    "all": "全部",
    "static_equipment": "静设备",
    "rotating_machinery": "旋转机组",
    "pump": "机泵",
    "reciprocating_machinery": "往复机组",
}

TYPE_PREFIX = {
    "static_equipment": "SE",
    "rotating_machinery": "RM",
    "pump": "PP",
    "reciprocating_machinery": "RC",
}

TYPE_COUNT = {
    "static_equipment": 1000,
    "rotating_machinery": 100,
    "pump": 1000,
    "reciprocating_machinery": 100,
}

AREAS = ["A区", "B区", "C区", "D区"]

EQUIPMENT_TYPE_KPIS: dict[str, list[str]] = {
    "all": [
        "runtime_rate", "downtime_count", "alarm_count", "energy_consumption",
    ],
    "static_equipment": [
        "runtime_rate", "alarm_count", "corrosion_rate", "thickness_loss",
        "energy_consumption",
    ],
    "rotating_machinery": [
        "runtime_rate", "vibration_level", "bearing_temp", "downtime_count",
        "energy_consumption",
    ],
    "pump": [
        "runtime_rate", "flow_rate", "outlet_pressure", "energy_consumption",
        "alarm_count",
    ],
    "reciprocating_machinery": [
        "runtime_rate", "vibration_level", "valve_temp", "downtime_count",
        "alarm_count",
    ],
}

KPI_DEFINITIONS: dict[str, dict[str, str]] = {
    "runtime_rate": {"name": "运行率", "unit": "%"},
    "downtime_count": {"name": "停机次数", "unit": "次"},
    "alarm_count": {"name": "告警数量", "unit": "条"},
    "energy_consumption": {"name": "能耗", "unit": "kWh"},
    "output": {"name": "产量", "unit": "件"},
    "corrosion_rate": {"name": "腐蚀速率", "unit": "mm/a"},
    "thickness_loss": {"name": "壁厚减薄量", "unit": "mm"},
    "vibration_level": {"name": "振动水平", "unit": "mm/s"},
    "bearing_temp": {"name": "轴承温度", "unit": "℃"},
    "flow_rate": {"name": "流量", "unit": "m³/h"},
    "outlet_pressure": {"name": "出口压力", "unit": "MPa"},
    "valve_temp": {"name": "阀温", "unit": "℃"},
}

SUB_TYPES: dict[str, list[str]] = {
    "static_equipment": ["换热器", "冷却器", "塔器", "容器", "反应器"],
    "rotating_machinery": ["压缩机", "汽轮机", "发电机", "风机"],
    "pump": ["离心泵", "柱塞泵", "螺杆泵", "齿轮泵"],
    "reciprocating_machinery": ["往复压缩机", "往复泵", "柴油机", "气缸"],
}


def _demo_equipment_for_type(eq_type: str) -> list[dict]:
    """Generate deterministic demo equipment list for a single type."""
    prefix = TYPE_PREFIX[eq_type]
    total = TYPE_COUNT[eq_type]
    per_area = total // len(AREAS)
    sub_types = SUB_TYPES[eq_type]
    equipment: list[dict] = []
    for area_idx, area in enumerate(AREAS):
        for i in range(per_area):
            seq = area_idx * per_area + i + 1
            sub_type = sub_types[seq % len(sub_types)]
            equipment.append({
                "id": f"{prefix}-{seq:03d}",
                "name": f"{sub_type}-{seq:03d}",
                "area": area,
                "sub_type": sub_type,
            })
    return equipment


def _get_all_demo_equipment(eq_type: str) -> list[dict]:
    """Return demo equipment, optionally filtered by type."""
    if eq_type == "all":
        result: list[dict] = []
        for t in TYPE_PREFIX:
            result.extend(_demo_equipment_for_type(t))
        return result
    return _demo_equipment_for_type(eq_type)


def _filter_by_scope(
    equipment: list[dict],
    scope: str,
    filter_values: list[str],
) -> list[dict]:
    if scope == "all":
        return equipment
    if scope == "area":
        area_set = set(filter_values)
        return [e for e in equipment if e["area"] in area_set]
    if scope == "specific":
        id_set = set(filter_values)
        return [e for e in equipment if e["id"] in id_set]
    return equipment


def _build_available_kpis(eq_type: str) -> list[dict]:
    kpi_keys = EQUIPMENT_TYPE_KPIS.get(eq_type, EQUIPMENT_TYPE_KPIS["all"])
    result: list[dict] = []
    for idx, key in enumerate(kpi_keys):
        defn = KPI_DEFINITIONS.get(key, {"name": key, "unit": ""})
        result.append({
            "key": key,
            "name": defn["name"],
            "unit": defn["unit"],
            "default": idx < 3,
        })
    return result


def _parse_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _validate_type(eq_type: str) -> str | None:
    if eq_type not in VALID_TYPES:
        return f"--type must be one of {sorted(VALID_TYPES)}, got: {eq_type}"
    return None


def _validate_scope(scope: str) -> str | None:
    if scope not in VALID_SCOPES:
        return f"--scope must be one of {sorted(VALID_SCOPES)}, got: {scope}"
    return None


def _validate_filter(scope: str, filter_values: list[str]) -> str | None:
    if scope == "area":
        invalid = [v for v in filter_values if not AREA_FILTER_PATTERN.fullmatch(v)]
        if invalid:
            return f"--filter contains invalid area name(s): {','.join(invalid)}"
    elif scope == "specific":
        invalid = [v for v in filter_values if not ID_FILTER_PATTERN.fullmatch(v)]
        if invalid:
            return f"--filter contains invalid equipment id(s): {','.join(invalid)}"
    return None


def query_equipment(
    eq_type: str = "all",
    scope: str = "all",
    filter_str: str = "",
    limit: int = 50,
) -> dict:
    """Query equipment catalog. Returns result dict matching design doc §4.1.

    Data source priority: MCP data catalog → http_connector → demo fallback.
    Currently only the demo fallback is implemented.
    """
    all_equipment = _get_all_demo_equipment(eq_type)
    filter_values = _parse_csv(filter_str)
    matched = _filter_by_scope(all_equipment, scope, filter_values)
    total_matched = len(matched)

    total_in_type = sum(TYPE_COUNT.values()) if eq_type == "all" else TYPE_COUNT.get(eq_type, 0)

    truncated = total_matched > limit
    display_equipment = matched[:limit]

    filter_display = filter_str if filter_str else ("全部" if scope == "all" else "")

    area_counts: dict[str, int] = {}
    for e in matched:
        area = e.get("area", "")
        area_counts[area] = area_counts.get(area, 0) + 1

    return {
        "equipment_type": eq_type,
        "type_display": TYPE_DISPLAY.get(eq_type, eq_type),
        "scope": scope,
        "filter_display": filter_display,
        "total_matched": total_matched,
        "total_in_type": total_in_type,
        "areas": list(AREAS),
        "area_counts": area_counts,
        "equipment": display_equipment,
        "equipment_truncated": truncated,
        "available_kpis": _build_available_kpis(eq_type),
    }


def _error(message: str) -> int:
    print(json.dumps({"error": message}, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Query equipment catalog")
    parser.add_argument("--type", default="all", help="Equipment type")
    parser.add_argument("--scope", default="all", help="Scope: all/area/specific")
    parser.add_argument("--filter", default="", help="Area names or equipment IDs (CSV)")
    parser.add_argument("--limit", type=int, default=50, help="Max equipment to return")
    args = parser.parse_args()

    try:
        eq_type = getattr(args, "type")
        type_error = _validate_type(eq_type)
        if type_error:
            return _error(type_error)

        scope_error = _validate_scope(args.scope)
        if scope_error:
            return _error(scope_error)

        filter_values = _parse_csv(args.filter)
        if filter_values:
            filter_error = _validate_filter(args.scope, filter_values)
            if filter_error:
                return _error(filter_error)

        result = query_equipment(eq_type, args.scope, args.filter, args.limit)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 0


if __name__ == "__main__":
    sys.exit(main())
