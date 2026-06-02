#!/usr/bin/env python
"""Query equipment catalog for ai-report--daily agent.

Returns matched equipment list and available KPIs by equipment type,
scope (all/area/specific), and optional filter.

Data source: Organize tree API (requires DEER_FLOW_EFFECTIVE_USER_ID).
Returns an error when the API is unreachable or user context is missing.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request

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

# Map organize tree device type numbers → equipment type keys
_ORG_TYPE_MAP: dict[int, str] = {
    1: "rotating_machinery",
    4: "pump",
    6: "static_equipment",
    9: "reciprocating_machinery",
}

_SUB_TYPE_NAMES: dict[int, str] = {
    1: "旋转机组",
    4: "机泵",
    6: "静设备",
    9: "往复机组",
}

EQUIPMENT_TYPE_KPIS: dict[str, list[str]] = {
    "all": [
        "runtime_rate", "downtime_count", "alarm_count",
    ],
    "static_equipment": [
        "runtime_rate", "alarm_count", "corrosion_rate", "thickness_loss",
    ],
    "rotating_machinery": [
        "runtime_rate", "vibration_level", "bearing_temp", "downtime_count",
    ],
    "pump": [
        "vibration_velocity_rms", "vibration_acceleration_peak", "bearing_temp",
        "kurtosis_index",
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
    "corrosion_rate": {"name": "腐蚀速率", "unit": "mm/a"},
    "thickness_loss": {"name": "壁厚减薄量", "unit": "mm"},
    "vibration_level": {"name": "振动水平", "unit": "mm/s"},
    "bearing_temp": {"name": "温度", "unit": "℃"},
    "flow_rate": {"name": "流量", "unit": "m³/h"},
    "outlet_pressure": {"name": "出口压力", "unit": "MPa"},
    "valve_temp": {"name": "阀温", "unit": "℃"},
    "vibration_velocity_rms": {"name": "振动速度有效值", "unit": "mm/s"},
    "vibration_acceleration_peak": {"name": "振动加速度峰值", "unit": "m/s²"},
    "kurtosis_index": {"name": "峭度指标", "unit": "—"},
}

# Per-type KPI name overrides (e.g. pump temperature is not necessarily bearing temp).
KPI_NAME_OVERRIDES: dict[str, dict[str, str]] = {
    "pump": {"bearing_temp": "温度"},
}

# ---------------------------------------------------------------------------
# Organize API data fetch (real data path)
# ---------------------------------------------------------------------------


def _get_gateway_url() -> str:
    return os.environ.get("DEER_FLOW_GATEWAY_URL", "http://localhost:8001")


def _collect_devices(node: dict, parent_area: str) -> list[dict]:
    """Recursively collect type<10 device nodes from an organize tree node."""
    devices: list[dict] = []
    node_type = node.get("type", 0)
    node_label = node.get("label", "")
    area = node_label if node_type >= 10 else parent_area

    if node_type < 10:
        eq_type = _ORG_TYPE_MAP.get(node_type, "static_equipment")
        sub_type = _SUB_TYPE_NAMES.get(node_type, "未知")
        devices.append({
            "id": str(node.get("id", "")),
            "name": node_label,
            "area": parent_area,
            "sub_type": sub_type,
            "org_type": eq_type,
        })

    for child in node.get("children", []) or []:
        devices.extend(_collect_devices(child, area))

    return devices


def _fetch_org_tree(user_id: str) -> list[dict] | None:
    """Fetch the organize device tree from Gateway for the given user."""
    global _last_org_api_error
    _last_org_api_error = None
    url = f"{_get_gateway_url()}/api/organize/tree?userId={user_id}&orgId=0&treeType=1"
    try:
        req = urllib.request.Request(url, method="GET")
        req.add_header("Accept", "application/json")
        internal_token = os.environ.get("DEER_FLOW_INTERNAL_AUTH_VALUE")
        if internal_token:
            req.add_header("X-DeerFlow-Internal-Token", internal_token)
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read(1_048_576)
            data = json.loads(raw.decode("utf-8"))
            if isinstance(data, list):
                return data
            _last_org_api_error = f"Organize API returned non-list: {type(data).__name__}"
            print(f"[list_equipment] {_last_org_api_error}", file=sys.stderr)
            return None
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read(4096).decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
        _last_org_api_error = f"Organize API HTTP {e.code}: {body}"
        print(f"[list_equipment] {_last_org_api_error}", file=sys.stderr)
        return None
    except urllib.error.URLError as e:
        _last_org_api_error = f"Organize API unreachable: {e.reason}"
        print(f"[list_equipment] {_last_org_api_error}", file=sys.stderr)
        return None
    except Exception as e:
        _last_org_api_error = f"Organize API error: {type(e).__name__}: {e}"
        print(f"[list_equipment] {_last_org_api_error}", file=sys.stderr)
        return None


_last_org_api_error: str | None = None


def _query_from_org_tree(
    user_id: str,
    eq_type: str = "all",
    scope: str = "all",
    filter_str: str = "",
    limit: int = 50,
) -> dict | None:
    """Query equipment from the organize tree API.

    Returns None when the API is unreachable (caller surfaces the error).
    """
    tree = _fetch_org_tree(user_id)
    if tree is None:
        return None

    # Flatten tree: collect all type<10 device nodes.
    all_devices: list[dict] = []
    for root_node in tree:
        all_devices.extend(_collect_devices(root_node, ""))

    # Filter by equipment type.
    if eq_type != "all":
        all_devices = [d for d in all_devices if d.get("org_type") == eq_type]

    # Filter by scope.
    filter_values = _parse_csv(filter_str)
    if scope == "area" and filter_values:
        area_set = set(filter_values)
        all_devices = [d for d in all_devices if d.get("area") in area_set]
    elif scope == "specific" and filter_values:
        id_set = set(filter_values)
        all_devices = [d for d in all_devices if d["id"] in id_set]

    total_matched = len(all_devices)
    total_in_type = total_matched

    truncated = total_matched > limit
    display_equipment = all_devices[:limit]

    filter_display = filter_str if filter_str else ("全部" if scope == "all" else "")

    area_counts: dict[str, int] = {}
    areas: list[str] = []
    for d in all_devices:
        area = d.get("area", "")
        if area not in area_counts:
            area_counts[area] = 0
            areas.append(area)
        area_counts[area] += 1

    return {
        "equipment_type": eq_type,
        "type_display": TYPE_DISPLAY.get(eq_type, eq_type),
        "scope": scope,
        "filter_display": filter_display,
        "total_matched": total_matched,
        "total_in_type": total_in_type,
        "areas": areas,
        "area_counts": area_counts,
        "equipment": display_equipment,
        "equipment_truncated": truncated,
        "available_kpis": _build_available_kpis(eq_type),
        "data_source": "organize_api",
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_available_kpis(eq_type: str) -> list[dict]:
    kpi_keys = EQUIPMENT_TYPE_KPIS.get(eq_type, EQUIPMENT_TYPE_KPIS["all"])
    overrides = KPI_NAME_OVERRIDES.get(eq_type, {})
    result: list[dict] = []
    for idx, key in enumerate(kpi_keys):
        defn = KPI_DEFINITIONS.get(key, {"name": key, "unit": ""})
        display_name = overrides.get(key, defn["name"])
        result.append({
            "key": key,
            "name": display_name,
            "label": display_name,
            "unit": defn["unit"],
            "description": defn["unit"],
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

    Returns an error dict when the Organize API is unreachable or user
    context is missing.
    """
    user_id = os.environ.get("DEER_FLOW_EFFECTIVE_USER_ID")
    if not user_id:
        return {"error": "DEER_FLOW_EFFECTIVE_USER_ID 未设置，无法查询设备列表"}

    result = _query_from_org_tree(
        user_id=user_id,
        eq_type=eq_type,
        scope=scope,
        filter_str=filter_str,
        limit=limit,
    )
    if result is not None:
        return result

    reason = _last_org_api_error or "组织树 API 不可达"
    return {"error": f"设备列表查询失败: {reason}"}


def _error(message: str) -> int:
    print(json.dumps({"error": message}, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Query equipment catalog")
    parser.add_argument("--type", default="all", help="Equipment type")
    parser.add_argument("--scope", default="all", help="Scope: all/area/specific")
    parser.add_argument("--filter", default="", help="Area names or equipment IDs (CSV)")
    parser.add_argument("--limit", type=int, default=50, help="Max equipment to return")
    parser.add_argument("--output-dir", default="", help="Write list_equipment.json here")
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

        output_dir = args.output_dir
        if output_dir:
            import os
            out_path = os.path.join(output_dir, "data", "list_equipment.json")
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)

        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 0


if __name__ == "__main__":
    sys.exit(main())
