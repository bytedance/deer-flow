---
name: ins-get-trend-data-6k
description: Use this skill when the user wants to fetch raw 6K series trend data from the InS feature tools for one or more measurement points on static-equipment corrosion monitoring devices (PIPELINE, positionType 61..64). This wraps `features-tool/tools/get_trend_data_6k_tool.py` which forces `endpoint_series="6k"`. Required inputs are component IDs, per-component feature lists, and a start/end time.
---

# InS Get Trend Data (6K)

Use this skill to fetch raw 6K trend history for static-equipment corrosion monitoring points through `features-tool/tools/get_trend_data_6k_tool.py`.

## When to Use This Skill

Use this skill when the user:

- Wants raw 6K trend data for one or more component IDs on **静设备腐蚀监测 PIPELINE** (positionType 61..64)
- Needs flattened `corrosionRate` / `thinningRate` / `thickness` / `temperature` time series from the InS nested 6K payload
- Already knows the target 6K component IDs and desired corrosion features
- Mentions `get_trend_data_6k_tool.py` or "6K raw trend"

Use the 8K default skill (`ins-get-trend-data`) for standard rotating machinery, the 2K skill for legacy multi-feature vibration pumps, or the 9K skill for high-end / reciprocating rotating machinery.

## Preconditions

- The workspace contains `features-tool/`
- The runtime can execute `python3`
- Required env vars or `.env` for the InS client are already available to `features-tool`

## Execution Rules

- Default to `ins-extract-trend-features-6k` for trend analysis tasks
- Use this skill only when the user explicitly needs raw detailed 6K trend data
- Pass `component_features` as a single JSON string argument
- Pass `start` and `end` as separate arguments in `YYYY-MM-DD HH:MM:SS` or supported datetime input format

## Default Feature Mapping

Unless the user explicitly overrides the feature list:

- For `positionType=62` (TH 探头) 6K corrosion points, default to `["corrosionRate", "thinningRate", "thickness", "temperature"]`
- For `positionType=61` (STA) 6K process measurement points, default to `["value"]`
- For `positionType=63` (P 腐蚀探针) and `positionType=64` (OTHER_TH 离线检测) points, default to `["corrosionRate", "thinningRate", "thickness"]`

All 6K features are flattened from the InS nested `value` array using the inner `key` field by `parse_trend_response(rows, "6k")` inside `client.py`. Empty strings are converted to `None` and skipped by downstream aggregation.

## Command

```bash
bash /mnt/skills/custom/ins-get-trend-data-6k/scripts/run.sh '{"5101":["corrosionRate","thinningRate","thickness","temperature"]}' '2026-04-15 00:00:00' '2026-04-16 00:00:00'
```

## Output

The tool returns JSON with:

- `component_ids`
- `start_time`
- `end_time`
- `component_features`
- `data`

## Notes

- This skill only fetches raw 6K corrosion trend data; it does not interpret anomalies
- Prefer `ins-extract-trend-features-6k` by default
- 6K nested response flattening is performed entirely inside `client.py`; the wrapper does no second-pass parsing
