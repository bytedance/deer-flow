---
name: ins-get-orbit-data
description: Use this skill when the user wants raw shaft orbit data for a machine, bearing, and timestamp. This wraps `features-tool/tools/get_orbit_data_tool.py`.
---

# InS Get Orbit Data

Use this skill to fetch raw shaft orbit data for a machine and bearing at a specific time.

## When to Use This Skill

Use this skill when the user:

- Wants raw orbit points for rotor-dynamics review
- Already knows `machine_id` and `bearing_id`
- Needs orbit payloads for downstream centerline/orbit feature extraction
- Mentions `get_orbit_data_tool.py`

## Preconditions

- The workspace contains `features-tool/`
- The target machine and bearing IDs are known
- In the component list, `type=70` means a bearing; choose `bearing_id` from those `type=70` components
- The time argument must be a millisecond timestamp that already exists in trend-analysis results, such as one of the timestamps in `anomaly_time_ms`

## Execution Rules

- Pass `machine_id`, `bearing_id`, and one millisecond timestamp from existing trend results
- When selecting a bearing from a component tree, treat `type=70` as the bearing type
- Do not invent a new time string and do not convert a natural-language time into an orbit query time
- Return the JSON payload directly unless the user asks for interpretation

## Command

```bash
bash /mnt/skills/custom/ins-get-orbit-data/scripts/run.sh 'machine-001' 'bearing-001' '1744761600000'
```

参考示例：

- 合法示例：从组件树中选择 `type=70` 的轴承作为 `bearing_id`
- 非法示例：不要把普通测点或非 `type=70` 的组件当成 `bearing_id`

## Output

The tool returns JSON with:

- `machine_id`
- `bearing_id`
- `time_ms`
- `probe_ids`
- `data.points`
- `data.points_1x`
- `data.points_2x`
- `data.speed`

## Notes

- This skill retrieves raw orbit payloads only
- For shape and centerline interpretation, use `ins-extract-orbit-centerline-features`
- The third argument should come directly from trend output timestamps, not from free-form time input
