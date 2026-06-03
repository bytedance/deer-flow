"""2K series device analysis tool (机泵 PUMP, positionType 22..30).

Filters slim component tree to keep only points whose endpoint_series == "2k".
Preserves alarm_thresholds (B/C/D tiers) for downstream diagnosis skills,
which default to the C-tier as the primary alarm threshold.
"""
import asyncio
import json
import sys
from pathlib import Path

# 添加 features-tool 到 sys.path（ins 模块 + tools 包）
_FEATURES_TOOL_ROOT = Path(__file__).resolve().parent.parent
if str(_FEATURES_TOOL_ROOT) not in sys.path:
    sys.path.insert(0, str(_FEATURES_TOOL_ROOT))

from ins import InsApiClient, load_dotenv_file, load_ins_settings

ENDPOINT_SERIES = "2k"

load_dotenv_file()
INS_SETTINGS = load_ins_settings()
ins_client = InsApiClient(INS_SETTINGS)


def _filter_node_by_series(node: dict, series: str) -> dict | None:
    if not isinstance(node, dict):
        return None

    own_series = node.get("endpoint_series")

    # Point node: keep iff series matches
    if own_series is not None:
        return node if own_series == series else None

    # Machine / group node: recurse and keep iff any descendant survives
    children = [
        filtered
        for child in node.get("children") or []
        for filtered in [_filter_node_by_series(child, series)]
        if filtered is not None
    ]
    points = [
        filtered
        for point in node.get("points") or []
        for filtered in [_filter_node_by_series(point, series)]
        if filtered is not None
    ]
    if not children and not points:
        return None

    new_node = {k: v for k, v in node.items() if k not in ("children", "points")}
    if children:
        new_node["children"] = children
    if points:
        new_node["points"] = points
    return new_node


async def get_device_children_2k(device_id: str) -> dict:
    if not INS_SETTINGS.access_token and (not INS_SETTINGS.username or not INS_SETTINGS.password):
        raise RuntimeError("缺少 INS_ACCESS_TOKEN，且未配置 INS_USERNAME/INS_PASSWORD，无法访问 InS 接口")

    components = await ins_client.get_slim_components(device_id)
    filtered = [
        node
        for raw in components
        for node in [_filter_node_by_series(raw, ENDPOINT_SERIES)]
        if node is not None
    ]
    return {
        "device_id": device_id,
        "endpoint_series": ENDPOINT_SERIES,
        "child_device_list": filtered,
    }


async def close_clients() -> None:
    await ins_client.close()


async def main() -> None:
    if len(sys.argv) <= 1:
        raise SystemExit("用法: python device_analysis_2k_tool.py <设备ID>")
    try:
        result = await get_device_children_2k(sys.argv[1])
        print(json.dumps(result, indent=2, ensure_ascii=False))
    finally:
        await close_clients()


if __name__ == "__main__":
    asyncio.run(main())
