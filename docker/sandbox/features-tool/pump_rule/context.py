from __future__ import annotations

from typing import Any

from .models import PumpPoint, PumpTargetContext


VIBRATION_KEYWORDS = ("振动", "轴振", "瓦振", "速度", "加速度", "DE", "NDE", "驱动端", "非驱动端")
TEMPERATURE_KEYWORDS = ("温度", "轴承温度", "瓦温", "T")


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
        "temp_h": ("temp_h", "hAlarm", "h_alarm", "H"),
        "temp_hh": ("temp_hh", "hhAlarm", "hh_alarm", "HH"),
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
