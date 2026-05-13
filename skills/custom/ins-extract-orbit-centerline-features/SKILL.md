---
name: ins-extract-orbit-centerline-features
description: Use this skill when the user wants structured orbit, centerline, 1X, and 2X feature extraction for a shaft orbit at a specific time. This wraps `features-tool/tools/extract_orbit_centerline_features_tool.py`, which internally fetches orbit data first.
---

# InS Extract Orbit Centerline Features

Use this skill to fetch orbit data internally and extract structured orbit geometry, center offset, 1X/2X shape, and suspected-fault signals.

## When to Use This Skill

Use this skill when the user:

- Wants orbit shape tags, centerline findings, and 1X / 2X interpretation
- Wants suspected rub / misalignment / instability / imbalance clues from orbit data
- Mentions `extract_orbit_centerline_features_tool.py`

## Preconditions

- The workspace contains `features-tool/`
- The caller can provide `machine_id` and `bearing_id`
- In the component list, `type=70` means a bearing; choose `bearing_id` from those `type=70` components
- The time argument must be a millisecond timestamp that already exists in trend-analysis results, such as one of the timestamps in `anomaly_time_ms`

## Execution Rules

- Pass `machine_id`, `bearing_id`, and one millisecond timestamp from existing trend results
- When selecting a bearing from a component tree, treat `type=70` as the bearing type
- Do not invent a new time string and do not convert a natural-language time into an orbit query time
- Let the tool fetch raw orbit data internally

## Command

```bash
bash /mnt/skills/custom/ins-extract-orbit-centerline-features/scripts/run.sh 'machine-001' 'bearing-001' '1744761600000'
```

## Output

The tool returns JSON with:

- `summary`
- `shape_findings`
- `centerline_findings`
- `one_x_findings`
- `two_x_findings`
- `suspected_faults`
- `feature_details`
- `probe_ids`

## Notes

- This tool now always calls `get_orbit_data_tool` internally
- The third argument should come directly from trend output timestamps, not from free-form time input
- The output does not expose raw orbit point arrays
