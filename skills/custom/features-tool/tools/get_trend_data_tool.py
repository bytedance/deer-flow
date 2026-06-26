import asyncio
import json
import sys
from pathlib import Path

# 添加 features-tool 到 sys.path（ins 模块 + tools 包）
_FEATURES_TOOL_ROOT = Path(__file__).resolve().parent.parent
if str(_FEATURES_TOOL_ROOT) not in sys.path:
    sys.path.insert(0, str(_FEATURES_TOOL_ROOT))

from ins import InsApiClient, close_shared_http_client, load_dotenv_file, load_ins_settings
from ins.client import datetime_input_to_ms

load_dotenv_file()
INS_SETTINGS = load_ins_settings()

ins_client = InsApiClient(INS_SETTINGS)


def normalize_component_features(component_features: dict[str, list[str]]) -> dict[str, list[str]]:
    normalized: dict[str, list[str]] = {}
    for raw_component_id, raw_features in component_features.items():
        component_id = str(raw_component_id).strip()
        if not component_id:
            continue

        if not isinstance(raw_features, list):
            continue

        features: list[str] = []
        seen: set[str] = set()
        for raw_feature in raw_features:
            feature = str(raw_feature).strip()
            if feature and feature not in seen:
                seen.add(feature)
                features.append(feature)

        if features:
            normalized[component_id] = features

    return normalized


def collect_union_features(component_features: dict[str, list[str]]) -> list[str]:
    seen: set[str] = set()
    union: list[str] = []
    for features in component_features.values():
        for feature in features:
            if feature not in seen:
                seen.add(feature)
                union.append(feature)
    return union


def group_trend_data_by_component(
    trend_data: list[dict[str, object]],
    component_ids: list[str],
) -> dict[str, list[dict[str, object]]]:
    grouped: dict[str, list[dict[str, object]]] = {component_id: [] for component_id in component_ids}
    for item in trend_data:
        raw_component_id = item.get("component_id")
        if not isinstance(raw_component_id, str) or not raw_component_id:
            continue
        grouped.setdefault(raw_component_id, []).append(item)
    return grouped


async def _get_trend_data_impl(
    component_features: dict[str, list[str]],
    start: str,
    end: str,
) -> dict[str, object]:
    normalized_component_features = normalize_component_features(component_features)
    if not normalized_component_features:
        raise ValueError("component_features is empty after normalization")

    component_ids = list(normalized_component_features.keys())
    all_features = collect_union_features(normalized_component_features)
    if not all_features:
        raise ValueError("No valid features found in component_features")

    start_ms = datetime_input_to_ms(start)
    end_ms = datetime_input_to_ms(end)

    data = await ins_client.get_trend_data(
        ",".join(component_ids),
        start_ms,
        end_ms,
        all_features,
    )

    return {
        "component_ids": component_ids,
        "start_time": start_ms,
        "end_time": end_ms,
        "component_features": normalized_component_features,
        "data": group_trend_data_by_component(data, component_ids),
    }


async def get_trend_data_tool(
    component_features: dict[str, list[str]],
    start: str,
    end: str,
) -> dict[str, object]:
    """
    获取多个测点的趋势图数据，按测点分别指定特征。

    输入示例:
    {
      "component_features": {
        "id_83": ["pp_value", "rms"],
        "id_82": ["value"]
      },
      "start": "2026-03-29 00:00:00",
      "end": "2026-03-30 00:00:00"
    }
    """
    return await _get_trend_data_impl(component_features, start, end)


async def close_clients() -> None:
    await close_shared_http_client()


async def main() -> None:
    if len(sys.argv) < 4:
        raise SystemExit(
            "用法: python get_trend_data_tool.py '<component_features_json>' <start> <end>"
        )

    component_features = json.loads(sys.argv[1])

    try:
        result = await _get_trend_data_impl(component_features, sys.argv[2], sys.argv[3])
        print(json.dumps(result, indent=2, ensure_ascii=False))
    finally:
        await close_clients()


if __name__ == "__main__":
    asyncio.run(main())
