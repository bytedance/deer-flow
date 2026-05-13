---
name: ins-get-waveform-data
description: Use this skill when the user wants raw waveform and spectrum data for a shaft vibration point at a specific timestamp. This wraps `features-tool/tools/get_waveform_data_tool.py`.
---

# InS Get Waveform Data

Use this skill to fetch raw waveform and spectrum data for a measurement point at a specific time.

## When to Use This Skill

Use this skill when the user:

- Wants waveform data for a component ID at a given time
- Wants spectrum data at a specific timestamp
- Needs raw input for spectral and waveform feature extraction
- Mentions `get_waveform_data_tool.py`

## Preconditions

- The workspace contains `features-tool/`
- The target component ID is known
- The point passed as `component_id` must be `type=83` and its name must not contain `波形`
- The time argument must be a millisecond timestamp that already exists in trend-analysis results, such as one of the timestamps in `anomaly_time_ms`

## Execution Rules

- Pass `component_id` and one millisecond timestamp from existing trend results
- Only use point IDs where `type=83` and the point name does not contain `波形`
- Do not invent a new time string and do not convert a natural-language time into a waveform query time
- Return the raw JSON output unless the user asks for interpretation

## Command

```bash
bash /mnt/skills/custom/ins-get-waveform-data/scripts/run.sh 1801 '1744761600000'
```

参考示例：

- 合法示例：选择 `type=83` 且名称不含 `波形` 的轴振测点，例如 `X轴振`、`Y轴振`
- 非法示例：名称包含 `波形` 的测点，即使 `type=83` 也不要作为 `component_id`

## Output

The tool returns JSON with:

- `component_id`
- `time_ms`
- `data.wave_x`
- `data.wave_y`
- `data.spec_x`
- `data.spec_y`
- `data.sample_rate`
- `data.speed`

## Notes

- This skill only retrieves raw waveform/spectrum data
- For structured fault-oriented feature extraction, use `ins-extract-spectral-waveform-features`
- The second argument should come directly from trend output timestamps, not from free-form time input
