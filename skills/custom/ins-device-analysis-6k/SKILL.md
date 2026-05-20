---
name: ins-device-analysis-6k
description: Use this skill when the user wants the 6K-filtered child-device tree for an InS machine ID (静设备腐蚀监测 PIPELINE, positionType 61..64). This wraps `features-tool/tools/device_analysis_6k_tool.py`, which filters component nodes by `endpoint_series == "6k"` and exposes corrosion-monitoring measurement points only.
---

# InS Device Analysis (6K)

Use this skill to fetch the 6K-filtered child-device tree for an InS machine ID.

## When to Use This Skill

Use this skill when the user:

- Knows a 6K-capable machine ID and wants its 6K child-device tree (PIPELINE, positionType 61..64)
- Wants the normalized 6K subtree for corrosion / wall-thickness diagnosis
- Wants to inspect the static-equipment measurement layout before downstream corrosion diagnosis
- Mentions `device_analysis_6k_tool.py`

This skill **only returns 6K static-equipment points**. Rotating-machinery vibration points belong to:

- `ins-device-analysis` (8K default, rotating machinery)
- `ins-device-analysis-2k` (legacy multi-feature vibration pump)
- `ins-device-analysis-9k` (high-end / reciprocating rotating machinery)

## Preconditions

- The workspace contains `features-tool/`
- The target device ID is known and exposes 6K measurement points
- Required InS env vars are already available to the tool runtime

## Execution Rules

- Pass the device ID as the only argument
- Return the JSON output directly unless the user asks for summarization
- Do not claim the tool inferred device type, process type, or structure
- Component nodes with no 6K points are filtered out by the wrapper

## Command

```bash
bash /mnt/skills/custom/ins-device-analysis-6k/scripts/run.sh 230520017412305
```

## Output

The tool returns JSON with:

- `device_id`
- `child_device_list`

Each 6K measurement point in the tree carries:

- `endpoint_series: "6k"`
- `positionType` (61 STA / 62 TH 探头 / 63 P 腐蚀探针 / 64 OTHER_TH 离线检测)

## Notes

- This skill is the preferred preprocessing step for `static-equipment-corrosion-diagnosis` workflows
- This skill no longer calls an LLM internally
