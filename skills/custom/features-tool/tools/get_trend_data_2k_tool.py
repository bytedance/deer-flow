"""2K series trend data tool (机泵 PUMP, positionType 22..30).

Thin derivative of get_trend_data_tool: forces endpoint_series="2k" so the
client routes to /ins-os-view/data/getTrendDataHis with density=1 and
flattens nested 2K responses by Chinese name → ASCII key.

Output schema is normalized to match the 8K default tool:
    {component_id, time_ms, time, values: {feature: float | None}}
so downstream extract_trend_features_2k_tool can reuse the standard
trend-feature pipeline.
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
from ins.client import datetime_input_to_ms, format_ms_timestamp
from tools.get_trend_data_tool import (
    collect_union_features,
    group_trend_data_by_component,
    normalize_component_features,
)

ENDPOINT_SERIES = "2k"

load_dotenv_file()
INS_SETTINGS = load_ins_settings()
ins_client = InsApiClient(INS_SETTINGS)


def _flat_row_to_unified(component_id: str, row: dict, features: list[str]) -> dict | None:
    ts = None
    for key in ("time_ms", "datatime", "time", "ts", "timestamp", "collectTime"):
        raw = row.get(key)
        if raw is None:
            continue
        if isinstance(raw, (int, float)):
            ts = str(int(raw))
            break
        if isinstance(raw, str):
            if raw.isdigit():
                ts = raw
                break
            converted = datetime_input_to_ms(raw)
            if converted != raw or raw.isdigit():
                ts = converted
                break
    if not ts:
        return None
    values: dict[str, float] = {}
    for feature in features:
        v = row.get(feature)
        if isinstance(v, (int, float)):
            values[feature] = float(v)
    return {
        "component_id": component_id,
        "time_ms": ts,
        "time": format_ms_timestamp(ts),
        "values": values,
    }


async def _get_trend_data_impl(
    component_features: dict[str, list[str]],
    start: str,
    end: str,
) -> dict[str, object]:
    normalized = normalize_component_features(component_features)
    if not normalized:
        raise ValueError("component_features is empty after normalization")

    component_ids = list(normalized.keys())
    union_features = collect_union_features(normalized)
    if not union_features:
        raise ValueError("No valid features found in component_features")

    start_ms = datetime_input_to_ms(start)
    end_ms = datetime_input_to_ms(end)

    unified_rows: list[dict] = []
    for component_id in component_ids:
        features = normalized[component_id]
        rows = await ins_client.get_trend_data(
            component_id,
            start_ms,
            end_ms,
            features,
            endpoint_series=ENDPOINT_SERIES,
        )
        for row in rows:
            if not isinstance(row, dict):
                continue
            unified = _flat_row_to_unified(component_id, row, features)
            if unified is not None:
                unified_rows.append(unified)

    return {
        "component_ids": component_ids,
        "start_time": start_ms,
        "end_time": end_ms,
        "component_features": normalized,
        "endpoint_series": ENDPOINT_SERIES,
        "data": group_trend_data_by_component(unified_rows, component_ids),
    }


async def get_trend_data_2k_tool(
    component_features: dict[str, list[str]],
    start: str,
    end: str,
) -> dict[str, object]:
    """获取 2K（机泵 PUMP，positionType 22..30）多测点趋势数据。

    输入示例:
    {
      "component_features": {
        "<2k_point_id>": ["v_rms", "a_peak", "kurtosis"]
      },
      "start": "2026-03-29 00:00:00",
      "end": "2026-03-30 00:00:00"
    }
    """
    return await _get_trend_data_impl(component_features, start, end)


async def close_clients() -> None:
    await ins_client.close()


async def main() -> None:
    if len(sys.argv) < 4:
        raise SystemExit(
            "用法: python get_trend_data_2k_tool.py '<component_features_json>' <start> <end>"
        )
    component_features = json.loads(sys.argv[1])
    try:
        result = await _get_trend_data_impl(component_features, sys.argv[2], sys.argv[3])
        print(json.dumps(result, indent=2, ensure_ascii=False))
    finally:
        await close_clients()


if __name__ == "__main__":
    asyncio.run(main())
