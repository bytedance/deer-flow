---
name: ins-device-analysis-9k
description: Use this skill when the user wants the 9K-filtered child-device tree for an InS machine ID (往复 / 高端旋转机组 RC, positionType 91..99). This wraps `features-tool/tools/device_analysis_9k_tool.py`, which filters component nodes by `endpoint_series == "9k"` and preserves the high-density measurement layout.
---

# InS Device Analysis (9K)

Use this skill to fetch the 9K-filtered child-device tree for an InS machine ID.

## When to Use This Skill

Use this skill when the user:

- Knows a 9K-capable machine ID and wants its 9K child-device tree (RC, positionType 91..99)
- Wants the normalized 9K subtree for reciprocating or high-end rotating machinery diagnosis
- Wants to inspect the 9K measurement layout before downstream `reciprocating-fault-diagnosis`
- Mentions `device_analysis_9k_tool.py`

Use the 8K default skill (`ins-device-analysis`) for standard rotating machinery, the 2K skill for legacy multi-feature vibration pumps, or the 6K skill for static-equipment corrosion monitoring.

## Preconditions

- The workspace contains `features-tool/`
- The target device ID is known and exposes 9K measurement points
- Required InS env vars are already available to the tool runtime

## Execution Rules

- Pass the device ID as the only argument
- Return the JSON output directly unless the user asks for summarization
- Do not claim the tool inferred device type, process type, or structure
- Component nodes with no 9K points are filtered out by the wrapper

## Command

```bash
bash /mnt/skills/custom/ins-device-analysis-9k/scripts/run.sh 230520011328851
```

## Output

The tool returns JSON with:

- `device_id`
- `child_device_list`

Each 9K measurement point in the tree carries:

- `endpoint_series: "9k"`
- `positionType` (91 JSZD / 92 SZT / 93 PBX / 94 PBY / 95 GTZD / 96 GCYL / 97 KEY / 98 STA / 99 ZCYL)

## Notes

- This skill is the preferred preprocessing step for `reciprocating-fault-diagnosis` workflows on 9K-monitored compressors
- The same calling contract as `ins-device-analysis` (8K default); only the upstream `endpoint_series` differs — keep both interchangeable from the SOUL layer's perspective
- This skill no longer calls an LLM internally
