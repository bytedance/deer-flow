---
name: ins-extract-trend-features-2k
description: Use this skill when the user wants structured 2K trend feature extraction, anomaly timestamps, and summary findings for 机泵 PUMP multi-feature vibration points (positionType 22..30). This wraps `features-tool/tools/extract_trend_features_2k_tool.py`, which forces `endpoint_series="2k"` and internally fetches the raw 2K trend first.
---

# InS Extract Trend Features (2K)

Use this skill to extract structured trend features and anomaly summaries from 2K multi-feature vibration points.

## When to Use This Skill

Use this skill when the user:

- Wants changepoints, outliers, trend classes, alarm status, and notable timestamps for **2K 机泵** (positionType 22..30) points
- Wants summarized 2K trend analysis without manually dealing with the raw nested payload
- Mentions `extract_trend_features_2k_tool.py`

Use the 8K default skill (`ins-extract-trend-features`) for standard rotating machinery, the 6K skill for static-equipment corrosion monitoring, or the 9K skill for high-end / reciprocating rotating machinery.

## Preconditions

- The workspace contains `features-tool/`
- The caller can provide `component_features`, `start`, and `end`

## Execution Rules

- Default to this skill for 2K trend-analysis tasks
- Only fall back to `ins-get-trend-data-2k` when raw detailed 2K trend samples are explicitly required
- Pass `component_features` as one JSON string argument
- Pass `start` and `end` as separate arguments

## Default Feature Mapping

Unless the user explicitly overrides:

- For `positionType in {22..30}` 2K vibration points, default to `["v_rms", "a_peak", "a_rms", "kurtosis", "margin", "pulse", "wave"]`

Feature naming follows the ASCII keys produced by `_TWO_K_NAME_KEY_MAP` in `client.py` (see `ins-get-trend-data-2k` for the full map). Do not invent features outside this map.

## Command

```bash
bash /mnt/skills/custom/ins-extract-trend-features-2k/scripts/run.sh '{"3102":["v_rms","a_peak"],"3103":["v_rms"]}' '2026-04-15 00:00:00' '2026-04-16 00:00:00'
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

- This tool always calls `get_trend_data_2k_tool` internally
- Prefer this skill over `ins-get-trend-data-2k` unless the user explicitly needs raw detailed trend data
- The output does not expose raw trend samples; for B/C/D tier alarm thresholds use `ins-device-analysis-2k`
