"""6K series trend data tool (静设备腐蚀监测 PIPELINE, positionType 61..64).

Thin derivative of get_trend_data_tool: forces endpoint_series="6k" so the
client routes to /ins-os-view/sg6kData/getTrendDataHis with density=1 and
flattens nested 6K responses by `key` (corrosionRate / thinningRate /
thickness / temperature) into a flat row.

Output schema is normalized to match the 8K default tool:
    {component_id, time_ms, time, values: {feature: float | None}}
"""
import asyncio
import json
import sys
from pathlib import Path

# 添加依赖路径：features-tool (ins模块) + rotating-fault-diagnosis (8k脚本) + pump-fault-diagnosis (2k脚本)
_FEATURES_TOOL_ROOT = Path(__file__).resolve().parent.parent
_ROTATING_SCRIPTS = Path("/mnt/skills/custom/rotating-fault-diagnosis/scripts")
_PUMP_SCRIPTS = Path("/mnt/skills/custom/pump-fault-diagnosis/scripts")
for _p in [str(_FEATURES_TOOL_ROOT), str(_ROTATING_SCRIPTS), str(_PUMP_SCRIPTS)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from ins import InsApiClient, load_dotenv_file, load_ins_settings
from ins.client import datetime_input_to_ms, format_ms_timestamp
from tools.get_trend_data_tool import (
    collect_union_features,
    group_trend_data_by_component,
    normalize_component_features,
)
from tools.get_trend_data_2k_tool import _flat_row_to_unified

ENDPOINT_SERIES = "6k"
DEFAULT_FEATURES = ["corrosionRate", "thinningRate", "thickness", "temperature"]

load_dotenv_file()
INS_SETTINGS = load_ins_settings()
ins_client = InsApiClient(INS_SETTINGS)


async def _get_trend_data_impl(
    component_features: dict[str, list[str]],
    start: str,
    end: str,
) -> dict[str, object]:
    # Inject 6K defaults for empty/missing feature lists BEFORE normalization
    # (normalize_component_features drops entries whose feature list is empty).
    expanded: dict[str, list[str]] = {}
    for raw_cid, raw_features in component_features.items():
        cid = str(raw_cid).strip()
        if not cid:
            continue
        if isinstance(raw_features, list) and any(str(f).strip() for f in raw_features):
            expanded[cid] = raw_features
        else:
            expanded[cid] = list(DEFAULT_FEATURES)

    normalized = normalize_component_features(expanded)
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


async def get_trend_data_6k_tool(
    component_features: dict[str, list[str]],
    start: str,
    end: str,
) -> dict[str, object]:
    """获取 6K（静设备腐蚀监测 PIPELINE，positionType 61..64）多测点趋势数据。

    若某测点 features 为空，使用默认 ["corrosionRate", "thinningRate", "thickness", "temperature"]。

    输入示例:
    {
      "component_features": {
        "<6k_point_id>": ["corrosionRate", "thickness"]
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
            "用法: python get_trend_data_6k_tool.py '<component_features_json>' <start> <end>"
        )
    component_features = json.loads(sys.argv[1])
    try:
        result = await _get_trend_data_impl(component_features, sys.argv[2], sys.argv[3])
        print(json.dumps(result, indent=2, ensure_ascii=False))
    finally:
        await close_clients()


if __name__ == "__main__":
    asyncio.run(main())
