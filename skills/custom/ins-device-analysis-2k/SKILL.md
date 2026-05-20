---
name: ins-device-analysis-2k
description: Use this skill when the user wants the 2K-filtered child-device tree for an InS machine ID (机泵 PUMP, positionType 22..30). This wraps `features-tool/tools/device_analysis_2k_tool.py`, which filters component nodes by `endpoint_series == "2k"` and preserves the B/C/D tier `alarm_thresholds` field on each 2K vibration point.
---

# InS Device Analysis (2K)

Use this skill to fetch the 2K-filtered child-device tree for an InS machine ID.

## When to Use This Skill

Use this skill when the user:

- Knows a 2K-capable machine ID and wants its 2K child-device tree (PUMP, positionType 22..30)
- Wants the normalized 2K subtree with B/C/D tier alarm thresholds preserved
- Wants to inspect the 2K measurement layout before downstream pump-fault diagnosis
- Mentions `device_analysis_2k_tool.py`

Use the 8K default skill (`ins-device-analysis`) for standard rotating machinery, the 6K skill for static-equipment corrosion monitoring, or the 9K skill for high-end / reciprocating rotating machinery.

## Preconditions

- The workspace contains `features-tool/`
- The target device ID is known and exposes 2K measurement points
- Required InS env vars are already available to the tool runtime

## Execution Rules

- Pass the device ID as the only argument
- Return the JSON output directly unless the user asks for summarization
- Do not claim the tool inferred device type, process type, or structure
- Component nodes with no 2K points are filtered out by the wrapper

## Command

```bash
bash /mnt/skills/custom/ins-device-analysis-2k/scripts/run.sh 260325070149111
```

## Output

The tool returns JSON with:

- `device_id`
- `child_device_list`

Each 2K measurement point in the tree carries:

- `endpoint_series: "2k"`
- `alarm_thresholds: {<feature>: {B, C, D}}` — B / C / D tier alarm bounds for `v_rms`, `a_peak`, `a_rms`, `kurtosis`, `margin`, `pulse`, `wave` (fields missing on the InS side are omitted; never inferred)

Downstream diagnosis skills (e.g. `pump-fault-diagnosis`) **default to C tier** when computing `alarm_count`; D tier is reserved for `danger_count`.

## Notes

- This skill is the preferred preprocessing step for `pump-fault-diagnosis` workflows running on 2K-monitored pumps
- This skill no longer calls an LLM internally
