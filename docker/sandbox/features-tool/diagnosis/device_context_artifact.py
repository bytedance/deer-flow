from __future__ import annotations

from typing import Any

from .context_index import build_device_context_index, resolve_sub_device_targets
from .models import DeviceContext


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _contains_any(text: str, keywords: list[str]) -> bool:
    lowered = text.lower()
    return any(keyword.lower() in lowered for keyword in keywords)


def _best_device_type_alias_match(name: str, config: dict[str, Any]) -> str | None:
    lowered = name.lower()
    best_match: tuple[int, int, str] | None = None
    for device_type, aliases in (config.get("device_type_aliases") or {}).items():
        for alias in aliases:
            keyword = str(alias or "").strip()
            if not keyword:
                continue
            lowered_keyword = keyword.lower()
            if lowered_keyword not in lowered:
                continue
            score = (1 if lowered == lowered_keyword else 0, len(keyword))
            if best_match is None or score > best_match[:2]:
                best_match = (score[0], score[1], str(device_type))
    return best_match[2] if best_match else None


def _infer_device_type_from_name(name: str, config: dict[str, Any]) -> str:
    matched = _best_device_type_alias_match(name, config)
    return matched or "未知"


def _infer_bearing_direction(name: str, config: dict[str, Any]) -> str | None:
    keywords = config.get("bearing_direction_keywords") or {}
    ordered_directions = ["非联端", "联端"] + [key for key in keywords.keys() if key not in {"非联端", "联端"}]
    for direction in ordered_directions:
        aliases = keywords.get(direction) or []
        if _contains_any(name, [str(item) for item in aliases]):
            return str(direction)
    return None


def _infer_bearing_types(name: str) -> list[str]:
    lowered = name.lower()
    values: list[str] = []
    if any(token in lowered for token in ["推力", "止推", "thrust"]):
        values.append("推力轴承")
    if any(token in lowered for token in ["支撑", "bearing", "轴承", "联端", "非联端", "自由端"]):
        values.append("支撑轴承")
    return values or ["无法推断"]


def _infer_point_type(type_num: Any, name: str, config: dict[str, Any]) -> str:
    num_text = str(type_num or "")
    lowered = name.lower()
    if num_text == "83":
        return "轴位移波形" if "波形" in lowered else "轴振"
    if num_text == "81":
        return "键相"

    keyword_map = config.get("point_type_keywords") or {}
    for point_type, keywords in keyword_map.items():
        if _contains_any(name, [str(item) for item in keywords]):
            return str(point_type)
    return "其他"


def _infer_system(name: str) -> str | None:
    lowered = name.lower()
    if any(token in lowered for token in ["汽轮机", "透平", "steam turbine", "电机", "发电机", "generator"]):
        return "动力部分"
    if any(token in lowered for token in ["齿轮", "gearbox", "联轴器", "coupling"]):
        return "传动部分"
    if any(token in lowered for token in ["压缩机", "空压机", "机组", "螺杆", "转子", "叶轮"]):
        return "工作部分"
    return None


