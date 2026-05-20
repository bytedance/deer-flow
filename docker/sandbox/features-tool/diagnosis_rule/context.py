from __future__ import annotations

from typing import Any

from diagnosis.context_index import build_device_context_index
from diagnosis.models import DeviceContext
from ins import InsApiClient, load_dotenv_file, load_ins_settings
from tools.device_analysis import analyze_device

from .config import load_config

load_dotenv_file()
_ins_client = InsApiClient(load_ins_settings())


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

    if unit_type == 3:
        result["type"] = _infer_point_type(type_num, name, config)

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


async def build_rule_device_context(device_id: str) -> DeviceContext:
    config = load_config()
    analysis_dict = await analyze_device(device_id)
    # Normalize the tree nodes so point_type, bearing_direction etc. are inferred
    raw_tree = analysis_dict.get("child_device_list") or []
    normalized_tree = [_normalize_tree_node(node, config) for node in raw_tree if isinstance(node, dict)]
    analysis_dict["child_device_list"] = normalized_tree
    return build_device_context_index(analysis_dict)


async def close_clients() -> None:
    await _ins_client.close()
    from tools.device_analysis import close_clients as close_device_analysis_clients
    await close_device_analysis_clients()
