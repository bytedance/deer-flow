from __future__ import annotations

import json
from typing import Any

from .models import PumpPoint, PumpTargetContext


VIBRATION_POINT_TYPES = {23, 24, 26, 27}
VIBRATION_KEYWORDS = ("振动", "轴振", "瓦振", "速度", "加速度", "DE", "NDE", "驱动端", "非驱动端")
TEMPERATURE_KEYWORDS = ("温度", "轴承温度", "瓦温", "T")


def build_target_context_from_component_tree(
    machine_id: str,
    component_id: str,
    component_tree: list[dict[str, Any]],
    *,
    component_name: str | None = None,
) -> PumpTargetContext:
    warnings: list[str] = []
    flat = list(_walk_nodes(component_tree))
    target = _find_node(flat, component_id)
    if target is None:
        warnings.append(f"未在组件树中找到子设备 {component_id}，已回退使用整台机泵测点")
        roots = [node for node in component_tree if isinstance(node, dict)]
        target = _find_node(flat, machine_id) or (roots[0] if roots else {"id": machine_id, "name": component_name or machine_id, "type": 4})
        related_nodes = flat
    else:
        related_nodes = _descendants(target)

    vibration_nodes = [
        node
        for node in related_nodes
        if _is_component_point(node)
        and _coerce_int(node.get("type")) in VIBRATION_POINT_TYPES
    ]
    temperature_nodes = [
        node
        for node in related_nodes
        if _is_component_point(node)
        and _coerce_int(node.get("type")) in {22, 28}
    ]

    if not vibration_nodes and target is not None:
        warnings.append(f"子设备 {component_id} 下未找到振动测点，已回退使用整台机泵测点")
        vibration_nodes = [
            node
            for node in flat
            if _is_component_point(node)
            and _coerce_int(node.get("type")) in VIBRATION_POINT_TYPES
        ]
        temperature_nodes = [
            node
            for node in flat
            if _is_component_point(node)
            and _coerce_int(node.get("type")) in {22, 28}
        ]

    points = [
        _component_node_to_point(node, "vibration")
        for node in vibration_nodes
    ] + [
        _component_node_to_point(node, "temperature")
        for node in temperature_nodes
    ]
    deduped = _dedupe_points(points)
    if not deduped:
        warnings.append(f"子设备 {component_id} 未解析到可用测点")

    target_name = component_name or str(target.get("name") or component_id)
    return PumpTargetContext(
        machine_id=machine_id,
        component_id=component_id,
        target_name=target_name,
        target_kind=_target_kind(target),
        points=deduped,
        warnings=_dedupe_text(warnings),
    )


def build_target_context_from_point_configs(
    machine_id: str,
    component_id: str,
    point_configs: dict[str, Any],
    *,
    component_name: str | None = None,
) -> PumpTargetContext:
    warnings: list[str] = []
    vibration_rows = [
        row
        for row in _as_rows(point_configs.get("vibPointConfig"))
        if _coerce_int(row.get("type")) in VIBRATION_POINT_TYPES
    ]
    temperature_rows = _as_rows(point_configs.get("staPointConfig"))

    matched_vibration = _filter_component_points(vibration_rows, component_id, component_name)
    matched_temperature = _filter_component_points(temperature_rows, component_id, component_name)
    matched_rows = matched_vibration + matched_temperature

    if not matched_rows:
        warnings.append(
            f"未在 getPointConfigs 返回中直接匹配到子设备 {component_id} 的关联测点，"
            "已回退使用整台机泵测点"
        )
        matched_vibration = vibration_rows
        matched_temperature = temperature_rows
        matched_rows = matched_vibration + matched_temperature

    target_name = component_name or _infer_target_name(matched_rows) or component_id
    points = [
        _point_config_to_point(row, "vibration")
        for row in matched_vibration
    ] + [
        _point_config_to_point(row, "temperature")
        for row in matched_temperature
    ]
    deduped = _dedupe_points(points)
    if not deduped:
        warnings.append(f"子设备 {component_id} 未解析到可用测点")

    return PumpTargetContext(
        machine_id=machine_id,
        component_id=component_id,
        target_name=target_name,
        target_kind=_target_kind_from_name(target_name),
        points=deduped,
        warnings=warnings,
    )


