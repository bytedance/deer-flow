---
name: ins-get-trend-data-2k
description: Use this skill when the user wants to fetch raw 2K series trend data from the InS feature tools for one or more measurement points on legacy multi-feature vibration devices (机泵 PUMP, positionType 22..30). This wraps `features-tool/tools/get_trend_data_2k_tool.py` which forces `endpoint_series="2k"`. Required inputs are component IDs, per-component feature lists, and a start/end time.
---

# InS Get Trend Data (2K)

Use this skill to fetch raw 2K trend history through the bundled `features-tool/tools/get_trend_data_2k_tool.py`.

## When to Use This Skill

Use this skill when the user:

- Wants raw 2K trend data for one or more component IDs on **机泵 PUMP** (positionType 22..30)
- Needs the nested-payload-flattened ASCII features (`v_rms`, `a_peak`, `a_rms`, `pp_value`, `envelope_peak`, `kurtosis`, `margin`, `pulse`, `wave`) for downstream extraction
- Already knows the target 2K component IDs and desired vibration features
- Mentions `get_trend_data_2k_tool.py` or "2K raw trend"

Use the 8K default skill (`ins-get-trend-data`) for standard rotating machinery, the 6K skill for static-equipment corrosion monitoring, or the 9K skill for high-end / reciprocating rotating machinery.

## Preconditions

- The workspace contains `features-tool/`
- The runtime can execute `python3`
- Required env vars or `.env` for the InS client are already available to `features-tool`

## Execution Rules

- Default to `ins-extract-trend-features-2k` for trend analysis tasks
- Use this skill only when the user explicitly needs raw detailed 2K trend data
- Run the wrapper script instead of manually reconstructing the Python invocation
- Pass `component_features` as a single JSON string argument
- Pass `start` and `end` as separate arguments in `YYYY-MM-DD HH:MM:SS` or supported datetime input format

## Default Feature Mapping

The 2K wrapper accepts the following ASCII features (translated from InS nested Chinese `name` fields via `_TWO_K_NAME_KEY_MAP` inside `client.py`):

| ASCII key | Source Chinese name |
|---|---|
| `v_rms` | 速度有效值 |
| `a_peak` | 加速度峰值 |
| `a_rms` | 加速度有效值 |
| `pp_value` | 位移峰峰值 |
| `envelope_peak` | 包络谱峰值 |
| `kurtosis` | 峭度 |
| `margin` | 裕度 |
| `pulse` | 脉冲指标 |
| `wave` | 波形指标 |

Unless the user explicitly overrides:

- For `positionType in {22..30}` 2K vibration points, default to `["v_rms", "a_peak", "a_rms", "kurtosis", "margin", "pulse", "wave"]`

Do not invent features outside this map; unknown InS Chinese names are passed through as-is by `client.py` and logged for the maintainer to extend the map.

## Command

```bash
bash /mnt/skills/custom/ins-get-trend-data-2k/scripts/run.sh '{"3102":["v_rms","a_peak"],"3103":["v_rms"]}' '2026-04-15 00:00:00' '2026-04-16 00:00:00'
```

## Output

The tool returns JSON with:

- `component_ids`
- `start_time`
- `end_time`
- `component_features`
- `data`

## Notes

- This skill only fetches raw 2K trend data; it does not interpret anomalies
- Prefer `ins-extract-trend-features-2k` by default
- For B/C/D tier threshold metadata, use `ins-device-analysis-2k` which exposes `alarm_thresholds: {<feature>: {B, C, D}}`
