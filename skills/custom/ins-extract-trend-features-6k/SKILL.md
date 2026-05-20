---
name: ins-extract-trend-features-6k
description: Use this skill when the user wants structured 6K trend feature extraction, anomaly timestamps, and summary findings for static-equipment corrosion monitoring points (PIPELINE, positionType 61..64). This wraps `features-tool/tools/extract_trend_features_6k_tool.py`, which forces `endpoint_series="6k"` and internally fetches the raw 6K trend first.
---

# InS Extract Trend Features (6K)

Use this skill to extract structured trend features and anomaly summaries from 6K static-equipment corrosion monitoring points.

## When to Use This Skill

Use this skill when the user:

- Wants changepoints, outliers, trend classes, alarm status, and notable timestamps for **6K 静设备腐蚀监测** (positionType 61..64) points
- Wants summarized 6K trend analysis without manually handling the nested payload
- Mentions `extract_trend_features_6k_tool.py`

Use the 8K default skill (`ins-extract-trend-features`) for standard rotating machinery, the 2K skill for legacy multi-feature vibration pumps, or the 9K skill for high-end / reciprocating rotating machinery.

## Preconditions

- The workspace contains `features-tool/`
- The caller can provide `component_features`, `start`, and `end`

## Execution Rules

- Default to this skill for 6K trend-analysis tasks
- Only fall back to `ins-get-trend-data-6k` when raw detailed 6K trend samples are explicitly required
- Pass `component_features` as one JSON string argument
- Pass `start` and `end` as separate arguments

## Default Feature Mapping

Unless the user explicitly overrides the feature list:

- For `positionType=62` (TH 探头) corrosion points, default to `["corrosionRate", "thinningRate", "thickness", "temperature"]`
- For `positionType=61` (STA) process measurement points, default to `["value"]`
- For `positionType=63` (P 腐蚀探针) and `positionType=64` (OTHER_TH 离线检测) points, default to `["corrosionRate", "thinningRate", "thickness"]`

## Command

```bash
bash /mnt/skills/custom/ins-extract-trend-features-6k/scripts/run.sh '{"5101":["corrosionRate","thinningRate","thickness","temperature"]}' '2026-04-15 00:00:00' '2026-04-16 00:00:00'
```

## Output

The tool returns JSON with:

- `component_ids`
- `start_time`
- `end_time`
- `component_features`
- `point_results`

Each point result includes:

- `feature_stats`
- `anomaly_time_ms`
- `summary`
- `notable_points`

## Notes

- This tool always calls `get_trend_data_6k_tool` internally
- Prefer this skill over `ins-get-trend-data-6k` unless the user explicitly needs raw detailed trend data
- Thickness time series should additionally output window-endpoint difference (`thickness_loss`) and linear-regression slope (`thinning_rate_fit`); both can be cross-validated against the InS-native `thinningRate` field
