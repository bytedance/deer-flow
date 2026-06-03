"""2K series trend feature extractor (机泵 PUMP, positionType 22..30)."""
import asyncio
import json
import sys
from pathlib import Path

# 添加依赖路径：features-tool (ins模块) + rotating-fault-diagnosis (8k脚本)
_SKILL_ROOT = Path(__file__).resolve().parent.parent
_FEATURES_TOOL_ROOT = Path("/mnt/skills/custom/features-tool")
_ROTATING_SCRIPTS = Path("/mnt/skills/custom/rotating-fault-diagnosis/scripts")
for _p in [str(_SKILL_ROOT), str(_FEATURES_TOOL_ROOT), str(_ROTATING_SCRIPTS)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from tools.extract_trend_features_tool import (
    TrendAnalysisResult,
    TrendPointAnalysisResult,
    _build_feature_detail,
    _build_notable_points_for_feature,
    _build_summary_for_feature,
    _collect_primary_anomaly_time_ms,
    _extract_feature_series,
    _merge_feature_notable_points,
    _merge_feature_summaries,
)
from tools.get_trend_data_2k_tool import _get_trend_data_impl


async def extract_trend_features_2k_tool(
    component_features: dict[str, list[str]],
    start: str,
    end: str,
) -> dict[str, object]:
    """提取 2K（机泵 PUMP）多 feature 振动测点的趋势特征。

    输入示例:
    {
      "component_features": {
        "<2k_point_id>": ["v_rms", "a_peak", "kurtosis"]
      },
      "start": "...",
      "end": "..."
    }
    """
    payload = await _get_trend_data_impl(component_features, start, end)

    component_ids = payload.get("component_ids") or []
    component_features_norm = payload.get("component_features") or {}
    grouped = payload.get("data") or {}

    point_results: list[TrendPointAnalysisResult] = []
    for component_id in component_ids:
        point_data = grouped.get(component_id) or []
        if not isinstance(point_data, list):
            point_data = []
        features = component_features_norm.get(component_id) or []
        if not isinstance(features, list):
            features = []

        feature_stats = {}
        feature_summaries = {}
        feature_notables = {}
        anomaly_ts: list[str] = []
        seen_ts: set[str] = set()

        for feature in features:
            series = _extract_feature_series(point_data, feature)
            detail = _build_feature_detail(point_data, series)
            feature_stats[feature] = detail
            feature_summaries[feature] = _build_summary_for_feature(feature, detail)
            feature_notables[feature] = _build_notable_points_for_feature(feature, series, detail)
            for ts in _collect_primary_anomaly_time_ms(detail):
                if ts and ts not in seen_ts:
                    seen_ts.add(ts)
                    anomaly_ts.append(ts)

        point_results.append(
            TrendPointAnalysisResult(
                component_id=component_id,
                features=features,
                feature_stats=feature_stats,
                anomaly_time_ms=anomaly_ts[:12],
                summary=_merge_feature_summaries(feature_summaries),
                notable_points=_merge_feature_notable_points(feature_notables),
            )
        )

    result = TrendAnalysisResult(
        component_ids=component_ids,
        start_time=str(payload.get("start_time") or ""),
        end_time=str(payload.get("end_time") or ""),
        component_features=component_features_norm,
        point_results=point_results,
    )
    return result.model_dump()


async def main() -> None:
    if len(sys.argv) < 4:
        raise SystemExit(
            "用法: python extract_trend_features_2k_tool.py '<component_features_json>' <start> <end>"
        )
    component_features = json.loads(sys.argv[1])
    result = await extract_trend_features_2k_tool(component_features, sys.argv[2], sys.argv[3])
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