def _normalize_tree_node(node: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    result = dict(node)
    name = _normalize_text(result.get("name"))
    unit_type = result.get("unit_type")
    type_num = result.get("type_num")

    merged_children: list[dict[str, Any]] = []
    for child in result.get("children") or []:
        if isinstance(child, dict):
            merged_children.append(_normalize_tree_node(child, config))
    for point in result.get("points") or []:
        if isinstance(point, dict):
            merged_children.append(_normalize_tree_node(point, config))

    result.pop("points", None)
    result["children"] = merged_children

    if unit_type == 2 and type_num == 70:
        result["direction"] = result.get("direction") or _infer_bearing_direction(name, config)
        result["bearing_type"] = result.get("bearing_type") or _infer_bearing_types(name)

    if unit_type == 2 and type_num == 80:
        result["type"] = result.get("type") or _infer_device_type_from_name(name, config)
        result["system"] = result.get("system") or _infer_system(name)

    if unit_type == 3:
        result["type"] = result.get("type") or _infer_point_type(type_num, name, config)

    return result


def _collect_summary(nodes: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for node in nodes:
        name = _normalize_text(node.get("name"))
        unit_type = node.get("unit_type")
        type_num = node.get("type_num")
        if name:
            lines.append(f"{name}(unit_type={unit_type}, type_num={type_num})")
        for child in node.get("children") or []:
            if isinstance(child, dict):
                child_name = _normalize_text(child.get("name"))
                if child_name:
                    lines.append(f"{name} -> {child_name}")
    return lines[:20]


def _infer_device_type(nodes: list[dict[str, Any]], config: dict[str, Any]) -> str:
    names: list[str] = []

    def walk(items: list[dict[str, Any]]) -> None:
        for item in items:
            if not isinstance(item, dict):
                continue
            name = _normalize_text(item.get("name"))
            if name:
                names.append(name)
            walk(item.get("children") or [])

    walk(nodes)
    joined = " | ".join(names)
    inferred = _infer_device_type_from_name(joined, config)
    if inferred != "未知":
        return inferred
    return "未知"


def normalize_device_analysis_result(
    analysis_dict: dict[str, Any],
    config: dict[str, Any],
) -> tuple[dict[str, Any], DeviceContext]:
    normalized = dict(analysis_dict)
    raw_tree = normalized.get("child_device_list") or []
    normalized_tree = [_normalize_tree_node(node, config) for node in raw_tree if isinstance(node, dict)]
    normalized["child_device_list"] = normalized_tree

    child_device_summary = _collect_summary(normalized_tree)
    device_type_value = _infer_device_type(normalized_tree, config)
    normalized.setdefault("child_device_summary", child_device_summary)
    normalized.setdefault(
        "device_type",
        {
            "value": device_type_value,
            "confidence": "high" if device_type_value != "未知" else "low",
            "reason": "基于子设备名称、层级关系与已知设备类型别名归一化推断。",
        },
    )
    normalized.setdefault(
        "process_type",
        {
            "value": "",
            "confidence": "low",
            "reason": "",
        },
    )
    normalized.setdefault(
        "device_structure",
        {
            "value": "",
            "confidence": "low",
            "reason": "",
        },
    )

    context = build_device_context_index(normalized)
    return normalized, context


def _inference_item(value: str, confidence: str, reason: str) -> dict[str, str]:
    return {
        "value": value,
        "confidence": confidence,
        "reason": reason,
    }


def _infer_process_type(context: DeviceContext, device_type: str) -> dict[str, str]:
    process_types = {probe.point_type for probe in context.process_points if probe.point_type}
    if {"防喘振阀开度", "压缩机进气参数", "入口流量", "出口温度"} & process_types:
        return _inference_item("压缩机工艺", "high", "检测到进气、流量、出口温度或防喘振相关工艺测点。")
    if device_type == "汽轮机":
        return _inference_item("蒸汽驱动工艺", "medium", "设备类型推断为汽轮机，但工艺测点证据有限。")
    if device_type in {"离心式&轴流式压缩机", "多轴式（齿轮式）压缩机", "螺杆式压缩机"}:
        return _inference_item("压缩输送工艺", "medium", "设备类型推断为压缩机类，工艺类型按机组用途补位。")
    if device_type == "齿轮箱":
        return _inference_item("传动支撑工艺", "low", "检测到齿轮箱结构，工艺属性主要体现为传动支撑。")
    if device_type == "发电机":
        return _inference_item("发电工艺", "medium", "设备类型推断为发电机。")
    if device_type == "烟气轮机":
        return _inference_item("烟气驱动工艺", "medium", "设备类型推断为烟气轮机。")
    return _inference_item("", "low", "缺少足够工艺测点或名称证据，暂不补位。")


def _infer_device_structure(context: DeviceContext) -> dict[str, str]:
    rotor_count = len(context.rotor_device_ids)
    bearing_count = len(context.bearings)
    process_point_count = len(context.process_points)
    has_thrust = any("推力轴承" in bearing.bearing_types for bearing in context.bearings)

    if rotor_count >= 2:
        value = "多转子/多轴耦合结构"
        confidence = "medium"
        reason = f"识别到 {rotor_count} 个转子级设备，存在多轴或级间耦合特征。"
    elif rotor_count == 1 and bearing_count >= 2:
        value = "单转子-多轴承支撑结构"
        confidence = "high"
        reason = f"识别到 1 个转子设备、{bearing_count} 个轴承节点，符合典型转子-轴承层级。"
    elif rotor_count == 1:
        value = "单转子结构"
        confidence = "medium"
        reason = "识别到单个转子级设备，但轴承层级信息有限。"
    elif bearing_count > 0:
        value = "轴承-测点层级结构"
        confidence = "low"
        reason = f"识别到 {bearing_count} 个轴承节点，但未可靠识别转子层。"
    else:
        value = "未知"
        confidence = "low"
        reason = "子设备树缺少足够的转子/轴承层级特征。"

    if has_thrust:
        reason += " 同时检测到推力轴承特征。"
    if process_point_count > 0:
        reason += f" 工艺测点数量 {process_point_count}。"

    return _inference_item(value, confidence, reason)


def build_device_context_artifact(
    analysis_dict: dict[str, Any],
    config: dict[str, Any],
    sub_device_id: str | None = None,
) -> dict[str, Any]:
    normalized, context = normalize_device_analysis_result(analysis_dict, config)
    device_type_item = normalized.get("device_type") or {}
    device_type_value = str(device_type_item.get("value") or "未知")

    artifact = {
        "device_id": str(normalized.get("device_id") or ""),
        "child_device_summary": [str(item) for item in (normalized.get("child_device_summary") or []) if str(item).strip()],
        "device_type": device_type_item,
        "process_type": _infer_process_type(context, device_type_value),
        "device_structure": _infer_device_structure(context),
        "child_device_list": normalized.get("child_device_list") or [],
        "resolved_context": {
            "rotor_device_ids": list(context.rotor_device_ids),
            "bearing_ids": [bearing.bearing_id for bearing in context.bearings],
            "probe_ids": [probe.point_id for probe in context.probes],
            "process_point_ids": [probe.point_id for probe in context.process_points],
        },
    }

    if sub_device_id:
        target_info = resolve_sub_device_targets(context, sub_device_id)
        owner_device_id = str(target_info.get("owner_device_id") or "") or None
        target_device_type = (
            context.rotor_device_type_map.get(owner_device_id or "")
            or context.rotor_device_type_map.get(sub_device_id, "")
            or device_type_value
        )
        artifact["target_info"] = {
            **target_info,
            "target_device_type": target_device_type,
        }

    return artifact
