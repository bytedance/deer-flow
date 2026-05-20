---
name: ins-get-trend-data-9k
description: Use this skill when the user wants to fetch raw 9K series trend data from the InS feature tools for one or more measurement points on high-end / reciprocating rotating machinery (RC, positionType 91..99). This wraps `features-tool/tools/get_trend_data_9k_tool.py` which forces `endpoint_series="9k"`. Required inputs are component IDs, per-component feature lists, and a start/end time.
---

# InS Get Trend Data (9K)

Use this skill to fetch raw 9K trend history for high-end / reciprocating rotating machinery points through `features-tool/tools/get_trend_data_9k_tool.py`.

## When to Use This Skill

Use this skill when the user:

- Wants raw 9K trend data for one or more component IDs on **往复 / 高端旋转机组 RC** (positionType 91..99)
- Needs server-side high-density historical samples (`density=high`, `includeFilter=history`)
- Already knows the target 9K component IDs and desired vibration / speed features
- Mentions `get_trend_data_9k_tool.py` or "9K raw trend"

Use the 8K default skill (`ins-get-trend-data`) for standard rotating machinery, the 2K skill for legacy multi-feature vibration pumps, or the 6K skill for static-equipment corrosion monitoring.

## Preconditions

- The workspace contains `features-tool/`
- The runtime can execute `python3`
- Required env vars or `.env` for the InS client are already available to `features-tool`

## Execution Rules

- Default to `ins-extract-trend-features-9k` for trend analysis tasks
- Use this skill only when the user explicitly needs raw detailed 9K trend data
- Pass `component_features` as a single JSON string argument
- Pass `start` and `end` as separate arguments in `YYYY-MM-DD HH:MM:SS` or supported datetime input format
- Do **not** manually pass `density` / `includeFilter` / `typeList`; `client.py` injects them automatically when `endpoint_series == "9k"`

## Default Feature Mapping

Unless the user explicitly overrides the feature list:

- For `positionType in {93, 94}` (PBX / PBY 轴瓦振动), default to `["pp_value", "rms", "p_value", "speed"]`
- For `positionType=91` (JSZD), default to `["pp_value", "speed"]`
- For `positionType=92` (SZT), default to `["pp_value"]`
- For other 9K process measurement points, default to `["value"]`

Do not invent other feature names unless the user explicitly asks for them.

## Command

```bash
bash /mnt/skills/custom/ins-get-trend-data-9k/scripts/run.sh '{"9301":["pp_value","rms","p_value","speed"]}' '2026-04-15 00:00:00' '2026-04-16 00:00:00'
```

## Output

The tool returns JSON with:

- `component_ids`
- `start_time`
- `end_time`
- `component_features`
- `data`

## Notes

- This skill only fetches raw 9K trend data; it does not interpret anomalies
- Prefer `ins-extract-trend-features-9k` by default
- 9K-specific request parameters (`density=high`, `includeFilter=history`, `typeList=<features>`) are injected by `client.py`; do not duplicate them in the wrapper
