---
name: ins-extract-trend-features-9k
description: Use this skill when the user wants structured 9K trend feature extraction, anomaly timestamps, and summary findings for high-end / reciprocating rotating machinery points (RC, positionType 91..99). This wraps `features-tool/tools/extract_trend_features_9k_tool.py`, which forces `endpoint_series="9k"` and internally fetches the raw 9K trend first.
---

# InS Extract Trend Features (9K)

Use this skill to extract structured trend features and anomaly summaries from 9K high-end / reciprocating rotating machinery points.

## When to Use This Skill

Use this skill when the user:

- Wants changepoints, outliers, trend classes, alarm status, and notable timestamps for **9K 往复 / 高端旋转机组** (positionType 91..99) points
- Wants summarized 9K trend analysis without manually dealing with raw payloads
- Mentions `extract_trend_features_9k_tool.py`

Use the 8K default skill (`ins-extract-trend-features`) for standard rotating machinery, the 2K skill for legacy multi-feature vibration pumps, or the 6K skill for static-equipment corrosion monitoring.

## Preconditions

- The workspace contains `features-tool/`
- The caller can provide `component_features`, `start`, and `end`

## Execution Rules

- Default to this skill for 9K trend-analysis tasks
- Only fall back to `ins-get-trend-data-9k` when raw detailed 9K trend samples are explicitly required
- Pass `component_features` as one JSON string argument
- Pass `start` and `end` as separate arguments
- 9K-specific request parameters (`density=high` / `includeFilter=history` / `typeList=<features>`) are injected by `client.py`; the wrapper and skill layers must not hand-roll them

## Default Feature Mapping

Unless the user explicitly overrides the feature list:

- For `positionType in {93, 94}` (PBX / PBY 轴瓦振动), default to `["pp_value", "rms", "p_value", "speed"]`
- For `positionType=91` (JSZD), default to `["pp_value", "speed"]`
- For `positionType=92` (SZT), default to `["pp_value"]`
- For other 9K process measurement points, default to `["value"]`

## Command

```bash
bash /mnt/skills/custom/ins-extract-trend-features-9k/scripts/run.sh '{"9301":["pp_value","rms","p_value","speed"]}' '2026-04-15 00:00:00' '2026-04-16 00:00:00'
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

- This tool always calls `get_trend_data_9k_tool` internally
- Prefer this skill over `ins-get-trend-data-9k` unless the user explicitly needs raw detailed trend data
