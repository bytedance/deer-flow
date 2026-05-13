---
name: ins-get-trend-data
description: Use this skill when the user wants to fetch raw trend data from the InS feature tools for one or more measurement points. This wraps `features-tool/tools/get_trend_data_tool.py`. The required inputs are component IDs, per-component feature lists, and a start/end time.
---

# InS Get Trend Data

Use this skill to fetch raw trend history data through the bundled `features-tool` Python tool.

## When to Use This Skill

Use this skill when the user:

- Wants raw trend data for one or more component IDs
- Wants a JSON payload for downstream trend feature extraction
- Explicitly needs the original detailed trend samples and values, not just summarized trend findings
- Already knows the target component IDs and desired trend features
- Mentions `get_trend_data_tool.py` or `get trend data`

## Preconditions

- The workspace contains `features-tool/`
- The runtime can execute `python3`
- Required env vars or `.env` for the InS client are already available to `features-tool`

## Execution Rules

- Default to `ins-extract-trend-features` for trend analysis tasks
- Use this skill only when the user explicitly needs raw detailed trend data or raw per-point values
- Run the wrapper script instead of manually reconstructing the Python invocation
- Before building `component_features`, choose feature names by component type using the default mapping below
- Pass `component_features` as a single JSON string argument
- Pass `start` and `end` as separate arguments in `YYYY-MM-DD HH:MM:SS` or supported datetime input format
- Return the tool JSON output directly unless the user explicitly asks for summarization

## Default Feature Mapping

Unless the user explicitly overrides the feature list, use these defaults:

- For `type=83` points whose name contains `波形`, ignore them and do not include them in trend queries
- For `type=83` shaft vibration points whose name does not contain `波形`, always use `["pp_value", "rms", "p_value", "speed", "gap", "one_freq_y", "one_freq_x", "two_freq_y", "two_freq_x", "half_freq", "remain_freq"]`
- For `type=82` process measurement points such as axial displacement, bearing temperature, lube oil temperature, and other process values, use `["value"]`
- For `type=81` speed points, use `["speed"]`

Do not invent other trend feature names unless the user explicitly asks for them.

## Command

```bash
bash /mnt/skills/custom/ins-get-trend-data/scripts/run.sh '{"1801":["pp_value","rms"],"1802":["value"]}' '2026-04-15 00:00:00' '2026-04-16 00:00:00'
```

## Output

The tool returns JSON with:

- `component_ids`
- `start_time`
- `end_time`
- `component_features`
- `data`

## Notes

- This skill only fetches raw trend data; it does not interpret anomalies
- Prefer `ins-extract-trend-features` by default
- Use this skill only when downstream work requires the original detailed trend payload