def build_target_context(machine_id: str, component_id: str, tree_payload: dict[str, Any]) -> PumpTargetContext:
    roots = tree_payload.get("child_device_list") or tree_payload.get("components") or []
    flat = list(_walk_nodes(roots))
    target = _find_node(flat, component_id)
    warnings: list[str] = []
    if target is None:
        warnings.append(f"未在设备树中找到子设备 {component_id}，将以整台设备测点作为诊断范围")
        target = _find_node(flat, machine_id) or (flat[0] if flat else {"id": machine_id, "name": machine_id})
        related_nodes = flat
    else:
        related_nodes = _related_nodes(target, flat)

    points = [_node_to_point(node) for node in related_nodes if _is_point(node)]
    deduped = _dedupe_points(points)
    if not deduped:
        warnings.append(f"子设备 {component_id} 未解析到可用测点")

    return PumpTargetContext(
        machine_id=machine_id,
        component_id=component_id,
        target_name=str(target.get("name") or component_id),
        target_kind=_target_kind(target),
        points=deduped,
        warnings=warnings,
    )


def _walk_nodes(nodes: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    if isinstance(nodes, dict):
        iterable = [nodes]
    elif isinstance(nodes, list):
        iterable = nodes
    else:
        iterable = []
    for node in iterable:
        if not isinstance(node, dict):
            continue
        result.append(node)
        for key in ("children", "points", "child_device_list"):
            result.extend(_walk_nodes(node.get(key)))
    return result


def _find_node(nodes: list[dict[str, Any]], node_id: str) -> dict[str, Any] | None:
    for node in nodes:
        if str(node.get("id") or "") == str(node_id):
            return node
    return None


def _descendants(node: dict[str, Any]) -> list[dict[str, Any]]:
    result = [node]
    for key in ("children", "points", "child_device_list"):
        result.extend(_walk_nodes(node.get(key)))
    return result


def _related_nodes(target: dict[str, Any], flat: list[dict[str, Any]]) -> list[dict[str, Any]]:
    descendants = _descendants(target)
    if any(_is_point(node) for node in descendants):
        return descendants
    target_id = str(target.get("id") or "")
    related = [
        node
        for node in flat
        if str((node.get("config") or {}).get("belongShaftId") or node.get("belongShaftId") or "") == target_id
    ]
    return related or descendants


def _is_point(node: dict[str, Any]) -> bool:
    if node.get("endpoint_series") == "2k":
        return True
    unit_type = node.get("unit_type", node.get("unitType"))
    if unit_type == 3:
        return True
    if node.get("position_type") or node.get("positionType"):
        return True
    return False


def _target_kind(node: dict[str, Any]) -> str:
    if _is_point(node):
        return "point"
    type_num = node.get("type_num", node.get("type"))
    if type_num in (70, 80):
        return "bearing"
    if type_num in (4, "4"):
        return "pump"
    return "component"


def _node_to_point(node: dict[str, Any]) -> PumpPoint:
    config = dict(node.get("config") or node.get("configInfo") or {})
    thresholds = _extract_thresholds(node, config)
    name = str(node.get("name") or node.get("label") or node.get("id") or "")
    return PumpPoint(
        point_id=str(node.get("id") or ""),
        name=name,
        point_kind=_point_kind(name, node),
        endpoint_series=str(node.get("endpoint_series") or "2k"),
        thresholds=thresholds,
        config=config,
        raw=node,
    )


def _is_component_point(node: dict[str, Any]) -> bool:
    return node.get("unitType", node.get("unit_type")) == 3


def _component_node_to_point(node: dict[str, Any], point_kind: str) -> PumpPoint:
    config = dict(node.get("configInfo") or node.get("config") or {})
    thresholds = _extract_thresholds(node, config)
    name = str(node.get("name") or node.get("label") or node.get("id") or "")
    return PumpPoint(
        point_id=str(node.get("id") or ""),
        name=name,
        point_kind=point_kind,
        endpoint_series="2k",
        thresholds=thresholds,
        config=config,
        raw=node,
    )


def _dedupe_text(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _as_rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _filter_component_points(
    rows: list[dict[str, Any]],
    component_id: str,
    component_name: str | None = None,
) -> list[dict[str, Any]]:
    component = str(component_id)
    matched_by_component = [
        row
        for row in rows
        if str(row.get("componentId") or "") == component
    ]
    if matched_by_component:
        return matched_by_component
    selected = next((row for row in rows if str(row.get("posId") or "") == component), None)
    if selected is None:
        return []
    selected_component_id = str(selected.get("componentId") or "")
    if not selected_component_id:
        return [selected]
    matched_by_selected_component = [row for row in rows if str(row.get("componentId") or "") == selected_component_id]
    if matched_by_selected_component:
        return matched_by_selected_component

    name = str(component_name or "").strip()
    if not name:
        return []
    return [
        row
        for row in rows
        if name in str(row.get("position") or "")
        or name in str(row.get("posName") or row.get("name") or "")
    ]


def _point_config_to_point(row: dict[str, Any], point_kind: str) -> PumpPoint:
    config = _parse_config(row.get("config"))
    thresholds = _extract_thresholds(row, config)
    name = str(row.get("posName") or row.get("name") or row.get("posId") or "")
    return PumpPoint(
        point_id=str(row.get("posId") or row.get("id") or ""),
        name=name,
        point_kind=point_kind,
        endpoint_series="2k",
        thresholds=thresholds,
        config=config,
        raw=row,
    )


def _parse_config(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _infer_target_name(rows: list[dict[str, Any]]) -> str | None:
    for row in rows:
        position = str(row.get("position") or "")
        if position:
            return position.split("/")[-1] or position
    return None


def _target_kind_from_name(name: str) -> str:
    if "轴承" in name or "bearing" in name.lower():
        return "bearing"
    return "component"


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _point_kind(name: str, node: dict[str, Any]) -> str:
    text = f"{name} {node.get('index') or ''} {node.get('position_type') or ''}".lower()
    if any(keyword.lower() in text for keyword in TEMPERATURE_KEYWORDS):
        return "temperature"
    if any(keyword.lower() in text for keyword in VIBRATION_KEYWORDS):
        return "vibration"
    position_type = node.get("position_type") or node.get("positionType")
    if position_type in range(22, 31):
        return "vibration"
    return "process"


def _extract_thresholds(node: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    thresholds: dict[str, Any] = {}
    alarm_thresholds = node.get("alarm_thresholds") or {}
    if isinstance(alarm_thresholds, dict):
        for feature, values in alarm_thresholds.items():
            if isinstance(values, dict):
                for label, value in values.items():
                    thresholds[f"{feature}_{str(label).lower()}"] = value
    mapping = {
        "rms_b": ("rms_b", "bValue", "vRmsBValue", "B"),
        "rms_c": ("rms_c", "cValue", "vRmsCValue", "C"),
        "rms_d": ("rms_d", "dValue", "vRmsDValue", "D"),
        "temp_h": ("temp_h", "tempH", "hAlarm", "h_alarm", "H"),
        "temp_hh": ("temp_hh", "tempHH", "hhAlarm", "hh_alarm", "HH"),
    }
    for normalized, keys in mapping.items():
        for key in keys:
            if key in node:
                thresholds[normalized] = node[key]
                break
            if key in config:
                thresholds[normalized] = config[key]
                break
    return thresholds


def _dedupe_points(points: list[PumpPoint]) -> list[PumpPoint]:
    seen: set[str] = set()
    result: list[PumpPoint] = []
    for point in points:
        if not point.point_id or point.point_id in seen:
            continue
        seen.add(point.point_id)
        result.append(point)
    return result
