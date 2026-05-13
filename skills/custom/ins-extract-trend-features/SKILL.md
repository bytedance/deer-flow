---
name: ins-extract-trend-features
description: Use this skill when the user wants structured trend feature extraction, anomaly timestamps, and summary findings for one or more measurement points. This wraps `features-tool/tools/extract_trend_features_tool.py`, which internally fetches the raw trend data first.
---

# InS Extract Trend Features

Use this skill to fetch trend data internally and convert it into structured trend features and anomaly summaries.

## When to Use This Skill

Use this skill when the user:

- Wants changepoints, outliers, trend classes, alarm status, and notable timestamps
- Wants a summarized trend analysis for one or more measurement points
- Wants the default trend-analysis path without manually dealing with raw trend payloads
- Mentions `extract_trend_features_tool.py`

## Preconditions

- The workspace contains `features-tool/`
- The caller can provide `component_features`, `start`, and `end`

## Execution Rules

- Default to this skill for trend-analysis tasks
- Only fall back to `ins-get-trend-data` when raw detailed trend samples are explicitly required
- Before building `component_features`, choose feature names by component type using the default mapping below
- Pass `component_features` as one JSON string argument
- Pass `start` and `end` as separate arguments
- Let the tool fetch raw trend data internally
- Preserve the returned JSON structure

## Default Feature Mapping

Unless the user explicitly overrides the feature list, use these defaults:

- For `type=83` points whose name contains `波形`, ignore them and do not include them in trend queries
- For `type=83` shaft vibration points whose name does not contain `波形`, always use `["pp_value", "rms", "p_value", "speed", "gap", "one_freq_y", "one_freq_x", "two_freq_y", "two_freq_x", "half_freq", "remain_freq"]`
- For `type=82` process measurement points such as axial displacement, bearing temperature, lube oil temperature, and other process values, use `["value"]`
- For `type=81` speed points, use `["speed"]`

Do not invent other trend feature names unless the user explicitly asks for them.

## Command

```bash
bash /mnt/skills/custom/ins-extract-trend-features/scripts/run.sh '{"1801":["pp_value","rms"],"1802":["value"]}' '2026-04-15 00:00:00' '2026-04-16 00:00:00'
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

- This tool now always calls `get_trend_data_tool` internally
- Prefer this skill over `ins-get-trend-data` unless the user explicitly needs raw detailed trend data
- The output does not expose raw trend samples
