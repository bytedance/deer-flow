---
name: ins-extract-spectral-waveform-features
description: Use this skill when the user wants structured waveform, spectrum, order, shock, clipping, and suspected-fault features for a shaft vibration point at a specific time. This wraps `features-tool/tools/extract_spectral_waveform_features_tool.py`, which internally fetches waveform data first.
---

# InS Extract Spectral Waveform Features

Use this skill to fetch waveform data internally and extract structured waveform and spectrum features.

## When to Use This Skill

Use this skill when the user:

- Wants 1X / 2X / harmonic / shock / clipping / broadband feature extraction
- Wants suspected fault hints based on waveform and spectrum
- Mentions `extract_spectral_waveform_features_tool.py`

## Preconditions

- The workspace contains `features-tool/`
- The caller can provide `component_id`
- The point passed as `component_id` must be `type=83` and its name must not contain `波形`
- The time argument must be a millisecond timestamp that already exists in trend-analysis results, such as one of the timestamps in `anomaly_time_ms`

## Execution Rules

- Pass `component_id` and one millisecond timestamp from existing trend results
- Only use point IDs where `type=83` and the point name does not contain `波形`
- Do not invent a new time string and do not convert a natural-language time into a waveform query time
- Let the tool fetch raw waveform data internally

## Command

```bash
bash /mnt/skills/custom/ins-extract-spectral-waveform-features/scripts/run.sh 'point_id' '1744761600000'
```

## Output

The tool returns JSON with:

- `summary`
- `spectral_findings`
- `waveform_findings`
- `suspected_faults`
- `feature_details`

## Notes

- This tool now always calls `get_waveform_data_tool` internally
- The second argument should come directly from trend output timestamps, not from free-form time input
- The output does not expose raw waveform or spectrum arrays
