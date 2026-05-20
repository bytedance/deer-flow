"""9K series trend data tool (往复 / 高端旋转机组 RC, positionType 91..99).

Thin derivative of get_trend_data_tool: forces endpoint_series="9k" so the
client routes to /ins-os-view/sg9kData/getTrendDataHis with the
density=high / includeFilter=history / typeList=<features> combo
auto-injected by the client.
"""
import asyncio
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ins import InsApiClient, load_dotenv_file, load_ins_settings
from ins.client import datetime_input_to_ms
from tools.get_trend_data_tool import (
    collect_union_features,
    group_trend_data_by_component,
    normalize_component_features,
)

ENDPOINT_SERIES = "9k"

load_dotenv_file()
INS_SETTINGS = load_ins_settings()
ins_client = InsApiClient(INS_SETTINGS)


async def _get_trend_data_impl(
    component_features: dict[str, list[str]],
    start: str,
    end: str,
) -> dict[str, object]:
    normalized = normalize_component_features(component_features)
    if not normalized:
        raise ValueError("component_features is empty after normalization")

    component_ids = list(normalized.keys())
    all_features = collect_union_features(normalized)
    if not all_features:
        raise ValueError("No valid features found in component_features")

    start_ms = datetime_input_to_ms(start)
    end_ms = datetime_input_to_ms(end)

    data = await ins_client.get_trend_data(
        ",".join(component_ids),
        start_ms,
        end_ms,
        all_features,
        endpoint_series=ENDPOINT_SERIES,
    )

    return {
        "component_ids": component_ids,
        "start_time": start_ms,
        "end_time": end_ms,
        "component_features": normalized,
        "endpoint_series": ENDPOINT_SERIES,
        "data": group_trend_data_by_component(data, component_ids),
    }


async def get_trend_data_9k_tool(
    component_features: dict[str, list[str]],
    start: str,
    end: str,
) -> dict[str, object]:
    """获取 9K（往复 / 高端旋转机组 RC，positionType 91..99）多测点趋势数据。"""
    return await _get_trend_data_impl(component_features, start, end)


async def close_clients() -> None:
    await ins_client.close()


async def main() -> None:
    if len(sys.argv) < 4:
        raise SystemExit(
            "用法: python get_trend_data_9k_tool.py '<component_features_json>' <start> <end>"
        )
    component_features = json.loads(sys.argv[1])
    try:
        result = await _get_trend_data_impl(component_features, sys.argv[2], sys.argv[3])
        print(json.dumps(result, indent=2, ensure_ascii=False))
    finally:
        await close_clients()


if __name__ == "__main__":
    asyncio.run(main())
